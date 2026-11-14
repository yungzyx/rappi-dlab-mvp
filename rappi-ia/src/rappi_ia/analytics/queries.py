"""Métricas del panel empresa (definiciones en docs/diseno-ia.md §5). Todas filtran por `source`
('synthetic' o 'prototype'): nunca se mezclan datos simulados con otros.

`as_of` = último evento de esa fuente (los datos simulados terminan en la fecha con que se generaron).
"""

from psycopg import Connection
from psycopg.rows import dict_row

from .. import config
from ..agent.verticals import MIN_ITEMS_ELSEWHERE, SHARES
from ..catalog.hours import TZ
from ..concepts.taxonomy import load_taxonomy
from ..events import experiments as exp
from ..events.store import EXPIRED_KIND
from ..motor.combos import OWN_SIGNALS_ONLY, expected_fine_retention, load_combos
from ..offers.autonomy import ORIGIN as AUTO_ORDER_ORIGIN
from ..offers.winback import reach
from .power import PILOT_MIN_EFFECT, difference_ci, sample_size

SOURCES = ("synthetic", "prototype")
ACTIVE_DAYS = 30
MULTI_VERTICAL_DAYS = 60
RETENTION_FROM, RETENTION_TO = 61, 120  # "retención" = pidió entre los días 61 y 120 desde su primer pedido
MIN_SUPPORT = 30  # usuarios mínimos para aprender una arista por co-ocurrencia
MIN_GROUP_USERS = 20  # agregados con menos usuarios no se muestran (privacidad)
# Meses con el siguiente completo que pide la retención de una combinación propia para mostrarse.
MIN_COMBO_RETENTION_N = 30
FINE_COMBO_ROWS = 15  # las combinaciones finas más frecuentes que muestra el panel
# Abandono de búsqueda (en `unmet`): una búsqueda sin toque se salva si otra con toque la sigue dentro de este plazo.
SEARCH_RESCUE_MINUTES = 2
MIN_SEARCHES_FOR_RATE = 10  # búsquedas mínimas para mostrar el % de abandono
# Los toques que salen de una lista de resultados (los mismos del CTR, `capa.v_ctr_posicion`, más aceptar la
# sugerencia que acompaña los resultados).
SEARCH_CLICKS = ("view_store", "view_item", "recommendation_click", "cart_add", "suggestion_accepted")
COMBO_NOTES = {
    "synthetic": "Simulado: no es evidencia",
    "prototype": "uso del MVP, pocas personas: no es evidencia",
}


def _rows(conn: Connection, sql: str, params: dict) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [{k: _plain(v) for k, v in row.items()} for row in cur.fetchall()]


def _plain(value):
    from decimal import Decimal

    return float(value) if isinstance(value, Decimal) else value


def _check(source: str) -> None:
    if source not in SOURCES:
        raise ValueError(f"source debe ser uno de {SOURCES}")


_AS_OF = "(SELECT max(ts) FROM app_events WHERE source = %(source)s)"

# Carros (docs/diseno-ia.md §5): con al menos un producto (agregados − quitados > 0, o con pedido); abandonado si su
# último evento de carro (agregar, quitar o ir a pagar) fue hace más de 24 h y no tiene pedido. Una vez por carro.
_CARTS = f"""
cart_events AS (  -- unidades: payload.qty si es un número (vaciar el carro saca la línea entera), si no 1
    SELECT cart_id, max(ts) AS last_cart_ts,
           coalesce(sum(qty) FILTER (WHERE type = 'cart_add'), 0)
             - coalesce(sum(qty) FILTER (WHERE type = 'cart_remove'), 0) AS units
    FROM (SELECT cart_id, ts, type,
                 CASE WHEN jsonb_typeof(payload -> 'qty') = 'number'
                      THEN least(greatest((payload ->> 'qty')::numeric, 0), 99) ELSE 1 END AS qty
          FROM app_events
          WHERE source = %(source)s AND type IN ('cart_add', 'cart_remove', 'checkout_start') AND cart_id IS NOT NULL) e
    GROUP BY cart_id
),
cart_status AS (
    SELECT c.cart_id, c.last_cart_ts,
           o.cart_id IS NULL AND c.last_cart_ts < {_AS_OF} - interval '24 hours' AS is_abandoned
    FROM cart_events c
    -- un pedido cancelado no cuenta como pedido (migración 051): su carro vuelve a poder quedar abandonado
    LEFT JOIN (SELECT DISTINCT cart_id FROM app_orders WHERE source = %(source)s AND status = 'confirmado') o
           ON o.cart_id = c.cart_id
    WHERE c.units > 0 OR o.cart_id IS NOT NULL
)"""

# Ritmo por usuario: mediana de días entre pedidos (180 días); con 2 pedidos, el único intervalo acotado a [7, 30].
_RHYTHM = f"""
user_orders AS (  -- por día con pedidos: dos pedidos del mismo carro (dos verticales) no son "ritmo 0"
    SELECT user_id, day AS ts, lag(day) OVER (PARTITION BY user_id ORDER BY day) AS prev
    FROM (SELECT DISTINCT user_id, date_trunc('day', ts) AS day FROM app_orders
          WHERE source = %(source)s AND status = 'confirmado' AND ts > {_AS_OF} - interval '180 days') d
),
rhythm AS (
    SELECT user_id, count(*) + 1 AS orders,
           CASE WHEN count(*) = 1 THEN least(greatest(max(extract(epoch FROM ts - prev) / 86400), 7), 30)
                ELSE percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM ts - prev) / 86400) END AS days
    FROM user_orders WHERE prev IS NOT NULL GROUP BY user_id
),
last_order AS (  -- compras, no pedidos: un carro dividido en dos verticales es una sola compra
    SELECT user_id, count(DISTINCT coalesce(cart_id, order_id)) AS orders, max(ts) AS last_ts
    FROM app_orders WHERE source = %(source)s AND status = 'confirmado' GROUP BY user_id
),
risk AS (
    SELECT l.user_id, l.orders, r.days AS rhythm,
           extract(epoch FROM {_AS_OF} - l.last_ts) / 86400 AS since,
           CASE WHEN l.orders < 2 THEN 'sin_segunda_compra'
                WHEN extract(epoch FROM {_AS_OF} - l.last_ts) / 86400 > greatest(3 * r.days, 45) THEN 'perdido'
                WHEN extract(epoch FROM {_AS_OF} - l.last_ts) / 86400 > greatest(2 * r.days, 21) THEN 'en_riesgo'
                ELSE 'activo' END AS status
    FROM last_order l LEFT JOIN rhythm r USING (user_id)
)"""

# Un `order_placed` (el evento `e`) cuyo pedido se canceló no cuenta: el evento queda, pero el pedido no ocurrió
# (migración 050). Los simulados no traen `payload.order_id` ni se cancelan, así que siguen contando.
_NOT_CANCELLED = """NOT (e.type = 'order_placed' AND EXISTS (
        SELECT 1 FROM app_orders x WHERE x.order_id = e.payload ->> 'order_id' AND x.status = 'cancelado'))"""

# Embudo (ver funnel()): una fila por sesión y vertical; la entrada se mira en toda la sesión.
_FUNNEL = f"""
entry AS (  -- buscó, chateó, navegó, aceptó una sugerencia o agregó desde una lista (el "+" solo manda cart_add),
            -- en cualquier vertical (o sin vertical)
    SELECT DISTINCT session_id FROM app_events
    WHERE source = %(source)s
      AND type IN ('search', 'chat', 'ask', 'view_store', 'view_item', 'suggestion_accepted', 'cart_add')
),
funnel_steps AS (
    SELECT session_id, vertical, session_id IN (SELECT session_id FROM entry) AS busca,
           bool_or(type = 'cart_add') AS carro,
           bool_or(type = 'checkout_start') AS pago,
           bool_or(type = 'order_placed') AS pedido
    FROM app_events e
    WHERE source = %(source)s AND vertical IS NOT NULL
      AND type NOT IN ('suggestion_shown', 'suggestion_dismissed', 'list_view', 'offer_withheld', 'offer_eligible')
      AND {_NOT_CANCELLED}
    GROUP BY 1, 2
)"""


