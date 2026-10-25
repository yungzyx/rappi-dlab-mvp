"""Métricas del panel empresa (definiciones en docs/diseno-ia.md §5). Todas filtran por `source`
('synthetic' o 'prototype'): nunca se mezclan datos simulados con otros.

`as_of` = último evento de esa fuente (los datos simulados terminan en la fecha con que se generaron).
"""

from datetime import UTC

from psycopg import Connection
from psycopg.rows import dict_row

from ..agent.verticals import MIN_ITEMS_ELSEWHERE, SHARES
from ..concepts.taxonomy import load_taxonomy
from ..motor.combos import OWN_SIGNALS_ONLY, expected_fine_retention, load_combos
from ..offers.winback import reach

SOURCES = ("synthetic", "prototype")
ACTIVE_DAYS = 30
MULTI_VERTICAL_DAYS = 60
RETENTION_FROM, RETENTION_TO = 61, 120  # "retención" = pidió entre los días 61 y 120 desde su primer pedido
MIN_SUPPORT = 30  # usuarios mínimos para aprender una arista por co-ocurrencia
MIN_GROUP_USERS = 20  # agregados con menos usuarios no se muestran (privacidad)
# Meses con el siguiente completo que pide la retención de una combinación propia para mostrarse.
MIN_COMBO_RETENTION_N = 30
FINE_COMBO_ROWS = 15  # las combinaciones finas más frecuentes que muestra el panel
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
    LEFT JOIN (SELECT DISTINCT cart_id FROM app_orders WHERE source = %(source)s) o ON o.cart_id = c.cart_id
    WHERE c.units > 0 OR o.cart_id IS NOT NULL
)"""

# Ritmo por usuario: mediana de días entre pedidos (180 días); con 2 pedidos, el único intervalo acotado a [7, 30].
_RHYTHM = f"""
user_orders AS (  -- por día con pedidos: dos pedidos del mismo carro (dos verticales) no son "ritmo 0"
    SELECT user_id, day AS ts, lag(day) OVER (PARTITION BY user_id ORDER BY day) AS prev
    FROM (SELECT DISTINCT user_id, date_trunc('day', ts) AS day FROM app_orders
          WHERE source = %(source)s AND ts > {_AS_OF} - interval '180 days') d
),
rhythm AS (
    SELECT user_id, count(*) + 1 AS orders,
           CASE WHEN count(*) = 1 THEN least(greatest(max(extract(epoch FROM ts - prev) / 86400), 7), 30)
                ELSE percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM ts - prev) / 86400) END AS days
    FROM user_orders WHERE prev IS NOT NULL GROUP BY user_id
),
last_order AS (  -- compras, no pedidos: un carro dividido en dos verticales es una sola compra
    SELECT user_id, count(DISTINCT coalesce(cart_id, order_id)) AS orders, max(ts) AS last_ts
    FROM app_orders WHERE source = %(source)s GROUP BY user_id
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

# Embudo (ver funnel()): una fila por sesión y vertical; la entrada se mira en toda la sesión.
_FUNNEL = """
entry AS (  -- buscó, chateó, navegó, aceptó una sugerencia o agregó desde una lista (el «+» solo manda cart_add),
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
    FROM app_events
    WHERE source = %(source)s AND vertical IS NOT NULL
      AND type NOT IN ('suggestion_shown', 'suggestion_dismissed')
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
                WHERE source = %(source)s AND ts > {_AS_OF} - interval '{ACTIVE_DAYS} days'
            ),
            {_CARTS.strip()},
            abandoned AS (  -- carros con actividad en los últimos 30 días, como los demás indicadores
                SELECT is_abandoned FROM cart_status WHERE last_cart_ts > {_AS_OF} - interval '{ACTIVE_DAYS} days'
            ),
            multi AS (
                SELECT user_id, count(DISTINCT vertical) AS verticals FROM app_orders
                WHERE source = %(source)s AND ts > {_AS_OF} - interval '{MULTI_VERTICAL_DAYS} days' GROUP BY user_id
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
               FROM app_orders WHERE source = %(source)s GROUP BY 1
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
               SELECT user_id, date_trunc('week', min(ts)) AS cohort FROM app_orders WHERE source = %(source)s
               GROUP BY 1
           ),
           sizes AS (SELECT cohort, count(*) AS usuarios FROM firsts GROUP BY 1 HAVING count(*) >= %(min_users)s),
           activity AS (
               SELECT DISTINCT o.user_id, f.cohort,
                      -- en días enteros: el cambio de hora (semana de 6 días y 23 h) no corre las semanas
                      (date_trunc('week', o.ts)::date - f.cohort::date) / 7 AS k
               FROM app_orders o JOIN firsts f USING (user_id) WHERE o.source = %(source)s
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
                WHERE o.source = %(source)s AND NOT c.sensitive
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
    """Rendimiento de las sugerencias cruzadas del agente por concepto sugerido (al preguntarle y en "Para ti").

    Aceptada = el producto sugerido se agregó al carro; convertida = llegó a un pedido. El aviso sobre el carro no
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
                      count(*) FILTER (WHERE type = 'suggestion_dismissed') AS ignoradas
               FROM app_events
               WHERE source = %(source)s AND type LIKE 'suggestion_%%' AND payload ->> 'origen' IS DISTINCT FROM 'aviso'
               GROUP BY 1, 2
           ),
           converted AS (
               SELECT l.concept_id, o.vertical, count(*) AS convertidas
               FROM app_order_lines l JOIN app_orders o USING (order_id)
               WHERE o.source = %(source)s AND l.from_suggestion GROUP BY 1, 2
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
            """SELECT coalesce(payload ->> 'servicio', payload ->> 'origen'),
                      CASE WHEN type = 'service_opened' AND payload ->> 'desde' = 'home'
                           THEN 'service_opened_home' ELSE type END,
                      count(*)
               FROM app_events
               WHERE source = %(source)s AND (type IN ('service_shown', 'service_opened')
                     OR (type IN ('suggestion_shown', 'suggestion_accepted') AND payload ->> 'origen' = ANY(%(ids)s)))
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


# Momentos de las ofertas del agente, en el orden del panel. «pregunta» = lo que sugiere al preguntarle; «para_ti» =
# la sección "Para ti"; «sin_momento» = sin origen o con uno desconocido (las sugerencias cruzadas simuladas no lo
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
    "perfil",
)
OFFER_ORDER = (*OFFER_MOMENTS, "pregunta", "para_ti", "sin_momento")


def offers(conn: Connection, source: str = "synthetic") -> dict:
    """Ofertas del agente mostradas y aceptadas por momento, según `payload.origen` de la sugerencia.

    `agent-<momento>` es el origen actual; `mochi-<momento>` y `chat` son nombres históricos que siguen en la base.
    Los servicios (RappiTravel, RappiFavor) tienen su propia vista y el aviso sobre el carro no es una oferta: no
    entran. El % de aceptación necesita 10 mostradas, como en `suggestions`.
    """
    _check(source)
    params = {
        "source": source,
        "excluded": [*load_taxonomy().services, "aviso"],
        "moments": list(OFFER_MOMENTS),
        "min_rate": MIN_SUGGESTIONS_SHOWN,
    }
    shown = """WITH e AS (
                   SELECT user_id, type,
                          CASE WHEN origen IN ('agent-ask', 'chat') THEN 'pregunta'  -- 'chat': nombre histórico
                               -- 'para-ti-local' y 'vertical-para-ti': nombres históricos de «Para ti»
                               WHEN origen IN ('para-ti', 'para-ti-local', 'vertical-para-ti') THEN 'para_ti'
                               -- 'mochi-<momento>': nombre histórico de 'agent-<momento>'
                               WHEN left(origen, 6) IN ('agent-', 'mochi-') AND substr(origen, 7) = ANY(%(moments)s)
                                    THEN substr(origen, 7)
                               ELSE 'sin_momento' END AS momento
                   FROM (SELECT user_id, type, payload ->> 'origen' AS origen FROM app_events
                         WHERE source = %(source)s AND type IN ('suggestion_shown', 'suggestion_accepted')) o
                   WHERE coalesce(origen, '') <> ALL(%(excluded)s)
               )"""
    [row] = _rows(conn, f"{shown} SELECT count(DISTINCT user_id) AS personas FROM e", params)
    row["momentos"] = _rows(
        conn,
        f"""{shown}
            SELECT momento, mostradas, aceptadas,
                   CASE WHEN mostradas >= %(min_rate)s THEN round(100.0 * aceptadas / mostradas, 1) END
                       AS aceptacion_pct
            FROM (SELECT momento, count(*) FILTER (WHERE type = 'suggestion_shown') AS mostradas,
                         count(*) FILTER (WHERE type = 'suggestion_accepted') AS aceptadas
                  FROM e GROUP BY 1) g""",
        params,
    )
    row["momentos"].sort(key=lambda m: OFFER_ORDER.index(m["momento"]))
    return row


def winback(conn: Connection, source: str = "synthetic") -> dict:
    """«¿Volvemos a…?»: a cuántas personas de la fuente les tocaría, por el tipo de su primera invitación (un concepto
    o una vertical que dejó), y a cuántas la recompra, el día de referencia (`offers.winback.reach`: el último pedido
    simulado, u hoy en el prototipo; `dia` solo en simulados). Es quién califica, no a quién se le mostró; con datos
    simulados no es evidencia."""
    _check(source)
    return reach(conn, source)


MAX_UNMET_ROWS = 20


def unmet(conn: Connection, source: str = "synthetic") -> dict:
    """Búsquedas y preguntas al agente que saben si encontraron algo (`unmet` no nulo) y, de las sin resultado, cuántas
    por vertical y concepto. Nunca el texto buscado (`concepto` es NULL si no se reconoció) ni conceptos sensibles."""
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
    return row


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
    """La tabla de Rappi («verticales usados juntos», `motor/combos.toml`) junto a la misma tabla medida con los datos
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
        "fecha": row["finished_at"].astimezone(UTC).isoformat(),
    }


