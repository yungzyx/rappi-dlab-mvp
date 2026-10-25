"""Planillas para juzgar a mano (las personas son el juez que le falta a Jev y al juez por concepto) y κ.

Dos planillas CSV que se llenan en Numbers o Excel, una columna cada una:
- `planilla-busqueda.csv`: pares (consulta, producto mostrado) estratificados por vertical, tipo de consulta y posición
  (top-3 / 4-10), con sobremuestreo donde el juez por concepto y la posición discrepan: ahí está el desacuerdo que más
  informa. Se juzga «sirve», «a medias» o «no sirve».
- `planilla-categorias.csv`: categorías del catálogo con su concepto propuesto hoy; la persona escribe el concepto
  correcto. Mezcla categorías sin mapear, decididas por el juez y de acuerdo (control).

Las planillas llevan textos del catálogo y quedan en `data/eval/` (fuera de git). En git van solo los ids y el estrato
(`planilla-*-ids.json`), con semilla fija, como en `layers/quality.py`.
"""

import codecs
import csv
import hashlib
import io
import json
import random
import unicodedata
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from psycopg import Connection

from .. import config
from ..concepts.report import coverage_report
from ..concepts.store import NO_CONCEPT, read_category_map_csv
from ..concepts.taxonomy import load_taxonomy
from ..text import normalize
from .search_eval import SHOWN, QueryRun

EVAL_DIR = Path(__file__).resolve().parent
SEARCH_IDS_FILE = EVAL_DIR / "planilla-busqueda-ids.json"
CATEGORY_IDS_FILE = EVAL_DIR / "planilla-categorias-ids.json"
SEARCH_SHEET = "planilla-busqueda.csv"
CATEGORY_SHEET = "planilla-categorias.csv"
README_FILE = "LEEME-planillas.md"
DEFAULT_SEED = 7

SEARCH_PAIRS = 200
DISCREPANT_SHARE = 0.4  # de los 200 pares, los que se piden de los que el juez por concepto y la posición discrepan
TOP = 3  # posiciones 1 a 3 = «top3»; 4 a 10 = «4-10»
CATEGORY_SIZES = {"sin_mapear": 40, "juez": 30, "acuerdo": 30}
EXAMPLES = 8

VERDICTS = {"sirve": 2, "a medias": 1, "no sirve": 0}  # lo que escribe la persona → nivel (0, 1, 2)
SEARCH_COLUMNS = ["id", "consulta", "vertical", "posicion", "nombre", "categoria", "tienda", "juicio"]
CATEGORY_COLUMNS = ["vertical", "categoria", "ejemplos", "concepto_propuesto", "concepto_correcto"]
# entity_type y entity_id son ids, no texto del catálogo: con ellos el piloto le pide a Jev los mismos pares.
_IDS_KEYS = (
    "id",
    "vertical",
    "consulta",
    "tipo",
    "posicion",
    "estrato",
    "relevante_auto",
    "discrepa",
    "entity_type",
    "entity_id",
)


class SheetInUse(Exception):
    """La planilla ya tiene juicios: volver a generarla los borraría."""


def sheet_dir() -> Path:
    return config.DATA_DIR / "eval"


# --- κ ---------------------------------------------------------------------------------------------------------------


def cohen_kappa(a: list, b: list) -> float:
    """κ de Cohen entre dos jueces que etiquetaron lo mismo: (acuerdo observado - esperado por azar) / (1 - esperado).
    1 = acuerdo total, 0 = el que daría el azar, negativo = peor que el azar."""
    _check_pairs(a, b)
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    count_a, count_b = Counter(a), Counter(b)
    expected = sum(count_a[label] * count_b[label] for label in count_a) / n**2
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def weighted_kappa(a: list[int], b: list[int], levels: int = 3) -> float:
    """κ ponderado lineal para niveles ordenados 0..levels-1: discrepar por dos niveles pesa el doble que por uno
    (1 - desacuerdo observado / desacuerdo esperado, con peso |i - j| / (levels - 1))."""
    _check_pairs(a, b)
    if any(not 0 <= x < levels for x in (*a, *b)):
        raise ValueError(f"Los niveles deben estar entre 0 y {levels - 1}")
    n = len(a)
    scale = levels - 1
    observed = sum(abs(x - y) for x, y in zip(a, b, strict=True)) / n / scale
    count_a, count_b = Counter(a), Counter(b)
    expected = sum(count_a[i] * count_b[j] * abs(i - j) for i in range(levels) for j in range(levels)) / n**2 / scale
    return 1.0 if expected == 0 else 1 - observed / expected


