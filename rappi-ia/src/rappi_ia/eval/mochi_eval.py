"""Evaluación de Mochi (`rappi-ia eval-mochi`): revisiones automáticas de sus respuestas, sin juez, y el juicio LLM de
tres niveles (eval/graded.py) donde lo hay. Solo lee la base.

Sets (cada frase, un primer turno, como lo pregunta la app):
- `necesidades`: las consultas "necesidad" de eval/queries.json, desde la pantalla de su vertical.
- `libres`: eval/frases_usuarios/preguntas-libres.txt, desde el buscador de la Home (sin vertical).
- `conversaciones`: el primer turno de cada conversación de eval/frases_usuarios/conversaciones.txt, igual.
- `apartado`: eval/mochi-heldout.json, frases de "producto + ocasión" y de bebé que no se usan para ajustar.

Revisiones (en las respuestas con productos):
- (a) Texto contra lo mostrado: lo que anuncia el texto ("Mira estas opciones de 🥤 bebidas gaseosas…": un concepto o
  una ocasión) tiene que ser de algún producto mostrado; se cuentan las que no tienen ninguno ("contradice") y las que
  tienen menos de la mitad.
- (b) "En X no hay…": si `search_products` en X trae productos de eso (del concepto que nombra o, si nombra un detalle
  como "lúcuma", del pedido y con el detalle en el nombre), el texto dice algo falso.
- (c) Duplicados: el mismo producto (tipo e id) dos veces.
- (d) Cuántos productos muestra: el promedio y las respuestas con menos de FEW.

Con los juicios de tres niveles (juicio LLM, no humano) de las necesidades: nDCG@6 (Mochi muestra hasta 6), P@3
"sirve" y útil@3 de Mochi y de `/search` en las mismas consultas, con cuántos de los productos mostrados tienen
juicio, y la diferencia consulta por consulta con su IC 95 % por bootstrap (semilla fija: el reporte es reproducible).

Regresiones (`eval-mochi --revisar`, `make eval-check`): contra la última corrida guardada (`--guardar-listas`,
eval/mochi-listas-AAAA-MM-DD.json), una necesidad que pierde un "sirve" de sus 3 primeros o muestra menos productos
(graded.regressions); un texto que contradice lo mostrado, un "No hay" falso o un duplicado (tienen que ser 0), y más
respuestas con menos de FEW productos, con menos de la mitad de lo anunciado o sin productos que en la corrida guardada
(esas no parten en 0: algunas lo son a propósito). Siempre con plantillas: con Claude el texto cambia de una vez a otra.
"""

import json
import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from psycopg import Connection

from ..agent.compose import _mid_sentence
from ..agent.rappi_agent import Context, RappiAgent
from ..agent.tools import VERTICAL_LABELS, search_products
from ..concepts.taxonomy import Taxonomy, load_taxonomy
from ..embeddings.base import TextEmbedder
from ..text import normalize, tokens
from . import graded, search_eval

EVAL_DIR = Path(__file__).resolve().parent
HELDOUT_FILE = EVAL_DIR / "mochi-heldout.json"
FREE_FILE = EVAL_DIR / "frases_usuarios" / "preguntas-libres.txt"
CONVERSATIONS_FILE = EVAL_DIR / "frases_usuarios" / "conversaciones.txt"
SETS = ("necesidades", "libres", "conversaciones", "apartado")
FEW = 4  # menos productos que esto es una respuesta corta
SHOWN_MAX = 6  # lo que muestra Mochi: el nDCG cuenta estos puestos
HALF = 0.5
LISTS_GLOB = "mochi-listas-*.json"  # lo que mostró Mochi en una fecha (`eval-mochi --guardar-listas`), en EVAL_DIR
MUST_BE_ZERO = {
    "contradice": "Texto que contradice lo mostrado",
    "no_hay_falso": '"No hay" falso',
    "duplicados": "Con duplicados",
}
NOT_ABOVE_SAVED = {
    "cortas": f"Menos de {FEW} productos",
    "menos_de_la_mitad": "Menos de la mitad de lo anunciado",
    "sin_productos": "Sin productos",
}
_LEADS = re.compile(r"(?:Mira estas opciones de|Otras opciones de|Lo más barato de) ")
_ABSENT = re.compile(r'En (?P<here>.+?) no hay (?P<what>"[^"]+"|.+?), pero en (?P<there>.+?) sí')
_VERTICALS_BY_LABEL = {label: code for code, label in VERTICAL_LABELS.items()}

