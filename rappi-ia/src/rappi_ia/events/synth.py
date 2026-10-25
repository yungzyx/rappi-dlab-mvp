"""Usuarios y eventos SIMULADOS para construir el panel antes de tener datos reales.

Todo queda con `source = 'synthetic'`. Los productos son reales (del catálogo), la conducta es inventada con
supuestos explícitos. El panel muestra la mecánica, no evidencia: por construcción, estos supuestos se
"confirman" en los gráficos.

SUPUESTOS (editables aquí):
- Cada persona simulada recibe un arquetipo de combinación (ARCHETYPES) que dice en qué grupos (rest, turbo, retail)
  pide. Se sortea con la parte de cada combinación en la tabla de Rappi (motor/combos.toml, sin Favor) por un factor
  de calibración (ARCHETYPE_CALIBRATION, ajustado con scripts/calibrar_simulados.py): la tabla cuenta personas-mes, no
  altas, y quien combina grupos vive más meses, pasa algunos en un solo grupo y las sugerencias aceptadas llevan a
  quien solo pide en Restaurantes a combinar. Por eso hay pocas altas «rest+retail» y «turbo+retail»: esas filas salen
  sobre todo de otros arquetipos. Su perfil (PERSONAS) dice qué conceptos, las horas, el abandono y el atributo que
  prefiere; solo cuentan sus verticales de los grupos del arquetipo. Si a un grupo no le queda ninguno, Turbo copia lo
  del súper y Express de la persona (sin alcohol, bebé, salud ni sensibles) y, si no hay, usa GENERIC_INTERESTS, como
  Restaurantes y Retail; con un catálogo, lo copiado se queda con lo que ese vertical vende. Cada sesión sortea primero
  el grupo, parejo entre los del arquetipo, y después el vertical dentro de él.
- El ritmo sale de los pedidos por persona de su arquetipo. La tabla los cuenta entre quienes pidieron ese mes, así que
  son la media de un Poisson sin el cero: λ / (1 − e^−λ) = pedidos, y se despeja λ (monthly_order_rate). Una sesión
  cada 30 × (parte de sesiones que terminan en pedido) / λ días: la parte depende del abandono de la persona, de
  TRIP y de BROWSE_ONLY (session_order_share). Ya no lo fija el perfil.
- La retención es la M+1 de la tabla de Rappi para la combinación de grupos de sus pedidos de los últimos 30 días (la
  de su arquetipo si no tiene pedidos), con el rendimiento decreciente de la escalera fina (motor/combos.toml,
  `[rendimiento_decreciente]`; supuesto propio, no viene de Rappi): cada vertical extra dentro de un grupo reduce la
  parte que no vuelve (10 %, 5 %, 2,5 %…), así que usar Súper y Express rinde más que solo Súper. Farmacia y Licores
  cuentan como cualquier otra vertical del grupo: son uso propio de la persona (Mochi igual nunca las propone). Los
  servicios (RappiFavor, RappiTravel) no suman: la persona simulada los abre de pasada, no con regularidad.
  La M+1 de Rappi es «pide el mes siguiente», y quien sigue activa puede saltarse un mes: la supervivencia mensual es
  esa retención dividida por la probabilidad de pedir en un mes con el ritmo de su arquetipo, 1 − e^−λ
  (month_order_probability), con tope MAX_SURVIVAL. En cada sesión sigue activa con probabilidad supervivencia^(días
  desde la anterior / 30). Con el tope, a quien pide poco y llegó a una combinación que retiene mucho (de «rest» a
  «rest+retail» por una sugerencia) no le alcanza para mostrar el rendimiento decreciente.
- Calibración, medida como el motor (personas-mes del nivel grueso) con el catálogo real (3.000 personas, semillas 7,
  11, 23, 31 y 47; 17-10-2026 en una copia, rappi_staging): cada combinación queda a menos de 2 puntos de su parte en
  la tabla sin Favor y la retención M+1 de las filas con 100 meses o más, a menos de 0,1 de la de Rappi;
  rest+turbo+retail es la que más retiene y cada combinación de dos o más grupos retiene más que cada una de un solo
  grupo (docs/resultados/simulados-2026-10-17.md). Los pedidos por persona quedan bajo los de la tabla en las
  combinaciones de varios grupos (los meses de alta y de salida son parciales).
- SUPUESTO EXPLÍCITO: la tabla es una correlación (quien pide mucho usa más grupos y además vuelve más), pero aquí se
  trata como efecto. Aceptar una sugerencia que la hace pedir en otro grupo cambia su combinación de verdad, y con ella
  su retención. Por construcción, el panel "confirma" que sumar grupos retiene: no es evidencia.
- El agente simulado respeta las guardias de ofertas del real (offers/guards.py: sin alcohol, bebé, salud, sensibles ni
  Farmacia o Licores, ni productos de tiendas Farmacia, Sex shop o Smoking shop o que dicen bebé) y muestra un
  complemento en una parte de los carros (SUGGESTION_SHOWN), en el primer vertical del orden del agente o, en la mitad
  de los casos (TURBO_SUGGESTION), en Turbo si Turbo lo vende. SUPUESTO PROPIO: el real sigue su orden; sin esto, lo
  aceptado llevaba a casi todos de «rest» a «rest+retail» (11,3 % de los meses-persona contra 5,4 % en Rappi) y dejaba
  corto «rest+turbo» (4,2 % contra 6,6 %). Con el catálogo real (3.000 personas, semilla 7; medido el 16-10-2026 en una
  copia, rappi_staging) quedan en 7,2 % y 8,0 %; la tabla reproducida está más cerca de la de Rappi en las semillas 7,
  11 y 23 (docs/resultados/motor-2026-10-16.md, «Mejora continua»; antes de la calibración de las altas).
- Personas pequeñas que ejercitan los segmentos de la capa de perfiles (sin gluten, vegana, mamá con bebé, perro, gato,
  fitness, nocturno, cazaofertas, gamer, cafetera, chocolatera, parrillera); algunas prefieren ítems con un atributo.
  La oficinista ya existe como «oficina». Los pesos (`share`) se normalizan al sortear: no hace falta que sumen 1.
- Una persona asiática (sushi, comida asiática y su despensa, snacks y bebidas en Restaurantes, Súper, Turbo y Express)
  alimenta el perfil de gusto principal; su peso sale del de la persona de carrete.
- 26 semanas: la retención (días 61 a 120) necesita usuarios con 120 días de historia. Las altas llegan parejas en todo
  el período, como cohortes mensuales (la tabla de Rappi junta cohortes con gente nueva cada mes): así la población
  activa no se vacía al final y la ventana de prueba del motor (28 días) tiene gente. Las métricas de retención
  (días 61 a 120) solo cuentan a quien tiene esa historia.
- Quien no encuentra lo que busca (demanda no satisfecha) o abandona carros, se va antes (CHURN_*): cada búsqueda sin
  resultado o carro abandonado de las últimas 4 semanas acelera la pérdida.
- Parte de quienes encuentran productos se va sin agregar nada al carro (BROWSE_ONLY).
- Algunas sesiones hablan de un viaje (TRIP: RappiTravel, sin su gancho de Farmacia) y a quien no encuentra lo que
  busca se le ofrece RappiFavor (FAVOR_OFFER).
- Parte de los carros abandonados alcanza a iniciar el pago (CHECKOUT_ABANDON_SHARE); el resto se va antes.
- Aceptar una sugerencia cruzada acorta un poco el ritmo de compra (SUGGESTION_CADENCE_BOOST).
- Algunos antojos no existen en el catálogo y crecen con el tiempo (WISHES): alimentan "oportunidades".
"""