def _check_pairs(a: list, b: list) -> None:
    if len(a) != len(b):
        raise ValueError(f"Los dos jueces deben etiquetar lo mismo ({len(a)} contra {len(b)})")
    if not a:
        raise ValueError("κ necesita al menos un par etiquetado")


# --- lectura de las planillas llenas ----------------------------------------------------------------------------------


def read_search_sheet(path: Path, counts: Counter | None = None) -> dict[str, int]:
    """{id de par: 2 («sirve»), 1 («a medias») o 0 («no sirve»)}. Las filas sin juicio (`vacias`) y las inválidas
    (`invalidas`: un valor que no existe, sin id, o un id repetido con respuestas distintas) no entran y se cuentan en
    `counts`, junto con las `leidas`."""
    return _read_sheet(path, counts, "id", "juicio", lambda raw: VERDICTS.get(normalize(raw)))


def read_category_sheet(path: Path, counts: Counter | None = None) -> dict[str, str]:
    """{categoría en minúsculas y sin espacios sobrantes (la clave de category_map): id del concepto o «ninguno»}.
    Cuenta las filas como `read_search_sheet`; un concepto que no está en la taxonomía es inválido."""
    valid = {*load_taxonomy().concepts, NO_CONCEPT}

    def concept(raw: str) -> str | None:
        value = raw.strip().lower()
        return value if value in valid else None

    return _read_sheet(path, counts, "categoria", "concepto_correcto", concept, key=lambda raw: raw.strip().lower())


def _read_sheet(
    path: Path,
    counts: Counter | None,
    key_column: str,
    answer_column: str,
    parse: Callable[[str], object],
    key: Callable[[str], str] = str.strip,
) -> dict:
    counts = counts if counts is not None else Counter()
    answers: dict[str, list] = {}
    for row in read_table(path):
        row_key, raw = key(row.get(key_column, "")), row.get(answer_column, "").strip()
        if not raw:
            counts["vacias"] += 1
            continue
        value = parse(raw)
        if not row_key or value is None:
            counts["invalidas"] += 1
            continue
        answers.setdefault(row_key, []).append(value)
    result = {}
    for row_key, given in answers.items():
        if len(set(given)) == 1:
            result[row_key] = given[0]
        else:  # repetida con respuestas distintas: no se sabe cuál vale
            counts["invalidas"] += len(given)
    counts["leidas"] += len(result)
    return result


def _decode(raw: bytes) -> str:
    """Nunca falla: UTF-16 por su BOM («Texto Unicode» de Excel), UTF-8, «CSV» a secas de Excel en Windows (cp1252) y,
    si ni eso (bytes que cp1252 no define, como los de «CSV (Macintosh)»), latin-1, que acepta cualquier byte. El id y
    el juicio son ASCII, así que sobreviven aunque un nombre salga con letras cambiadas."""
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def read_table(path: Path) -> list[dict[str, str]]:
    """Filas de un CSV como lo guardan Numbers (coma) o Excel en español (punto y coma), con o sin BOM."""
    text = unicodedata.normalize("NFC", _decode(path.read_bytes()))  # Numbers puede guardar las tildes descompuestas
    header = text.splitlines()[0] if text.strip() else ""
    delimiter = max(",;\t", key=header.count)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    names = [normalize(name).replace(" ", "_") for name in next(reader, [])]
    return [dict(zip(names, row, strict=False)) for row in reader if any(cell.strip() for cell in row)]