Search = Callable[[str, str, list[str] | None], list[dict]]  # (vertical, consulta, conceptos) → productos (to_dict)


@dataclass
class MochiRun:
    set: str
    vertical: str | None  # la pantalla desde donde se pregunta
    query: str
    tipo: str
    intent: str
    text: str
    products: list[dict]  # entity_type, entity_id, name, concept, vertical
    share: float | None = None  # (a) parte de lo mostrado que es de lo que anuncia el texto (None: no anuncia nada)
    announced: str | None = None
    says_absent: bool = False  # (b) el texto dice "En X no hay…"
    absent: str | None = None  # (b) lo que dice que no hay y sí trae la búsqueda
    duplicates: list[str] = field(default_factory=list)  # (c)
    ms: float = 0.0


def load_cases(
    queries_file: Path = search_eval.QUERIES_FILE,
    free_file: Path = FREE_FILE,
    conversations_file: Path = CONVERSATIONS_FILE,
    heldout_file: Path = HELDOUT_FILE,
) -> list[dict]:
    needs = [
        {"set": "necesidades", "vertical": q["vertical"], "query": q["query"], "tipo": q["tipo"]}
        for q in search_eval.load_queries(queries_file)
        if q["tipo"] == "necesidad"
    ]
    free = [{"set": "libres", "vertical": None, "query": line, "tipo": ""} for line in _phrases(free_file)]
    first = [
        {"set": "conversaciones", "vertical": None, "query": line, "tipo": ""} for line in _phrases(conversations_file)
    ]
    heldout = [
        {"set": "apartado", "vertical": q["vertical"], "query": q["query"], "tipo": q["tipo"]}
        for q in json.loads(heldout_file.read_text(encoding="utf-8"))["queries"]
    ]
    return needs + free + first + heldout


def _phrases(path: Path) -> list[str]:
    """Las frases de un archivo de frases_usuarios: sin comentarios (#) ni seguimientos (+): solo primeros turnos."""
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith(("#", "+"))]


def announce_labels(taxonomy: Taxonomy) -> dict[str, set[str]]:
    """{cómo nombra el texto un concepto u ocasión, en medio de la frase: los conceptos que cubre}."""
    labels = {_mid_sentence(c.label): {c.id} for c in taxonomy.concepts.values()}
    labels |= {f"{o.name.lower()} {o.emoji}": set(o.concepts) for o in taxonomy.occasions.values()}
    return labels


def announced(text: str, labels: dict[str, set[str]]) -> str | None:
    """El concepto u ocasión que anuncia el texto ("Mira estas opciones de 🥤 bebidas gaseosas en Licores.")."""
    for lead in _LEADS.finditer(text):
        rest = text[lead.end() :]
        if found := max((label for label in labels if rest.startswith(label)), key=len, default=None):
            return found
    return None


def announced_share(response: dict, labels: dict[str, set[str]]) -> tuple[str | None, float | None]:
    """(lo que anuncia el texto, parte de los productos mostrados que es de eso); (None, None) si no anuncia nada o no
    muestra productos."""
    label = announced(response["text"], labels)
    products = response["products"]
    if label is None or not products:
        return None, None
    return label, sum(p.get("concept") in labels[label] for p in products) / len(products)


def claimed_absent(text: str) -> tuple[str, str] | None:
    """(vertical, qué) de un "En X no hay …, pero en Y sí" (no de un "casi no hay")."""
    match = _ABSENT.search(text)
    if not match or match.group("here") not in _VERTICALS_BY_LABEL:
        return None
    return _VERTICALS_BY_LABEL[match.group("here")], match.group("what").strip('"')


def false_absence(response: dict, taxonomy: Taxonomy, search: Search) -> str | None:
    """Si el texto dice que en X no hay algo y la búsqueda en X sí lo trae: qué y cuántos; si no, None."""
    claim = claimed_absent(response["text"])
    if claim is None:
        return None
    vertical, what = claim
    said = normalize(what)
    concept = next(
        (c for c in taxonomy.concepts.values() if said in (normalize(c.name), normalize(_mid_sentence(c.label)))), None
    )
    if concept is not None:
        found = [p for p in search(vertical, concept.name, [concept.id]) if p.get("concept") == concept.id]
    else:  # un detalle del pedido ("lúcuma"): los productos del pedido que lo dicen en su nombre
        concepts = response["intent"].get("concepts") or None
        query = response["intent"].get("query") or what
        found = [
            p
            for p in search(vertical, query, concepts)
            if _says(p["name"], what) and (not concepts or p.get("concept") in concepts)
        ]
    return f'{len(found)} de "{what}" en {vertical}' if found else None


