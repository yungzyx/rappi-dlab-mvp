"""Rol B de Jev: juez de la búsqueda, junto al juez por concepto y a las personas.

El juez por concepto es binario y usa la misma etiqueta con que el híbrido refuerza sus resultados; Jev lee la consulta
y el resultado (nombre, categoría, tienda) y reparte probabilidad entre tres niveles. Su juicio es la ganancia
esperada Σ p(nivel)·{0, ½, 1}, un número entre 0 y 1 que entra a nDCG sin binarizar. Los juicios quedan en
`eval_judgments`, con la versión del modelo en la clave, para pagar una sola vez por cada par mientras el modelo no
cambie. `judge_pairs` no mira si Jev está adoptado: el piloto lo necesita antes de que alguien lo adopte.
"""

import logging
from dataclasses import dataclass

from psycopg import Connection
from psycopg.types.json import Jsonb

from ..jev import JevClient, Score
from .search_eval import SHOWN, QueryRun, ndcg_at_k, precision_at_k, reciprocal_rank, summarize
from .sheets import category_names, pair_id

log = logging.getLogger(__name__)

QUESTION = "relevancia"
INSTRUCTIONS = (
    "Eres el juez de un buscador de Rappi Chile. El estado trae lo que una persona escribió en el buscador de un"
    " vertical (consulta, vertical) y un resultado que el buscador le mostró (nombre, categoría y tienda)."
    " Decide cuánto le sirve ese resultado a quien escribió la consulta."
)
CRITERIA = [
    "No sirve: es otro tipo de producto",
    "Sirve a medias: está relacionado o es un sustituto razonable",
    "Sirve: es lo que pide la consulta",
]
GAINS = (0.0, 0.5, 1.0)  # ganancia de cada nivel de CRITERIA
RELEVANT_GAIN = 0.5  # desde aquí un resultado cuenta como relevante para el MRR (que necesita un sí o un no)


@dataclass(frozen=True)
class JevJudgment:
    gain: float  # ganancia esperada, 0..1
    probabilities: dict[str, float]  # lo que devolvió Jev por nivel: {"0": p, "1": p, "2": p}


def expected_gain(probabilities: dict[str, float]) -> float | None:
    """Σ p(nivel)·ganancia del nivel, repartida sobre la masa total. None si Jev no dio probabilidades."""
    total = sum(probabilities.get(str(level), 0.0) for level in range(len(GAINS)))
    if total <= 0:
        return None
    return sum(probabilities.get(str(level), 0.0) * gain for level, gain in enumerate(GAINS)) / total


def pairs_from_runs(runs: list[QueryRun]) -> list[dict]:
    """Los pares (consulta, resultado) distintos de las consultas con resultado esperado, de todos los modos. La tienda
    solo se conoce en lo que se muestra al usuario."""
    pairs: dict[str, dict] = {}
    for run in runs:
        if run.tipo == "negativa":
            continue
        for item in run.items:
            key = pair_id(run.vertical, run.query, item["entity_type"], item["entity_id"])
            pair = pairs.setdefault(
                key,
                {
                    "consulta": run.query,
                    "vertical": run.vertical,
                    "entity_type": item["entity_type"],
                    "entity_id": item["entity_id"],
                    "nombre": item["texto"],
                    "tienda": None,
                },
            )
            pair["tienda"] = pair["tienda"] or item.get("tienda")
    return list(pairs.values())