import io
import json
import logging
import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import cache

from psycopg import Connection

from ..agent.verticals import ranked_verticals
from ..concepts.taxonomy import load_taxonomy
from ..motor.combos import (
    GROUP_ORDER,
    NONE_COMBO,
    SERVICE_COMBO,
    expected_fine_retention,
    expected_retention,
    fine_of,
    load_combos,
)
from ..offers.guards import baby_in_name, is_offerable, offerable_vertical, unofferable_subverticals

log = logging.getLogger(__name__)
CHILE = timezone(timedelta(hours=-3))


@dataclass(frozen=True)
class Persona:
    id: str
    share: float  # fracción de usuarios
    hours: tuple[int, ...]  # horas típicas de uso
    interests: dict[str, dict[str, float]]  # vertical → concepto → peso
    abandon: float  # probabilidad de abandonar un carro
    prefer: str | None = None  # atributo que prefiere al elegir ítem (`sin-gluten`, `vegano`…) si el concepto lo tiene


PERSONAS = [
    Persona(
        "carrete",
        0.14,  # eran 0,22: 0,08 pasó al asiático (el carrete es el perfil secundario; el principal es el sushi)
        (19, 20, 21, 22, 23),
        {
            "licores": {"cerveza": 5, "pisco": 3, "ron": 1.5, "vodka": 1, "snacks-salados": 2, "hielo": 0.5},
            "conveniencia": {"cerveza": 2, "snacks-salados": 2, "gaseosas": 1.5, "energizantes": 1},
            "restaurantes": {"pizza": 3, "hamburguesa": 2, "sushi": 1},
        },
        0.35,
    ),
    # El perfil principal de la demo (offers/perfiles.toml): sushi y comida asiática hecha, y lo que se lleva a casa
    # para prepararla (despensa, snacks y bebidas asiáticas) en Súper, Turbo y Express.
    Persona(
        "asiatico",
        0.08,
        (12, 13, 19, 20, 21),
        {
            "restaurantes": {"sushi": 4, "asiatica": 3},
            "supermercado": {"despensa-asiatica": 2.5, "bebidas-asiaticas": 1},
            "turbo": {"despensa-asiatica": 1.5, "snacks-asiaticos": 2},
            "conveniencia": {"snacks-asiaticos": 1.5, "bebidas-asiaticas": 1},
        },
        0.28,
    ),
    Persona(
        "familia",
        0.26,
        (10, 11, 17, 18, 19),
        {
            "supermercado": {
                "lacteos": 4,
                "panales": 3,
                "frutas": 3,
                "carnes": 2.5,
                "limpieza": 2,
                "panaderia": 2,
                "cereales": 1.5,
                "alimentacion-bebe": 1.5,
            },
            "restaurantes": {"pizza": 2, "pollo-preparado": 1.5},
            "chocolateria": {"pasteleria": 0.5},
        },
        0.25,
    ),
    Persona(
        "oficina",
        0.2,
        (12, 13, 14),
        {
            "restaurantes": {"ensaladas-bowls": 3, "sandwiches": 2.5, "sushi": 2, "pastas": 1.5, "asiatica": 1.5},
            "conveniencia": {"cafe": 2, "energizantes": 1, "galletas": 1},
        },
        0.3,
    ),
    Persona(
        "foodie",
        0.14,
        (20, 21, 22),
        {
            "restaurantes": {"sushi": 3, "pastas": 2.5, "postres": 2, "helados": 1.5, "carnes": 1.5},
            "chocolateria": {"chocolates": 2, "pasteleria": 1.5},
            "licores": {"vino": 2, "espumante": 1},
        },
        0.28,
    ),
    Persona(
        "mascotero",
        0.1,
        (9, 10, 18, 19),
        {
            "supermercado": {"alimento-perro": 4, "alimento-gato": 3, "accesorios-mascota": 1.5, "limpieza": 1},
            "conveniencia": {"alimento-perro": 1},
        },
        0.2,
    ),
    Persona(
        "hogar",
        0.08,
        (11, 16, 21),
        {
            "mall": {"cocina-menaje": 3, "decoracion": 2.5, "juguetes-infantiles": 2, "textil-hogar": 1.5, "audio": 1},
            "supermercado": {"limpieza": 1.5},
        },
        0.4,
    ),
    # Compran en una sola vertical: sin ellas, «¿retiene más quien usa dos verticales?» no tenía contra qué comparar.
    # El agente igual puede llevarlas a otra con una sugerencia aceptada.
    Persona(
        "rutina",
        0.14,
        (9, 10, 19, 20),
        {"supermercado": {"lacteos": 4, "frutas": 3, "panaderia": 2.5, "limpieza": 2, "snacks-salados": 1.5}},
        0.25,
    ),
    Persona(
        "delivery",
        0.12,
        (13, 20, 21),
        {"restaurantes": {"pizza": 3, "hamburguesa": 3, "sushi": 2, "pollo-preparado": 2}},
        0.3,
    ),
    Persona(
        "sin-gluten",
        0.02,
        (10, 11, 18, 19),
        {
            "supermercado": {
                "galletas": 3,
                "panaderia": 3,
                "pastas": 2,
                "cereales": 2,
                "snacks-salados": 1.5,
                "chocolates": 1,
                "lacteos": 1.5,
                "frutas": 1,
            }
        },
        0.25,
        "sin-gluten",
    ),
    Persona(
        "vegana",
        0.02,
        (11, 12, 19, 20),
        {
            "supermercado": {
                "vegano": 4,
                "verduras": 3,
                "frutas": 3,
                "arroz-legumbres": 2,
                "frutos-secos": 1.5,
                "cereales": 1.5,
            },
            "restaurantes": {"ensaladas-bowls": 2, "asiatica": 1.5},
        },
        0.25,
        "vegano",
    ),
    Persona(
        "mama-bebe",
        0.03,
        (9, 10, 16, 17),
        {
            "supermercado": {"panales": 5, "alimentacion-bebe": 4, "articulos-bebe": 2, "lacteos": 2},
            "farmacia": {"panales": 1.5, "articulos-bebe": 1},
        },
        0.2,
    ),
    Persona(
        "perro",
        0.03,
        (8, 9, 18, 19),
        {"supermercado": {"alimento-perro": 5, "accesorios-mascota": 2}, "conveniencia": {"alimento-perro": 1}},
        0.2,
    ),
    Persona(
        "gato",
        0.025,
        (9, 10, 19, 20),
        {"supermercado": {"alimento-gato": 5, "accesorios-mascota": 2}, "conveniencia": {"alimento-gato": 1}},
        0.2,
    ),
    Persona(
        "fitness",
        0.025,
        (7, 8, 18, 19),
        {
            "supermercado": {"frutas": 3, "lacteos": 2, "carnes": 2, "cereales": 1.5, "barras-cereal": 2},
            "farmacia": {"vitaminas": 3},
            "mall": {"articulos-deportivos": 2},
        },
        0.25,
        "alto-proteina",
    ),
    Persona(
        "nocturno",
        0.025,
        (22, 23, 0, 1, 2),
        {
            "licores": {"cerveza": 3, "pisco": 1, "snacks-salados": 1.5},
            "restaurantes": {"pizza": 3, "hamburguesa": 3, "sushi": 1.5},
            "conveniencia": {"gaseosas": 2, "snacks-salados": 2},
        },
        0.3,
    ),
    Persona(
        "cazaofertas",
        0.025,
        (10, 11, 17, 18),
        {
            "supermercado": {"lacteos": 2, "limpieza": 2, "carnes": 2, "frutas": 1.5, "snacks-salados": 1.5},
            "mall": {"electrohogar": 1},
        },
        0.35,
        "con-descuento",
    ),
    Persona(
        "gamer",
        0.02,
        (21, 22, 23),
        {
            "mall": {"videojuegos": 4, "audio": 2, "computacion": 2, "celulares": 1},
            "restaurantes": {"pizza": 2, "hamburguesa": 2},
            "conveniencia": {"energizantes": 3, "snacks-salados": 2},
        },
        0.3,
    ),
    Persona(
        "cafetera",
        0.025,
        (8, 9, 16, 17),
        {
            "conveniencia": {"cafe": 4, "galletas": 1.5, "snacks-salados": 1},
            "supermercado": {"cafe": 3, "te": 1.5, "cereales": 1},
            "restaurantes": {"desayuno": 1.5},
        },
        0.25,
    ),
    Persona(
        "chocolatera",
        0.025,
        (15, 16, 20, 21),
        {
            "chocolateria": {"chocolates": 4, "pasteleria": 2},
            "supermercado": {"chocolates": 3, "helados": 1.5, "postres": 1.5, "golosinas": 1.5},
        },
        0.25,
    ),
    Persona(
        "parrillero",
        0.03,
        (11, 12, 17, 18),
        {
            "supermercado": {"carnes": 4, "carbon": 2.5, "aceites-condimentos": 1},
            "licores": {"cerveza": 3, "vino": 2.5, "pisco": 1},
            "conveniencia": {"carbon": 1.5, "hielo": 1},
        },
        0.3,
    ),
]