def _says(name: str, what: str) -> bool:
    """El nombre tiene cada palabra de `what` (sus primeras 5 letras): "Helado Lúcuma" dice "lúcuma"."""
    words = tokens(name)
    return all(any(w.startswith(root[:5]) for w in words) for root in tokens(what))


def duplicates(response: dict) -> list[str]:
    seen, repeated = set(), []
    for p in response["products"]:
        key = f"{p['entity_type']}:{p['entity_id']}"
        if key in seen:
            repeated.append(key)
        seen.add(key)
    return repeated


def check(response: dict, labels: dict[str, set[str]], taxonomy: Taxonomy, search: Search) -> dict:
    """Las revisiones (a), (b) y (c) de una respuesta."""
    label, share = announced_share(response, labels)
    return {
        "announced": label,
        "share": share,
        "says_absent": claimed_absent(response["text"]) is not None,
        "absent": false_absence(response, taxonomy, search),
        "duplicates": duplicates(response),
    }


def run_cases(conn: Connection, embedder: TextEmbedder | None, cases: list[dict]) -> list[MochiRun]:
    agent = RappiAgent(embedder)
    taxonomy = load_taxonomy()
    labels = announce_labels(taxonomy)

    def search(vertical: str, query: str, concepts: list[str] | None) -> list[dict]:
        found = search_products(conn, vertical, query, concepts, embedder, k=search_eval.K)
        return [p.to_dict() for p in found.products]

    runs = []
    for case in cases:
        start = time.perf_counter()
        response = agent.reply(conn, case["query"], Context(vertical=case["vertical"]))
        ms = (time.perf_counter() - start) * 1000
        runs.append(
            MochiRun(
                case["set"],
                case["vertical"],
                case["query"],
                case["tipo"],
                response["intent"]["kind"],
                response["text"],
                [
                    {key: p.get(key) for key in ("entity_type", "entity_id", "name", "concept", "vertical")}
                    for p in response["products"]
                ],
                ms=ms,
                **check(response, labels, taxonomy, search),
            )
        )
    return runs


def graded_lists(runs: list[MochiRun]) -> list[dict]:
    """Lo que mostró Mochi en las necesidades, como las listas de eval/graded.py (el par lleva la vertical de la
    pantalla: la de la consulta en queries.json)."""
    return [
        {
            "vertical": r.vertical,
            "consulta": r.query,
            "tipo": r.tipo,
            "productos": [[p["entity_type"], p["entity_id"]] for p in r.products],
        }
        for r in runs
        if r.set == "necesidades"
    ]


def search_lists(conn: Connection, embedder: TextEmbedder, runs: list[MochiRun]) -> list[dict]:
    """Lo que muestra `/search` en las mismas necesidades (sus primeros SHOWN_MAX, como Mochi)."""
    needs = [
        {"vertical": r.vertical, "query": r.query, "tipo": r.tipo, "concepts": []}
        for r in runs
        if r.set == "necesidades"
    ]
    found = search_eval.run_queries(conn, embedder, needs, modes=(search_eval.SHOWN,))
    return [{**shown, "productos": shown["productos"][:SHOWN_MAX]} for shown in graded.shown_lists(found)]


def saved_run(runs: list[MochiRun]) -> dict:
    """Lo que se guarda para `--revisar` (sin textos del catálogo): lo que mostró Mochi en las necesidades (ids) y los
    totales de las revisiones que se comparan."""
    totals = summary(runs)["total"]
    return {
        "nota": "Lo que mostró Mochi en las necesidades (ids) y los totales de sus revisiones automáticas, con"
        " plantillas; ver eval/mochi_eval.py.",
        "revisiones": {key: totals[key] for key in (*MUST_BE_ZERO, *NOT_ABOVE_SAVED)},
        "listas": graded_lists(runs),
    }