def kpis(conn: Connection, source: str = "synthetic") -> dict:
    _check(source)
    [row] = _rows(
        conn,
        f"""WITH {_RHYTHM.strip()},
            active AS (
                SELECT DISTINCT user_id FROM app_events
                WHERE source = %(source)s AND ts > {_AS_OF} - interval '{ACTIVE_DAYS} days'
            ),
            orders30 AS (
                SELECT count(*) AS n FROM app_orders
                WHERE source = %(source)s AND status = 'confirmado' AND ts > {_AS_OF} - interval '{ACTIVE_DAYS} days'
            ),
            {_CARTS.strip()},
            abandoned AS (  -- carros con actividad en los últimos 30 días, como los demás indicadores
                SELECT is_abandoned FROM cart_status WHERE last_cart_ts > {_AS_OF} - interval '{ACTIVE_DAYS} days'
            ),
            multi AS (
                SELECT user_id, count(DISTINCT vertical) AS verticals FROM app_orders
                WHERE source = %(source)s AND status = 'confirmado'
                  AND ts > {_AS_OF} - interval '{MULTI_VERTICAL_DAYS} days'
                GROUP BY user_id
            ),
            searches AS (  -- solo lo que sabe si encontró algo: la búsqueda local del prototipo no lo sabe (unmet NULL)
                SELECT count(*) FILTER (WHERE unmet) AS unmet, count(*) FILTER (WHERE unmet IS NOT NULL) AS total
                FROM app_events
                WHERE source = %(source)s AND type IN ('search', 'chat', 'ask')
                  AND ts > {_AS_OF} - interval '{ACTIVE_DAYS} days'
            ),
            {_FUNNEL.strip()}
            SELECT {_AS_OF} AS as_of,
                   (SELECT count(*) FROM active) AS usuarios_activos,
                   (SELECT n FROM orders30) AS pedidos_30d,
                   round((SELECT n FROM orders30)::numeric / nullif((SELECT count(*) FROM active), 0), 2) AS frecuencia,
                   (SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY days)::numeric, 1) FROM rhythm)
                       AS mediana_dias_entre_pedidos,
                   round(100.0 * (SELECT count(*) FILTER (WHERE is_abandoned) FROM abandoned)
                         / nullif((SELECT count(*) FROM abandoned), 0), 1) AS abandono_carrito_pct,
                   round(100.0 * (SELECT count(*) FILTER (WHERE verticals >= 2) FROM multi)
                         / nullif((SELECT count(*) FROM multi), 0), 1) AS multi_vertical_pct,
                   (SELECT count(*) FROM risk WHERE status = 'en_riesgo') AS en_riesgo,
                   (SELECT count(*) FROM risk WHERE status = 'perdido') AS perdidos,
                   round(100.0 * (SELECT unmet FROM searches) / nullif((SELECT total FROM searches), 0), 1)
                       AS busquedas_sin_resultado_pct,
                   -- titular del embudo: cada sesión una vez, aunque la sugerencia cruzada la ponga en dos verticales
                   round(100.0 * (SELECT count(DISTINCT session_id) FROM funnel_steps
                                  WHERE busca AND carro AND pago AND pedido)
                         / nullif((SELECT count(DISTINCT session_id) FROM funnel_steps WHERE busca), 0), 1)
                       AS conversion_sesiones_pct""",
        {"source": source},
    )
    row["source"] = source
    return row


def weekly(conn: Connection, source: str = "synthetic") -> list[dict]:
    """Serie semanal: usuarios activos, pedidos, búsquedas sin resultado y abandono de carrito (una sola pasada)."""
    _check(source)
    return _rows(
        conn,
        f"""WITH {_CARTS.strip()},
           ev AS (
               SELECT date_trunc('week', ts) AS week, user_id, type, unmet
               FROM app_events WHERE source = %(source)s
           ),
           activity AS (
               SELECT week, count(DISTINCT user_id) AS usuarios_activos,
                      round(100.0 * count(*) FILTER (WHERE type IN ('search', 'chat', 'ask') AND unmet)
                            / nullif(
                                count(*) FILTER (WHERE type IN ('search', 'chat', 'ask') AND unmet IS NOT NULL), 0
                            ), 1)
                          AS sin_resultado_pct
               FROM ev GROUP BY week
           ),
           orders AS (
               SELECT date_trunc('week', ts) AS week, count(*) AS pedidos
               FROM app_orders WHERE source = %(source)s AND status = 'confirmado' GROUP BY 1
           ),
           abandonment AS (  -- cada carro, en la semana de su último evento
               SELECT date_trunc('week', last_cart_ts) AS week,
                      round(100.0 * count(*) FILTER (WHERE is_abandoned) / nullif(count(*), 0), 1)
                          AS abandono_carrito_pct
               FROM cart_status GROUP BY 1
           )
           SELECT a.week::date AS semana, a.usuarios_activos, coalesce(o.pedidos, 0) AS pedidos,
                  a.sin_resultado_pct, ab.abandono_carrito_pct
           FROM activity a
           LEFT JOIN orders o USING (week)
           LEFT JOIN abandonment ab USING (week)
           ORDER BY a.week""",
        {"source": source},
    )


def opportunities(conn: Connection, source: str = "synthetic", weeks: int = 4) -> list[dict]:
    """Demanda no satisfecha por concepto (o consulta) y vertical, con tendencia y acción sugerida."""
    _check(source)
    return _rows(
        conn,
        f"""WITH unmet AS (
                SELECT e.user_id, e.vertical, e.concept_id, lower(e.query) AS query, e.ts, u.city
                FROM app_events e JOIN app_users u USING (user_id)
                WHERE e.source = %(source)s AND e.unmet AND e.type IN ('search', 'chat', 'ask')
                  AND (e.concept_id IS NOT NULL OR e.query IS NOT NULL)  -- la purga de 90 días deja ambas vacías
            ),
            agg AS (
                SELECT vertical, concept_id, CASE WHEN concept_id IS NULL THEN query END AS query,
                       count(*) AS busquedas, count(DISTINCT user_id) AS usuarios,
                       array_agg(DISTINCT city) FILTER (WHERE city IS NOT NULL) AS ciudades,
                       count(*) FILTER (WHERE ts > {_AS_OF} - make_interval(weeks => %(weeks)s)) AS recientes,
                       count(*) FILTER (WHERE ts <= {_AS_OF} - make_interval(weeks => %(weeks)s)
                                          AND ts > {_AS_OF} - make_interval(weeks => 2 * %(weeks)s)) AS anteriores
                FROM unmet GROUP BY 1, 2, 3
            ),
            elsewhere AS (  -- donde el agente lo ofrecería: la regla de agent.verticals.available_elsewhere
                SELECT concept_id, vertical, items FROM ({SHARES}) s WHERE items >= %(min_items)s
            )
            SELECT a.vertical, a.concept_id, coalesce(c.emoji || ' ' || c.name, a.query) AS que,
                   a.busquedas, a.usuarios, a.ciudades, a.recientes, a.anteriores,
                   CASE WHEN a.anteriores = 0 THEN NULL
                        ELSE round(100.0 * (a.recientes - a.anteriores) / a.anteriores, 0) END AS crecimiento_pct,
                   (SELECT string_agg(e.vertical, ', ' ORDER BY e.items DESC) FROM elsewhere e
                    WHERE e.concept_id = a.concept_id AND e.vertical <> a.vertical)
                       AS existe_en,
                   CASE WHEN a.concept_id IS NULL THEN 'Revisar la consulta: sumar sinónimo o concepto nuevo'
                        WHEN EXISTS (SELECT 1 FROM elsewhere e
                                     WHERE e.concept_id = a.concept_id AND e.vertical <> a.vertical)
                             THEN 'Existe en otro vertical: que el agente lo ofrezca ahí'
                        ELSE 'Oportunidad: sumar comercios o categoría' END AS accion
            FROM agg a LEFT JOIN concepts c ON c.concept_id = a.concept_id
            WHERE a.usuarios >= %(min_users)s
              AND c.sensitive IS NOT TRUE  -- ninguna palanca usa conceptos sensibles (regla 6)
            ORDER BY a.usuarios DESC""",
        {"source": source, "weeks": weeks, "min_users": 5, "min_items": MIN_ITEMS_ELSEWHERE},
    )


def trends(conn: Connection, source: str = "synthetic", weeks: int = 4, limit: int = 12) -> list[dict]:
    """Conceptos que suben o bajan: interés (búsquedas, preguntas al agente y carro) en las últimas N semanas
    contra las N anteriores."""
    _check(source)
    return _rows(
        conn,
        f"""WITH e AS (
                SELECT concept_id, ts FROM app_events
                WHERE source = %(source)s AND concept_id IS NOT NULL AND type IN ('search', 'chat', 'ask', 'cart_add')
            ),
            agg AS (
                SELECT concept_id,
                       count(*) FILTER (WHERE ts > {_AS_OF} - make_interval(weeks => %(weeks)s)) AS recientes,
                       count(*) FILTER (WHERE ts <= {_AS_OF} - make_interval(weeks => %(weeks)s)
                                          AND ts > {_AS_OF} - make_interval(weeks => 2 * %(weeks)s)) AS anteriores
                FROM e GROUP BY 1
            )
            SELECT a.concept_id, c.emoji || ' ' || c.name AS concepto, a.recientes, a.anteriores,
                   round(100.0 * (a.recientes - a.anteriores) / nullif(a.anteriores, 0), 0) AS crecimiento_pct
            FROM agg a JOIN concepts c USING (concept_id)
            WHERE a.anteriores >= 20 AND NOT c.sensitive
            ORDER BY abs(a.recientes - a.anteriores)::float / a.anteriores DESC
            LIMIT %(limit)s""",
        {"source": source, "weeks": weeks, "limit": limit},
    )


def funnel(conn: Connection, source: str = "synthetic") -> list[dict]:
    """Por vertical: sesiones que buscan (llegan a la vertical) → agregan al carro → inician pago → piden.

    La entrada (buscar, chatear, navegar, aceptar una sugerencia o agregar al carro desde una lista) se mira en toda
    la sesión: la sugerencia cruzada del agente lleva la compra a otra vertical, y exigirla en la misma dejaba fuera
    esos pedidos (Farmacia y Turbo quedaban en 0). Una sesión cuenta en una vertical si tuvo ahí algún evento que no
    sea ver o descartar una sugerencia: ver una sugerencia sin aceptarla no la mete en esa vertical.
    """
    _check(source)
    return _rows(
        conn,
        f"""WITH {_FUNNEL.strip()}
           SELECT vertical, count(*) FILTER (WHERE busca) AS buscan,
                  count(*) FILTER (WHERE busca AND carro) AS agregan,
                  count(*) FILTER (WHERE busca AND carro AND pago) AS pagan,
                  count(*) FILTER (WHERE busca AND carro AND pago AND pedido) AS piden
           FROM funnel_steps GROUP BY 1 ORDER BY 2 DESC""",
        {"source": source},
    )


