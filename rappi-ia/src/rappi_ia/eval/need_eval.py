"""Evaluación de las necesidades "X para Y" (eval/necesidades.json): si se muestra lo pedido (X) y no lo que lo
acompaña (Y).

Cada caso se busca como /search de su vertical (`search_products`, corrigiendo como la app), en la búsqueda agrupada
(`search_grouped`, la del buscador de la app: cuenta su primer grupo, el que se ve primero) y con Mochi (`/agent/ask` en
la vertical del caso, con plantillas). En cada una pasa (`judge`) si muestra al menos MIN_SHOWN productos, de los
primeros SHOWN_TOP al menos MIN_SHOWN son de un concepto que sirve, ninguno de los primeros SHOWN_MAX es de un concepto
que no se puede mostrar y, si el caso no permite alcohol, ninguno es +18. El juicio es por concepto: mide si se busca
lo pedido, no si cada producto sirve (eso lo juzgan personas o el juez de tres niveles).
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from psycopg import Connection

from ..agent.grouped_search import search_grouped
from ..agent.rappi_agent import Context, RappiAgent
from ..agent.tools import search_products
from ..embeddings.base import TextEmbedder
from .search_eval import K

NEEDS_FILE = Path(__file__).resolve().parent / "necesidades.json"
SHOWN_TOP = 5  # de estos, al menos MIN_SHOWN tienen que ser de lo pedido
MIN_SHOWN = 3
SHOWN_MAX = 6  # lo que muestra Mochi; en estos no puede haber nada de lo que no se puede mostrar
SURFACES = ("search", "grouped", "mochi")
SURFACE_NAMES = {"search": "/search", "grouped": "agrupada", "mochi": "Mochi"}


@dataclass(frozen=True)
class Shown:
    name: str
    concept: str | None
    adult: bool


@dataclass
class NeedRun:
    vertical: str
    query: str
    kind: str  # "patron" o "control"
    passed: dict[str, bool] = field(default_factory=dict)  # por superficie
    why: dict[str, str] = field(default_factory=dict)  # por qué no pasa, por superficie
    shown: dict[str, list[Shown]] = field(default_factory=dict)


def load_needs(path: Path = NEEDS_FILE) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["queries"]


def judge(case: dict, shown: list[Shown], unmet: bool) -> tuple[bool, str]:
    """(pasa, por qué no). Ver el docstring del módulo."""
    if unmet or not shown:
        return False, "sin productos"
    if len(shown) < MIN_SHOWN:
        return False, f"muestra {len(shown)}"
    wrong = [s for s in shown[:SHOWN_MAX] if s.concept in case["no"]]
    if wrong:
        return False, f"muestra {wrong[0].concept}: {wrong[0].name}"
    if not case["alcohol"] and (adult := [s for s in shown[:SHOWN_MAX] if s.adult]):
        return False, f"muestra alcohol: {adult[0].name}"
    asked = sum(s.concept in case["sirve"] for s in shown[:SHOWN_TOP])
    if asked < MIN_SHOWN:
        return False, f"{asked} de {min(SHOWN_TOP, len(shown))} de lo pedido"
    return True, ""


def _from_products(products) -> list[Shown]:
    return [Shown(p.name, p.concept, p.age_restricted) for p in products]


def _from_dicts(products: list[dict]) -> list[Shown]:
    return [Shown(p["name"], p["concept"], bool(p["age_restricted"])) for p in products]


def run_needs(conn: Connection, embedder: TextEmbedder | None, cases: list[dict]) -> list[NeedRun]:
    agent = RappiAgent(embedder)
    runs = []
    for case in cases:
        vertical, query = case["vertical"], case["query"]
        found = search_products(conn, vertical, query, None, embedder, k=K, correct=True)
        grouped = search_grouped(conn, query, embedder, None, K)
        first = grouped.groups[0].products if grouped.groups else []
        mochi = agent.reply(conn, query, Context(vertical=vertical))
        run = NeedRun(vertical, query, case["tipo"])
        for surface, shown, unmet in (
            ("search", _from_products(found.products), found.result.unmet),
            ("grouped", _from_products(first), grouped.unmet),
            ("mochi", _from_dicts(mochi["products"]), mochi["unmet"]),
        ):
            run.passed[surface], run.why[surface] = judge(case, shown, unmet)
            run.shown[surface] = shown
        runs.append(run)
        conn.rollback()
    return runs


def render_markdown(runs: list[NeedRun]) -> str:
    lines = ['# Necesidades "X para Y"', ""]
    for kind, label in (("patron", 'Con la forma "X para Y"'), ("control", "Controles (no se pueden romper)")):
        some = [r for r in runs if r.kind == kind]
        counts = ", ".join(f"{SURFACE_NAMES[s]} {sum(r.passed[s] for r in some)}" for s in SURFACES)
        lines.append(f"- {label}: {len(some)} casos; pasan {counts}")
    total = ", ".join(f"{SURFACE_NAMES[s]} {sum(r.passed[s] for r in runs)}" for s in SURFACES)
    lines += [f"- Total: {len(runs)} casos; pasan {total}", ""]
    lines += [
        "| Vertical | Consulta | Tipo | /search | Agrupada | Mochi | Mochi muestra |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in runs:
        cells = [("sí" if r.passed[s] else f"no ({r.why[s]})") for s in SURFACES]
        names = "; ".join(s.name[:32] for s in r.shown["mochi"][:3])
        lines.append(f"| {r.vertical} | {r.query} | {r.kind} | {' | '.join(cells)} | {names} |")
    return "\n".join(lines) + "\n"