def regressions(saved: dict, runs: list[MochiRun], judgments: dict[str, graded.Judged]) -> list[str]:
    """Lo que empeora contra una corrida guardada (`saved_run`): las necesidades, como en graded.regressions; las
    revisiones de MUST_BE_ZERO que no dan 0 y las de NOT_ABOVE_SAVED que suben."""
    found = graded.regressions(saved["listas"], graded_lists(runs), judgments)
    totals = summary(runs)["total"]
    found += [f"{label}: {totals[key]} (tiene que ser 0)" for key, label in MUST_BE_ZERO.items() if totals[key]]
    found += [
        f"{label}: {saved['revisiones'][key]} → {totals[key]}"
        for key, label in NOT_ABOVE_SAVED.items()
        if totals[key] > saved["revisiones"][key]
    ]
    return found


def summary(runs: list[MochiRun]) -> dict:
    """Por set y en total: casos, con productos, promedio de productos, cortas (< FEW), (a), (b) y (c)."""
    groups = {name: [r for r in runs if r.set == name] for name in SETS}
    groups["total"] = runs
    out = {}
    for name, rows in groups.items():
        shown = [r for r in rows if r.products]
        out[name] = {
            "casos": len(rows),
            "con_productos": len(shown),
            "sin_productos": len(rows) - len(shown),
            "promedio": round(sum(len(r.products) for r in shown) / len(shown), 1) if shown else None,
            "cortas": sum(len(r.products) < FEW for r in shown),
            "anuncia": sum(r.share is not None for r in rows),
            "contradice": sum(r.share == 0 for r in rows),
            "menos_de_la_mitad": sum(r.share is not None and 0 < r.share < HALF for r in rows),
            "dice_no_hay": sum(r.says_absent for r in rows),
            "no_hay_falso": sum(r.absent is not None for r in rows),
            "duplicados": sum(bool(r.duplicates) for r in rows),
        }
    return out