def cohorts(conn: Connection, source: str = "synthetic", max_weeks: int = 8) -> list[dict]:
    """Retención por cohorte semanal (semana del primer pedido): % que vuelve a pedir en la semana k.

    Incluye las semanas sin nadie (0%) hasta la última semana terminada (la en curso queda vacía en el panel, no
    en 0%), y solo cohortes de al menos 20 usuarios.
    """
    _check(source)
    return _rows(
        conn,
        f"""WITH firsts AS (
               SELECT user_id, date_trunc('week', min(ts)) AS cohort FROM app_orders
               WHERE source = %(source)s AND status = 'confirmado'
               GROUP BY 1
           ),
           sizes AS (SELECT cohort, count(*) AS usuarios FROM firsts GROUP BY 1 HAVING count(*) >= %(min_users)s),
           activity AS (
               SELECT DISTINCT o.user_id, f.cohort,
                      -- en días enteros: el cambio de hora (semana de 6 días y 23 h) no corre las semanas
                      (date_trunc('week', o.ts)::date - f.cohort::date) / 7 AS k
               FROM app_orders o JOIN firsts f USING (user_id) WHERE o.source = %(source)s AND o.status = 'confirmado'
           ),
           grid AS (
               SELECT s.cohort, s.usuarios, k
               FROM sizes s
               CROSS JOIN LATERAL generate_series(
                   0, greatest(0, least(%(max_weeks)s, ((date_trunc('week', {_AS_OF}) - interval '1 day')::date
                                                         - s.cohort::date) / 7))) AS k
           )
           SELECT g.cohort::date AS cohorte, g.k AS semana,
                  round(100.0 * count(a.user_id) / g.usuarios, 1) AS retencion_pct, g.usuarios
           FROM grid g
           LEFT JOIN activity a ON a.cohort = g.cohort AND a.k = g.k
           GROUP BY g.cohort, g.k, g.usuarios
           ORDER BY g.cohort, g.k""",
        {"source": source, "max_weeks": max_weeks, "min_users": MIN_GROUP_USERS},
    )


def rhythm_histogram(conn: Connection, source: str = "synthetic") -> list[dict]:
    """Distribución del ritmo de compra (mediana de días entre pedidos por usuario)."""
    _check(source)
    return _rows(
        conn,
        f"""WITH {_RHYTHM.strip()}
            SELECT bucket AS dias, count(*) AS usuarios FROM (
                SELECT CASE WHEN days < 3 THEN '0–3' WHEN days < 7 THEN '3–7' WHEN days < 14 THEN '7–14'
                            WHEN days < 30 THEN '14–30' ELSE '30+' END AS bucket,
                       CASE WHEN days < 3 THEN 1 WHEN days < 7 THEN 2 WHEN days < 14 THEN 3
                            WHEN days < 30 THEN 4 ELSE 5 END AS ord
                FROM rhythm) b
            GROUP BY bucket, ord ORDER BY ord""",
        {"source": source},
    )


def at_risk(conn: Connection, source: str = "synthetic", limit: int = 100) -> list[dict]:
    """Usuarios en riesgo o perdidos (id seudónimo) con su concepto top NO sensible y la acción sugerida."""
    _check(source)
    return _rows(
        conn,
        f"""WITH {_RHYTHM.strip()},
            top_concept AS (
                SELECT DISTINCT ON (o.user_id) o.user_id, l.concept_id, count(*) AS n
                FROM app_order_lines l JOIN app_orders o USING (order_id)
                JOIN concepts c ON c.concept_id = l.concept_id
                WHERE o.source = %(source)s AND o.status = 'confirmado' AND NOT c.sensitive
                GROUP BY o.user_id, l.concept_id
                ORDER BY o.user_id, n DESC
            )
            SELECT 'u-' || left(md5(r.user_id), 8) AS usuario, u.segment AS persona, r.status AS estado,
                   round(r.rhythm::numeric, 1) AS ritmo_dias, round(r.since::numeric, 0) AS dias_sin_pedir,
                   c.emoji || ' ' || c.name AS concepto_top, u.consent_notifications AS consiente_avisos,
                   CASE WHEN NOT u.consent_notifications THEN 'Sin consentimiento: solo en la app (el agente)'
                        WHEN r.status = 'perdido' THEN 'Reactivar con novedad de su concepto top'
                        ELSE 'Recordatorio en su ritmo con su concepto top + complemento' END AS accion
            FROM risk r
            JOIN app_users u USING (user_id)
            LEFT JOIN (SELECT user_id, concept_id FROM top_concept) t USING (user_id)
            LEFT JOIN concepts c ON c.concept_id = t.concept_id
            WHERE r.status IN ('en_riesgo', 'perdido')
            -- Primero los "en riesgo" (todavía recuperables) y, entre ellos, los más atrasados respecto a su ritmo.
            ORDER BY (r.status = 'en_riesgo') DESC, r.since / nullif(r.rhythm, 0) DESC NULLS LAST
            LIMIT %(limit)s""",
        {"source": source, "limit": limit},
    )


MIN_SUGGESTIONS_SHOWN = 10  # mostradas para calcular (y, con datos simulados, mostrar) la aceptación


def suggestions(conn: Connection, source: str = "synthetic") -> list[dict]:
    """Rendimiento de las sugerencias del agente por concepto sugerido: todas (al preguntarle, en "Para ti" y en cada
    momento de oferta), el mismo material que `offers()` corta por momento.

    Aceptada = el producto sugerido se agregó al carro; convertida = llegó a un pedido; ignorada = "Ahora no" o
    "Después" (no la que se fue sola del globo, `payload.kind` "expirada"). El aviso sobre el carro no
    entra: ahí "aceptar" es abrir al agente, otra cosa. El % de aceptación necesita 10 mostradas; con la fuente
    prototipo las filas aparecen desde la primera (una demo en vivo debe verse) y el % queda vacío hasta entonces.
    """
    _check(source)
    return _rows(
        conn,
        """WITH s AS (
               SELECT concept_id, vertical,
                      count(*) FILTER (WHERE type = 'suggestion_shown') AS mostradas,
                      count(*) FILTER (WHERE type = 'suggestion_accepted') AS aceptadas,
                      count(*) FILTER (WHERE type = 'suggestion_dismissed'
                                         AND payload ->> 'kind' IS DISTINCT FROM %(expired)s) AS ignoradas
               FROM app_events
               WHERE source = %(source)s AND type LIKE 'suggestion_%%'
                 AND coalesce(origin, payload ->> 'origen') IS DISTINCT FROM 'aviso'
               GROUP BY 1, 2
           ),
           converted AS (
               SELECT l.concept_id, o.vertical, count(*) AS convertidas
               FROM app_order_lines l JOIN app_orders o USING (order_id)
               WHERE o.source = %(source)s AND o.status = 'confirmado' AND l.from_suggestion GROUP BY 1, 2
           )
           SELECT c.emoji || ' ' || c.name AS concepto, s.vertical, s.mostradas, s.aceptadas, s.ignoradas,
                  coalesce(cv.convertidas, 0) AS convertidas,
                  CASE WHEN s.mostradas >= %(min_rate)s
                       THEN round(100.0 * s.aceptadas / s.mostradas, 1) END AS aceptacion_pct
           FROM s JOIN concepts c USING (concept_id)
           LEFT JOIN converted cv ON cv.concept_id = s.concept_id AND cv.vertical = s.vertical
           WHERE s.mostradas >= %(min_shown)s AND NOT c.sensitive
           ORDER BY s.mostradas DESC""",
        {
            "source": source,
            "min_rate": MIN_SUGGESTIONS_SHOWN,
            "min_shown": 1 if source == "prototype" else MIN_SUGGESTIONS_SHOWN,
            "expired": EXPIRED_KIND,
        },
    )


def services(conn: Connection, source: str = "synthetic") -> list[dict]:
    """Servicios sin catálogo (RappiTravel, RappiFavor): cuántas veces el agente los ofreció, cuántas se abrieron
    (`abierto`) y cuántas desde los accesos de la Home (`desde_home`, `payload.desde = 'home'`: no mide al agente), y
    los ganchos del catálogo (sugerencias con su origen) mostrados y aceptados. Una fila por servicio de la taxonomía.
    """
    _check(source)
    counts = {
        (service, kind): n
        for service, kind, n in conn.execute(
            """SELECT coalesce(payload ->> 'servicio', origin, payload ->> 'origen'),
                      CASE WHEN type = 'service_opened' AND payload ->> 'desde' = 'home'
                           THEN 'service_opened_home' ELSE type END,
                      count(*)
               FROM app_events
               WHERE source = %(source)s AND (type IN ('service_shown', 'service_opened')
                     OR (type IN ('suggestion_shown', 'suggestion_accepted')
                         AND coalesce(origin, payload ->> 'origen') = ANY(%(ids)s)))
               GROUP BY 1, 2""",
            {"source": source, "ids": list(load_taxonomy().services)},
        )
    }
    return [
        {
            "servicio": s.id,
            "nombre": s.label,
            "ofrecido": counts.get((s.id, "service_shown"), 0),
            "abierto": counts.get((s.id, "service_opened"), 0),
            "desde_home": counts.get((s.id, "service_opened_home"), 0),
            "ganchos_mostrados": counts.get((s.id, "suggestion_shown"), 0),
            "ganchos_aceptados": counts.get((s.id, "suggestion_accepted"), 0),
        }
        for s in load_taxonomy().services.values()
    ]


