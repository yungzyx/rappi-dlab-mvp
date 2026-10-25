"""Juez de tres niveles de la búsqueda: el juicio LLM de pares (consulta, producto mostrado). No es un juicio humano.

El juez por concepto de `search_eval` da por relevante todo lo del mismo concepto, aunque sea otro formato, un
repuesto o una versión infantil: contra el juicio LLM del 25-10 coincide en el 70,5 % (κ 0,32;
docs/resultados/juicio-llm-busqueda-2026-10-25.md). Este juez puntúa lo que ve la persona (la fila
`hibrido_mostrado`, `search_products` como /search) con 2 «sirve», 1 «a medias» y 0 «no sirve».

- Consultas: las positivas de queries.json con algún par juzgado. Son siempre las mismas: el antes y el después se
  comparan sobre las mismas consultas.
- nDCG@10: ganancia 0, 1 o 2. Un producto sin juicio se salta (lista condensada) y el ideal sale de todos los pares
  juzgados de la consulta, también los que la búsqueda ya no muestra.
- P@3: «sirve» entre los tres primeros, sobre 3 (un puesto vacío o sin juicio cuenta como que no sirve); útil@3, lo
  mismo con «sirve» o «a medias».
- Cobertura: cuántos de los productos mostrados tienen juicio. Los que no, van a una planilla (`pendientes`, con
  textos del catálogo: fuera de git) para juzgarlos con el mismo criterio; sus juicios se suman a COMPLEMENT_FILE, por
  id de par y sin textos (`import_sheet`).
"""

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from psycopg import Connection

from .search_eval import SHOWN, QueryRun
from .sheets import SEARCH_IDS_FILE, VERDICTS, category_names, pair_id, read_search_sheet, read_table

EVAL_DIR = Path(__file__).resolve().parent
LLM_FILE = EVAL_DIR / "juicio-llm-2026-10-25.json"  # los 200 pares de planilla-busqueda-ids.json, por id de par
COMPLEMENT_FILE = EVAL_DIR / "juicio-llm-complemento.json"  # pares que la búsqueda mostró después, con su clave
K = 10
TOP = 3
PENDING_COLUMNS = ["id", "consulta", "vertical", "entity_type", "entity_id", "nombre", "categoria", "tienda", "juicio"]


@dataclass(frozen=True)
class Judged:
    vertical: str
    query: str
    level: int  # 2 «sirve», 1 «a medias», 0 «no sirve»


def load_judgments(
    llm_file: Path = LLM_FILE, pairs_file: Path = SEARCH_IDS_FILE, complement_file: Path = COMPLEMENT_FILE
) -> dict[str, Judged]:
    """{id de par: juicio}: los del juicio LLM del 25-10 (su clave sale de la planilla) y los del complemento. Un par
    juzgado dos veces, o con un id que no corresponde a su clave, es un error del archivo."""
    pairs = {p["id"]: p for p in _read(pairs_file)["pares"]}
    judged = {
        pid: Judged(pairs[pid]["vertical"], pairs[pid]["consulta"], VERDICTS[verdict])
        for pid, verdict in _read(llm_file)["juicios"].items()
    }
    if complement_file.exists():
        for p in _read(complement_file)["pares"]:
            if p["id"] != pair_id(p["vertical"], p["consulta"], p["entity_type"], p["entity_id"]):
                raise ValueError(f"{complement_file.name}: el id {p['id']} no corresponde a su consulta y producto")
            if p["id"] in judged:
                raise ValueError(f"{complement_file.name}: el par {p['id']} ya tiene juicio")
            judged[p["id"]] = Judged(p["vertical"], p["consulta"], VERDICTS[p["juicio"]])
    return judged


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def shown_lists(runs: list[QueryRun]) -> list[dict]:
    """Lo que vio la persona en cada consulta positiva (solo ids): se guarda para volver a puntuarlo con más juicios."""
    return [
        {
            "vertical": r.vertical,
            "consulta": r.query,
            "tipo": r.tipo,
            "productos": [[item["entity_type"], item["entity_id"]] for item in r.items],
        }
        for r in runs
        if r.mode == SHOWN and r.tipo != "negativa"
    ]