# Antojos que el catálogo no tiene (o casi): (vertical, texto, concepto, peso inicial, crecimiento semanal)
WISHES = [
    ("restaurantes", "comida peruana, un lomo saltado", "peruana", 0.4, 0.12),
    ("restaurantes", "tacos mexicanos", "mexicana", 0.5, 0.04),
    ("restaurantes", "shawarma de pollo", "arabe", 0.25, 0.06),
    ("restaurantes", "desayuno a domicilio", "desayuno", 0.3, 0.1),
    ("supermercado", "kombucha", None, 0.2, 0.08),
    ("mall", "neumáticos para el auto", "automotriz", 0.1, 0.0),
]

CHURN_UNMET = 0.35  # +35% de riesgo por cada búsqueda sin resultado en las últimas 4 semanas
CHURN_ABANDON = 0.2  # +20% por cada carro abandonado en las últimas 4 semanas
CHECKOUT_ABANDON_SHARE = 0.4  # de los carros abandonados, la parte que alcanza a iniciar el pago
MAX_SURVIVAL = 0.99  # la supervivencia mensual nunca llega a 1
COMBO_WINDOW_DAYS = 30  # la combinación de una persona: los grupos de sus pedidos de los últimos 30 días
_COMBOS = load_combos()
# Las 7 combinaciones de la tabla de Rappi (sin Favor, que no tiene catálogo) con su parte de usuarios.
_SHARES = {combo: row.pct_users for combo, row in _COMBOS.rappi.items() if combo != SERVICE_COMBO}
# Cuánto se corrige el sorteo de cada arquetipo al darse de alta para que la mezcla de personas-mes (la que mide el
# motor) se parezca a la de la tabla: quien combina grupos vive más meses, pasa meses en un solo grupo y las sugerencias
# aceptadas llevan a quien solo pide en Restaurantes a combinar. Ajustado el 17-10-2026 con
# `scripts/calibrar_simulados.py --base rappi_staging --ajustar --altas 12000 --hasta 2026-10-17` (semilla FIT_SEED =
# 101) sobre el catálogo de rappi_staging de esa noche, mientras se reetiquetaban sus conceptos: la misma orden, más
# tarde, dio factores algo distintos (rest+retail 0,15, turbo+retail 0,13), y con estos cada fila siguió a menos de
# 1,2 puntos de la tabla (docs/resultados/simulados-2026-10-17.md).
ARCHETYPE_CALIBRATION: dict[str, float] = {
    "rest": 1.15,
    "turbo": 0.87,
    "rest+turbo": 0.67,
    "retail": 1.14,
    "rest+retail": 0.20,
    "rest+turbo+retail": 0.68,
    "turbo+retail": 0.19,
}
_DRAW = {combo: share * ARCHETYPE_CALIBRATION[combo] for combo, share in _SHARES.items()}
ARCHETYPES: dict[str, float] = {combo: weight / sum(_DRAW.values()) for combo, weight in _DRAW.items()}
# Lo que pide quien cae en un grupo sin verticales en su perfil (sin alcohol, bebé ni salud).
GENERIC_INTERESTS: dict[str, dict[str, float]] = {
    "turbo": {"snacks-salados": 2, "gaseosas": 2, "lacteos": 1.5, "frutas": 1},
    "restaurantes": {"pizza": 3, "hamburguesa": 2.5, "sushi": 2, "pollo-preparado": 1.5},
    "supermercado": {"lacteos": 3, "frutas": 2, "limpieza": 2, "panaderia": 1.5},
}
_GROUP_FALLBACK = {"rest": "restaurantes", "turbo": "turbo", "retail": "supermercado"}  # vertical del grupo vacío
_TURBO_SOURCES = ("supermercado", "conveniencia")  # de dónde copia Turbo cuando el perfil no lo tiene
# Personas por defecto (también en el CLI): con el catálogo real, el último mes completo queda con ~400 o más activas.
DEFAULT_USERS = 3000
TRIP = 0.03  # sesiones que hablan de un viaje (RappiTravel)
TRAVEL_OPEN = 0.35  # de ellas, las que abren RappiTravel
FAVOR_OFFER = 0.6  # búsquedas sin resultado donde el agente ofrece RappiFavor (en «Propuesta»)
FAVOR_OPEN = 0.2
BROWSE_ONLY = 0.12  # encuentra productos y se va sin agregar nada al carro
SUGGESTION_SHOWN = 0.3  # carros donde el agente muestra un complemento de otro vertical (no en todos)
SUGGESTION_ACCEPT = 0.22  # probabilidad base de aceptar una sugerencia cruzada (× peso de la arista)
# Sugerencias que van a Turbo cuando Turbo vende el concepto (el resto sigue el orden del agente).
TURBO_SUGGESTION = 0.5
SUGGESTION_CADENCE_BOOST = 0.93  # aceptar una sugerencia acorta el ritmo 7%
MODALITIES = (("texto", 1.0),)  # solo texto; se sigue sorteando para conservar la misma secuencia aleatoria
PREFERRED_ATTRIBUTES = ("sin-gluten", "vegano", "alto-proteina", "con-descuento")
PREFER_SHARE = 0.85  # con qué frecuencia elige un ítem con su atributo cuando el concepto tiene alguno


