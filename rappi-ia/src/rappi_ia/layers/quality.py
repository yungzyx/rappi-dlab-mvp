"""Precisión de la capa de datos: una muestra fija de lo que la capa afirma (este ítem es vegano, es de la marca X,
es del concepto Y) para juzgar, y el reporte que cruza los juicios. La cobertura no dice si algo está bien; esto sí.

La muestra prioriza lo que deciden reglas propias (frases en el nombre, marca deducida, concepto por palabra clave o
por mapeo de categoría), donde están los errores; lo que declara Rappi va en una muestra menor, como control. Semilla
fija: el catálogo cambia cada semana, la muestra no. En git van solo ids y afirmaciones (los datos descargados no se
suben); nombres, descripciones y tiendas quedan en una copia local para quien juzga."""

import json
import math
from pathlib import Path

from psycopg import Connection

from ..config import DATA_DIR

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
DEFAULT_SEED = 7
_VERSIONED_KEYS = ("id", "kind", "clave", "fuente", "entity_type", "entity_id")


def _suffix(seed: int) -> str:
    return "" if seed == DEFAULT_SEED else f"-s{seed}"


def sample_file(seed: int = DEFAULT_SEED) -> Path:
    return EVAL_DIR / f"capas-muestra{_suffix(seed)}.json"


def judgments_file(seed: int = DEFAULT_SEED) -> Path:
    return EVAL_DIR / f"capas-juicios{_suffix(seed)}.json"


def local_sample_file(seed: int = DEFAULT_SEED) -> Path:
    """Con los textos del catálogo, para juzgar: fuera de git (`data/`)."""
    return DATA_DIR / "eval" / f"capas-muestra-textos{_suffix(seed)}.json"


ATTRIBUTE_RULE_PER_KEY = 10
ATTRIBUTE_RAPPI_PER_KEY = 3
BRAND_SAMPLE = {"regla": 100, "rappi": 40}
CONCEPT_SAMPLE = {
    ("menu_item", "regla"): 120,
    ("menu_item", "embedding"): 80,
    ("menu_item", "llm"): 60,
    ("catalog_item", "llm"): 80,
    ("catalog_item", "regla"): 60,
    ("catalog_item", "embedding"): 40,
    ("catalog_item", "jev"): 40,  # mapeos de categoría propuestos por Jev (solo hay de productos)
}
MIN_TO_REVIEW = 5  # juicios mínimos para mandar una regla a revisión
REVIEW_BELOW = 0.8  # precisión bajo la cual una regla se revisa

_TEXTS = """
    coalesce(ci.name, mi.name) AS nombre, coalesce(cat.name, ms.name) AS categoria,
    left(regexp_replace(coalesce(ci.description, mi.description, ''), '\\s+', ' ', 'g'), 300) AS descripcion,
    st.name AS tienda
"""
_TEXT_JOINS = """
    LEFT JOIN catalog_items ci ON t.entity_type = 'catalog_item' AND ci.master_product_id::text = t.entity_id
    LEFT JOIN categories cat ON cat.category_id = ci.category_id
    LEFT JOIN menu_items mi ON t.entity_type = 'menu_item' AND mi.item_id::text = t.entity_id
    LEFT JOIN menu_sections ms ON ms.store_id = mi.store_id AND ms.section_id = mi.section_id
    LEFT JOIN stores st ON st.store_id = mi.store_id
"""