def score(lists: list[dict], judgments: dict[str, Judged]) -> dict:
    """Las métricas de las consultas con algún par juzgado: en total, por tipo de consulta y por vertical."""
    pool: dict[tuple[str, str], list[int]] = defaultdict(list)
    for judged in judgments.values():
        pool[(judged.vertical, judged.query)].append(judged.level)
    rows = []
    for shown in lists:
        levels = pool.get((shown["vertical"], shown["consulta"]))
        if not levels:
            continue
        gains = [
            judged.level if (judged := judgments.get(pair_id(shown["vertical"], shown["consulta"], t, i))) else None
            for t, i in shown["productos"][:K]
        ]
        rows.append({**{key: shown[key] for key in ("vertical", "consulta", "tipo")}, **_query_scores(gains, levels)})
    return {
        "total": _means(rows),
        "por_tipo": {t: _means([r for r in rows if r["tipo"] == t]) for t in sorted({r["tipo"] for r in rows})},
        "por_vertical": {
            v: _means([r for r in rows if r["vertical"] == v]) for v in sorted({r["vertical"] for r in rows})
        },
        "consultas": rows,
    }


def _query_scores(gains: list[int | None], levels: list[int]) -> dict:
    judged = [g for g in gains if g is not None]
    ideal = sorted(levels, reverse=True)[:K]
    return {
        "mostrados": len(gains),
        "juzgados": len(judged),
        "no_sirve": sum(g == 0 for g in judged),
        "ndcg@10": _dcg(judged[:K]) / _dcg(ideal) if _dcg(ideal) else 0.0,
        "p@3": sum(g == 2 for g in gains[:TOP]) / TOP,
        "util@3": sum(g is not None and g >= 1 for g in gains[:TOP]) / TOP,
    }


def _dcg(gains: list[int]) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def _means(rows: list[dict]) -> dict:
    n = len(rows)
    shown = sum(r["mostrados"] for r in rows)
    judged = sum(r["juzgados"] for r in rows)
    return {
        "n": n,
        "ndcg@10": round(sum(r["ndcg@10"] for r in rows) / n, 3) if n else None,
        "p@3": round(sum(r["p@3"] for r in rows) / n, 3) if n else None,
        "util@3": round(sum(r["util@3"] for r in rows) / n, 3) if n else None,
        "mostrados": shown,
        "sin_juicio": shown - judged,
        "no_sirve": round(sum(r["no_sirve"] for r in rows) / judged, 3) if judged else None,
    }


def pending(lists: list[dict], judgments: dict[str, Judged]) -> list[dict]:
    """Los pares mostrados sin juicio de las consultas que se puntúan, sin repetir."""
    queries = {(j.vertical, j.query) for j in judgments.values()}
    found: dict[str, dict] = {}
    for shown in lists:
        if (shown["vertical"], shown["consulta"]) not in queries:
            continue
        for t, i in shown["productos"][:K]:
            pid = pair_id(shown["vertical"], shown["consulta"], t, i)
            if pid not in judgments:
                found[pid] = {
                    "id": pid,
                    "vertical": shown["vertical"],
                    "consulta": shown["consulta"],
                    "entity_type": t,
                    "entity_id": i,
                }
    return list(found.values())


def pending_rows(conn: Connection, pairs: list[dict]) -> list[dict]:
    """La planilla de lo que falta juzgar: nombre, categoría y tienda, sin la posición ni el concepto (se juzga a
    ciegas, como en el juicio del 25-10). Por consulta y, dentro de ella, en el orden del id (un hash: al azar)."""
    categories = category_names(conn, pairs)
    names = _names_and_stores(conn, pairs)
    rows = [
        {
            **p,
            "nombre": names.get((p["entity_type"], p["entity_id"]), ("", ""))[0],
            "categoria": categories.get((p["entity_type"], p["entity_id"]), ""),
            "tienda": names.get((p["entity_type"], p["entity_id"]), ("", ""))[1],
            "juicio": "",
        }
        for p in pairs
    ]
    return sorted(rows, key=lambda r: (r["vertical"], r["consulta"], r["id"]))