# Momentos de las ofertas del agente, en el orden del panel. "pregunta" = lo que sugiere al preguntarle; "para_ti" =
# la sección "Para ti"; "sin_momento" = sin origen o con uno desconocido (las sugerencias cruzadas simuladas no lo
# traen): se cuentan aparte en vez de perderse.
OFFER_MOMENTS = (
    "plan",
    "carrito",
    "checkout",
    "proximo_pedido",
    "sin_resultado",
    "vertical_por_probar",
    "recompra",
    "volver",
    "ontop",
    "perfil",
)
OFFER_ORDER = (*OFFER_MOMENTS, "pregunta", "para_ti", "sin_momento")


def offers(conn: Connection, source: str = "synthetic") -> dict:
    """Ofertas del agente mostradas, aceptadas y rechazadas por momento, cuántas veces se abrió su "¿Por qué?"
    (`offer_why_open`) y cuántas veces se abrió su vertical desde la oferta (`abiertas`: `vertical_open` con el origen
    `agent-<momento>`, como "Ver …" o "Abrir …"; no es una aceptación), según el origen de la sugerencia (la columna
    `origin`, o `payload.origen` en los eventos de antes de la migración 043). Rechazada = "Ahora no" o "Después"
    (`suggestion_dismissed`); la oferta que se fue sola del globo (`payload.kind` "expirada") no es un rechazo y no
    cuenta.

    `agent-<momento>` es el origen actual; `mochi-<momento>` y `chat` son nombres históricos que siguen en la base.
    Los servicios (RappiTravel, RappiFavor) tienen su propia vista y el aviso sobre el carro no es una oferta: no
    entran. El % de aceptación necesita 10 mostradas, como en `suggestions`. `autopedidos` cuenta aparte los pedidos
    que Mochi hizo solo con permiso ("Pedir por mí"): `{pedidos, personas}`.
    """
    _check(source)
    params = {
        "source": source,
        "excluded": [*load_taxonomy().services, "aviso"],
        "moments": list(OFFER_MOMENTS),
        "min_rate": MIN_SUGGESTIONS_SHOWN,
        "types": ["suggestion_shown", "suggestion_accepted", "suggestion_dismissed", "offer_why_open"],
        "expired": EXPIRED_KIND,
    }
    # `vertical_open` solo entra con el origen de un momento: los toques a los accesos de la Home no son ofertas.
    shown = """WITH e AS (
                   SELECT user_id, type, kind,
                          CASE WHEN origen IN ('agent-ask', 'chat') THEN 'pregunta'  -- 'chat': nombre histórico
                               -- 'para-ti-local' y 'vertical-para-ti': nombres históricos de "Para ti"
                               WHEN origen IN ('para-ti', 'para-ti-local', 'vertical-para-ti') THEN 'para_ti'
                               -- 'mochi-<momento>': nombre histórico de 'agent-<momento>'
                               WHEN left(origen, 6) IN ('agent-', 'mochi-') AND substr(origen, 7) = ANY(%(moments)s)
                                    THEN substr(origen, 7)
                               ELSE 'sin_momento' END AS momento
                   FROM (SELECT user_id, type, coalesce(origin, payload ->> 'origen') AS origen,
                                payload ->> 'kind' AS kind
                         FROM app_events
                         WHERE source = %(source)s
                           AND (type = ANY(%(types)s)
                                OR (type = 'vertical_open' AND left(origin, 6) = 'agent-'
                                    AND substr(origin, 7) = ANY(%(moments)s)))) o
                   WHERE coalesce(origen, '') <> ALL(%(excluded)s)
               )"""
    [row] = _rows(conn, f"{shown} SELECT count(DISTINCT user_id) AS personas FROM e", params)
    row["momentos"] = _rows(
        conn,
        f"""{shown}
            SELECT momento, mostradas, aceptadas, rechazadas, abiertas, por_que_abiertos,
                   CASE WHEN mostradas >= %(min_rate)s THEN round(100.0 * aceptadas / mostradas, 1) END
                       AS aceptacion_pct
            FROM (SELECT momento, count(*) FILTER (WHERE type = 'suggestion_shown') AS mostradas,
                         count(*) FILTER (WHERE type = 'suggestion_accepted') AS aceptadas,
                         count(*) FILTER (WHERE type = 'suggestion_dismissed'
                                            AND kind IS DISTINCT FROM %(expired)s) AS rechazadas,
                         count(*) FILTER (WHERE type = 'vertical_open') AS abiertas,
                         count(*) FILTER (WHERE type = 'offer_why_open') AS por_que_abiertos
                  FROM e GROUP BY 1) g""",
        params,
    )
    row["momentos"].sort(key=lambda m: OFFER_ORDER.index(m["momento"]))
    # Los pedidos que Mochi hizo solo, con permiso ("Pedir por mí", offers/autonomy.py), aparte: no son ofertas
    # aceptadas. Su `order_placed` lleva el origen `agent-autopedido`.
    [auto] = _rows(
        conn,
        f"""SELECT count(*) AS pedidos, count(DISTINCT user_id) AS personas FROM app_events e
            WHERE source = %(source)s AND type = 'order_placed' AND origin = %(origin)s AND {_NOT_CANCELLED}""",
        {"source": source, "origin": AUTO_ORDER_ORIGIN},
    )
    row["autopedidos"] = auto
    return row


def winback(conn: Connection, source: str = "synthetic") -> dict:
    """ "¿Volvemos a…?": a cuántas personas de la fuente les tocaría, por el tipo de su primera invitación (un concepto
    o una vertical que dejó), y a cuántas la recompra, el día de referencia (`offers.winback.reach`: el último pedido
    simulado, u hoy en el prototipo; `dia` solo en simulados). Es quién califica, no a quién se le mostró; con datos
    simulados no es evidencia."""
    _check(source)
    return reach(conn, source)


MAX_UNMET_ROWS = 20


def unmet(conn: Connection, source: str = "synthetic") -> dict:
    """Búsquedas y preguntas al agente que saben si encontraron algo (`unmet` no nulo) y, de las sin resultado, cuántas
    por vertical y concepto. Nunca el texto buscado (`concepto` es NULL si no se reconoció) ni conceptos sensibles.

    `abandono`: de las búsquedas que saben qué se tocó desde ellas (con `request_id`), cuántas tuvieron un toque con
    ese mismo `request_id` en su sesión (`con_clic`), cuántas no pero otra búsqueda con toque las siguió en
    `SEARCH_RESCUE_MINUTES` (`rescatadas`: la reformulación funcionó) y cuántas quedaron en nada (`abandonadas`). El %
    necesita `MIN_SEARCHES_FOR_RATE` búsquedas. Solo búsquedas: lo que se le pide a Mochi se refina con chips."""
    _check(source)
    params = {"source": source, "limit": MAX_UNMET_ROWS}
    # Los conceptos sensibles no entran en ninguna cifra, ni en los totales: no se deducen de la resta.
    searched = """FROM app_events e LEFT JOIN concepts c ON c.concept_id = e.concept_id
                  WHERE e.source = %(source)s AND e.type IN ('search', 'chat', 'ask') AND e.unmet IS NOT NULL
                    AND c.sensitive IS NOT TRUE"""
    [row] = _rows(
        conn,
        f"""SELECT count(DISTINCT e.user_id) AS personas, count(*) AS busquedas,
                   count(*) FILTER (WHERE e.unmet) AS sin_resultado
            {searched}""",
        params,
    )
    row["por_vertical"] = _rows(
        conn,
        f"""SELECT e.vertical, c.emoji || ' ' || c.name AS concepto, count(*) AS sin_resultado
            {searched} AND e.unmet
            GROUP BY e.vertical, e.concept_id, c.emoji, c.name
            -- empates por códigos en "C": el mismo orden en cualquier base (las respuestas de ejemplo se comparan)
            ORDER BY 3 DESC, e.vertical COLLATE "C" NULLS LAST, e.concept_id COLLATE "C" NULLS LAST
            LIMIT %(limit)s""",
        params,
    )
    row["abandono"] = _search_abandonment(conn, source)
    return row


def _search_abandonment(conn: Connection, source: str) -> dict:
    [row] = _rows(
        conn,
        """WITH searched AS (
               SELECT e.user_id, e.session_id, e.ts,
                      EXISTS (SELECT 1 FROM app_events k
                              WHERE k.request_id = e.request_id AND k.source = e.source AND k.user_id = e.user_id
                                AND k.session_id = e.session_id AND k.type = ANY(%(clicks)s)) AS clic
               FROM app_events e LEFT JOIN concepts c ON c.concept_id = e.concept_id
               WHERE e.source = %(source)s AND e.type = 'search' AND e.request_id IS NOT NULL
                 AND c.sensitive IS NOT TRUE
           ),
           followed AS (  -- la próxima búsqueda con toque de la misma sesión
               SELECT clic, ts, min(ts) FILTER (WHERE clic) OVER (
                          PARTITION BY user_id, session_id ORDER BY ts
                          ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING) AS next_clicked
               FROM searched
           ),
           counted AS (
               SELECT count(*) AS busquedas, count(*) FILTER (WHERE clic) AS con_clic,
                      count(*) FILTER (WHERE NOT clic AND next_clicked <= ts + make_interval(mins => %(minutes)s))
                          AS rescatadas
               FROM followed
           )
           SELECT busquedas, con_clic, rescatadas, busquedas - con_clic - rescatadas AS abandonadas,
                  CASE WHEN busquedas >= %(min_rate)s
                       THEN round(100.0 * (busquedas - con_clic - rescatadas) / busquedas, 1) END AS abandono_pct
           FROM counted""",
        {
            "source": source,
            "clicks": list(SEARCH_CLICKS),
            "minutes": SEARCH_RESCUE_MINUTES,
            "min_rate": MIN_SEARCHES_FOR_RATE,
        },
    )
    return row | {"plazo_minutos": SEARCH_RESCUE_MINUTES}