# --- planilla B: pares (consulta, producto) --------------------------------------------------------------------------


def pair_id(vertical: str, query: str, entity_type: str, entity_id: str) -> str:
    """Corto y solo ASCII: sobrevive a cualquier forma de guardar el CSV."""
    return "P" + hashlib.md5("|".join((vertical, query, entity_type, entity_id)).encode()).hexdigest()[:10]  # noqa: S324


def search_pool(runs: list[QueryRun]) -> list[dict]:
    """Los pares que ve el usuario (híbrido mostrado) de las consultas con resultado esperado. `posicion` es el lugar
    en la lista (1 = el primero) y `relevante_auto`, lo que dice el juez por concepto."""
    pool = []
    for run in runs:
        if run.mode != SHOWN or run.tipo == "negativa":
            continue
        for position, (item, relevant) in enumerate(zip(run.items, run.relevance, strict=True), start=1):
            pool.append(
                {
                    "id": pair_id(run.vertical, run.query, item["entity_type"], item["entity_id"]),
                    "vertical": run.vertical,
                    "consulta": run.query,
                    "tipo": run.tipo,
                    "entity_type": item["entity_type"],
                    "entity_id": item["entity_id"],
                    "posicion": position,
                    "relevante_auto": bool(relevant),
                    "nombre": item["texto"],
                    "tienda": item.get("tienda"),
                }
            )
    return pool


def sample_search_pairs(
    pool: list[dict], n: int = SEARCH_PAIRS, seed: int = DEFAULT_SEED, discrepant_share: float = DISCREPANT_SHARE
) -> list[dict]:
    """`n` pares repartidos parejo entre los estratos (vertical, tipo de consulta, top-3 / 4-10), con
    `discrepant_share` de ellos entre los que el juez por concepto y la posición discrepan (un top-3 que el juez da por
    no relevante, o un 4-10 que da por relevante). Mismo pool y semilla, misma muestra."""
    pairs = sorted(
        (
            {
                **p,
                "estrato": "top3" if p["posicion"] <= TOP else "4-10",
                "discrepa": (p["posicion"] <= TOP) != p["relevante_auto"],
            }
            for p in pool
        ),
        key=lambda p: p["id"],
    )
    if len(pairs) <= n:
        return pairs
    rng = random.Random(seed)
    strata = sorted({_stratum(p) for p in pairs})
    rng.shuffle(strata)  # el desempate entre estratos no favorece al orden alfabético
    counts: Counter = Counter()

    def groups(subset: list[dict]) -> dict[tuple, list[dict]]:
        grouped: dict[tuple, list[dict]] = {s: [] for s in strata}
        for p in subset:
            grouped[_stratum(p)].append(p)
        for members in grouped.values():
            rng.shuffle(members)
        return grouped

    discrepant = groups([p for p in pairs if p["discrepa"]])
    others = groups([p for p in pairs if not p["discrepa"]])
    chosen = _spread(discrepant, round(n * discrepant_share), counts, strata)
    chosen += _spread(others, n - len(chosen), counts, strata)
    chosen += _spread(
        discrepant, n - len(chosen), counts, strata
    )  # si faltaron sin discrepancia, vuelven los sobrantes
    return sorted(chosen, key=lambda p: p["id"])


def _stratum(pair: dict) -> tuple:
    return (pair["vertical"], pair["tipo"], pair["estrato"])


def _spread(groups: dict[tuple, list], n: int, counts: Counter, order: list[tuple]) -> list:
    """Saca `n` elementos pidiendo siempre al grupo con menos elegidos hasta ahora (`counts`, compartido entre
    etapas), así ningún estrato manda aunque tenga más pares."""
    chosen = []
    while len(chosen) < n:
        live = [s for s in order if groups.get(s)]
        if not live:
            break
        s = min(live, key=lambda s: (counts[s], order.index(s)))
        chosen.append(groups[s].pop())
        counts[s] += 1
    return chosen