@dataclass
class Catalog:
    """Ítems reales por (vertical, concepto): (entity_type, entity_id, precio)."""

    items: dict[tuple[str, str], list[tuple[str, str, float]]]
    edges: dict[str, list[tuple[str, float]]]
    names: dict[str, str]
    ranked: dict[str, list[str]]  # concepto sugerible → verticales en el orden del agente (`ranked_verticals`)
    # (vertical, concepto, atributo) → ítems con ese atributo: solo los usa quien lo prefiere. Aparte de `items` para no
    # inflar el surtido de las demás personas (una muestra al azar casi no trae ítems sin gluten o veganos).
    preferred: dict[tuple[str, str, str], list[tuple[str, str, float]]] = field(default_factory=dict)
    # (vertical, entity_type, entity_id) que el agente real no ofrece por su cuenta (`_unofferable`): se pueden pedir,
    # no sugerir.
    unofferable: set[tuple[str, str, str]] = field(default_factory=set)

    def offer_options(self, vertical: str, concept: str) -> list[tuple[str, str, float]]:
        """Los ítems del concepto en la vertical que el agente podría sugerir, en el mismo orden."""
        return [i for i in self.items.get((vertical, concept), []) if (vertical, i[0], i[1]) not in self.unofferable]

    def pick(self, rng: random.Random, vertical: str, concept: str, prefer: str | None = None, offer: bool = False):
        """Un ítem del concepto en la vertical (con `prefer`, casi siempre uno con ese atributo si hay). Con `offer`,
        solo lo que el agente sugeriría, también entre los preferidos."""
        options = self.offer_options(vertical, concept) if offer else self.items.get((vertical, concept))
        if not options:
            return None
        if prefer and rng.random() < PREFER_SHARE:
            liked = self.preferred.get((vertical, concept, prefer), [])
            if offer:
                liked = [i for i in liked if (vertical, i[0], i[1]) not in self.unofferable]
            if liked:
                return rng.choice(liked)
        return rng.choice(options)