def _rappi_row(row) -> dict:
    return {
        "combo": row.combo,
        "usuarios": row.users,
        "pct_usuarios": row.pct_users,
        "pct_pedidos": row.pct_orders,
        "pedidos_por_usuario": row.orders_per_user,
        "retencion_m1": row.retention_m1,
        "gasto_por_usuario": row.spend_per_user,
    }


def combos(conn: Connection, source: str = "synthetic") -> dict:
    """La tabla de Rappi ("verticales usados juntos", `motor/combos.toml`) junto a la misma tabla medida con los datos
    de la fuente (`combo_stats`, de la última corrida del motor). La de Rappi es un dato compartido por su equipo y no
    depende de la fuente; la propia sí, y lleva su rótulo en `nota`. La retención propia solo se entrega con
    `MIN_COMBO_RETENTION_N` meses que tengan el siguiente completo. Es una correlación, no un efecto.

    `fino`: las `FINE_COMBO_ROWS` combinaciones finas (verticales una por una) más frecuentes de la fuente, con su
    retención aprendida (con la misma regla) y la `esperada` de la tabla de Rappi con el supuesto propio del
    rendimiento decreciente, sin lo aprendido; `supuesto`, los valores de ese supuesto (`[rendimiento_decreciente]`).
    Con pocas personas (`prototype`) la tabla fina no señala a nadie: sin las combinaciones que incluyen Farmacia o
    Licores (solo suben por señales propias) y solo las de al menos `MIN_GROUP_USERS` personas-mes."""
    _check(source)
    table = load_combos()
    own = _rows(
        conn,
        """SELECT combo, user_months AS meses_usuario, pct_users AS pct_usuarios, pct_orders AS pct_pedidos,
                  orders_per_user AS pedidos_por_usuario,
                  CASE WHEN retention_n >= %(min_n)s THEN retention_m1 END AS retencion_m1,
                  retention_n AS retencion_n, spend_per_user AS gasto_por_usuario
           FROM combo_stats WHERE data_source = %(source)s AND nivel = 'grueso'
           ORDER BY user_months DESC, combo COLLATE "C" """,
        {"source": source, "min_n": MIN_COMBO_RETENTION_N},
    )
    fine = _rows(
        conn,
        """SELECT combo, user_months AS meses_usuario,
                  CASE WHEN retention_n >= %(min_n)s THEN retention_m1 END AS retencion_m1,
                  retention_n AS retencion_n
           FROM combo_stats WHERE data_source = %(source)s AND nivel = 'fino'
             AND (%(source)s <> 'prototype' OR (user_months >= %(min_group)s AND combo !~ %(own_only)s))
           ORDER BY user_months DESC, combo COLLATE "C" LIMIT %(limit)s""",
        {
            "source": source,
            "min_n": MIN_COMBO_RETENTION_N,
            "limit": FINE_COMBO_ROWS,
            "min_group": MIN_GROUP_USERS,
            "own_only": r"(^|\+)(" + "|".join(sorted(OWN_SIGNALS_ONLY)) + r")(\+|$)",
        },
    )
    for row in fine:
        expected = expected_fine_retention(row["combo"])
        row["esperada"] = None if expected is None else round(expected, 4)
    dim = table.diminishing
    return {
        "rappi": {
            "filas": [_rappi_row(row) for row in table.rappi.values()],
            "total": _rappi_row(table.rappi_total),
            "nota": table.source_note,
        },
        "propio": own,
        "fino": fine,
        "supuesto": {
            "reduccion_base": dim.reduction_base,
            "decaimiento": dim.decay,
            "servicio": dim.service,
            "nota": dim.note,
        },
        "nota": COMBO_NOTES[source],
    }


def motor(conn: Connection, source: str = "synthetic") -> dict | None:
    """Los pesos, el λ y la evaluación de la última corrida terminada del motor de esa fuente, con su fecha; `None`
    si todavía no corrió. La evaluación va como la guardó `motor.evaluate` (`None` si no hubo 84 días de datos)."""
    _check(source)
    [row] = _rows(
        conn,
        """SELECT counts -> 'pesos' AS pesos, counts -> 'lambda_cruzada' AS lambda_cruzada,
                  counts -> 'evaluacion' AS evaluacion, finished_at
           FROM layer_runs
           WHERE layer = 'motor' AND status = 'done' AND counts ->> 'fuente' = %(source)s
           ORDER BY run_id DESC LIMIT 1""",
        {"source": source},
    ) or [None]
    if row is None:
        return None
    return {
        "pesos": row["pesos"],
        "lambda_cruzada": row["lambda_cruzada"],
        "evaluacion": row["evaluacion"],
        "fecha": row["finished_at"].astimezone(TZ).isoformat(),
    }


def home(conn: Connection, source: str = "synthetic") -> dict:
    """Toques de los accesos de la Home (`vertical_open`) por vertical: personas y toques. "Rappi hoy"
    (`payload.mode = 'actual'`) no cuenta, como en todo lo que aprende el motor, ni los servicios sin catálogo. Solo los
    de la Home (`surface`; sin ella, los de antes de la migración 043, que solo anotaba la Home) y no los que abren una
    oferta de Mochi (origen `agent-<momento>`, como el perfil de gusto o "Ver …" de una oferta), que el motor sí
    aprende."""
    _check(source)
    taps = """FROM app_events
              WHERE source = %(source)s AND type = 'vertical_open' AND vertical IS NOT NULL
                AND NOT payload ? 'servicio' AND payload ->> 'mode' IS DISTINCT FROM 'actual'
                AND coalesce(surface, 'home') = 'home' AND coalesce(origin, '') NOT LIKE 'agent-%%'"""
    rows = _rows(
        conn,
        f"""SELECT vertical, count(DISTINCT user_id) AS personas, count(*) AS toques {taps}
            GROUP BY vertical ORDER BY 3 DESC, vertical COLLATE "C" """,
        {"source": source},
    )
    [totals] = _rows(conn, f"SELECT count(DISTINCT user_id) AS personas, count(*) AS toques {taps}", {"source": source})
    return {**totals, "verticales": rows}


def presence(conn: Connection, source: str = "synthetic") -> dict:
    """Si Mochi molesta: en los últimos ACTIVE_DAYS días (hasta el último evento de la fuente, como `kpis`), de las
    personas activas (algún evento), cuántas lo tienen oculto (su último `agent_visibility`, de cuando sea, es
    `visible: false`) y qué % son; cuántas veces lo ocultaron y cuántas personas lo trajeron de vuelta (algún
    `visible: true`); cuántas veces lo silenciaron por hoy (`silenciadas`), cuántas personas (`silenciaron`) y qué %
    de las activas son (`silenciaron_pct`); y cuántas veces explicó por qué movió los accesos de la Home
    (`vertical_reorder_shown`), a cuántas personas. La app no anota "¿Por qué?" ni "Entendido" del globo: no se
    cuentan. "Repetir escena" lo devuelve y lo anota (`visible: true`); cambiar de persona en la demo o "Borrar mis
    datos" lo devuelven sin evento, porque es otra persona: "oculto" es el último cambio que hizo la persona. Silenciar
    y despertar también son `agent_visibility`, con `payload.quiet` (`visible` sigue en true): no cuentan como ocultar
    ni como traerlo de vuelta."""
    _check(source)
    [row] = _rows(
        conn,
        f"""WITH active AS (
                SELECT DISTINCT user_id FROM app_events
                WHERE source = %(source)s AND ts > {_AS_OF} - interval '{ACTIVE_DAYS} days'
            ),
            visibility AS (
                SELECT user_id, ts, (payload ->> 'visible')::boolean AS visible FROM app_events
                WHERE source = %(source)s AND type = 'agent_visibility'
                  AND jsonb_typeof(payload -> 'visible') = 'boolean' AND NOT payload ? 'quiet'
            ),
            quieted AS (
                SELECT user_id FROM app_events
                WHERE source = %(source)s AND type = 'agent_visibility' AND payload -> 'quiet' = 'true'::jsonb
                  AND ts > {_AS_OF} - interval '{ACTIVE_DAYS} days'
            ),
            last_visibility AS (
                SELECT DISTINCT ON (user_id) user_id, visible FROM visibility ORDER BY user_id, ts DESC
            ),
            recent AS (SELECT * FROM visibility WHERE ts > {_AS_OF} - interval '{ACTIVE_DAYS} days'),
            explained AS (
                SELECT user_id FROM app_events
                WHERE source = %(source)s AND type = 'vertical_reorder_shown'
                  AND ts > {_AS_OF} - interval '{ACTIVE_DAYS} days'
            ),
            hidden AS (
                SELECT count(*) AS n FROM last_visibility WHERE NOT visible AND user_id IN (SELECT * FROM active)
            )
            SELECT (SELECT count(*) FROM active) AS personas_activas,
                   (SELECT n FROM hidden) AS ocultos,
                   round(100.0 * (SELECT n FROM hidden) / nullif((SELECT count(*) FROM active), 0), 1) AS ocultos_pct,
                   (SELECT count(*) FROM recent WHERE NOT visible) AS ocultadas,
                   (SELECT count(DISTINCT user_id) FROM recent WHERE visible) AS volvieron,
                   (SELECT count(*) FROM quieted) AS silenciadas,
                   (SELECT count(DISTINCT user_id) FROM quieted) AS silenciaron,
                   round(100.0 * (SELECT count(DISTINCT user_id) FROM quieted)
                         / nullif((SELECT count(*) FROM active), 0), 1) AS silenciaron_pct,
                   (SELECT count(*) FROM explained) AS explicaciones,
                   (SELECT count(DISTINCT user_id) FROM explained) AS explicaciones_personas""",
        {"source": source},
    )
    return row