def judge_pairs(conn: Connection, client: JevClient, pairs: list[dict]) -> dict[str, JevJudgment]:
    """{id de par: juicio}. Lee primero `eval_judgments` (mismo modelo) y solo le pregunta a Jev lo que falta; lo nuevo
    se guarda. Un par que Jev no responde (falla o tope de llamadas) no está en el resultado ni se guarda, así la
    próxima corrida lo vuelve a intentar. Cada par lleva consulta, vertical, entity_type y entity_id, y opcionalmente
    nombre (si no se encuentra en la base) y tienda. No hace commit."""
    keyed = {pair_id(p["vertical"], p["consulta"], p["entity_type"], p["entity_id"]): p for p in pairs}
    if not keyed:
        return {}
    judgments = _read_cache(conn, client.model, keyed)
    missing = [key for key in keyed if key not in judgments]
    if missing:
        asked = [keyed[key] for key in missing]
        names, categories = item_names(conn, asked), category_names(conn, asked)
        questions = {QUESTION: Score(INSTRUCTIONS, CRITERIA)}
        answers = client.ask_many([(_state(p, names, categories), questions) for p in asked])
        fresh = {}
        for key, answer in zip(missing, answers, strict=True):
            judgment = _judgment(answer[QUESTION]) if answer else None
            if judgment:
                fresh[key] = judgment
        _save(conn, client.model, keyed, fresh)
        judgments.update(fresh)
        if len(fresh) < len(missing):
            log.warning(
                "Jev dejó %s de %s pares sin juicio; se vuelven a pedir la próxima vez",
                len(missing) - len(fresh),
                len(missing),
            )
    return judgments


def item_names(conn: Connection, pairs: list[dict]) -> dict[tuple[str, str], str]:
    """El nombre de cada producto o plato: {(tipo, id): nombre}."""
    found: dict[tuple[str, str], str] = {}
    for etype, sql in (
        (
            "catalog_item",
            "SELECT master_product_id::text, name FROM catalog_items WHERE master_product_id = ANY(%s::bigint[])",
        ),
        ("menu_item", "SELECT item_id::text, name FROM menu_items WHERE item_id = ANY(%s::bigint[])"),
    ):
        ids = [p["entity_id"] for p in pairs if p["entity_type"] == etype]
        if ids:
            found.update({(etype, eid): name for eid, name in conn.execute(sql, (ids,))})
    return found


def _state(pair: dict, names: dict, categories: dict) -> dict:
    key = (pair["entity_type"], pair["entity_id"])
    return {
        "consulta": pair["consulta"],
        "vertical": pair["vertical"],
        "resultado": {
            "nombre": names.get(key) or pair.get("nombre") or "",
            "categoria": categories.get(key, ""),
            "tienda": pair.get("tienda") or "",
        },
    }


def _judgment(answer) -> JevJudgment | None:
    """Con probabilidades, la ganancia esperada. Sin ellas (o sin masa en los tres niveles), el nivel que dio Jev, para
    que el par igual quede en la caché."""
    gain = expected_gain(answer.probabilities)
    if gain is not None:
        # 6 decimales: la columna es `real` y lo guardado debe leerse igual a lo calculado.
        probabilities = {str(level): answer.probabilities.get(str(level), 0.0) for level in range(len(GAINS))}
        return JevJudgment(round(gain, 6), probabilities)
    if answer.score is None:
        return None
    return JevJudgment(min(1.0, max(0.0, answer.score / (len(GAINS) - 1))), {})


def _read_cache(conn: Connection, model: str, keyed: dict[str, dict]) -> dict[str, JevJudgment]:
    by_key = {(p["consulta"], p["vertical"], p["entity_type"], p["entity_id"]): key for key, p in keyed.items()}
    columns = list(zip(*by_key, strict=True))
    rows = conn.execute(
        """SELECT e.query, e.vertical, e.entity_type, e.entity_id, e.score, e.probabilities
           FROM eval_judgments e
           JOIN unnest(%s::text[], %s::text[], %s::text[], %s::text[]) AS k(query, vertical, entity_type, entity_id)
             USING (query, vertical, entity_type, entity_id)
           WHERE e.judge = 'jev' AND e.model_version = %s""",
        (*(list(column) for column in columns), model),
    ).fetchall()
    return {by_key[row[:4]]: JevJudgment(round(row[4], 6), row[5] or {}) for row in rows}


