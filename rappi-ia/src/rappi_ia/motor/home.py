"""El orden de los accesos chicos de la Home: Restaurantes y Turbo van fijos arriba; los otros seis se ordenan por lo
que la persona más usa (la afinidad propia del motor), y sin uso propio quedan en el orden de siempre."""

from psycopg import Connection

from ..agent.tools import VERTICAL_LABELS
from ..text import contract_articles
from .predict import next_verticals

HOME_FIXED = ("restaurantes", "turbo")
HOME_ORDERABLE = ("supermercado", "farmacia", "mall", "licores", "conveniencia", "chocolateria")
REASON_ORDERS = "Porque pides seguido en {vertical}."
REASON_VISITS = "Porque entras seguido a {vertical}."  # la afinidad sale también de los eventos: sin pedidos ahí


def home_verticals(conn: Connection, user_id: str) -> dict:
    """`{fixed, order, personalized}`: `order` son los 6 de `HOME_ORDERABLE`. Primero los que la persona usa (afinidad
    > 0), de más a menos uso propio (afinidad; a igual afinidad, por puntaje de la predicción); después el resto, en el
    orden de `HOME_ORDERABLE`, para que la Home de quien no ha usado nada no cambie con la población. Solo el primero
    lleva `reason`, y solo si la persona lo usa: «Porque pides seguido en…» si pidió ahí y, si solo entró (abrir,
    buscar, ver, agregar al carro), «Porque entras seguido a…»."""
    scores = {s.vertical: s for s in next_verticals(conn, user_id)}
    used = sorted(
        (v for v in scores if v in HOME_ORDERABLE and scores[v].affinity > 0),
        key=lambda v: (-scores[v].affinity, -scores[v].score),
    )
    ids = used + [v for v in HOME_ORDERABLE if v not in used]
    order = [{"id": v, "score": round(scores[v].score, 4), "reason": None} for v in ids]
    if used:
        ordered = conn.execute(
            "SELECT 1 FROM app_orders WHERE user_id = %s AND mode = 'propuesta' AND vertical = %s LIMIT 1",
            (user_id, used[0]),
        ).fetchone()
        template = REASON_ORDERS if ordered else REASON_VISITS
        order[0]["reason"] = {
            "text": contract_articles(template.format(vertical=VERTICAL_LABELS[used[0]])),
            "basis": [{"kind": "afinidad_vertical", "id": used[0], "source": "eventos"}],
        }
    return {"fixed": list(HOME_FIXED), "order": order, "personalized": bool(used)}
