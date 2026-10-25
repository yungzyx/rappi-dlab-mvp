"""Evaluación de la corrección de errores de tipeo (eval/typos.json): cuántos se recuperan y que las negativas de
eval/queries.json sigan «sin resultado».

Cada caso se busca como /search de una vertical (`search_products`) sin corregir (antes) y corrigiendo (después). Un
producto es de lo pedido si su nombre tiene cada palabra de lo que se quiso escribir (`quiso`; sus primeras
ROOT_LETTERS letras, para que «papas fritas» calce «Papas Fritas Individual» y «pañales» calce «Pañal»). Se recupera
si no queda «sin resultado» y de lo que muestra, los primeros SHOWN_TOP traen al menos tantos de lo pedido como trae
`quiso` (hasta RECOVERED_MIN). Una negativa sigue detectada si, corrigiendo, queda «sin resultado» y sin productos:
como la registra el agente.

También se mide la búsqueda agrupada (`search_grouped`, la que usa la app): un caso se recupera ahí si algún grupo
trae en sus primeros SHOWN_TOP tanto de lo pedido como el mejor grupo de `quiso`, y de las negativas (cada consulta una
vez) se cuenta cuántas de las que la agrupada deja sin resultado siguen así corrigiendo.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

from psycopg import Connection

from ..agent.grouped_search import search_grouped
from ..agent.tools import search_products
from ..embeddings.base import TextEmbedder
from ..text import tokens
from .search_eval import K, load_queries

TYPOS_FILE = Path(__file__).resolve().parent / "typos.json"
SHOWN_TOP = 5
RECOVERED_MIN = 3
ROOT_LETTERS = 5
_STOPWORDS = {"de", "del", "la", "el", "los", "las", "con", "sin", "para", "por", "en", "y"}


@dataclass
class TypoRun:
    vertical: str
    query: str
    intended: str
    reason: str
    before: bool  # se recuperaba sin corregir
    after: bool  # se recupera corrigiendo
    corrected_query: str | None
    intended_shown: int  # de lo pedido que muestra `quiso`, hasta RECOVERED_MIN (0: el caso no mide nada)
    shown: list[str]  # lo que se muestra corrigiendo (los primeros nombres)
    ms: float  # lo que tardó la búsqueda corrigiendo
    grouped_needed: int = 0  # como `intended_shown`, en la búsqueda agrupada
    grouped_before: bool = False
    grouped_after: bool = False
    grouped_corrected: str | None = None


@dataclass
class NegativeRun:
    vertical: str
    query: str
    before: bool  # «sin resultado» sin corregir
    detected: bool  # «sin resultado» corrigiendo
    corrected_query: str | None


@dataclass
class GroupedNegativeRun:
    query: str
    before: bool  # la agrupada la deja sin resultado sin corregir
    detected: bool  # y corrigiendo
    corrected_query: str | None


def load_typos(path: Path = TYPOS_FILE) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["queries"]


def is_meant(name: str, meant: str) -> bool:
    """El nombre tiene cada palabra de `meant` (sus primeras ROOT_LETTERS letras, sin tildes ni ñ)."""
    roots = [w[:ROOT_LETTERS] for w in tokens(meant) if w not in _STOPWORDS]
    words = tokens(name)
    return bool(roots) and all(any(word.startswith(root) for word in words) for root in roots)


def meant_count(names: list[str], meant: str) -> int:
    return sum(is_meant(name, meant) for name in names[:SHOWN_TOP])


def recovered(unmet: bool, shown: list[str], meant: str, needed: int) -> bool:
    """De los primeros SHOWN_TOP de `shown`, al menos `needed` son de lo pedido. `needed` es lo que trae lo que se
    quiso escribir, hasta RECOVERED_MIN; con 0 el caso no mide nada y no cuenta como recuperado."""
    return not unmet and needed > 0 and meant_count(shown, meant) >= needed


def _grouped_meant(conn: Connection, embedder: TextEmbedder | None, query: str, meant: str, correct: bool):
    """(sin resultado, lo más de lo pedido que trae un grupo en sus primeros SHOWN_TOP, consulta corregida)."""
    found = search_grouped(conn, query, embedder, None, K, correct=correct)
    best = max((meant_count([p.name for p in g.products], meant) for g in found.groups), default=0)
    return found.unmet, best, found.corrected_query


def run_typos(conn: Connection, embedder: TextEmbedder | None, cases: list[dict]) -> list[TypoRun]:
    runs = []
    for case in cases:
        vertical = case["vertical"]
        meant = case["quiso"]
        intended = [p.name for p in search_products(conn, vertical, meant, None, embedder, k=K).products]
        needed = min(RECOVERED_MIN, meant_count(intended, meant))
        before = search_products(conn, vertical, case["query"], None, embedder, k=K)
        start = time.perf_counter()
        after = search_products(conn, vertical, case["query"], None, embedder, k=K, correct=True)
        ms = (time.perf_counter() - start) * 1000
        grouped_needed = min(RECOVERED_MIN, _grouped_meant(conn, embedder, meant, meant, False)[1])
        unmet_before, best_before, _ = _grouped_meant(conn, embedder, case["query"], meant, False)
        unmet_after, best_after, grouped_corrected = _grouped_meant(conn, embedder, case["query"], meant, True)
        runs.append(
            TypoRun(
                vertical,
                case["query"],
                case["quiso"],
                case["motivo"],
                recovered(before.result.unmet, [p.name for p in before.products], meant, needed),
                recovered(after.result.unmet, [p.name for p in after.products], meant, needed),
                after.corrected_query,
                needed,
                [p.name for p in after.products[:3]],
                round(ms, 1),
                grouped_needed,
                not unmet_before and grouped_needed > 0 and best_before >= grouped_needed,
                not unmet_after and grouped_needed > 0 and best_after >= grouped_needed,
                grouped_corrected,
            )
        )
        conn.rollback()
    return runs


def run_negatives(conn: Connection, embedder: TextEmbedder | None) -> list[NegativeRun]:
    runs = []
    for q in load_queries():
        if q["tipo"] != "negativa":
            continue
        plain = search_products(conn, q["vertical"], q["query"], None, embedder, k=K)
        outcome = search_products(conn, q["vertical"], q["query"], None, embedder, k=K, correct=True)
        runs.append(
            NegativeRun(
                q["vertical"],
                q["query"],
                plain.result.unmet and not plain.products,
                outcome.result.unmet and not outcome.products,
                outcome.corrected_query,
            )
        )
        conn.rollback()
    return runs


def run_grouped_negatives(conn: Connection, embedder: TextEmbedder | None) -> list[GroupedNegativeRun]:
    runs = []
    for query in dict.fromkeys(q["query"] for q in load_queries() if q["tipo"] == "negativa"):
        plain = search_grouped(conn, query, embedder, None, K, correct=False)
        found = search_grouped(conn, query, embedder, None, K)
        runs.append(GroupedNegativeRun(query, plain.unmet, found.unmet, found.corrected_query))
        conn.rollback()
    return runs


def render_markdown(
    typos: list[TypoRun], negatives: list[NegativeRun], grouped_negatives: list[GroupedNegativeRun]
) -> str:
    measured = [r for r in typos if r.intended_shown]
    grouped = [r for r in typos if r.grouped_needed]
    grouped_unmet = [r for r in grouped_negatives if r.before]
    missed = [r for r in measured if not r.after]
    detected = sum(r.detected for r in negatives)
    lines = [
        "# Errores de tipeo en la búsqueda",
        "",
        f"- Casos: {len(typos)} ({len(typos) - len(measured)} no miden: lo que se quiso escribir no muestra nada de lo"
        " pedido)",
        f"- Recuperados sin corregir: {sum(r.before for r in measured)} de {len(measured)}",
        f"- Recuperados corrigiendo: {sum(r.after for r in measured)} de {len(measured)}",
        f"- Negativas de queries.json sin resultado: {sum(r.before for r in negatives)} de {len(negatives)} sin"
        f" corregir, {detected} corrigiendo",
        f"- Búsqueda agrupada (la de la app): recuperados {sum(r.grouped_before for r in grouped)} de {len(grouped)}"
        f" sin corregir y {sum(r.grouped_after for r in grouped)} corrigiendo; de las {len(grouped_negatives)}"
        f" negativas distintas, la agrupada deja {len(grouped_unmet)} sin resultado y corrigiendo siguen"
        f" {sum(r.detected for r in grouped_unmet)}",
        "",
        "| Vertical | Escrito | Quiso | Antes | Después | Corregida | Agrupada antes | Agrupada después | Corregida"
        " (agrupada) | Se muestra | ms |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in typos:
        before = "—" if not r.intended_shown else ("sí" if r.before else "no")
        after = "—" if not r.intended_shown else ("sí" if r.after else "no")
        g_before = "—" if not r.grouped_needed else ("sí" if r.grouped_before else "no")
        g_after = "—" if not r.grouped_needed else ("sí" if r.grouped_after else "no")
        shown = "; ".join(name[:40] for name in r.shown)
        lines.append(
            f"| {r.vertical} | {r.query} | {r.intended} | {before} | {after} | {r.corrected_query or ''} | {g_before} "
            f"| {g_after} | {r.grouped_corrected or ''} | {shown} | {r.ms} |"
        )
    if missed:
        lines += ["", "## No se recuperan", ""]
        lines += [f"- {r.vertical} «{r.query}» ({r.reason}): {r.corrected_query or 'sin corrección'}" for r in missed]
    grouped_missed = [r for r in grouped if not r.grouped_after]
    if grouped_missed:
        lines += ["", "## No se recuperan en la agrupada", ""]
        lines += [f"- «{r.query}»: {r.grouped_corrected or 'sin corrección'}" for r in grouped_missed]
    changed = [r for r in negatives if r.before and not r.detected]
    changed_grouped = [r for r in grouped_unmet if not r.detected]
    if changed or changed_grouped:
        lines += ["", "## Negativas que dejan de estar sin resultado", ""]
        lines += [f"- {r.vertical} «{r.query}» → «{r.corrected_query}»" for r in changed]
        lines += [f"- agrupada «{r.query}» → «{r.corrected_query}»" for r in changed_grouped]
    return "\n".join(lines) + "\n"
