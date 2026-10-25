"""Reporte de una corrida: conteos, errores frecuentes y validaciones de calidad con umbrales.

Las validaciones buscan detectar a tiempo un cambio en el sitio de Rappi o un bloqueo, no
evaluar el negocio: por eso los umbrales son holgados y cada uno explica qué señal da.
"""

from datetime import datetime
from pathlib import Path

from psycopg import Connection

from .config import DATA_DIR, SKIPPED_PAGES_MAX
from .storage import repository

REPORTS_DIR = DATA_DIR / "reports"

# Umbrales: (máximo o mínimo aceptable, qué indica si se sale del rango).
MAX_FAILED_JOBS_PCT = 10  # más fallas que esto suele ser bloqueo, caída o cambio del sitio
MAX_MISSING_PRICE_PCT = 5  # Rappi siempre muestra precio: faltantes = el JSON cambió
MAX_MISSING_CATEGORY_PCT = 5  # todos los productos traen category_id
MAX_MISSING_IMAGE_PCT = 10  # casi todos traen imagen
MAX_ZERO_PRODUCT_STORES_PCT = 5  # una tienda "hecha" sin productos = página vacía o parser roto
MIN_COVERAGE_PCT = 5  # lo normal es 8–58% (tope de 24 por sub-pasillo); menos = parser roto
MAX_MISSING_DISH_PRICE_PCT = 2  # los platos siempre tienen precio
MIN_DISHES_PER_RESTAURANT = 5  # menos indica menús que no se leyeron completos
MAX_DROP_VS_PREVIOUS_PCT = 25  # caer más que esto frente a la corrida anterior suele ser bloqueo parcial o parser roto
COMPARED_TOTALS = {"stores": ("ofertas",), "restaurants": ("restaurantes", "platos")}
# Clave en scrape_runs.params: el sitemap de restaurantes no respondió y se usó la lista de una corrida anterior.
FALLBACK_LIST = "lista_de_respaldo"

STORE_QUALITY_SQL = """
SELECT count(*),
       count(*) FILTER (WHERE s.price IS NULL OR s.price = 0),
       count(*) FILTER (WHERE ci.category_id IS NULL),
       count(*) FILTER (WHERE coalesce(ci.image_url, '') = ''),
       count(*) FILTER (WHERE coalesce(ci.trademark, '') = '')
FROM price_snapshots s
JOIN store_products sp USING (store_id, sku)
LEFT JOIN catalog_items ci USING (master_product_id)
WHERE s.run_id = %(run)s
"""

STORE_VERTICALS_SQL = """
WITH store_vertical AS (SELECT DISTINCT store_id, vertical FROM v_store_verticals)
SELECT sv.vertical,
       count(DISTINCT s.store_id) AS tiendas,
       count(*) AS ofertas,
       count(DISTINCT sp.master_product_id) AS productos_unicos,
       count(DISTINCT sp.master_product_id) FILTER (WHERE ci.first_seen >= %(start)s) AS productos_nuevos
FROM price_snapshots s
JOIN store_products sp USING (store_id, sku)
JOIN store_vertical sv ON sv.store_id = s.store_id
LEFT JOIN catalog_items ci ON ci.master_product_id = sp.master_product_id
WHERE s.run_id = %(run)s
GROUP BY sv.vertical
ORDER BY sv.vertical
"""

COVERAGE_SQL = """
SELECT coalesce(sum(obtenidos), 0), coalesce(sum(declarados), 0)
FROM v_coverage
WHERE store_id IN (SELECT DISTINCT store_id FROM price_snapshots WHERE run_id = %(run)s)
"""