def render_markdown(runs: list[MochiRun], mochi_scores: dict | None = None, search_scores: dict | None = None) -> str:
    totals = summary(runs)
    lines = [
        "# Mochi: revisiones automáticas y juicio de tres niveles",
        "",
        "**Revisiones automáticas** (evaluación automática, sin juez): el primer turno de cada frase con el agente de"
        " `/agent/ask` (plantillas, sin Claude), sobre la base de `DATABASE_URL` en solo lectura. Ver"
        " eval/mochi_eval.py.",
        "",
        "| Set | Casos | Con productos | Productos (promedio) | Menos de 4 | Texto que contradice lo mostrado"
        ' | Menos de la mitad de lo anunciado | "No hay" falso | Con duplicados |',
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name in (*SETS, "total"):
        t = totals[name]
        lines.append(
            f"| {name} | {t['casos']} | {t['con_productos']} | {t['promedio']} | {t['cortas']}"
            f" | {t['contradice']} de {t['anuncia']} | {t['menos_de_la_mitad']}"
            f" | {t['no_hay_falso']} de {t['dice_no_hay']} | {t['duplicados']} |"
        )
    flagged = [r for r in runs if r.share == 0 or (r.share is not None and r.share < HALF) or r.absent or r.duplicates]
    if flagged:
        lines += ["", "## Revisiones que fallan", "", "| Set | Pantalla | Frase | Qué falla | Texto | Productos |"]
        lines.append("|---|---|---|---|---|---|")
        lines += [_flag_row(r) for r in flagged]
    short = [r for r in runs if r.products and len(r.products) < FEW]
    if short:
        lines += [
            "",
            f"## Respuestas con menos de {FEW} productos",
            "",
            "| Set | Pantalla | Frase | Productos | Texto |",
        ]
        lines.append("|---|---|---|---|---|")
        lines += [f"| {r.set} | {r.vertical or '-'} | {r.query} | {len(r.products)} | {_cell(r.text)} |" for r in short]
    empty = [r for r in runs if not r.products]
    if empty:
        lines += [
            "",
            "## Respuestas sin productos",
            "",
            "| Set | Pantalla | Frase | Intención | Texto |",
            "|---|---|---|---|---|",
        ]
        lines += [f"| {r.set} | {r.vertical or '-'} | {r.query} | {r.intent} | {_cell(r.text)} |" for r in empty]
    if mochi_scores and search_scores:
        lines += ["", *_graded_part(mochi_scores, search_scores)]
    return "\n".join(lines) + "\n"


def _graded_part(mochi: dict, search: dict) -> list[str]:
    m, s = mochi["total"], search["total"]
    lines = [
        "## Necesidades con el juez de tres niveles (juicio LLM, no humano)",
        "",
        f"Las necesidades de queries.json con algún par juzgado ({m['n']}), con los juicios de eval/graded.py: lo que"
        f" muestra Mochi (hasta {SHOWN_MAX}) y los {SHOWN_MAX} primeros de `/search` en la misma vertical. Un producto"
        " sin juicio se salta en el nDCG y cuenta como que no sirve en P@3.",
        "",
    ]
    if m["sin_juicio"] or s["sin_juicio"]:
        lines += [
            f"> **{m['sin_juicio']} productos de Mochi y {s['sin_juicio']} de `/search` sin juicio: las cifras no son"
            " comparables con otra fecha.** La fila de las consultas juzgadas completas sí.",
            "",
        ]
    lines += [
        f'| | Consultas | nDCG@{SHOWN_MAX} | P@3 "sirve" | Útil@3 | "No sirve" entre lo juzgado | Mostrados'
        " | Sin juicio |",
        "|---|---|---|---|---|---|---|---|",
        graded._row("Mochi", m),
        graded._row("/search", s),
        graded._row("Mochi: juzgadas completas", mochi["completas"]),
        graded._row("/search: juzgadas completas", search["completas"]),
    ]
    diffs = [paired_difference(mochi["consultas"], search["consultas"], metric) for metric in ("ndcg", "p@3")]
    if diffs[0]["n"]:
        lines += [
            "",
            f"Diferencia Mochi − `/search` consulta por consulta ({diffs[0]['n']} consultas; IC 95 % por bootstrap de"
            f" {search_eval.BOOTSTRAP_RESAMPLES} remuestreos, semilla 7):",
            "",
            "| Métrica | Sube | Empata | Baja | Diferencia media | IC 95 % |",
            "|---|---|---|---|---|---|",
        ]
        for label, d in zip((f"nDCG@{SHOWN_MAX}", 'P@3 "sirve"'), diffs, strict=True):
            low, high = d["ic95"]
            counts = f"{d['sube']} | {d['empata']} | {d['baja']}"
            lines.append(f"| {label} | {counts} | {d['diferencia']} | {low} a {high} |")
        lines += ["", "Si el intervalo incluye el 0, la diferencia no es concluyente con estas consultas."]
    return lines


def paired_difference(a: list[dict], b: list[dict], metric: str, seed: int = 7) -> dict:
    """`metric` de `a` menos la de `b` en las consultas que están en las dos (filas de graded.score()["consultas"]):
    cuántas suben, empatan y bajan, y la diferencia media con su IC 95 % por bootstrap, como
    search_eval.paired_comparison."""
    by_query = [{(r["vertical"], r["consulta"]): r[metric] for r in rows} for rows in (a, b)]
    keys = sorted(by_query[0].keys() & by_query[1].keys())
    diffs = [by_query[0][key] - by_query[1][key] for key in keys]
    rng = random.Random(seed)
    resamples = search_eval.BOOTSTRAP_RESAMPLES if diffs else 0
    means = sorted(sum(rng.choices(diffs, k=len(diffs))) / len(diffs) for _ in range(resamples))
    return {
        "n": len(diffs),
        "sube": sum(d > 1e-9 for d in diffs),
        "empata": sum(abs(d) <= 1e-9 for d in diffs),
        "baja": sum(d < -1e-9 for d in diffs),
        "diferencia": round(sum(diffs) / len(diffs), 3) if diffs else None,
        "ic95": (round(means[int(0.025 * len(means))], 3), round(means[int(0.975 * len(means)) - 1], 3))
        if means
        else None,
    }


def _flag_row(r: MochiRun) -> str:
    what = []
    if r.share is not None and r.share < HALF:
        what.append(f'anuncia "{r.announced}" y {round(r.share * len(r.products))} de {len(r.products)} lo son')
    if r.absent:
        what.append(f'dice "no hay" y la búsqueda trae {r.absent}')
    if r.duplicates:
        what.append(f"repite {', '.join(r.duplicates)}")
    names = "; ".join(p["name"] for p in r.products[:4])
    return f"| {r.set} | {r.vertical or '-'} | {r.query} | {'; '.join(what)} | {_cell(r.text)} | {_cell(names)} |"


def _cell(text: str, limit: int = 160) -> str:
    text = text.replace("|", "/").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"