def search_ids_document(sample: list[dict], seed: int = DEFAULT_SEED) -> dict:
    """Lo versionado: ids, consulta, posición, estrato y lo que dijo el juez por concepto. Ningún nombre, categoría
    ni tienda del catálogo."""
    return {
        "nota": "Pares de planilla-busqueda.csv (los textos están en data/eval/, fuera de git); ver eval/sheets.py.",
        "semilla": seed,
        "pares": [{key: pair[key] for key in _IDS_KEYS} for pair in sample],
    }


def category_names(conn: Connection, pairs: list[dict]) -> dict[tuple[str, str], str]:
    """La categoría de cada producto (o la sección de cada plato): {(tipo, id): nombre}."""
    found: dict[tuple[str, str], str] = {}
    for etype, sql in (
        (
            "catalog_item",
            """SELECT ci.master_product_id::text, c.name FROM catalog_items ci
               JOIN categories c USING (category_id) WHERE ci.master_product_id = ANY(%s::bigint[])""",
        ),
        (
            "menu_item",
            """SELECT mi.item_id::text, ms.name FROM menu_items mi
               JOIN menu_sections ms ON ms.store_id = mi.store_id AND ms.section_id = mi.section_id
               WHERE mi.item_id = ANY(%s::bigint[])""",
        ),
    ):
        ids = [p["entity_id"] for p in pairs if p["entity_type"] == etype]
        if ids:
            found.update({(etype, eid): name for eid, name in conn.execute(sql, (ids,))})
    return found


def search_sheet_rows(sample: list[dict], categories: dict[tuple[str, str], str]) -> list[dict]:
    rows = [
        {
            "id": p["id"],
            "consulta": p["consulta"],
            "vertical": p["vertical"],
            "posicion": p["posicion"],
            "nombre": p["nombre"],
            "categoria": categories.get((p["entity_type"], p["entity_id"]), ""),
            "tienda": p.get("tienda") or "",
            "juicio": "",
        }
        for p in sample
    ]
    return sorted(rows, key=lambda r: (r["vertical"], r["consulta"], r["posicion"]))


# --- planilla A: categorías ------------------------------------------------------------------------------------------


def category_details(conn: Connection, keys: list[str]) -> dict[str, dict]:
    """Por clave de categoría (minúsculas): su nombre, su vertical (la de las tiendas que más la venden) y los 8
    productos que más tiendas ofrecen. Una categoría sin productos no aparece."""
    if not keys:
        return {}
    details: dict[str, dict] = {}
    for key, name in conn.execute(
        """SELECT lower(trim(c.name)), min(c.name) FROM categories c
           WHERE lower(trim(c.name)) = ANY(%s)
             AND EXISTS (SELECT 1 FROM catalog_items ci WHERE ci.category_id = c.category_id)
           GROUP BY 1""",
        (keys,),
    ):
        details[key] = {"nombre": name, "vertical": "", "ejemplos": []}
    for key, vertical in conn.execute(
        """SELECT DISTINCT ON (lower(trim(c.name))) lower(trim(c.name)), iv.vertical
           FROM catalog_items ci JOIN categories c USING (category_id)
           JOIN v_item_verticals iv ON iv.master_product_id = ci.master_product_id
           WHERE lower(trim(c.name)) = ANY(%s)
           GROUP BY 1, 2 ORDER BY 1, count(*) DESC, 2""",
        (keys,),
    ):
        details[key]["vertical"] = vertical
    for key, name in conn.execute(
        f"""SELECT key, name FROM (
                SELECT lower(trim(c.name)) AS key, ci.name,
                       row_number() OVER (PARTITION BY lower(trim(c.name))
                                          ORDER BY count(sp.sku) DESC, ci.name, ci.master_product_id) AS rn
                FROM catalog_items ci JOIN categories c USING (category_id)
                LEFT JOIN store_products sp ON sp.master_product_id = ci.master_product_id
                WHERE lower(trim(c.name)) = ANY(%s)
                GROUP BY lower(trim(c.name)), ci.master_product_id, ci.name) t
            WHERE rn <= {EXAMPLES} ORDER BY key, rn""",  # noqa: S608 (constante)
        (keys,),
    ):
        details[key]["ejemplos"].append(name)
    return details


