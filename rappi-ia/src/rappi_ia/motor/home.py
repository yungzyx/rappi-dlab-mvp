"""El orden de los accesos chicos de la Home: Restaurantes y Turbo van fijos arriba; los otros seis se ordenan por lo
que la persona más usa (la afinidad propia del motor), y sin uso propio quedan en el orden de siempre."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from psycopg import Connection

from ..agent.tools import VERTICAL_LABELS
from ..concepts.taxonomy import load_taxonomy
from ..text import contract_articles
from .data import Signal, load_signals
from .model import AFFINITY_WINDOW_DAYS, affinity, local_day
from .predict import next_verticals, source_of

HOME_FIXED = ("restaurantes", "turbo")
HOME_ORDERABLE = ("supermercado", "farmacia", "mall", "licores", "conveniencia", "chocolateria")
REASON_ORDERS = "Porque pides seguido en {vertical}."
REASON_VISITS = "Porque entras seguido a {vertical}."  # la afinidad sale también de los eventos: sin pedidos ahí
# Uso mínimo para mover un acceso: un pedido ahí o señales en al menos 2 días distintos (hora de Santiago). Con un
# solo ver y agregar al carro (unos Doritos de una botillería, la tarea 1 de la prueba con personas), Licores subía
# primero y Mochi decía "entras seguido a Licores": una visita no es "seguido".
MIN_USE_DAYS = 2
# Farmacia y Licores solo suben por lo propio de la vertical: un evento o un pedido con un concepto de su grupo de la
# taxonomía (unos snacks o una bebida sin alcohol de una botillería no son uso de Licores), o un toque a su acceso
# (`vertical_open`, que no trae concepto).
OWN_CONCEPT_GROUPS = {"licores": "alcohol", "farmacia": "salud"}


def _counts(signal: Signal) -> bool:
    """Si la señal cuenta como uso de su vertical en la Home (`OWN_CONCEPT_GROUPS`)."""
    group = OWN_CONCEPT_GROUPS.get(signal.vertical)
    if group is None or signal.kind == "vertical_open":
        return True
    concepts = load_taxonomy().concepts
    return any((concepts[c].parent if c in concepts else c) == group for c in signal.concepts)  # o el grupo mismo


def home_verticals(conn: Connection, user_id: str) -> dict:
    """`{fixed, order, personalized}`: `order` son los 6 de `HOME_ORDERABLE`. Primero los que la persona usa (un
    pedido o señales en `MIN_USE_DAYS` días distintos, en Farmacia y Licores solo las propias), de más a menos uso
    propio (su afinidad; a igual afinidad, por puntaje de la predicción); después el resto, en el orden de
    `HOME_ORDERABLE`, para que la Home de quien no ha usado nada no cambie con la población. Solo el primero lleva
    `reason`: "Porque pides seguido en…" si pidió ahí y, si solo entró (abrir, buscar, ver, agregar al carro) en días
    distintos, "Porque entras seguido a…"."""
    now = datetime.now(UTC)
    scores = {s.vertical: s for s in next_verticals(conn, user_id, now=now)}
    source = source_of(conn, user_id)
    window = timedelta(days=AFFINITY_WINDOW_DAYS)
    signals = [
        s
        for s in (load_signals(conn, source, user_id) if source else [])
        if s.vertical in HOME_ORDERABLE and timedelta(0) <= now - s.ts <= window and _counts(s)
    ]
    aff = affinity(signals, now).get(user_id, {})
    ordered = {s.vertical for s in signals if s.kind == "order"}
    days = defaultdict(set)
    for s in signals:
        days[s.vertical].add(local_day(s.ts))
    used = sorted(
        (v for v in HOME_ORDERABLE if v in aff and (v in ordered or len(days[v]) >= MIN_USE_DAYS)),
        key=lambda v: (-aff[v], -scores[v].score),
    )
    ids = used + [v for v in HOME_ORDERABLE if v not in used]
    order = [{"id": v, "score": round(scores[v].score, 4), "reason": None} for v in ids]
    if used:
        template = REASON_ORDERS if used[0] in ordered else REASON_VISITS
        order[0]["reason"] = {
            "text": contract_articles(template.format(vertical=VERTICAL_LABELS[used[0]])),
            "basis": [{"kind": "afinidad_vertical", "id": used[0], "source": "eventos"}],
        }
    return {"fixed": list(HOME_FIXED), "order": order, "personalized": bool(used)}