def build_quality_sample(conn: Connection, seed: int = 7) -> list[dict]:
    params = {
        "seed": str(seed),
        "rule": ATTRIBUTE_RULE_PER_KEY,
        "rappi": ATTRIBUTE_RAPPI_PER_KEY,
        "brand_rule": BRAND_SAMPLE["regla"],
        "brand_rappi": BRAND_SAMPLE["rappi"],
    }
    rows = conn.execute(
        f"""SELECT 'atributo', t.attribute_id, t.source, t.entity_type, t.entity_id, d.name || ': ' || d.description,
                   t.evidence, {_TEXTS}
            FROM (SELECT a.*, row_number() OVER (PARTITION BY a.attribute_id, a.source
                                                 ORDER BY md5(%(seed)s || a.entity_type || a.entity_id)) AS rn
                  FROM item_attributes a WHERE a.source IN ('regla', 'rappi')) t
            JOIN attribute_defs d USING (attribute_id)
            {_TEXT_JOINS}
            WHERE (t.source = 'regla' AND t.rn <= %(rule)s) OR (t.source = 'rappi' AND t.rn <= %(rappi)s)
            UNION ALL
            SELECT 'marca', t.brand_key, t.source, t.entity_type, t.entity_id, 'Marca: ' || p.name, NULL, {_TEXTS}
            FROM (SELECT b.*, row_number() OVER (PARTITION BY b.source
                                                 ORDER BY md5(%(seed)s || b.entity_type || b.entity_id)) AS rn
                  FROM item_brands b WHERE b.source IN ('regla', 'rappi')) t
            JOIN product_brands p USING (brand_key)
            {_TEXT_JOINS}
            WHERE (t.source = 'regla' AND t.rn <= %(brand_rule)s)
               OR (t.source = 'rappi' AND t.rn <= %(brand_rappi)s)""",
        params,
    ).fetchall()
    for (entity_type, method), size in CONCEPT_SAMPLE.items():
        rows += conn.execute(
            f"""SELECT 'concepto', t.concept_id, t.method, t.entity_type, t.entity_id,
                       'Concepto: ' || c.name || ' (grupo ' || g.name || ')', t.source, {_TEXTS}
                FROM (SELECT ic.* FROM item_concepts ic
                      WHERE ic.entity_type = %(type)s AND ic.method = %(method)s
                      ORDER BY md5(%(seed)s || ic.entity_id) LIMIT %(size)s) t
                JOIN concepts c USING (concept_id) LEFT JOIN concepts g ON g.concept_id = c.parent_id
                {_TEXT_JOINS}""",
            {"seed": str(seed), "type": entity_type, "method": method, "size": size},
        ).fetchall()
    sample = [
        {
            "id": f"{kind}|{key}|{entity_type}|{entity_id}",
            "kind": kind,
            "clave": key,
            "fuente": source,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "afirmacion": claim,
            "evidencia": evidence,
            "nombre": name,
            "categoria": category,
            "descripcion": description or None,
            "tienda": store,
        }
        for kind, key, source, entity_type, entity_id, claim, evidence, name, category, description, store in rows
    ]
    return sorted(sample, key=lambda r: (r["kind"], r["clave"], r["fuente"], r["id"]))


def save_sample(sample: list[dict], versioned: Path, local: Path) -> None:
    note = "Afirmaciones de la capa de datos para juzgar; ver src/rappi_ia/layers/quality.py."
    slim = [{key: row[key] for key in _VERSIONED_KEYS} for row in sample]
    versioned.write_text(json.dumps({"nota": note, "filas": slim}, indent=1, ensure_ascii=False) + "\n", "utf-8")
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(json.dumps({"nota": note, "filas": sample}, indent=1, ensure_ascii=False) + "\n", "utf-8")


def with_names(conn: Connection, sample: list[dict]) -> list[dict]:
    """Agrega el nombre de cada ítem desde la base (la muestra versionada no lo trae), para listar los errores."""
    types, ids = [r["entity_type"] for r in sample], [r["entity_id"] for r in sample]
    names = {
        (etype, eid): name
        for etype, eid, name in conn.execute(
            """SELECT k.entity_type, k.entity_id, coalesce(ci.name, mi.name)
               FROM unnest(%s::text[], %s::text[]) AS k(entity_type, entity_id)
               LEFT JOIN catalog_items ci
                 ON k.entity_type = 'catalog_item' AND ci.master_product_id::text = k.entity_id
               LEFT JOIN menu_items mi ON k.entity_type = 'menu_item' AND mi.item_id::text = k.entity_id""",
            (types, ids),
        )
    }
    return [{**r, "nombre": names.get((r["entity_type"], r["entity_id"])) or r["entity_id"]} for r in sample]