def sample_categories(
    conn: Connection,
    unmapped: list[dict],
    map_rows: list[dict],
    seed: int = DEFAULT_SEED,
    sizes: dict[str, int] | None = None,
) -> list[dict]:
    """Las categorías a juzgar, por grupo: `sin_mapear` (el concepto propuesto es el sugerido, si hay), `juez` y
    `acuerdo` (los de category_map.csv con esa revisión: decididos por el juez o por los dos mapeadores, de control).
    Repartidas parejo entre verticales; la persona no ve el grupo."""
    sizes = sizes or CATEGORY_SIZES
    candidates = {
        "sin_mapear": [(row["nombre"].strip().lower(), row["sugerido"] or "") for row in unmapped],
        **{
            group: [(row["nombre"].strip().lower(), row["concept_id"]) for row in map_rows if _is(row, group)]
            for group in ("juez", "acuerdo")
        },
    }
    details = category_details(conn, sorted({key for pairs in candidates.values() for key, _ in pairs}))
    rng = random.Random(seed)
    chosen = []
    for group, size in sizes.items():
        by_vertical: dict[tuple, list[dict]] = {}
        for key, proposed in sorted(candidates[group]):
            if key in details:
                row = {"clave": key, "grupo": group, "concepto_propuesto": proposed, **details[key]}
                by_vertical.setdefault((row["vertical"],), []).append(row)
        for members in by_vertical.values():
            rng.shuffle(members)
        order = sorted(by_vertical)
        rng.shuffle(order)
        chosen += _spread(by_vertical, size, Counter(), order)
    return sorted(chosen, key=lambda r: (r["vertical"], r["clave"]))


def _is(row: dict, group: str) -> bool:
    return row["tipo"] == "categoria" and row["revision"] == group


def category_sheet_rows(sample: list[dict]) -> list[dict]:
    return [
        {
            "vertical": r["vertical"],
            "categoria": r["nombre"],
            "ejemplos": " | ".join(r["ejemplos"]),
            "concepto_propuesto": r["concepto_propuesto"],
            "concepto_correcto": "",
        }
        for r in sample
    ]


def category_ids_document(sample: list[dict], seed: int = DEFAULT_SEED) -> dict:
    return {
        "nota": "Categorías de planilla-categorias.csv; los ejemplos de productos están en data/eval/, fuera de git.",
        "semilla": seed,
        "categorias": [
            {key: row[key] for key in ("clave", "vertical", "grupo", "concepto_propuesto")} for row in sample
        ],
    }


# --- salida ----------------------------------------------------------------------------------------------------------


def count_filled(path: Path, column: str) -> int:
    if not path.exists():
        return 0
    return sum(bool(row.get(column, "").strip()) for row in read_table(path))


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    """Con BOM: Excel abre así un CSV UTF-8 sin deformar las tildes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def readme_text() -> str:
    taxonomy = load_taxonomy()
    concepts = "\n".join(
        f"- `{c.id}`: {c.label}" for c in sorted(taxonomy.concepts.values(), key=lambda c: (c.parent or "", c.id))
    )
    return f"""# Planillas para juzgar a mano

Dos planillas CSV. Se abren en Numbers o Excel, se llena **una sola columna** y se guarda como CSV (UTF-8) con el
mismo nombre, en esta misma carpeta. **Guarda como CSV UTF-8** (en Numbers: Archivo › Exportar a › CSV, codificación
Unicode UTF-8; en Excel: Datos › Desde texto/CSV para abrir, y Guardar como › CSV UTF-8). No cambies las demás
columnas ni el orden de las filas. Lo que quede en blanco se ignora, así que puedes juzgar de a ratos y guardar.

## `{SEARCH_SHEET}`: ¿sirve este resultado para la búsqueda?