def _names_and_stores(conn: Connection, pairs: list[dict]) -> dict[tuple[str, str], tuple[str, str]]:
    """El nombre de cada producto o plato y una tienda donde está (la del plato; la del producto, la primera por id)."""
    found: dict[tuple[str, str], tuple[str, str]] = {}
    for etype, sql in (
        (
            "catalog_item",
            """SELECT DISTINCT ON (ci.master_product_id) ci.master_product_id::text, ci.name, btrim(s.name)
               FROM catalog_items ci
               LEFT JOIN store_products sp USING (master_product_id)
               LEFT JOIN stores s USING (store_id)
               WHERE ci.master_product_id = ANY(%s::bigint[])
               ORDER BY ci.master_product_id, sp.store_id""",
        ),
        (
            "menu_item",
            """SELECT mi.item_id::text, mi.name, btrim(s.name) FROM menu_items mi JOIN stores s USING (store_id)
               WHERE mi.item_id = ANY(%s::bigint[])""",
        ),
    ):
        ids = [p["entity_id"] for p in pairs if p["entity_type"] == etype]
        if ids:
            found.update({(etype, eid): (name, store or "") for eid, name, store in conn.execute(sql, (ids,))})
    return found


def import_sheet(sheet: Path, complement_file: Path = COMPLEMENT_FILE) -> int:
    """Suma al complemento los juicios de la planilla de pendientes (`sirve`, `a medias` o `no sirve`): solo ids y
    claves, sin textos. Devuelve cuántos pares sumó; los que ya tenían juicio quedan como estaban."""
    levels = read_search_sheet(sheet)
    names = {level: verdict for verdict, level in VERDICTS.items()}
    rows = {row["id"]: row for row in read_table(sheet) if row.get("id") in levels}
    document = (
        _read(complement_file)
        if complement_file.exists()
        else {"nota": "Juicio LLM (no humano) de pares mostrados sin juicio; ver eval/graded.py.", "pares": []}
    )
    known = {p["id"] for p in document["pares"]} | set(_read(LLM_FILE)["juicios"])
    added = [
        {key: rows[pid][key] for key in ("id", "vertical", "consulta", "entity_type", "entity_id")}
        | {"juicio": names[level]}
        for pid, level in levels.items()
        if pid not in known
    ]
    document["pares"] = sorted(document["pares"] + added, key=lambda p: p["id"])
    complement_file.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(added)


def render_markdown(scores: dict, title: str = "Juez de tres niveles") -> str:
    total = scores["total"]
    lines = [
        f"## {title} (juicio LLM, no humano)",
        "",
        "Lo que ve la persona (`hibrido_mostrado`) puntuado con el juicio LLM de pares: 2 «sirve», 1 «a medias», 0 «no"
        " sirve». Solo las consultas con algún par juzgado; un producto sin juicio se salta en el nDCG y cuenta como"
        " que no sirve en P@3 (ver eval/graded.py).",
        "",
        "| | Consultas | nDCG@10 | P@3 «sirve» | Útil@3 | «No sirve» entre lo juzgado | Mostrados | Sin juicio |",
        "|---|---|---|---|---|---|---|---|",
        _row("Total", total),
    ]
    lines += [_row(f"Tipo: {tipo}", data) for tipo, data in scores["por_tipo"].items()]
    lines += [_row(f"Vertical: {vertical}", data) for vertical, data in scores["por_vertical"].items()]
    if total["sin_juicio"]:
        lines += [
            "",
            f"{total['sin_juicio']} productos mostrados sin juicio: el nDCG no los cuenta y P@3 los cuenta como que no"
            " sirven. `rappi-ia eval-graded` deja la planilla para juzgarlos en data/eval/.",
        ]
    return "\n".join(lines) + "\n"


def _row(label: str, data: dict) -> str:
    return (
        f"| {label} | {data['n']} | {data['ndcg@10']} | {data['p@3']} | {data['util@3']} | {data['no_sirve']}"
        f" | {data['mostrados']} | {data['sin_juicio']} |"
    )