CTR_POSITIONS = 10  # las primeras posiciones de cada lista que muestra el panel


def ctr_by_position(conn: Connection, source: str = "synthetic") -> dict:
    """CTR por posición (`capa.v_ctr_posicion`, migración 048) en el prototipo con Mochi (`modo = 'propuesta'`):
    `posiciones`, las primeras CTR_POSITIONS de todas las listas juntas, y `listas`, cada pantalla y lista con sus
    totales, de la más vista a la menos. Un elemento cuenta una vez por sesión, respuesta y lugar."""
    _check(source)
    params = {"source": source, "positions": CTR_POSITIONS}
    where = "FROM capa.v_ctr_posicion WHERE source = %(source)s AND modo = 'propuesta'"
    positions = _rows(
        conn,
        f"""SELECT position AS posicion, sum(impresiones)::bigint AS impresiones, sum(clics)::bigint AS clics,
                   round(sum(clics)::numeric / sum(impresiones), 4) AS ctr
            {where} AND position < %(positions)s GROUP BY position ORDER BY position""",
        params,
    )
    lists = _rows(
        conn,
        f"""SELECT surface AS pantalla, origin AS lista, sum(impresiones)::bigint AS impresiones,
                   sum(clics)::bigint AS clics, round(sum(clics)::numeric / sum(impresiones), 4) AS ctr
            {where} GROUP BY surface, origin ORDER BY 3 DESC, 1, 2""",
        params,
    )
    return {"posiciones": positions, "listas": lists}


def session_funnel(conn: Connection, source: str = "synthetic") -> list[dict]:
    """El embudo por sesión (`capa.v_embudo_sesion`, migración 048), por modo: sesiones → vieron algo → además tocaron
    algo → además agregaron al carro → además pidieron. Cada paso exige los anteriores."""
    _check(source)
    return _rows(
        conn,
        """SELECT modo, count(*) AS sesiones,
                  count(*) FILTER (WHERE vio) AS vieron,
                  count(*) FILTER (WHERE vio AND clic) AS tocaron,
                  count(*) FILTER (WHERE vio AND clic AND carro) AS agregaron,
                  count(*) FILTER (WHERE vio AND clic AND carro AND pedido) AS pidieron
           FROM capa.v_embudo_sesion WHERE source = %(source)s
           GROUP BY modo ORDER BY modo = 'actual', modo""",
        {"source": source},
    )


# Cómo leer cada experimento en el panel. Uno que no esté aquí se lee con su `description` (tabla `experiments`).
EXPERIMENT_NOTES = {
    exp.MODE: (
        'No es al azar: el modo lo elige quien presenta la demo. Comparar la propuesta con "Rappi hoy" describe, '
        "no mide efecto."
    ),
    exp.OFFERS_CONTROL: (
        "Al azar: un sorteo estable con el id de la persona. A control no se le muestran las ofertas que "
        f"{config.AGENT_NAME} propone solo (quedan como retenidas). La diferencia entre los grupos mide el efecto de "
        "esas ofertas cuando cada grupo llega al mínimo del plan de piloto (docs/plan-piloto.md); antes, no es "
        "concluyente."
    ),
}


# Lo que anota la API cuando tiene una oferta retenible para alguien de `ofertas_control` (api/agent.py: `_withheld`),
# con la misma regla en los dos grupos: `offer_withheld` en control (no la ve) y `offer_eligible` en tratamiento.
# La parte expuesta se cuenta con ellos, no con lo que la app alcanzó a mostrar (`suggestion_shown`).
OFFERED_EVENTS = ("offer_withheld", "offer_eligible")


def experiment_results(conn: Connection, source: str = "synthetic") -> dict:
    """Los experimentos (migración 047) por variante, dentro de una sola población: personas asignadas, con pedido y
    verticales por persona con pedido (distintas en sus pedidos confirmados, como el multi-vertical de `kpis`), todo
    desde que se le asignó la variante. `al_azar` dice si comparar variantes mide un efecto (`azar`) o solo describe
    (`elegida`). En `ofertas_control`, además, `control_pct` (OFFERS_CONTROL_PCT: en 0 nadie entra) y por variante las
    ofertas de los momentos que Mochi propone solo (`exp.HOLDOUT_MOMENTS`): mostradas (`suggestion_shown`), retenidas
    (`offer_withheld`), aceptadas, personas con alguna y los pedidos confirmados después de la primera; y su
    `retencion` (`_offers_retention`). Las mostradas y aceptadas son las de fuera del buscador (`exp.ASKED_SURFACE`):
    lo que la persona pide ahí lo ven los dos grupos, así que no cuenta ni como oferta ni como persona expuesta. Las
    personas con alguna se cuentan en los dos grupos con lo que anota la API (OFFERED_EVENTS: `offer_withheld` en
    control y `offer_eligible` en tratamiento), desde la asignación y sin tope."""
    _check(source)
    params = {
        "source": source,
        "offers": exp.OFFERS_CONTROL,
        "origins": [f"agent-{m}" for m in exp.HOLDOUT_MOMENTS],
        "asked": exp.ASKED_SURFACE,
        "offered": list(OFFERED_EVENTS),
    }
    declared = _rows(
        conn,
        "SELECT experiment_id, description, variants, assignment FROM experiments ORDER BY started_at, experiment_id",
        params,
    )
    groups = _rows(
        conn,
        """WITH per_person AS (
               SELECT a.experiment_id, a.variant, a.user_id,
                      count(o.order_id) AS pedidos, count(DISTINCT o.vertical) AS verticales
               FROM experiment_assignments a
               LEFT JOIN app_orders o ON o.user_id = a.user_id AND o.source = a.source AND o.status = 'confirmado'
                    AND o.ts >= a.assigned_at
               WHERE a.source = %(source)s
               GROUP BY 1, 2, 3
           )
           SELECT experiment_id, variant, count(*) AS personas,
                  count(*) FILTER (WHERE pedidos > 0) AS con_pedido,
                  round(avg(verticales) FILTER (WHERE pedidos > 0), 2) AS verticales_por_persona
           FROM per_person GROUP BY 1, 2""",
        params,
    )
    offers = _rows(
        conn,
        """WITH assigned AS (
               SELECT user_id, variant, assigned_at FROM experiment_assignments
               WHERE source = %(source)s AND experiment_id = %(offers)s
           ),
           seen AS (
               SELECT a.user_id, a.variant, e.type, e.ts FROM assigned a
               JOIN app_events e ON e.user_id = a.user_id AND e.source = %(source)s AND e.ts >= a.assigned_at
               WHERE e.type = ANY(%(offered)s)
                  OR (e.type IN ('suggestion_shown', 'suggestion_accepted')
                      AND coalesce(e.origin, e.payload ->> 'origen') = ANY(%(origins)s)
                      AND e.surface IS DISTINCT FROM %(asked)s)
           ),
           first_offer AS (
               SELECT user_id, variant, min(ts) AS ts FROM seen
               WHERE type = ANY(%(offered)s) GROUP BY 1, 2
           ),
           after AS (
               SELECT f.variant, count(o.order_id) AS pedidos FROM first_offer f
               JOIN app_orders o ON o.user_id = f.user_id AND o.source = %(source)s AND o.status = 'confirmado'
                    AND o.ts > f.ts
               GROUP BY 1
           )
           SELECT s.variant,
                  count(*) FILTER (WHERE s.type = 'suggestion_shown') AS mostradas,
                  count(*) FILTER (WHERE s.type = 'offer_withheld') AS retenidas,
                  count(*) FILTER (WHERE s.type = 'suggestion_accepted') AS aceptadas,
                  (SELECT count(*) FROM first_offer f WHERE f.variant = s.variant) AS personas_con_oferta,
                  coalesce((SELECT pedidos FROM after WHERE after.variant = s.variant), 0) AS pedidos_despues
           FROM seen s GROUP BY 1""",
        params,
    )
    by_group = {(g["experiment_id"], g["variant"]): g for g in groups}
    offers_by_variant = {o.pop("variant"): o for o in offers}
    no_offers = {"mostradas": 0, "retenidas": 0, "aceptadas": 0, "personas_con_oferta": 0, "pedidos_despues": 0}
    result = []
    for e in declared:
        variants = []
        for variant in e["variants"]:
            group = by_group.get((e["experiment_id"], variant), {})
            row = {
                "variante": variant,
                "personas": group.get("personas", 0),
                "con_pedido": group.get("con_pedido", 0),
                "verticales_por_persona": group.get("verticales_por_persona"),
            }
            if e["experiment_id"] == exp.OFFERS_CONTROL:
                row["ofertas"] = offers_by_variant.get(variant, no_offers)
            variants.append(row)
        item = {
            "id": e["experiment_id"],
            "al_azar": e["assignment"] == "azar",
            "nota": EXPERIMENT_NOTES.get(e["experiment_id"], e["description"]),
            "variantes": variants,
        }
        if e["experiment_id"] == exp.OFFERS_CONTROL:
            item["control_pct"] = config.OFFERS_CONTROL_PCT
            item["retencion"] = _offers_retention(conn, params, variants)
        result.append(item)
    return {"experimentos": result}


