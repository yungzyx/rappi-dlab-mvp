"""Evaluación de la búsqueda por vertical: léxico vs vectorial vs híbrido, y calibración de τ ("sin resultado").

Relevancia: un resultado es relevante si su concepto (item_concepts) está entre los esperados de la consulta.
Es una etiqueta automática y ruidosa (depende de la precisión de la capa 2), pero es la misma para los tres
modos, así que la comparación es justa. Métricas: P@10, MRR y nDCG@10 (ganancia binaria).

Además del ranking (`retrieve`), mide lo que ve el usuario: los productos de `search_products` (lo que muestran
/search y el agente) y «sin resultado» con la regla con que el agente lo registra.
"""

import json
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from psycopg import Connection

from ..agent.tools import search_products
from ..agent.understand import Understander
from ..embeddings.base import TextEmbedder
from ..retrieval.hybrid import DEFAULT_TAU, MODES, THRESHOLDS_FILE, UNNAMED_TAU, retrieve

QUERIES_FILE = Path(__file__).resolve().parent / "queries.json"
K = 10
MIN_UNMET_PRECISION = 0.9  # "sin resultado" debe acertar al menos 9 de cada 10 veces (docs/diseno-ia.md §1)
STALE_STRICT_MATCHES = 3  # una negativa con tantos productos que calzan todas sus palabras quizás ya no lo es
# Híbrido sin el refuerzo por concepto: el refuerzo reordena con la misma etiqueta (item_concepts) con que se juzga la
# relevancia, así que infla al híbrido. Esta fila mide cuánto aporta la fusión léxico + vector por sí sola.
ABLATION = "hibrido_sin_refuerzo"
# Lo que ve el usuario: el híbrido después de search_products (sensibles, foco en el concepto de la consulta, precio
# vigente, sin repetidos). `retrieve` puede traer 10 relevantes y que se muestre 1.
SHOWN = "hibrido_mostrado"
EVAL_MODES = (*MODES, ABLATION, SHOWN)
COMPARISONS = [
    ("hibrido", "vector"),
    ("hibrido", "lexico"),
    (ABLATION, "vector"),
    ("hibrido", ABLATION),
    (SHOWN, "hibrido"),
]
BOOTSTRAP_RESAMPLES = 2000
TAU_CANDIDATES = [round(0.70 + 0.01 * i, 2) for i in range(26)]


@dataclass
class QueryRun:
    vertical: str
    query: str
    tipo: str
    mode: str
    relevance: list[int]
    strict_lexical: int
    max_cosine: float | None
    concept_in_vertical: bool
    names_concept: bool = False
    items: list[dict] = field(default_factory=list)  # los resultados (tipo, id, texto, concepto, tienda si se muestra)
    shown_unmet: bool | None = None  # solo en SHOWN: «sin resultado» como lo registra el agente (y nada a la vista)
    has_words: bool = True  # le queda alguna palabra sin las stopwords («té» no): sin ellas no hay «sin resultado»
    names_occasion: bool = False  # sin concepto, si nombra una ocasión: solo entonces decide el τ del vertical


def load_queries(path: Path = QUERIES_FILE) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["queries"]