@dataclass
class UserState:
    user_id: str
    persona: Persona
    city: str
    cadence: float
    archetype: str  # combinación de Rappi sorteada (ARCHETYPES)
    interests: dict[str, dict[str, float]]  # los de la persona en los grupos del arquetipo (`effective_interests`)
    active: bool = True
    orders_by_vertical: dict[str, list[datetime]] = field(default_factory=dict)
    recent_unmet: list[datetime] = field(default_factory=list)
    recent_abandon: list[datetime] = field(default_factory=list)


def load_catalog(conn: Connection, per_concept: int = 40) -> Catalog:
    rows = conn.execute(
        """SELECT vertical, concept_id, entity_type, entity_id, price FROM (
               SELECT d.vertical, ic.concept_id, d.entity_type, d.entity_id,
                      coalesce((d.metadata->>'precio_min')::numeric, (d.metadata->>'precio')::numeric) AS price,
                      row_number() OVER (PARTITION BY d.vertical, ic.concept_id ORDER BY md5(d.entity_id)) AS rn
               FROM search_documents d
               JOIN item_concepts ic USING (entity_type, entity_id)
               WHERE d.entity_type IN ('catalog_item', 'menu_item')
           ) s
           WHERE rn <= %s AND price IS NOT NULL""",
        (per_concept,),
    ).fetchall()
    items: dict[tuple[str, str], list] = {}
    for vertical, concept, etype, eid, price in rows:
        items.setdefault((vertical, concept), []).append((etype, eid, float(price)))
    preferred: dict[tuple[str, str, str], list] = {}
    for vertical, concept, etype, eid, price, attribute in conn.execute(
        """SELECT vertical, concept_id, entity_type, entity_id, price, attribute_id FROM (
               SELECT d.vertical, ic.concept_id, d.entity_type, d.entity_id, ia.attribute_id,
                      coalesce((d.metadata->>'precio_min')::numeric, (d.metadata->>'precio')::numeric) AS price,
                      row_number() OVER (PARTITION BY d.vertical, ic.concept_id, ia.attribute_id
                                         ORDER BY md5(d.entity_id)) AS rn
               FROM search_documents d
               JOIN item_concepts ic USING (entity_type, entity_id)
               JOIN item_attributes ia ON ia.entity_type = d.entity_type AND ia.entity_id = d.entity_id
               WHERE d.entity_type IN ('catalog_item', 'menu_item') AND ia.attribute_id = ANY(%s)
           ) s
           WHERE rn <= 15 AND price IS NOT NULL""",
        (list(PREFERRED_ATTRIBUTES),),
    ):
        preferred.setdefault((vertical, concept, attribute), []).append((etype, eid, float(price)))
    edges: dict[str, list] = {}
    for source, target, weight in conn.execute(
        "SELECT from_concept, to_concept, weight FROM concept_edges WHERE method = 'curado'"
    ):
        edges.setdefault(source, []).append((target, float(weight)))
    names = dict(conn.execute("SELECT concept_id, name FROM concepts").fetchall())
    targets = {target for options in edges.values() for target, _ in options}
    ranked = {target: ranked_verticals(conn, [target]) for target in targets}
    return Catalog(items, edges, names, ranked, preferred, _unofferable(conn, items))


def _unofferable(conn: Connection, items: dict[tuple[str, str], list]) -> set[tuple[str, str, str]]:
    """Los productos de `items` que el agente real no ofrece (offers/guards.py), por vertical: el que dice bebé en su
    nombre y el que en esa vertical solo venden tiendas Farmacia, Sex shop o Smoking shop. Los platos no."""
    ids = sorted({eid for options in items.values() for etype, eid, _ in options if etype == "catalog_item"})
    names = dict(
        conn.execute(
            "SELECT master_product_id::text, name FROM catalog_items WHERE master_product_id = ANY(%s::bigint[])",
            (ids,),
        ).fetchall()
    )
    sold = set(
        conn.execute(
            """SELECT DISTINCT v.vertical, sp.master_product_id::text
               FROM store_products sp JOIN v_store_verticals v USING (store_id)
               WHERE sp.master_product_id = ANY(%s::bigint[])
                 AND NOT EXISTS (SELECT 1 FROM store_verticals own
                                 WHERE own.store_id = sp.store_id AND own.subvertical = ANY(%s))""",
            (ids, unofferable_subverticals()),
        ).fetchall()
    )
    return {
        (vertical, etype, eid)
        for (vertical, _concept), options in items.items()
        for etype, eid, _price in options
        if etype == "catalog_item" and ((vertical, eid) not in sold or baby_in_name(etype, names.get(eid, "")))
    }