# Cambios de precio de la corrida: cada fila de la corrida contra la anterior del mismo SKU en la tienda, buscada por
# el índice (store_id, sku, scraped_at). Cuenta lo mismo que v_price_changes (`lag` por tienda y SKU), cuya ventana
# ordena todo el historial antes de filtrar por corrida. Con la misma fecha, la anterior es la de la corrida previa.
PRICE_CHANGES_SQL = """
SELECT count(*)
FROM price_snapshots cur
CROSS JOIN LATERAL (
    SELECT p.price FROM price_snapshots p
    WHERE p.store_id = cur.store_id AND p.sku = cur.sku AND p.scraped_at <= cur.scraped_at
      AND (p.scraped_at, p.run_id) < (cur.scraped_at, cur.run_id)
    ORDER BY p.scraped_at DESC, p.run_id DESC
    LIMIT 1
) prev
WHERE cur.run_id = %(run)s AND prev.price <> cur.price
"""

RESTAURANT_SQL = """
SELECT count(DISTINCT mi.store_id),
       count(*),
       count(*) FILTER (WHERE mps.price IS NULL OR mps.price = 0),
       count(*) FILTER (WHERE mi.first_seen >= %(start)s)
FROM menu_price_snapshots mps
JOIN menu_items mi USING (item_id)
WHERE mps.run_id = %(run)s
"""


def fallback_message(fallback: dict) -> str:
    """Una línea para el log y el reporte: de qué corrida salió la lista y cuántos restaurantes trajo."""
    message = (
        f"sitemap bloqueado o caído: se usó la lista de la corrida {fallback['corrida']} "
        f"({fallback['restaurantes']} restaurantes)"
    )
    if fallback["descubierta_en"] != fallback["corrida"]:  # esa corrida también usó una lista anterior
        message += f", descubierta en la corrida {fallback['descubierta_en']}"
    return message


def _pct(part: int, total: int) -> float:
    return round(100 * part / total, 1) if total else 0.0


def _check(label: str, value: float, limit: float, *, minimum: bool = False) -> dict:
    ok = value >= limit if minimum else value <= limit
    return {"label": label, "value": value, "limit": limit, "minimum": minimum, "ok": ok}


def _job_section(conn: Connection, run_id: int) -> tuple[dict, list[dict]]:
    jobs = dict(
        conn.execute("SELECT status, count(*) FROM scrape_jobs WHERE run_id = %s GROUP BY 1", (run_id,)).fetchall()
    )
    errors = conn.execute(
        "SELECT left(error, 140), count(*) FROM scrape_jobs WHERE run_id = %s AND status = 'failed' "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 5",
        (run_id,),
    ).fetchall()
    return jobs, [{"error": e, "count": n} for e, n in errors]


def _store_section(conn: Connection, params: dict, jobs: dict) -> tuple[list[dict], dict, list[dict]]:
    total, no_price, no_category, no_image, no_brand = conn.execute(STORE_QUALITY_SQL, params).fetchone()
    cur = conn.execute(STORE_VERTICALS_SQL, params)
    columns = [d.name for d in cur.description]
    verticals = [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]
    obtained, declared = conn.execute(COVERAGE_SQL, params).fetchone()
    zero_stores, skipped_pages = conn.execute(
        "SELECT count(*) FILTER (WHERE (result->>'products')::int = 0), "
        "coalesce(sum((result->>'paginas_omitidas')::int), 0) "
        "FROM scrape_jobs WHERE run_id = %(run)s AND status = 'done'",
        params,
    ).fetchone()
    # Sobre todos los jobs que las cuentan, también los que fallaron por omitir demasiadas (los hechos no pasan del
    # 5 %).
    skipped_all, attempted_all = conn.execute(
        "SELECT coalesce(sum((result->>'paginas_omitidas')::int), 0), "
        "coalesce(sum((result->>'paginas_intentadas')::int), 0) "
        "FROM scrape_jobs WHERE run_id = %(run)s AND result ? 'paginas_intentadas'",
        params,
    ).fetchone()
    price_changes = conn.execute(PRICE_CHANGES_SQL, params).fetchone()[0]
    # La marca es solo informativa: depende del vertical (chocolaterías y tecnología suelen no traerla).
    # paginas_omitidas: pasillos y sub-pasillos que no se pudieron leer en tiendas que sí quedaron hechas.
    totals = {
        "ofertas": total,
        "cambios_de_precio": price_changes,
        "paginas_omitidas": skipped_pages,
        "sin_marca_pct": _pct(no_brand, total),
    }
    checks = [
        _check("Productos sin precio (%)", _pct(no_price, total), MAX_MISSING_PRICE_PCT),
        _check("Productos sin categoría (%)", _pct(no_category, total), MAX_MISSING_CATEGORY_PCT),
        _check("Productos sin imagen (%)", _pct(no_image, total), MAX_MISSING_IMAGE_PCT),
        _check("Tiendas sin productos (%)", _pct(zero_stores, jobs.get("done", 0)), MAX_ZERO_PRODUCT_STORES_PCT),
        _check("Páginas omitidas (%)", _pct(int(skipped_all), int(attempted_all)), SKIPPED_PAGES_MAX * 100),
        _check(
            "Cobertura obtenidos/declarados (%)", _pct(int(obtained), int(declared)), MIN_COVERAGE_PCT, minimum=True
        ),
    ]
    return verticals, totals, checks