Cada fila es una búsqueda y un producto que la app mostró en esa posición (1 es el primero). Piensa en alguien que
escribió esa consulta en ese vertical y llena la columna `juicio` con exactamente uno de estos valores:

- `sirve`: es lo que esa persona quería encontrar.
- `a medias`: se parece o sirve para parte de lo que pedía (otra marca o formato que podría aceptar).
- `no sirve`: no tiene que ver con lo que pedía.

## `{CATEGORY_SHEET}`: ¿qué concepto es esta categoría?

Cada fila es una categoría del catálogo con 8 ejemplos de sus productos y el concepto que se le propone hoy
(`concepto_propuesto`, puede estar vacío). En la columna `concepto_correcto` escribe el id del concepto que mejor
la describe, copiado de la lista de abajo, o `ninguno` si la categoría mezcla cosas que no caben en un solo concepto.
Si la propuesta está bien, escríbela igual: así sabemos que la revisaste.

Conceptos posibles:

{concepts}

## Después

Con las planillas llenas, `rappi-ia eval-human` calcula cuánto coincide el juez por concepto con tu juicio (κ de
Cohen contra «sirve» y κ ponderado con los tres valores). Si vuelves a correr `rappi-ia jev-planillas` con una
planilla ya llena, se niega a pisarla (`--forzar` la reemplaza).
"""


def shortfalls(summary: dict) -> list[str]:
    """Lo que quedó bajo la meta (200 pares; 40 / 30 / 30 categorías) de lo que devolvió `build_sheets`."""
    missing = []
    if summary["pares"] < SEARCH_PAIRS:
        missing.append(f"búsqueda: {summary['pares']} de {SEARCH_PAIRS} pares")
    for group, target in CATEGORY_SIZES.items():
        got = summary["categorias"].get(group, 0)
        if got < target:
            missing.append(f"{group.replace('_', ' ')}: {got} de {target}")
    return missing


def build_sheets(
    conn: Connection,
    runs: list[QueryRun],
    out_dir: Path | None = None,
    ids_dir: Path = EVAL_DIR,
    seed: int = DEFAULT_SEED,
    map_rows: list[dict] | None = None,
    force: bool = False,
    pairs: int = SEARCH_PAIRS,
    category_sizes: dict[str, int] | None = None,
) -> dict:
    """Escribe las dos planillas y el LEEME en `out_dir` (por defecto `data/eval/`) y los ids en `ids_dir`.
    Se niega (`SheetInUse`) a pisar una planilla que ya tiene juicios, salvo `force`."""
    out_dir = out_dir or sheet_dir()
    if not force:
        for name, column in ((SEARCH_SHEET, "juicio"), (CATEGORY_SHEET, "concepto_correcto")):
            filled = count_filled(out_dir / name, column)
            if filled:
                raise SheetInUse(f"{out_dir / name} ya tiene {filled} juicios; usa --forzar si quieres reemplazarla")
    sample = sample_search_pairs(search_pool(runs), pairs, seed)
    write_csv(out_dir / SEARCH_SHEET, SEARCH_COLUMNS, search_sheet_rows(sample, category_names(conn, sample)))
    write_json(ids_dir / SEARCH_IDS_FILE.name, search_ids_document(sample, seed))

    map_rows = read_category_map_csv() if map_rows is None else map_rows
    categories = sample_categories(conn, coverage_report(conn)["categorias_sin_mapear"], map_rows, seed, category_sizes)
    write_csv(out_dir / CATEGORY_SHEET, CATEGORY_COLUMNS, category_sheet_rows(categories))
    write_json(ids_dir / CATEGORY_IDS_FILE.name, category_ids_document(categories, seed))
    (out_dir / README_FILE).write_text(readme_text(), encoding="utf-8")
    return {
        "pares": len(sample),
        "pares_discrepantes": sum(p["discrepa"] for p in sample),
        "categorias": dict(Counter(r["grupo"] for r in categories)),
    }