def run_queries(
    conn: Connection, embedder: TextEmbedder | None, queries: list[dict], modes: tuple[str, ...] = EVAL_MODES
) -> list[QueryRun]:
    runs = []
    understander = Understander()
    for q in queries:
        for mode in modes:
            if mode != "lexico" and embedder is None:
                continue
            shown_unmet = None
            if mode == SHOWN:
                # Como /search: los conceptos los detecta la consulta (y si queda «sin resultado», se corrigen los
                # errores de tipeo y se vuelve a buscar: retrieval/spelling.py). El agente registra la demanda solo sin
                # productos, y nunca por síntomas: ahí los medicamentos se ocultan por la regla 6d, no por falta de
                # surtido.
                outcome = search_products(conn, q["vertical"], q["query"], None, embedder, k=K, correct=True)
                result = outcome.result
                items = [(p.entity_type, p.entity_id, p.name, p.concept, p.store) for p in outcome.products]
                symptom = understander.understand(conn, q["query"], q["vertical"]).symptom
                shown_unmet = result.unmet and not outcome.products and not symptom
            else:
                if mode == ABLATION:
                    result = retrieve(conn, q["vertical"], q["query"], embedder, k=K, mode="hibrido", concepts=[])
                else:
                    result = retrieve(conn, q["vertical"], q["query"], embedder, k=K, mode=mode)
                items = [(h.entity_type, h.entity_id, h.content, h.concept_id, None) for h in result.hits]
            expected = set(q["concepts"])
            relevance = [1 if item[3] in expected else 0 for item in items]
            runs.append(
                QueryRun(
                    q["vertical"],
                    q["query"],
                    q["tipo"],
                    mode,
                    relevance,
                    result.strict_lexical_matches,
                    result.max_cosine,
                    result.concept_in_vertical,
                    bool(result.query_concepts),
                    [
                        {"entity_type": etype, "entity_id": eid, "texto": text, "concepto": concept, "tienda": store}
                        for etype, eid, text, concept, store in items
                    ],
                    shown_unmet,
                    result.has_words,
                    result.names_occasion,
                )
            )
    return runs


def precision_at_k(relevance: Sequence[float], k: int = K) -> float:
    return sum(relevance[:k]) / k


def reciprocal_rank(relevance: Sequence[float]) -> float:
    return next((1 / (i + 1) for i, rel in enumerate(relevance) if rel), 0.0)


def ndcg_at_k(relevance: Sequence[float], k: int = K, available: int = K) -> float:
    """`available`: relevantes que existen en el vertical (por defecto se asume que hay al menos k)."""
    dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(relevance[:k]))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, available)))
    return dcg / ideal if ideal else 0.0


def summarize(runs: list[QueryRun]) -> dict:
    """Promedios por modo (total, por tipo y por vertical) sobre consultas positivas."""
    summary: dict = {}
    for mode in EVAL_MODES:
        positives = [r for r in runs if r.mode == mode and r.tipo != "negativa"]
        if not positives:
            continue
        summary[mode] = {
            "total": _means(positives),
            "por_tipo": {t: _means([r for r in positives if r.tipo == t]) for t in sorted({r.tipo for r in positives})},
            "por_vertical": {
                v: _means([r for r in positives if r.vertical == v]) for v in sorted({r.vertical for r in positives})
            },
        }
    return summary


def paired_comparison(runs: list[QueryRun], a: str, b: str, seed: int = 7) -> dict:
    """nDCG@10 de `a` contra `b` consulta por consulta (positivas): victorias, empates, derrotas y la diferencia
    media con su intervalo de confianza del 95 % por bootstrap (semilla fija: el reporte es reproducible)."""
    by_mode = {
        mode: {(r.vertical, r.query): ndcg_at_k(r.relevance) for r in runs if r.mode == mode and r.tipo != "negativa"}
        for mode in (a, b)
    }
    keys = sorted(by_mode[a].keys() & by_mode[b].keys())
    diffs = [by_mode[a][key] - by_mode[b][key] for key in keys]
    rng = random.Random(seed)
    means = (
        sorted(sum(rng.choices(diffs, k=len(diffs))) / len(diffs) for _ in range(BOOTSTRAP_RESAMPLES)) if diffs else []
    )
    return {
        "a": a,
        "b": b,
        "n": len(diffs),
        "gana": sum(d > 1e-9 for d in diffs),
        "empata": sum(abs(d) <= 1e-9 for d in diffs),
        "pierde": sum(d < -1e-9 for d in diffs),
        "diferencia": round(sum(diffs) / len(diffs), 3) if diffs else None,
        "ic95": (round(means[int(0.025 * len(means))], 3), round(means[int(0.975 * len(means)) - 1], 3))
        if means
        else None,
    }


def compare_modes(runs: list[QueryRun]) -> list[dict]:
    present = {r.mode for r in runs}
    return [paired_comparison(runs, a, b) for a, b in COMPARISONS if a in present and b in present]