def _offers_retention(conn: Connection, params: dict, variants: list[dict]) -> dict:
    """La retención en `ofertas_control` (docs/plan-piloto.md), por variante, sobre la cohorte de asignación con su mes
    siguiente completo (quien recibió la variante en el mes M, con M+1 ya terminado en los datos): `retencion_m1_pct`,
    la parte con algún pedido confirmado en M+1 (como la M+1 de la tabla de Rappi), y `suma_vertical_pct`, la parte que
    pide en los 28 días desde la asignación en una vertical en la que no había pedido antes (M+1 termina al menos 28
    días después de cualquier día de M: la misma cohorte vale para las dos). `diferencia` es tratamiento − control en
    puntos. `minimo` son las personas que pide cada grupo para un efecto de +5 puntos sobre la M+1 de "solo
    Restaurantes" de la tabla de Rappi (un supuesto), con el reparto de quienes tienen variante; bajo ese mínimo,
    `concluyente` es falso y la diferencia va sin su IC de 95 % (`ic95` nulo): con pocas personas, un grupo en 0 % o
    100 % lo encoge y parecería un efecto.
    `expuestas` (y `expuestas_pct`) es la parte expuesta de la misma cohorte: quien tuvo una oferta retenible
    (OFFERED_EVENTS, el mismo hecho del servidor en los dos grupos) entre su asignación y el inicio de M+1. Sirve para
    pasar del efecto por intención de tratar al efecto entre expuestos (docs/plan-piloto.md)."""
    cohort = _rows(
        conn,
        f"""WITH cohort AS (
               SELECT user_id, variant, assigned_at,
                      date_trunc('month', assigned_at AT TIME ZONE %(tz)s) AS month
               FROM experiment_assignments
               WHERE source = %(source)s AND experiment_id = %(offers)s
           ),
           confirmed AS NOT MATERIALIZED (  -- en cada EXISTS, con el índice (user_id, ts) de la persona
               SELECT user_id, vertical, ts FROM app_orders WHERE source = %(source)s AND status = 'confirmado'
           )
           SELECT c.variant, count(*) AS personas,
                  count(*) FILTER (WHERE EXISTS (
                      SELECT 1 FROM confirmed o WHERE o.user_id = c.user_id
                         AND o.ts AT TIME ZONE %(tz)s >= c.month + interval '1 month'
                         AND o.ts AT TIME ZONE %(tz)s < c.month + interval '2 months')) AS retenidas,
                  count(*) FILTER (WHERE EXISTS (
                      SELECT 1 FROM confirmed o WHERE o.user_id = c.user_id
                         AND o.ts >= c.assigned_at AND o.ts < c.assigned_at + interval '28 days'
                         AND NOT EXISTS (
                             SELECT 1 FROM confirmed b WHERE b.user_id = c.user_id AND b.vertical = o.vertical
                                AND b.ts < c.assigned_at))) AS suman_vertical,
                  count(*) FILTER (WHERE EXISTS (
                      SELECT 1 FROM app_events e WHERE e.user_id = c.user_id AND e.source = %(source)s
                         AND e.type = ANY(%(offered)s) AND e.ts >= c.assigned_at
                         AND e.ts AT TIME ZONE %(tz)s < c.month + interval '1 month')) AS expuestas
           FROM cohort c
           WHERE c.month + interval '2 months' <= {_AS_OF} AT TIME ZONE %(tz)s
           GROUP BY 1""",
        {**params, "tz": TZ.key},
    )
    by_variant = {row["variant"]: row for row in cohort}
    groups = {}
    for v in variants:
        row = by_variant.get(v["variante"], {})
        n = row.get("personas", 0)
        groups[v["variante"]] = {
            "variante": v["variante"],
            "personas": n,
            "retenidas": row.get("retenidas", 0),
            "suman_vertical": row.get("suman_vertical", 0),
            "expuestas": row.get("expuestas", 0),
        }

    def pct(part: int, n: int) -> float | None:
        return round(100 * part / n, 1) if n else None

    assigned = {v["variante"]: v["personas"] for v in variants}
    minimum = None
    base = load_combos().rappi["rest"].retention_m1
    if assigned[exp.TREATMENT] and assigned[exp.CONTROL]:
        share = assigned[exp.CONTROL] / (assigned[exp.TREATMENT] + assigned[exp.CONTROL])
        need_control, need_treated = sample_size(base, PILOT_MIN_EFFECT, share)
        minimum = {exp.TREATMENT: need_treated, exp.CONTROL: need_control}
    conclusive = minimum is not None and all(groups[variant]["personas"] >= need for variant, need in minimum.items())
    treated, control = groups[exp.TREATMENT], groups[exp.CONTROL]
    difference = None
    if treated["personas"] and control["personas"]:
        difference = {}
        for key, metric in (("retenidas", "retencion_m1"), ("suman_vertical", "suma_vertical")):
            diff, low, high = difference_ci((treated[key], treated["personas"]), (control[key], control["personas"]))
            ci = [round(100 * low, 1), round(100 * high, 1)] if conclusive else None
            difference[metric] = {"puntos": round(100 * diff, 1), "ic95": ci}
    return {
        "variantes": [
            {
                "variante": g["variante"],
                "personas": g["personas"],
                "retencion_m1_pct": pct(g["retenidas"], g["personas"]),
                "suma_vertical_pct": pct(g["suman_vertical"], g["personas"]),
                "expuestas": g["expuestas"],
                "expuestas_pct": pct(g["expuestas"], g["personas"]),
            }
            for g in groups.values()
        ],
        "diferencia": difference,
        "minimo": minimum,
        "efecto_minimo_puntos": round(100 * PILOT_MIN_EFFECT),
        "base_pct": round(100 * base, 1),
        "concluyente": conclusive,
    }


def multi_vertical_retention(conn: Connection, source: str = "synthetic") -> list[dict]:
    """Retención (pedido entre días 61 y 120) de multi-vertical vs un vertical, a igual número de compras.

    Estratificar por compras evita la confusión obvia (quien pide más cae más en 2 verticales y retiene más). Una
    compra es un carro: dividido en dos verticales son dos pedidos, pero una compra.
    Solo usuarios cuyo primer pedido fue hace ≥ 120 días.
    """
    _check(source)
    return _rows(
        conn,
        f"""WITH firsts AS (
                SELECT user_id, min(ts) AS first_ts FROM app_orders
                WHERE source = %(source)s AND status = 'confirmado' GROUP BY 1
            ),
            eligible AS (SELECT * FROM firsts WHERE first_ts <= {_AS_OF} - interval '{RETENTION_TO} days'),
            early AS (  -- compras (un carro dividido en dos verticales es una), como en el estado de riesgo
                SELECT e.user_id, count(DISTINCT coalesce(o.cart_id, o.order_id)) AS compras,
                       count(DISTINCT o.vertical) AS verticales
                FROM eligible e
                JOIN app_orders o ON o.user_id = e.user_id AND o.source = %(source)s AND o.status = 'confirmado'
                WHERE o.ts < e.first_ts + interval '{MULTI_VERTICAL_DAYS} days'
                GROUP BY e.user_id
            ),
            retained AS (
                SELECT e.user_id, EXISTS (
                    SELECT 1 FROM app_orders o
                    WHERE o.user_id = e.user_id AND o.source = %(source)s AND o.status = 'confirmado'
                      AND o.ts >= e.first_ts + interval '{RETENTION_FROM} days'
                      AND o.ts < e.first_ts + interval '{RETENTION_TO} days') AS kept
                FROM eligible e
            )
            SELECT CASE WHEN compras <= 2 THEN '1–2 compras' WHEN compras <= 5 THEN '3–5 compras'
                        ELSE '6+ compras' END AS estrato,
                   CASE WHEN verticales >= 2 THEN 'multi-vertical' ELSE 'un vertical' END AS grupo,
                   count(*) AS usuarios, round(100.0 * avg(kept::int), 1) AS retencion_pct
            FROM early JOIN retained USING (user_id)
            GROUP BY 1, 2 HAVING count(*) >= %(min_users)s ORDER BY 1, 2""",
        {"source": source, "min_users": MIN_GROUP_USERS},
    )