def draw_archetype(rng: random.Random) -> str:
    """Una combinación de grupos sorteada con la mezcla calibrada (ARCHETYPES): la de la tabla de Rappi por
    ARCHETYPE_CALIBRATION."""
    return rng.choices(list(ARCHETYPES), weights=list(ARCHETYPES.values()))[0]


@cache
def monthly_order_rate(archetype: str) -> float:
    """Pedidos al mes de una persona activa del arquetipo (λ de un Poisson). La tabla de Rappi da los pedidos por
    persona entre quienes pidieron ese mes, que es la media de un Poisson sin el cero: λ / (1 − e^−λ). Se despeja λ."""
    target = _COMBOS.rappi[archetype].orders_per_user
    low, high = 1e-9, target
    for _ in range(60):
        mid = (low + high) / 2
        low, high = (mid, high) if mid / -math.expm1(-mid) < target else (low, mid)
    return (low + high) / 2


def month_order_probability(archetype: str) -> float:
    """La probabilidad de que una persona activa del arquetipo pida algo en un mes: 1 − e^−λ."""
    return -math.expm1(-monthly_order_rate(archetype))


def session_order_share(persona: Persona) -> float:
    """La parte de las sesiones que termina en pedido, sin contar búsquedas sin resultado: no habla de un viaje, no se
    va solo mirando y no abandona el carro."""
    return (1 - TRIP) * (1 - BROWSE_ONLY) * (1 - persona.abandon)


def archetype_cadence(archetype: str, persona: Persona) -> float:
    """Días entre sesiones: las que hacen falta para los pedidos al mes del arquetipo, dado que no toda sesión termina
    en pedido."""
    return 30 * session_order_share(persona) / monthly_order_rate(archetype)


def effective_interests(
    persona: Persona, archetype: str, catalog: Catalog | None = None
) -> dict[str, dict[str, float]]:
    """Los intereses de la persona solo en los verticales de los grupos del arquetipo. Un grupo sin verticales en el
    perfil toma otros: Turbo, lo ofrecible del súper y Express de la persona (o GENERIC_INTERESTS); Restaurantes y
    Retail, GENERIC_INTERESTS. Con `catalog`, lo tomado se queda con lo que ese vertical vende, si algo vende."""
    groups = set(archetype.split("+"))
    group_of = _COMBOS.group_of
    interests = {v: dict(c) for v, c in persona.interests.items() if group_of[v] in groups}
    have = {group_of[v] for v in interests}
    for group in (g for g in GROUP_ORDER if g in groups - have):
        vertical = _GROUP_FALLBACK[group]
        options = [GENERIC_INTERESTS[vertical]]
        if group == "turbo":
            options.insert(0, _offerable_copy(persona, _TURBO_SOURCES))
        options = [o for o in options if o]
        sold = [{c: w for c, w in o.items() if (vertical, c) in catalog.items} for o in options] if catalog else options
        interests[vertical] = next((o for o in sold if o), options[-1])
    return interests


def _offerable_copy(persona: Persona, verticals: tuple[str, ...]) -> dict[str, float]:
    """Los conceptos de esos verticales de la persona que se pueden llevar a otro: sin alcohol, bebé, salud ni
    sensibles (`is_offerable`). Un concepto en dos verticales suma sus pesos."""
    concepts = load_taxonomy().concepts
    copied: dict[str, float] = {}
    for vertical in verticals:
        for concept, weight in persona.interests.get(vertical, {}).items():
            if concept in concepts and is_offerable(concepts[concept]):
                copied[concept] = copied.get(concept, 0) + weight
    return copied


def draw_signup(rng: random.Random, start: datetime, weeks: int) -> datetime:
    """Fecha de alta: pareja en todo el período (cohortes mensuales), no solo en su primera parte."""
    return start + timedelta(days=rng.uniform(0, weeks * 7))


def generate(
    conn: Connection, users: int = DEFAULT_USERS, weeks: int = 26, seed: int = 7, until: date | None = None
) -> dict:
    """Borra los datos simulados anteriores y genera nuevos (reproducible con la misma semilla y fecha)."""
    rng = random.Random(seed)
    catalog = load_catalog(conn)
    end = datetime.combine(until or date.today(), datetime.min.time(), CHILE)
    start = end - timedelta(weeks=weeks)
    conn.execute("DELETE FROM app_users WHERE source = 'synthetic'")

    buffers = {"users": io.StringIO(), "events": io.StringIO(), "orders": io.StringIO(), "lines": io.StringIO()}
    counts = {"usuarios": 0, "eventos": 0, "pedidos": 0}
    for n in range(users):
        persona = rng.choices(PERSONAS, weights=[p.share for p in PERSONAS])[0]
        archetype = draw_archetype(rng)
        state = UserState(
            user_id=f"syn-{seed}-{n:05d}",
            persona=persona,
            city=rng.choices(["Santiago", "Valparaíso", "Concepción", "Antofagasta"], [0.7, 0.12, 0.1, 0.08])[0],
            cadence=archetype_cadence(archetype, persona) * math.exp(rng.gauss(0, 0.35)),
            archetype=archetype,
            interests=effective_interests(persona, archetype, catalog),
        )
        signup = draw_signup(rng, start, weeks)
        _write(buffers["users"], state.user_id, "synthetic", persona.id, state.city, rng.random() < 0.4, _iso(signup))
        counts["usuarios"] += 1
        _simulate_user(rng, catalog, state, signup, end, start, buffers, counts)

    _copy(conn, "app_users (user_id, source, segment, city, consent_notifications, created_at)", buffers["users"])
    _copy(conn, "app_orders (order_id, user_id, session_id, cart_id, ts, vertical, total, source)", buffers["orders"])
    _copy(
        conn,
        "app_order_lines (order_id, line_no, entity_type, entity_id, concept_id, qty, unit_price, from_suggestion)",
        buffers["lines"],
    )
    _copy(
        conn,
        "app_events (user_id, session_id, ts, type, vertical, concept_id, entity_type, entity_id, cart_id, query,"
        " modality, results, unmet, value, payload, source)",
        buffers["events"],
    )
    conn.commit()
    log.info("Simulados: %s", counts)
    return counts