def _restaurant_section(conn: Connection, params: dict) -> tuple[dict, list[dict]]:
    restaurants, dishes, no_price, new_dishes = conn.execute(RESTAURANT_SQL, params).fetchone()
    totals = {"restaurantes": restaurants, "platos": dishes, "platos_nuevos": new_dishes}
    checks = [
        _check("Platos sin precio (%)", _pct(no_price, dishes), MAX_MISSING_DISH_PRICE_PCT),
        _check(
            "Platos por restaurante (promedio)",
            round(dishes / restaurants, 1) if restaurants else 0.0,
            MIN_DISHES_PER_RESTAURANT,
            minimum=True,
        ),
    ]
    return totals, checks


def build_run_report(conn: Connection, run_id: int, alert: str | None = None) -> dict:
    kind, status, started_at, finished_at = conn.execute(
        "SELECT kind, status, started_at, finished_at FROM scrape_runs WHERE run_id = %s", (run_id,)
    ).fetchone()
    params = {"run": run_id, "start": started_at}
    jobs, top_errors = _job_section(conn, run_id)
    report = {
        "run_id": run_id,
        "kind": kind,
        "status": status,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat() if finished_at else None,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "alert": alert,
        "jobs": jobs,
        "top_errors": top_errors,
        "verticals": [],
        "totals": {},
    }
    if kind == "restaurants":
        report["totals"], checks = _restaurant_section(conn, params)
        fallback = repository.run_params(conn, run_id).get(FALLBACK_LIST)
        if fallback:
            report["fallback_list"] = fallback
    else:
        report["verticals"], report["totals"], checks = _store_section(conn, params, jobs)
        # Un listado que falla no deja jobs fallidos: sus tiendas nunca entran a la cola (licores, 04-10).
        failed = conn.execute("SELECT params->'listados_fallidos' FROM scrape_runs WHERE run_id = %s", (run_id,))
        report["failed_listings"] = sorted(tuple(pair) for pair in failed.fetchone()[0] or [])
        checks.append(_check("Listados fallidos al descubrir", len(report["failed_listings"]), 0))
    # Sobre los intentados: los omitidos (marca ya descargada, ya no existe) diluían la tasa de fallas.
    attempted = jobs.get("done", 0) + jobs.get("failed", 0)
    if jobs:
        checks.insert(0, _check("Jobs fallidos (%)", _pct(jobs.get("failed", 0), attempted), MAX_FAILED_JOBS_PCT))
    checks += _versus_previous(conn, kind, run_id, report["totals"])
    report["checks"] = checks
    return report


def _versus_previous(conn: Connection, kind: str, run_id: int, totals: dict) -> list[dict]:
    """Variación (%) de los totales clave frente a la última corrida terminada del mismo tipo."""
    row = conn.execute(
        "SELECT run_id, report FROM scrape_runs WHERE kind = %s AND run_id < %s AND status = 'done' "
        "AND report IS NOT NULL ORDER BY run_id DESC LIMIT 1",
        (kind, run_id),
    ).fetchone()
    if row is None:
        return []
    previous_id, previous = row
    checks = []
    for key in COMPARED_TOTALS.get(kind, ()):
        before, now = previous.get("totals", {}).get(key), totals.get(key)
        if before and now is not None:
            change = round(100 * (now - before) / before, 1)
            label = f"{key.capitalize()} vs corrida {previous_id} (%)"
            checks.append(_check(label, change, -MAX_DROP_VS_PREVIOUS_PCT, minimum=True))
    return checks