def pro_split(conn: Connection, source: str = "synthetic") -> dict:
    """Pro y sin Pro (`app_users.pro`, migración 046), entre las personas de la fuente con algún pedido: cuántas son,
    sus pedidos de los últimos 30 días (y por persona), recompra (% con una segunda compra; una compra es un carro),
    multi-vertical (% con 2+ verticales entre quienes pidieron en los últimos 60 días, como en `kpis`) y retención
    (pedido entre los días 61 y 120 desde el primero, solo de quien tiene esa historia, como en
    `multi_vertical_retention`). Un grupo con menos de MIN_GROUP_USERS personas no sale (privacidad), y su retención
    tampoco con menos elegibles. `sin_dato`: personas con pedidos y sin la marca (las de antes de la 046).

    En los simulados la marca es un SUPUESTO del generador que sigue a cuántas verticales combina cada arquetipo
    (events/synth.py, PRO_SHARE): ahí la diferencia en multi-vertical la puso el generador, no es evidencia."""
    _check(source)
    params = {"source": source, "min_users": MIN_GROUP_USERS}
    people = f"""
        purchases AS (
            SELECT o.user_id, min(o.ts) AS first_ts,
                   count(DISTINCT coalesce(o.cart_id, o.order_id)) AS compras,
                   count(*) FILTER (WHERE o.ts > {_AS_OF} - interval '{ACTIVE_DAYS} days') AS pedidos_30d,
                   count(DISTINCT o.vertical) FILTER (WHERE o.ts > {_AS_OF} - interval '{MULTI_VERTICAL_DAYS} days')
                       AS verticales_60d,
                   bool_or(o.ts > {_AS_OF} - interval '{MULTI_VERTICAL_DAYS} days') AS activa_60d
            FROM app_orders o WHERE o.source = %(source)s AND o.status = 'confirmado' GROUP BY o.user_id
        ),
        people AS (
            SELECT p.*, u.pro FROM purchases p JOIN app_users u ON u.user_id = p.user_id AND u.source = %(source)s
        )"""
    groups = _rows(
        conn,
        f"""WITH {people.strip()},
            retained AS (
                SELECT p.user_id, EXISTS (
                    SELECT 1 FROM app_orders o
                    WHERE o.user_id = p.user_id AND o.source = %(source)s AND o.status = 'confirmado'
                      AND o.ts >= p.first_ts + interval '{RETENTION_FROM} days'
                      AND o.ts < p.first_ts + interval '{RETENTION_TO} days') AS kept
                FROM people p WHERE p.first_ts <= {_AS_OF} - interval '{RETENTION_TO} days'
            )
            SELECT CASE WHEN p.pro THEN 'pro' ELSE 'sin_pro' END AS grupo,
                   count(*) AS personas,
                   sum(p.pedidos_30d)::bigint AS pedidos_30d,
                   round(sum(p.pedidos_30d)::numeric / count(*), 2) AS pedidos_por_persona_30d,
                   round(100.0 * avg((p.compras >= 2)::int), 1) AS recompra_pct,
                   round(100.0 * count(*) FILTER (WHERE p.verticales_60d >= 2)
                         / nullif(count(*) FILTER (WHERE p.activa_60d), 0), 1) AS multi_vertical_pct,
                   count(r.user_id) AS retencion_n,
                   CASE WHEN count(r.user_id) >= %(min_users)s THEN round(100.0 * avg(r.kept::int), 1) END
                       AS retencion_pct
            FROM people p LEFT JOIN retained r USING (user_id)
            WHERE p.pro IS NOT NULL
            GROUP BY 1 HAVING count(*) >= %(min_users)s ORDER BY 1""",
        params,
    )
    [missing] = _rows(conn, f"WITH {people.strip()} SELECT count(*) AS sin_dato FROM people WHERE pro IS NULL", params)
    return {"grupos": groups, "sin_dato": missing["sin_dato"], "minimo_personas": MIN_GROUP_USERS}


def affinity(conn: Connection, source: str = "synthetic", limit: int = 25) -> list[dict]:
    """Afinidad dirigida A → B: P(B | A) entre usuarios que compran A (lift como filtro), sin sensibles.

    No cuenta las líneas que vinieron de una sugerencia del agente (evita que el sistema se retroalimente).
    """
    _check(source)
    return _rows(
        conn,
        _AFFINITY_SQL + " ORDER BY confianza DESC LIMIT %(limit)s",
        {"source": source, "limit": limit, "min_support": MIN_SUPPORT},
    )


_AFFINITY_SQL = """
WITH bought AS (
    SELECT DISTINCT o.user_id, l.concept_id
    FROM app_order_lines l JOIN app_orders o USING (order_id) JOIN concepts c ON c.concept_id = l.concept_id
    WHERE o.source = %(source)s AND o.status = 'confirmado' AND NOT l.from_suggestion AND NOT c.sensitive
),
users AS (SELECT count(DISTINCT user_id)::float AS n FROM bought),
per_concept AS (SELECT concept_id, count(*) AS n FROM bought GROUP BY 1),
pairs AS (
    SELECT a.concept_id AS a, b.concept_id AS b, count(*) AS both_n
    FROM bought a JOIN bought b ON a.user_id = b.user_id AND a.concept_id <> b.concept_id
    GROUP BY 1, 2
)
SELECT p.a AS desde, p.b AS hacia,
       ca.emoji || ' ' || ca.name AS desde_nombre, cb.emoji || ' ' || cb.name AS hacia_nombre,
       p.both_n AS usuarios, round((p.both_n::float / pa.n)::numeric, 3) AS confianza,
       round((p.both_n::float / pa.n / (pb.n / users.n))::numeric, 2) AS lift
FROM pairs p
JOIN per_concept pa ON pa.concept_id = p.a
JOIN per_concept pb ON pb.concept_id = p.b
JOIN concepts ca ON ca.concept_id = p.a
JOIN concepts cb ON cb.concept_id = p.b
CROSS JOIN users
WHERE p.both_n >= %(min_support)s AND p.both_n::float / pa.n / (pb.n / users.n) > 1
"""


def learn_edges(conn: Connection, source: str = "synthetic") -> int:
    """Guarda aristas aprendidas (method 'coocurrencia', data_source = source). El agente ignora las 'synthetic'."""
    _check(source)
    conn.execute("DELETE FROM concept_edges WHERE method = 'coocurrencia' AND data_source = %s", (source,))
    rows = _rows(conn, _AFFINITY_SQL, {"source": source, "min_support": MIN_SUPPORT})
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO concept_edges (from_concept, to_concept, method, weight, support, data_source)
               VALUES (%s, %s, 'coocurrencia', %s, %s, %s)""",
            [(r["desde"], r["hacia"], min(1.0, r["confianza"]), r["usuarios"], source) for r in rows],
        )
    conn.commit()
    return len(rows)


def catalog_health(conn: Connection) -> dict:
    """Muestra pública REAL del catálogo: cobertura, calidad y precios (no depende de datos simulados)."""
    coverage = _rows(
        conn,
        # Declarados y obtenidos en la misma unidad (productos por tienda) y sobre las mismas tiendas.
        """WITH declared AS (
               SELECT sv.vertical, a.store_id, sum(a.product_count_declared) AS declared
               FROM aisles a JOIN store_verticals sv USING (store_id)
               WHERE a.parent_aisle_id IS NULL
               GROUP BY 1, 2
           ),
           obtained AS (SELECT store_id, count(*) AS obtained FROM store_products GROUP BY 1)
           SELECT d.vertical, count(*) AS tiendas, sum(d.declared) AS declarados,
                  coalesce(sum(o.obtained), 0) AS obtenidos
           FROM declared d LEFT JOIN obtained o USING (store_id)
           GROUP BY 1 ORDER BY 3 DESC NULLS LAST""",
        {},
    )
    quality = _rows(
        conn,
        """SELECT iv.vertical, count(DISTINCT ci.master_product_id) AS productos,
                  round(100.0 * count(DISTINCT ci.master_product_id) FILTER (
                      WHERE ci.image_url IS NULL OR ci.image_url ILIKE '%%NO-IMAGE%%')
                      / nullif(count(DISTINCT ci.master_product_id), 0), 1) AS sin_imagen_pct,
                  round(100.0 * count(DISTINCT ci.master_product_id) FILTER (WHERE ci.category_id IS NULL)
                      / nullif(count(DISTINCT ci.master_product_id), 0), 1) AS sin_categoria_pct,
                  round(100.0 * count(DISTINCT ci.master_product_id) FILTER (WHERE ic.entity_id IS NULL)
                      / nullif(count(DISTINCT ci.master_product_id), 0), 1) AS sin_concepto_pct
           FROM v_item_verticals iv
           JOIN catalog_items ci USING (master_product_id)
           LEFT JOIN item_concepts ic ON ic.entity_type = 'catalog_item' AND ic.entity_id = ci.master_product_id::text
           GROUP BY 1 ORDER BY 2 DESC""",
        {},
    )
    cross = _rows(
        conn,
        "SELECT n_verticales, count(*) AS productos FROM v_cross_vertical_items_real GROUP BY 1 ORDER BY 1",
        {},
    )
    return {"cobertura": coverage, "calidad": quality, "cruzados_reales": cross}


def assortment_vs_demand(conn: Connection, source: str = "synthetic", limit: int = 20) -> list[dict]:
    """Surtido real por concepto frente a la demanda (simulada): dónde hay más interés que oferta."""
    _check(source)
    return _rows(
        conn,
        """WITH demand AS (
               SELECT concept_id, vertical, count(DISTINCT user_id) AS usuarios FROM app_events
               WHERE source = %(source)s AND concept_id IS NOT NULL AND type IN ('search', 'chat', 'ask') GROUP BY 1, 2
           )
           SELECT c.emoji || ' ' || c.name AS concepto, d.vertical, d.usuarios AS usuarios_que_buscan,
                  coalesce(a.items, 0) AS items_en_catalogo,
                  round(d.usuarios::numeric / nullif(a.items, 0), 2) AS usuarios_por_item  -- NULL = sin oferta
           FROM demand d JOIN concepts c USING (concept_id)
           LEFT JOIN concept_assortment a ON a.concept_id = d.concept_id AND a.vertical = d.vertical
           WHERE NOT c.sensitive
           ORDER BY usuarios_por_item DESC NULLS FIRST, d.usuarios DESC LIMIT %(limit)s""",
        {"source": source, "limit": limit},
    )