def calibrate_tau(runs: list[QueryRun], candidates=None) -> dict[str, float]:
    """τ por vertical: el que maximiza el recall de 'sin resultado' con precisión ≥ 0,9 (modo híbrido).

    Solo cuentan las consultas que dependen de τ (sin coincidencia léxica estricta ni concepto nombrado, con palabras
    que buscar y una ocasión nombrada: sin ella decide UNNAMED_TAU): las demás dan el mismo recall con cualquier τ.
    Un vertical sin esas negativas, o donde ningún τ detecta alguna, no recibe propuesta. Ante un empate gana el τ más
    bajo: el más prudente con las consultas que no están en el set.
    """
    candidates = candidates or TAU_CANDIDATES
    hybrid = [r for r in runs if r.mode == "hibrido"]
    taus = {}
    for vertical in sorted({r.vertical for r in hybrid}):
        rows = [
            r
            for r in hybrid
            if r.vertical == vertical
            and r.strict_lexical == 0
            and not r.names_concept
            and r.has_words
            and r.names_occasion
        ]
        actual = [r.tipo == "negativa" for r in rows]
        if not any(actual):
            continue
        best = (None, 0.0)
        for tau in candidates:
            predicted = [_is_unmet(r, tau) for r in rows]
            tp = sum(p and a for p, a in zip(predicted, actual, strict=True))
            fp = sum(p and not a for p, a in zip(predicted, actual, strict=True))
            precision = tp / (tp + fp) if tp + fp else 1.0
            recall = tp / sum(actual)
            if precision >= MIN_UNMET_PRECISION and recall > best[1]:
                best = (tau, recall)
        if best[0] is not None:
            taus[vertical] = best[0]
    return taus


def unmet_quality(runs: list[QueryRun], taus: dict[str, float], run_taus: dict[str, float] | None = None) -> dict:
    """«Sin resultado» de la búsqueda (modo híbrido, con `taus`) y, si se corrió, el que registra el agente («mostrado»:
    marcado y sin productos a la vista, con los τ vigentes al correr la evaluación, `run_taus`; por defecto `taus`)."""
    hybrid = [r for r in runs if r.mode == "hibrido"]
    quality = _detection(hybrid, [_is_unmet(r, taus.get(r.vertical, DEFAULT_TAU)) for r in hybrid])
    quality["negativas_detalle"] = negative_diagnosis(runs, taus)
    shown = [r for r in runs if r.mode == SHOWN]
    if shown:
        quality["mostrado"] = _detection(shown, [bool(r.shown_unmet) for r in shown])
        # Marcadas por la búsqueda con los mismos τ con que se calculó «mostrado» (no con los recién guardados).
        at_run = taus if run_taus is None else run_taus
        flagged = {(r.vertical, r.query) for r in hybrid if _is_unmet(r, at_run.get(r.vertical, DEFAULT_TAU))}
        quality["mostrado"]["marcadas_con_productos"] = [
            f"{r.vertical}: {r.query}"
            for r in shown
            if r.tipo == "negativa" and not r.shown_unmet and (r.vertical, r.query) in flagged
        ]
    return quality


def _detection(runs: list[QueryRun], predicted: list[bool]) -> dict:
    actual = [r.tipo == "negativa" for r in runs]
    tp = sum(p and a for p, a in zip(predicted, actual, strict=True))
    fp = sum(p and not a for p, a in zip(predicted, actual, strict=True))
    fn = sum(a and not p for p, a in zip(predicted, actual, strict=True))
    return {
        "negativas": sum(actual),
        "detectadas": tp,
        "falsas_alarmas": fp,
        "no_detectadas": fn,
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "no_detectadas_detalle": [
            f"{r.vertical}: {r.query}" for r, p, a in zip(runs, predicted, actual, strict=True) if a and not p
        ],
        "falsas_alarmas_detalle": [
            f"{r.vertical}: {r.query}" for r, p, a in zip(runs, predicted, actual, strict=True) if p and not a
        ],
    }