def home(conn: Connection, source: str = "synthetic") -> dict:
    """Toques de los accesos de la Home (`vertical_open`) por vertical: personas y toques. «Rappi hoy»
    (`payload.mode = 'actual'`) no cuenta, como en todo lo que aprende el motor, ni los servicios sin catálogo."""
    _check(source)
    taps = """FROM app_events
              WHERE source = %(source)s AND type = 'vertical_open' AND vertical IS NOT NULL
                AND NOT payload ? 'servicio' AND payload ->> 'mode' IS DISTINCT FROM 'actual'"""
    rows = _rows(
        conn,
        f"""SELECT vertical, count(DISTINCT user_id) AS personas, count(*) AS toques {taps}
            GROUP BY vertical ORDER BY 3 DESC, vertical COLLATE "C" """,
        {"source": source},
    )
    [totals] = _rows(conn, f"SELECT count(DISTINCT user_id) AS personas, count(*) AS toques {taps}", {"source": source})
    return {**totals, "verticales": rows}


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
                SELECT user_id, min(ts) AS first_ts FROM app_orders WHERE source = %(source)s GROUP BY 1
            ),
            eligible AS (SELECT * FROM firsts WHERE first_ts <= {_AS_OF} - interval '{RETENTION_TO} days'),
            early AS (  -- compras (un carro dividido en dos verticales es una), como en el estado de riesgo
                SELECT e.user_id, count(DISTINCT coalesce(o.cart_id, o.order_id)) AS compras,
                       count(DISTINCT o.vertical) AS verticales
                FROM eligible e JOIN app_orders o ON o.user_id = e.user_id AND o.source = %(source)s
                WHERE o.ts < e.first_ts + interval '{MULTI_VERTICAL_DAYS} days'
                GROUP BY e.user_id
            ),
            retained AS (
                SELECT e.user_id, EXISTS (
                    SELECT 1 FROM app_orders o WHERE o.user_id = e.user_id AND o.source = %(source)s
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
    WHERE o.source = %(source)s AND NOT l.from_suggestion AND NOT c.sensitive
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