def render_markdown(report: dict) -> str:
    warnings = [c for c in report["checks"] if not c["ok"]]
    lines = [f"# Reporte corrida {report['run_id']} ({report['kind']})", ""]
    if report.get("alert") and report["status"] == "failed":  # falló al descubrir: quedó cerrada
        lines += [f"⛔ Corrida fallida: {report['alert']}. La próxima actualización empieza otra.", ""]
    elif report.get("alert"):
        lines += [f"⛔ Corrida detenida: {report['alert']}. Quedó abierta: la próxima actualización la retoma.", ""]
    if report.get("fallback_list"):  # la corrida se hizo, pero sin descubrir: restaurantes nuevos no entraron
        fallback = report["fallback_list"]
        # Detenida por un bloqueo, la próxima actualización la retoma con la misma lista: no vuelve a descubrir.
        again = "" if report.get("alert") else " La próxima actualización vuelve a descubrir."
        lines += [f"⚠ {fallback_message(fallback)}. Error del sitemap: {fallback['error']}.{again}", ""]
    if warnings:
        names = ", ".join(c["label"] for c in warnings)
        lines.append(f"⚠ {len(warnings)} validaciones fuera de rango: {names}")
    else:
        lines.append("✓ Todas las validaciones dentro de rango")
    lines += [
        "",
        f"- Estado: {report['status']} · inicio {report['started_at']} · fin {report['finished_at'] or '—'}",
        "- Jobs: " + (", ".join(f"{k} {v}" for k, v in sorted(report["jobs"].items())) or "—"),
        "- Totales: " + (", ".join(f"{k} {v}" for k, v in report["totals"].items()) or "—"),
    ]
    if report["verticals"]:
        lines += ["", "| Vertical | Tiendas | Ofertas | Productos únicos | Nuevos |", "|---|---|---|---|---|"]
        lines += [
            f"| {v['vertical']} | {v['tiendas']} | {v['ofertas']} | {v['productos_unicos']} | {v['productos_nuevos']} |"
            for v in report["verticals"]
        ]
    lines += ["", "| Validación | Valor | Rango | Estado |", "|---|---|---|---|"]
    for c in report["checks"]:
        bound = f"≥ {c['limit']}" if c["minimum"] else f"≤ {c['limit']}"
        lines.append(f"| {c['label']} | {c['value']} | {bound} | {'ok' if c['ok'] else '⚠'} |")
    if report.get("failed_listings"):
        by_vertical: dict[str, list[str]] = {}
        for city, vertical in report["failed_listings"]:
            by_vertical.setdefault(vertical, []).append(city)
        lines += ["", "Listados que fallaron al descubrir (sus tiendas no se descargaron):"]
        lines += [f"- {vertical}: {', '.join(sorted(cities))}" for vertical, cities in sorted(by_vertical.items())]
    if report["top_errors"]:
        lines += ["", "Errores más frecuentes:"]
        lines += [f"- ({e['count']}) {e['error']}" for e in report["top_errors"]]
    return "\n".join(lines) + "\n"


def write_run_report(
    conn: Connection, run_id: int, reports_dir: Path = REPORTS_DIR, alert: str | None = None
) -> tuple[dict, Path]:
    """Arma el reporte, lo guarda en `scrape_runs.report` y en `data/reports/run_<id>_<tipo>.md`."""
    report = build_run_report(conn, run_id, alert)
    repository.save_run_report(conn, run_id, report)
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"run_{run_id}_{report['kind']}.md"
    path.write_text(render_markdown(report), encoding="utf-8")
    return report, path