def _save(conn: Connection, model: str, keyed: dict[str, dict], fresh: dict[str, JevJudgment]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO eval_judgments (query, vertical, entity_type, entity_id, judge, model_version, score,
                                           probabilities)
               VALUES (%s, %s, %s, %s, 'jev', %s, %s, %s)
               ON CONFLICT DO NOTHING""",
            [
                (p["consulta"], p["vertical"], p["entity_type"], p["entity_id"], model, j.gain, Jsonb(j.probabilities))
                for key, j in fresh.items()
                for p in [keyed[key]]
            ],
        )


# --- métricas y reporte --------------------------------------------


def jev_means(runs: list[QueryRun], judgments: dict[str, JevJudgment]) -> dict[str, dict]:
    """P@10, MRR y nDCG@10 por modo (consultas con resultado esperado) con la ganancia de Jev en vez de 0 o 1. P@10 y
    nDCG@10 usan la ganancia tal cual; el MRR, que necesita un sí o un no, cuenta como relevante desde `RELEVANT_GAIN`.
    Un resultado sin juicio de Jev vale 0 y se cuenta en `sin_juicio`."""
    means: dict[str, dict] = {}
    for mode in dict.fromkeys(r.mode for r in runs):
        positives = [r for r in runs if r.mode == mode and r.tipo != "negativa"]
        if not positives:
            continue
        gains = [_gains(r, judgments) for r in positives]
        n = len(positives)
        means[mode] = {
            "n": n,
            "p@10": round(sum(precision_at_k(g) for g in gains) / n, 3),
            "mrr": round(sum(reciprocal_rank([int(x >= RELEVANT_GAIN) for x in g]) for g in gains) / n, 3),
            "ndcg@10": round(sum(ndcg_at_k(g) for g in gains) / n, 3),
            "sin_juicio": sum(_pair(r, item) not in judgments for r in positives for item in r.items),
        }
    return means


def jev_report(runs: list[QueryRun], judgments: dict[str, JevJudgment], human: dict[str, int], model: str) -> dict:
    """Lo que el reporte necesita de Jev: sus métricas junto a las del juez por concepto, los pares que quedaron sin
    juicio y, si hay planilla juzgada, los tres jueces sobre los mismos pares (`human`: nivel 0, 1 o 2 por id)."""
    concept = summarize(runs)
    jev = jev_means(runs, judgments)
    asked = {_pair(r, item) for r in runs if r.tipo != "negativa" for item in r.items}
    return {
        "modelo": model,
        "modos": {mode: {"concepto": concept[mode]["total"], "jev": jev[mode]} for mode in jev},
        "pares_sin_juicio": len(asked - judgments.keys()),
        "muestra": _sample_means(runs, judgments, human),
    }


def _sample_means(runs: list[QueryRun], judgments: dict[str, JevJudgment], human: dict[str, int]) -> dict | None:
    """La ganancia media de los tres jueces en los pares mostrados que las personas juzgaron y Jev también."""
    rows = []
    for run in runs:
        if run.mode != SHOWN or run.tipo == "negativa":
            continue
        for item, relevant in zip(run.items, run.relevance, strict=True):
            key = _pair(run, item)
            if key in human and key in judgments:
                rows.append((relevant, judgments[key].gain, human[key] / 2))
    if not rows:
        return None
    n = len(rows)
    concept, jev, people = (round(sum(row[i] for row in rows) / n, 3) for i in range(3))
    return {"n": n, "concepto": concept, "jev": jev, "personas": people}


def _gains(run: QueryRun, judgments: dict[str, JevJudgment]) -> list[float]:
    return [judgments[key].gain if (key := _pair(run, item)) in judgments else 0.0 for item in run.items]


def _pair(run: QueryRun, item: dict) -> str:
    return pair_id(run.vertical, run.query, item["entity_type"], item["entity_id"])
