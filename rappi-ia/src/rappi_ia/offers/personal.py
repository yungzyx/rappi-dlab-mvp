"""Las señales de una persona para ofrecerle cosas: lo que hace en la app (eventos), los segmentos no sensibles que
tiene y las marcas que repite en sus pedidos.

Solo se personaliza a quien usa el prototipo (`app_users.source = 'prototype'`): un visitante sin id o un usuario
simulado no tiene señales. Cada señal guarda de dónde viene (`source`), para poder decirle a la persona por qué se le
ofrece algo. Los conceptos que el agente no ofrece por su cuenta (`guards.is_offerable`) y los segmentos sensibles no
entran nunca.
"""

from dataclasses import asdict, dataclass, field

from psycopg import Connection

from ..concepts.taxonomy import load_taxonomy
from ..events import store as events
from .guards import is_offerable

LEVEL_WEIGHT = {"bajo": 1.0, "medio": 2.0, "alto": 3.0}  # lo que suma un concepto de la evidencia de un segmento
MIN_BRAND_ORDERS = 2  # pedidos distintos con una marca para que cuente como «su marca»


@dataclass(frozen=True)
class Signal:
    kind: str  # "concepto" o "marca"
    id: str
    # Un peso (los eventos con decaimiento; el nivel de un segmento, `LEVEL_WEIGHT`) o una cuenta (los pedidos con una
    # marca; los pedidos o las búsquedas de un concepto en el «por qué» de un perfil, `offers/profiles.py`).
    score: float
    source: str  # "eventos", "segmento:<segment_id>", "pedidos" o "busquedas"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Interests:
    concepts: dict[str, float] = field(default_factory=dict)  # concepto → puntaje, de mayor a menor
    basis: dict[str, list[Signal]] = field(default_factory=dict)  # concepto → las señales que suman su puntaje
    brands: dict[str, int] = field(default_factory=dict)  # brand_key → pedidos distintos

    @classmethod
    def empty(cls) -> "Interests":
        return cls()

    def top(self, n: int) -> list[str]:
        return list(self.concepts)[:n]


def is_prototype_user(conn: Connection, user_id: str | None) -> bool:
    """Si es una persona del prototipo: la única a quien se personaliza (un visitante sin id o alguien simulado, no)."""
    if user_id is None:
        return False
    row = conn.execute("SELECT 1 FROM app_users WHERE user_id = %s AND source = 'prototype'", (user_id,)).fetchone()
    return row is not None


def user_interests(conn: Connection, user_id: str | None) -> Interests:
    """Los intereses de la persona: eventos con decaimiento más los conceptos de la evidencia de sus segmentos no
    sensibles (pesados por nivel), y las marcas que repite. Vacío si no es un usuario del prototipo."""
    if not is_prototype_user(conn, user_id):
        return Interests.empty()
    concepts = load_taxonomy().concepts
    signals: list[Signal] = [Signal("concepto", c, s, "eventos") for c, s in events.profile(conn, user_id).items()]
    rows = conn.execute(
        """SELECT s.segment_id, s.level, t.item ->> 'id'
           FROM user_segments s
           JOIN segment_defs d USING (segment_id)
           CROSS JOIN LATERAL jsonb_array_elements(coalesce(s.evidence -> 'top', '[]'::jsonb)) AS t(item)
           WHERE s.user_id = %s AND NOT d.sensitive AND t.item ->> 'kind' = 'concepto'
           ORDER BY s.segment_id""",
        (user_id,),
    ).fetchall()
    signals += [Signal("concepto", c, LEVEL_WEIGHT[level], f"segmento:{seg}") for seg, level, c in rows]

    basis: dict[str, list[Signal]] = {}
    for signal in signals:
        if signal.id in concepts and is_offerable(concepts[signal.id]):
            basis.setdefault(signal.id, []).append(signal)
    totals = {c: round(sum(s.score for s in group), 3) for c, group in basis.items()}
    ordered = dict(sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])))
    return Interests(ordered, {c: basis[c] for c in ordered}, _brand_orders(conn, user_id))


def bought_brands(conn: Connection, user_id: str | None) -> dict[str, int]:
    """Marcas que la persona compró en `MIN_BRAND_ORDERS` pedidos distintos o más: brand_key → pedidos. Sin cadenas de
    restaurantes ni marcas propias de una tienda (repetir ahí habla de la tienda o del precio, no de la marca). Vacío
    si no es un usuario del prototipo."""
    return _brand_orders(conn, user_id) if is_prototype_user(conn, user_id) else {}


def _brand_orders(conn: Connection, user_id: str) -> dict[str, int]:
    """Sin los pedidos de «Rappi hoy» (modo actual): ahí la app no aprende."""
    rows = conn.execute(
        """SELECT b.brand_key, count(DISTINCT o.order_id) AS orders
           FROM app_orders o
           JOIN app_order_lines l USING (order_id)
           JOIN item_brands b ON b.entity_type = l.entity_type AND b.entity_id = l.entity_id
           JOIN product_brands p USING (brand_key)
           WHERE o.user_id = %s AND o.mode = 'propuesta' AND p.kind <> 'cadena' AND NOT p.is_store_brand
           GROUP BY b.brand_key
           HAVING count(DISTINCT o.order_id) >= %s
           ORDER BY orders DESC, b.brand_key""",
        (user_id, MIN_BRAND_ORDERS),
    ).fetchall()
    return dict(rows)