def wilson_low(correct: int, n: int, z: float = 1.96) -> float | None:
    """Límite inferior del intervalo de Wilson al 95 %: con pocas muestras, cuánto se puede asegurar como mínimo."""
    if n == 0:
        return None
    p = correct / n
    center = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, round((center - margin) / (1 + z * z / n), 3))


def _summary(rows: list[tuple[dict, str, str | None]]) -> dict:
    decided = [(r, j, note) for r, j, note in rows if j in ("si", "no")]
    correct = sum(j == "si" for _r, j, _n in decided)
    n = len(decided)
    doubts = sum(j == "dudoso" for _r, j, _n in rows)
    return {
        "n": n,
        "correctos": correct,
        "dudosos": doubts,
        "precision": round(correct / n, 3) if n else None,
        "pesimista": round(correct / (n + doubts), 3) if n + doubts else None,  # si cada dudoso fuera un error
        "minimo": wilson_low(correct, n),
        "errores": [(r["nombre"], note) for r, j, note in decided if j == "no"],
    }


def precision_report(sample: list[dict], judgments: dict[str, dict]) -> dict:
    """Precisión por (tipo, clave, fuente) y por (tipo, fuente). Los «dudoso» no cuentan ni a favor ni en contra."""
    by_group: dict[tuple, list] = {}
    by_kind: dict[tuple, list] = {}
    missing = 0
    for row in sample:
        given = judgments.get(row["id"])
        if not given:
            missing += 1
            continue
        entry = (row, given.get("juicio"), given.get("nota"))
        by_group.setdefault((row["kind"], row["clave"], row["fuente"]), []).append(entry)
        by_kind.setdefault((row["kind"], row["fuente"]), []).append(entry)
    groups = {key: _summary(rows) for key, rows in sorted(by_group.items())}
    review = sorted(
        (key for key, g in groups.items() if g["n"] >= MIN_TO_REVIEW and g["precision"] < REVIEW_BELOW),
        key=lambda key: (groups[key]["precision"], key),
    )
    return {
        "grupos": groups,
        "por_tipo": {key: _summary(rows) for key, rows in sorted(by_kind.items())},
        "revisar": review,
        "sin_juicio": missing,
    }


def render_precision(report: dict, judge: str) -> str:
    def pct(value):
        return "—" if value is None else f"{100 * value:.0f} %"

    out = ["# Precisión de la capa de datos", "", f"Juicios: {judge}. Los «dudoso» no cuentan. «Mínimo» es el límite"]
    out += ["inferior del intervalo de Wilson al 95 %: con pocas muestras, lo que se puede asegurar.", ""]
    out += [
        "## Por tipo y fuente",
        "",
        "| Tipo | Fuente | Juzgados | Precisión | Mínimo | Dudosos | Si los dudosos fueran errores |",
        "|---|---|---|---|---|---|---|",
    ]
    for (kind, source), s in report["por_tipo"].items():
        out.append(
            f"| {kind} | {source} | {s['n']} | {pct(s['precision'])} | {pct(s['minimo'])} | {s['dudosos']} "
            f"| {pct(s['pesimista'])} |"
        )
    out += ["", f"## Reglas a revisar (precisión bajo {pct(REVIEW_BELOW)} con {MIN_TO_REVIEW} o más juicios)", ""]
    for kind, key, source in report["revisar"]:
        s = report["grupos"][(kind, key, source)]
        out.append(f"### {kind} · {key} · {source}: {pct(s['precision'])} ({s['correctos']} de {s['n']})")
        out += [f"- {name}" + (f": {note}" if note else "") for name, note in s["errores"]] + [""]
    out += [
        "## Todas las reglas",
        "",
        "| Tipo | Clave | Fuente | Juzgados | Precisión | Mínimo |",
        "|---|---|---|---|---|---|",
    ]
    for (kind, key, source), s in report["grupos"].items():
        out.append(f"| {kind} | {key} | {source} | {s['n']} | {pct(s['precision'])} | {pct(s['minimo'])} |")
    if report["sin_juicio"]:
        out += ["", f"Filas de la muestra sin juicio: {report['sin_juicio']}."]
    return "\n".join(out) + "\n"