def _simulate_user(
    rng, catalog: Catalog, s: UserState, signup: datetime, end: datetime, start: datetime, buffers, counts
):
    day = signup
    while day < end and s.active:
        gap = max(1.0, rng.expovariate(1 / s.cadence))
        day = day + timedelta(days=gap)
        if day >= end:
            break
        ts = day.replace(hour=rng.choice(s.persona.hours), minute=rng.randrange(60))
        _session(rng, catalog, s, ts, start, buffers, counts)
        s.active = rng.random() < _stay_probability(s, ts, gap)


def _session(rng, catalog: Catalog, s: UserState, ts: datetime, start: datetime, buffers, counts) -> None:
    session_id = uuid.UUID(int=rng.getrandbits(128)).hex[:16]
    events = buffers["events"]

    def emit(kind, when, **kw):
        _write(
            events,
            s.user_id,
            session_id,
            _iso(when),
            kind,
            kw.get("vertical"),
            kw.get("concept"),
            kw.get("etype"),
            kw.get("eid"),
            kw.get("cart"),
            kw.get("query"),
            kw.get("modality"),
            kw.get("results"),
            _bool(kw.get("unmet")),
            kw.get("value"),
            json.dumps(kw.get("payload", {})),
            "synthetic",
        )
        counts["eventos"] += 1

    emit("app_open", ts)
    clock = ts + timedelta(seconds=rng.randint(5, 40))
    week = (ts - start).days / 7

    wish = _maybe_wish(rng, week)
    if wish:  # un antojo que el catálogo no tiene: búsqueda sin resultado, se va sin comprar
        vertical, text, concept, _, _ = wish
        emit(
            "search",
            clock,
            vertical=vertical,
            concept=concept,
            query=text,
            modality=_modality(rng),
            results=0,
            unmet=True,
        )
        s.recent_unmet.append(ts)
        if rng.random() < FAVOR_OFFER:  # el agente ofrece pedirlo con RappiFavor
            favor = {"servicio": "rappifavor"}
            emit("service_shown", clock + timedelta(seconds=2), payload=favor)
            if rng.random() < FAVOR_OPEN:
                emit("service_opened", clock + timedelta(seconds=9), payload=favor)
        return

    if rng.random() < TRIP:  # habla de un viaje: RappiTravel (su gancho es de Farmacia y el agente no lo ofrece)
        travel = {"servicio": "rappitravel"}
        emit("ask", clock, query="me voy de vacaciones", modality=_modality(rng), results=0)
        emit("service_shown", clock + timedelta(seconds=2), payload=travel)
        if rng.random() < TRAVEL_OPEN:
            emit("service_opened", clock + timedelta(seconds=12), payload=travel)
        return

    vertical = _pick_vertical(rng, s.interests)
    concept = _weighted(rng, s.interests[vertical])
    prefer = s.persona.prefer
    item = catalog.pick(rng, vertical, concept, prefer)
    kind = "ask" if rng.random() < 0.3 else "search"
    emit(
        kind,
        clock,
        vertical=vertical,
        concept=concept,
        query=catalog.names.get(concept, concept).lower(),
        modality=_modality(rng),
        results=0 if item is None else rng.randint(4, 20),
        unmet=item is None,
    )
    if item is None:
        s.recent_unmet.append(ts)
        return
    if rng.random() < BROWSE_ONLY:
        return
    cart_id = uuid.UUID(int=rng.getrandbits(128)).hex[:12]
    lines = []
    for _ in range(1 + int(rng.random() < 0.5) + int(rng.random() < 0.2)):
        item = catalog.pick(rng, vertical, concept, prefer) or item
        clock += timedelta(seconds=rng.randint(10, 90))
        emit("view_item", clock, vertical=vertical, concept=concept, etype=item[0], eid=item[1], value=item[2])
        emit(
            "cart_add",
            clock + timedelta(seconds=5),
            vertical=vertical,
            concept=concept,
            etype=item[0],
            eid=item[1],
            cart=cart_id,
            value=item[2],
        )
        lines.append((item, concept, False))

    suggestion = _suggestion(catalog, concept, vertical, rng) if rng.random() < SUGGESTION_SHOWN else None
    if suggestion:
        target, sug_vertical, weight = suggestion
        clock += timedelta(seconds=rng.randint(5, 30))
        emit("suggestion_shown", clock, vertical=sug_vertical, concept=target)
        if rng.random() < SUGGESTION_ACCEPT * (0.5 + weight):
            sug_item = catalog.pick(rng, sug_vertical, target, offer=True)
            emit("suggestion_accepted", clock + timedelta(seconds=4), vertical=sug_vertical, concept=target)
            if sug_item:
                emit(
                    "cart_add",
                    clock + timedelta(seconds=8),
                    vertical=sug_vertical,
                    concept=target,
                    etype=sug_item[0],
                    eid=sug_item[1],
                    cart=cart_id,
                    value=sug_item[2],
                )
                lines.append((sug_item, target, True))
                s.cadence *= SUGGESTION_CADENCE_BOOST
        else:
            emit("suggestion_dismissed", clock + timedelta(seconds=3), vertical=sug_vertical, concept=target)

    clock += timedelta(seconds=rng.randint(20, 120))
    abandon = rng.random() < s.persona.abandon
    if abandon and rng.random() >= CHECKOUT_ABANDON_SHARE:  # se va antes de ir a pagar
        s.recent_abandon.append(ts)
        return
    by_vertical: dict[str, list] = {}
    for line in lines:
        line_vertical = vertical if not line[2] else suggestion[1]
        by_vertical.setdefault(line_vertical, []).append(line)
    for order_vertical in by_vertical:  # un pago por tienda/vertical, antes de saber si termina en pedido
        emit("checkout_start", clock, vertical=order_vertical, cart=cart_id)
    if abandon:  # inició el pago y no lo terminó
        s.recent_abandon.append(ts)
        return
    for order_vertical, order_lines in by_vertical.items():  # un pedido por tienda/vertical
        order_id = f"ord-syn-{uuid.UUID(int=rng.getrandbits(128)).hex[:12]}"
        total = 0.0
        for i, ((etype, eid, price), line_concept, from_suggestion) in enumerate(order_lines, start=1):
            qty = 1 + int(rng.random() < 0.25)
            total += price * qty
            _write(buffers["lines"], order_id, i, etype, eid, line_concept, qty, price, _bool(from_suggestion))
        when = clock + timedelta(seconds=30)
        _write(
            buffers["orders"],
            order_id,
            s.user_id,
            session_id,
            cart_id,
            _iso(when),
            order_vertical,
            round(total),
            "synthetic",
        )
        emit("order_placed", when, vertical=order_vertical, cart=cart_id, value=round(total))
        counts["pedidos"] += 1
        s.orders_by_vertical.setdefault(order_vertical, []).append(ts)