def thresholds_after_saving(current: dict[str, float], proposed: dict[str, float]) -> dict[str, float]:
    """Los propuestos reemplazan a los vigentes; un vertical sin propuesta no tiene evidencia para cambiar y conserva
    el suyo (pasarlo al τ por defecto metía falsas alarmas, p. ej. «regalo para mi polola» en Mall)."""
    return {**current, **proposed}


def save_thresholds(taus: dict[str, float], path: Path = THRESHOLDS_FILE) -> None:
    path.write_text(json.dumps(taus, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def render_markdown(
    summary: dict,
    unmet: dict,
    current: dict[str, float],
    proposed: dict[str, float],
    saved: bool,
    model: str | None,
    comparisons: list[dict] = (),
    jev: dict | None = None,
) -> str:
    """`current`: τ vigentes antes de esta evaluación; `unmet` se mide con los propuestos solo si se guardaron.
    `jev`: lo que arma `judge.jev_report`, para mostrar a Jev junto al juez por concepto (y a las personas)."""
    lines = [
        f"# Evaluación de búsqueda ({model or 'solo léxico'})",
        "",
        "| Modo | P@10 | MRR | nDCG@10 | n |",
        "|---|---|---|---|---|",
    ]
    for mode, data in summary.items():
        t = data["total"]
        lines.append(f"| {mode} | {t['p@10']} | {t['mrr']} | {t['ndcg@10']} | {t['n']} |")
    if ABLATION in summary:
        lines += [
            "",
            f"`{ABLATION}`: el híbrido sin el refuerzo por concepto. El refuerzo reordena con la misma etiqueta con"
            " que se juzga la relevancia, así que esta fila es la medida justa de la fusión léxico + vector.",
        ]
    if SHOWN in summary:
        lines += [
            "",
            f"`{SHOWN}`: lo que ve el usuario. Son los productos que devuelve `search_products` (/search y el agente):"
            " sin sensibles no pedidos, enfocados en el concepto que detecta la consulta, con precio vigente y sin"
            " repetidos. Si muestra menos de 10, P@10 y nDCG@10 bajan.",
        ]
    if comparisons:
        lines += [
            "",
            "## Comparación pareada (nDCG@10 consulta por consulta)",
            "",
            "| Comparación | Gana | Empata | Pierde | Diferencia media | IC 95 % (bootstrap) |",
            "|---|---|---|---|---|---|",
        ]
        for c in comparisons:
            low, high = c["ic95"] or ("-", "-")
            counts = f"{c['gana']} | {c['empata']} | {c['pierde']}"
            lines.append(f"| {c['a']} vs {c['b']} | {counts} | {c['diferencia']} | {low} a {high} |")
        lines += ["", "Si el intervalo incluye el 0, la diferencia no es concluyente con este set de consultas."]
    if jev:
        lines += _jev_lines(jev)
    lines += [
        "",
        "## Por tipo de consulta (nDCG@10)",
        "",
        "| Tipo | " + " | ".join(summary) + " |",
        "|---|" + "---|" * len(summary),
    ]
    tipos = sorted({t for data in summary.values() for t in data["por_tipo"]})
    for tipo in tipos:
        cells = [str(summary[m]["por_tipo"].get(tipo, {}).get("ndcg@10", "-")) for m in summary]
        lines.append(f"| {tipo} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Por vertical (nDCG@10)",
        "",
        "| Vertical | " + " | ".join(summary) + " |",
        "|---|" + "---|" * len(summary),
    ]
    verticals = sorted({v for data in summary.values() for v in data["por_vertical"]})
    for vertical in verticals:
        cells = [str(summary[m]["por_vertical"].get(vertical, {}).get("ndcg@10", "-")) for m in summary]
        lines.append(f"| {vertical} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Sin resultado (demanda no satisfecha)",
        "",
        f"Umbral τ por vertical (sin τ propio rige {DEFAULT_TAU}). Decide en las consultas que nombran una ocasión y no"
        f" un concepto; sin concepto ni ocasión rige {UNNAMED_TAU} en todas:",
        "",
        "| Vertical | τ vigente | τ propuesto |",
        "|---|---|---|",
    ]
    for vertical in sorted(current.keys() | proposed.keys()):
        suggestion = proposed.get(vertical, "sin propuesta")
        lines.append(f"| {vertical} | {current.get(vertical, '-')} | {suggestion} |")
    lines += [
        "",
        "Sin propuesta: el vertical no tiene negativas que dependan de τ (todas cortan por coincidencia léxica, por"
        f" concepto nombrado o, sin concepto ni ocasión, por {UNNAMED_TAU}), o ningún τ entre 0,70 y 0,95 las detecta"
        " con precisión ≥ 0,9. Un vertical sin propuesta, al guardar, conserva su τ vigente.",
    ]
    floor = [v for v in sorted(current) if current[v] <= min(TAU_CANDIDATES)]
    if floor:
        lines += [
            "",
            f"⚠ τ vigente en el piso de la grilla (0,70): {', '.join(floor)}. No viene de una calibración y con él la"
            " regla del coseno casi nunca se dispara (los cosenos e5 rara vez bajan de 0,76). Hacen falta negativas"
            " que nombren una ocasión y no un concepto en ese vertical para calibrarlo.",
        ]
    lines += [
        "",
        "Calidad medida con los τ guardados en eval/thresholds.json (propuestos, y vigentes donde no hay propuesta):"
        if saved
        else "Calidad medida con los τ vigentes (los propuestos no se guardaron):",
        "",
        _detection_line(unmet),
    ]
    if unmet["falsas_alarmas_detalle"]:
        lines.append(f"- Falsas alarmas: {', '.join(unmet['falsas_alarmas_detalle'])}")
    if "mostrado" in unmet:
        shown = unmet["mostrado"]
        lines += [
            "",
            "Lo que registra el agente (`search_products`: la búsqueda marca «sin resultado» y no se muestra ningún"
            " producto), con los τ vigentes al correr la evaluación:",
            "",
            _detection_line(shown),
        ]
        if shown["falsas_alarmas_detalle"]:
            lines.append(f"- Falsas alarmas: {', '.join(shown['falsas_alarmas_detalle'])}")
        if shown["marcadas_con_productos"]:
            lost = ", ".join(shown["marcadas_con_productos"])
            lines.append(f"- La búsqueda las marca, pero se muestran productos: {lost}")
    if unmet["negativas_detalle"]:
        lines += [
            "",
            "### Por qué se detecta o no cada negativa",
            "",
            "| Vertical | Consulta | ¿Detectada? | Causa |",
            "|---|---|---|---|",
        ]
        for row in unmet["negativas_detalle"]:
            cause = row["causa"] + (" · ⚠ posiblemente desactualizada" if row["desactualizada"] else "")
            lines.append(f"| {row['vertical']} | {row['consulta']} | {'sí' if row['detectada'] else 'no'} | {cause} |")
        lines += [
            "",
            f"Posiblemente desactualizada: {STALE_STRICT_MATCHES} o más productos calzan todas las palabras; el"
            " catálogo quizás ya lo tiene y la consulta dejó de ser negativa.",
        ]
    return "\n".join(lines) + "\n"


def _jev_lines(jev: dict) -> list[str]:
    lines = [
        "",
        f"## Tres jueces: concepto, Jev ({jev['modelo']}) y personas",
        "",
        "Cada resultado se juzga con el concepto (0 o 1), con Jev (ganancia esperada entre 0 y 1: «no sirve» 0,"
        " «a medias» 0,5, «sirve» 1, ponderada por la probabilidad de cada nivel) y, donde hay planilla juzgada, con"
        " las personas. El juez por concepto es binario y Jev es graduado: P@10 y nDCG@10 de Jev usan la ganancia"
        " esperada tal cual, así que sus columnas P@10 no son directamente comparables con las del concepto. El MRR de"
        " Jev cuenta como relevante desde 0,5.",
        "",
        "| Modo | P@10 concepto | P@10 Jev | MRR concepto | MRR Jev | nDCG@10 concepto | nDCG@10 Jev"
        " | Sin juicio de Jev (cuentan 0) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for mode, judges in jev["modos"].items():
        c, j = judges["concepto"], judges["jev"]
        lines.append(
            f"| {mode} | {c['p@10']} | {j['p@10']} | {c['mrr']} | {j['mrr']} | {c['ndcg@10']} | {j['ndcg@10']}"
            f" | {j['sin_juicio']} |"
        )
    if jev["pares_sin_juicio"]:
        lines += [
            "",
            f"{jev['pares_sin_juicio']} pares sin juicio de Jev (falló la llamada o se llegó al tope): cuentan 0 en sus"
            " métricas y se vuelven a pedir en la próxima corrida.",
        ]
    if sample := jev["muestra"]:
        lines += [
            "",
            f"Pares que juzgaron las personas ({sample['n']} pares de lo que ve el usuario, también juzgados por Jev):",
            "",
            "| Juez | Ganancia media |",
            "|---|---|",
            f"| Juez por concepto | {sample['concepto']} |",
            f"| Jev | {sample['jev']} |",
            f"| Personas | {sample['personas']} |",
        ]
    return lines


def _detection_line(quality: dict) -> str:
    return (
        f"Negativas: {quality['negativas']} · detectadas: {quality['detectadas']}"
        f" · falsas alarmas: {quality['falsas_alarmas']} · precisión: {quality['precision']}"
        f" · recall: {quality['recall']}"
    )


def negative_diagnosis(runs: list[QueryRun], taus: dict[str, float]) -> list[dict]:
    """Por cada negativa (modo híbrido): si «sin resultado» la detecta y qué lo decidió, con la misma regla que
    `_is_unmet`."""
    rows = []
    for r in (r for r in runs if r.mode == "hibrido" and r.tipo == "negativa"):
        tau = taus.get(r.vertical, DEFAULT_TAU)
        if r.strict_lexical > 0:
            n = r.strict_lexical
            cause = f"{n} {'coincidencia léxica estricta' if n == 1 else 'coincidencias léxicas estrictas'}"
        elif r.names_concept:
            cause = f"el concepto nombrado {'está' if r.concept_in_vertical else 'no está'} en el vertical"
        elif not r.has_words:
            cause = "sin palabras que buscar (solo stopwords)"
        elif r.max_cosine is None:
            cause = "sin coseno (sin embeddings)"
        else:
            used = _tau(r, tau)
            unnamed = "" if r.names_occasion else "sin concepto ni ocasión: "
            cause = f"{unnamed}coseno {r.max_cosine:.3f} {'<' if r.max_cosine < used else '≥'} τ {used}"
        rows.append(
            {
                "vertical": r.vertical,
                "consulta": r.query,
                "detectada": _is_unmet(r, tau),
                "causa": cause,
                "desactualizada": r.strict_lexical >= STALE_STRICT_MATCHES,
            }
        )
    return rows


def _is_unmet(run: QueryRun, tau: float) -> bool:
    """Misma regla que retrieval.hybrid._unmet, con el τ del vertical variable para calibrar."""
    if run.strict_lexical > 0:
        return False
    if run.names_concept:
        return not run.concept_in_vertical
    if not run.has_words:
        return False
    return run.max_cosine is None or run.max_cosine < _tau(run, tau)


def _tau(run: QueryRun, tau: float) -> float:
    """El τ que decide una consulta sin concepto: el del vertical si nombra una ocasión; si no, UNNAMED_TAU."""
    return tau if run.names_occasion else UNNAMED_TAU


def _means(runs: list[QueryRun]) -> dict:
    n = len(runs)
    return {
        "n": n,
        "p@10": round(sum(precision_at_k(r.relevance) for r in runs) / n, 3),
        "mrr": round(sum(reciprocal_rank(r.relevance) for r in runs) / n, 3),
        "ndcg@10": round(sum(ndcg_at_k(r.relevance) for r in runs) / n, 3),
    }