def still_asserted(conn: Connection, sample: list[dict]) -> set[str]:
    """Ids de la muestra cuya afirmación sigue en la base (mismo atributo, marca o concepto para ese ítem)."""
    found = set()
    for kind, table, column in (
        ("atributo", "item_attributes", "attribute_id"),
        ("marca", "item_brands", "brand_key"),
        ("concepto", "item_concepts", "concept_id"),
    ):
        rows = [(r["entity_type"], r["entity_id"], r["clave"]) for r in sample if r["kind"] == kind]
        current = (
            set(conn.execute(f"SELECT entity_type, entity_id, {column} FROM {table}").fetchall()) if rows else set()
        )
        found |= {f"{kind}|{key}|{etype}|{eid}" for etype, eid, key in rows if (etype, eid, key) in current}
    return found


def after_changes(sample: list[dict], judgments: dict[str, dict], still: set[str]) -> dict:
    """Sin volver a juzgar: de lo juzgado, cuántos aciertos se perdieron y cuántos errores se eliminaron al cambiar
    las reglas, y la precisión de lo que sigue afirmándose (por tipo y fuente original)."""
    out: dict[tuple, dict] = {}
    for row in sample:
        verdict = judgments.get(row["id"], {}).get("juicio")
        if verdict not in ("si", "no"):
            continue
        g = out.setdefault(
            (row["kind"], row["fuente"]),
            {"aciertos_que_siguen": 0, "aciertos_perdidos": 0, "errores_que_siguen": 0, "errores_eliminados": 0},
        )
        kept = row["id"] in still
        g[("aciertos_que_siguen" if kept else "aciertos_perdidos") if verdict == "si" else
          ("errores_que_siguen" if kept else "errores_eliminados")] += 1  # fmt: skip
    for g in out.values():
        hits, errors = (
            g["aciertos_que_siguen"] + g["aciertos_perdidos"],
            g["errores_que_siguen"] + g["errores_eliminados"],
        )
        kept = g["aciertos_que_siguen"] + g["errores_que_siguen"]
        g["precision_antes"] = round(hits / (hits + errors), 3) if hits + errors else None
        g["precision_despues"] = round(g["aciertos_que_siguen"] / kept, 3) if kept else None
    return dict(sorted(out.items()))


def render_after(result: dict) -> str:
    def pct(value):
        return "—" if value is None else f"{100 * value:.0f} %"

    out = ["## Después de los cambios de reglas (sin volver a juzgar)", ""]
    out += ["Lo ya juzgado que la base sigue afirmando hoy: los errores eliminados y los aciertos perdidos miden el"]
    out += ["cambio; la precisión «después» es la de lo que sigue afirmándose.", ""]
    out += [
        "| Tipo | Fuente | Precisión antes | Después | Errores eliminados | Aciertos perdidos |",
        "|---|---|---|---|---|---|",
    ]
    for (kind, source), g in result.items():
        removed = f"{g['errores_eliminados']} de {g['errores_eliminados'] + g['errores_que_siguen']}"
        lost = f"{g['aciertos_perdidos']} de {g['aciertos_perdidos'] + g['aciertos_que_siguen']}"
        out.append(
            f"| {kind} | {source} | {pct(g['precision_antes'])} | {pct(g['precision_despues'])} | {removed} | {lost} |"
        )
    return "\n".join(out) + "\n"
