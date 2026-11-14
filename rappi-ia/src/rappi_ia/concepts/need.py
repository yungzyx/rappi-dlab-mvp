"""Lo pedido y para qué: en "X para Y" o "X con Y", lo pedido es X; Y dice con qué va.

Con "para" se busca solo X (`Need.end`); con "con" se busca la frase entera, porque "X con Y" suele ser el nombre de lo
pedido ("café con leche", "pan con palta", "pisco con bebida"): Y igual no es un concepto pedido. Salvo que Y sea +18:
"algo para picar con la cerveza" busca solo lo de antes, porque no se muestra nada +18 y la cerveza solo llenaría los
candidatos.

"bebida para mezclar con pisco" pide bebidas, no pisco; "algo dulce para el café de la tarde" pide algo dulce, no café.
Solo cuando los complementos curados (complements.toml) dicen que X e Y van juntos, en cualquier sentido: así "comida
para gato" (un solo concepto), "pilas para control" o "shampoo para perro" (sin arista: el perro dice de qué tipo es el
shampoo) quedan como estaban. X puede ser un concepto o una ocasión ("algo dulce" es antojo); en una ocasión, lo pedido
son sus conceptos que van con Y, del que va más al que va menos ("algo dulce para el café": pastelería y galletas antes
que chocolates).
"""

from collections import defaultdict
from dataclasses import dataclass
from functools import cache

from .matcher import Match
from .taxonomy import complement_queries, load_complements, load_taxonomy

# Lo que separa lo pedido de su para qué. "de" no: "galletas de chocolate" dice cómo son las galletas.
CONNECTORS = frozenset({"para", "con"})


@dataclass(frozen=True)
class Need:
    asked: tuple[Match, ...]  # los conceptos pedidos (sin los del para qué)
    context: tuple[str, ...] = ()  # los conceptos que solo dicen para qué o con qué va lo pedido
    end: int | None = None  # el conector: lo pedido son las palabras antes de él (None con un "con" sin +18)
    occasion: str | None = None  # si lo pedido es una ocasión ("algo dulce"), cuál
    occasion_concepts: tuple[str, ...] = ()  # y sus conceptos que van con el contexto


@cache
def _weights() -> dict[tuple[str, str], float]:
    weights: dict[tuple[str, str], float] = defaultdict(float)
    for source, target, weight in load_complements():
        for pair in ((source, target), (target, source)):
            weights[pair] = max(weights[pair], weight)
    return dict(weights)


def goes_with(a: str, b: str) -> float:
    """El peso de la arista curada entre dos conceptos, en cualquier sentido (0 si no van juntos)."""
    return _weights().get((a, b), 0.0)


def context_text(asked: list[str], context: list[str]) -> str:
    """Cómo se nombra lo pedido cuando va con su para qué: el texto de búsqueda de la arista contexto → pedido
    (complements.toml), si lo trae. "salsa para la pasta" busca también "salsa de tomate pomodoro…": solo "salsa"
    traía primero tabasco y salsa de ostión."""
    texts = complement_queries()
    return " ".join(dict.fromkeys(texts[(y, x)] for x in asked for y in context if (y, x) in texts))


def read_need(
    words: list[str], matches: list[Match], occasion: Match | None = None, occasion_concepts: tuple[str, ...] = ()
) -> Need:
    """`words`: el texto en palabras (normalizado, como lo leen `matches` y `occasion`). Un concepto nombrado después de
    un conector es contexto si antes de ese conector se nombra lo que va con él: un concepto distinto con arista, o la
    ocasión `occasion` con alguno de sus conceptos (`occasion_concepts`) con arista. Un concepto nombrado antes del
    conector manda sobre la ocasión ("chocolate para el café" pide chocolate)."""
    connectors = [i for i, word in enumerate(words) if word in CONNECTORS]
    context: dict[str, int] = {}  # concepto del para qué → su conector
    with_occasion: list[str] = []
    for y in matches:
        for c in (c for c in connectors if c < y.position):
            heads = [h for h in matches if h.position + h.words <= c and h.target != y.target]
            if any(goes_with(h.target, y.target) for h in heads):
                context.setdefault(y.target, c)
                break
            if heads or occasion is None or occasion.position + occasion.words > c:
                continue
            linked = [k for k in occasion_concepts if k != y.target and goes_with(k, y.target)]
            if linked:
                context.setdefault(y.target, c)
                with_occasion += [k for k in linked if k not in with_occasion]
                break
    if not context:
        return Need(tuple(matches))
    weight = {k: max(goes_with(k, y) for y in context) for k in with_occasion}
    end = min(context.values())
    concepts = load_taxonomy().concepts
    adult = any(concepts[c].age_restricted for c in context if c in concepts)
    return Need(
        tuple(m for m in matches if m.target not in context),
        tuple(context),
        None if words[end] == "con" and not adult else end,  # "café con leche" se llama así: se busca entero
        occasion.target if with_occasion and occasion else None,
        tuple(sorted(with_occasion, key=lambda k: -weight[k])),
    )