def _stay_probability(s: UserState, now: datetime, gap: float) -> float:
    """Probabilidad de seguir activa después de una sesión: la retención M+1 esperada de su combinación fina de los
    últimos 30 días (la de Rappi del arquetipo si no pidió), llevada a los días desde la sesión anterior. Las
    búsquedas sin resultado y los carros abandonados de las últimas 4 semanas multiplican el riesgo (el exponente)."""
    window = now - timedelta(days=28)
    unmet = sum(1 for t in s.recent_unmet if t >= window)
    abandon = sum(1 for t in s.recent_abandon if t >= window)
    since = now - timedelta(days=COMBO_WINDOW_DAYS)
    fine = fine_of(v for v, ts in s.orders_by_vertical.items() if any(t >= since for t in ts))
    retention = expected_retention(s.archetype) if fine == NONE_COMBO else expected_fine_retention(fine)
    survival = min(retention / month_order_probability(s.archetype), MAX_SURVIVAL)
    risk = (1 + CHURN_UNMET * unmet) * (1 + CHURN_ABANDON * abandon)
    return survival ** (gap / 30 * risk)


def _maybe_wish(rng, week: float):
    for wish in WISHES:
        _, _, _, base, growth = wish
        if rng.random() < 0.02 * base * (1 + growth) ** week:
            return wish
    return None


def _suggestion(catalog: Catalog, concept: str, vertical: str, rng: random.Random | None = None):
    """Complemento curado en OTRO vertical con ítems reales: el primero en el orden del agente (`ranked_verticals`,
    donde el concepto es más típico y restaurantes solo para lo que se pide hecho), no uno al azar; si Turbo también lo
    vende, con `rng` va a Turbo con probabilidad TURBO_SUGGESTION (solo entonces se sortea). Con las guardias de
    ofertas del agente real: nada de alcohol, bebé, salud ni sensibles, ni de Farmacia o Licores, ni un producto de
    `Catalog.unofferable` (de una tienda Farmacia, Sex shop o Smoking shop, o que dice bebé)."""
    concepts = load_taxonomy().concepts
    for target, weight in sorted(catalog.edges.get(concept, []), key=lambda e: -e[1]):
        if target not in concepts or not is_offerable(concepts[target]):
            continue
        verticals = [
            v
            for v in catalog.ranked.get(target, [])
            if v != vertical and offerable_vertical(v) and catalog.offer_options(v, target)
        ]
        if verticals:
            chosen = verticals[0]
            if chosen != "turbo" and "turbo" in verticals and rng is not None and rng.random() < TURBO_SUGGESTION:
                chosen = "turbo"
            return target, chosen, weight
    return None


def _pick_vertical(rng, interests: dict[str, dict[str, float]]) -> str:
    """El vertical de una sesión: primero el grupo, parejo entre los grupos de sus intereses, y dentro de él un
    vertical según el peso de sus conceptos. Sin el sorteo por grupo, el grupo con más conceptos se llevaba casi todas
    las sesiones y quien combina grupos pasaba muchos meses en uno solo."""
    group_of = _COMBOS.group_of
    groups = [g for g in GROUP_ORDER if any(group_of[v] == g for v in interests)]
    group = rng.choice(groups)
    return _weighted(rng, {v: sum(c.values()) for v, c in interests.items() if group_of[v] == group})


def _weighted(rng, weights: dict[str, float]) -> str:
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


def _modality(rng) -> str:
    return rng.choices([m for m, _ in MODALITIES], weights=[w for _, w in MODALITIES])[0]


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _bool(value) -> str | None:
    return None if value is None else ("t" if value else "f")


def _write(buffer: io.StringIO, *values) -> None:
    buffer.write("\t".join("\\N" if v is None else str(v).replace("\t", " ").replace("\n", " ") for v in values) + "\n")


def _copy(conn: Connection, target: str, buffer: io.StringIO) -> None:
    buffer.seek(0)
    with conn.cursor() as cur, cur.copy(f"COPY {target} FROM STDIN") as copy:
        while chunk := buffer.read(1 << 20):
            copy.write(chunk)
