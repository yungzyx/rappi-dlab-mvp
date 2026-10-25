"""Perfiles de gusto: lo que la persona pide seguido arma un perfil («Amante de lo asiático»), y cada perfil tiene una
escalera de verticales que el agente ofrece de a un peldaño, más un viaje opcional («Idea para RappiTravel»).

Todo vive en datos: `perfiles.toml` y `destinos.toml`, junto a este módulo. Se validan al cargar contra la taxonomía,
los segmentos y las guardias de ofertas (`guards.py`): un peldaño nunca nombra lo que el agente no ofrece por su cuenta.

El motor:
- `active_profiles`: los perfiles de una persona del prototipo, desde sus segmentos no sensibles (como
  `personal.py`), con su «por qué» contado en sus pedidos y búsquedas. «Olvidar» borra o recalcula sus segmentos, así
  que el perfil se va con ellos.
- `ladder`: la escalera de un perfil, con productos de verdad: una búsqueda de oferta por peldaño
  (`search_products(..., offer=True)`), así que pasan todas las guardias (nada +18, ni un nombre o una sección de menú
  que dice alcohol, ni tiendas Farmacia, Sex shop o Smoking shop). Además, una escalera no muestra tiendas que se
  llaman «Licores» o «Botillería» (venden hielo y bebidas, pero el perfil no lleva ahí), y sus restaurantes son de la
  ciudad de la persona (`person_city`).
"""

import tomllib
from dataclasses import dataclass
from functools import cache
from itertools import zip_longest
from pathlib import Path

from psycopg import Connection
from rappi_scraper.storage.search import VERTICALS

from .. import config
from ..agent.grouped_search import SCREEN_VERTICALS, SpareConnector, search_each
from ..agent.tools import Product, search_products
from ..concepts.taxonomy import load_taxonomy
from ..embeddings.base import MemoizedQueryEmbedder, TextEmbedder
from ..layers.segments import LEVELS, load_segment_rules
from ..text import normalize, tokens
from .guards import is_offerable, offerable_vertical
from .personal import LEVEL_WEIGHT, Signal, is_prototype_user

DATA_DIR = Path(__file__).resolve().parent
MIN_STEPS = 2  # con menos peldaños no hay escalera que ofrecer
FACTS = 2  # hechos por destino: los que muestra la tarjeta del viaje
STEP_PRODUCTS = 4  # lo más que muestra un peldaño; basta uno («Lindor Matcha» es el único matcha de chocolaterías)
# Productos que se piden por peldaño, antes de quedarse con los de sus conceptos, con sus palabras y, en restaurantes,
# uno por cadena que la persona no conoce. En restaurantes, más: los primeros platos suelen ser de un mismo local (en la
# base real, 10 de 12).
STEP_CANDIDATES = 12
RESTAURANT_CANDIDATES = 40
# Palabras clave de cada concepto en la consulta de un peldaño sin palabras, después del nombre del concepto. En
# restaurantes, sin el nombre: sus palabras genéricas («comida», «tablas») contra 165 mil platos costaban 150 ms más por
# peldaño en la base real, y los platos se llaman por sus palabras clave (sushi, roll, wok, chorrillana).
STEP_QUERY_KEYWORDS = 2
LIQUOR_STORE_WORDS = ("licor", "botiller")  # tiendas (nombre o marca) que una escalera no muestra: «Turbo Licores»
# Las comunas de una ciudad del scraper (la de `stores.city` en las tiendas: «Santiago de Chile»). Un restaurante guarda
# la comuna de su página («Ñuñoa», «Maipú»), no esa ciudad: los restaurantes salen del sitemap, no de un listado por
# ciudad. Gran Santiago: las 32 comunas de la provincia de Santiago, Puente Alto, San Bernardo, Colina (Chicureo) y
# Lampa; Melipilla y el resto de la región quedan fuera. Una ciudad que no está aquí es su propia comuna («Viña del
# Mar»).
CITY_COMUNAS = {
    "Santiago de Chile": (
        *("Cerrillos", "Cerro Navia", "Conchalí", "El Bosque", "Estación Central", "Huechuraba", "Independencia"),
        *("La Cisterna", "La Florida", "La Granja", "La Pintana", "La Reina", "Las Condes", "Lo Barnechea"),
        *("Lo Espejo", "Lo Prado", "Macul", "Maipú", "Ñuñoa", "Pedro Aguirre Cerda", "Peñalolén", "Providencia"),
        *("Pudahuel", "Quilicura", "Quinta Normal", "Recoleta", "Renca", "San Joaquín", "San Miguel", "San Ramón"),
        *("Santiago", "Vitacura", "Puente Alto", "San Bernardo", "Colina", "Lampa"),
    ),
}
REASON_CONCEPTS = 3  # conceptos que nombra el «por qué»
QUERY_EVENTS = ("search", "chat", "ask")  # lo que cuenta como «buscaste»
# El «por qué» sin nada que contar: un perfil que se armó con lo que el agente no nombra (los cócteles del carrete)
# o con búsquedas sin concepto.
REASON_NEUTRAL = "Por lo que has pedido y buscado últimamente."


@dataclass(frozen=True)
class Fact:
    text: str
    source: str
    url: str


@dataclass(frozen=True)
class Destination:
    id: str
    name: str
    text: str  # la pregunta: «¿Y si un día vas a Japón?»
    facts: tuple[Fact, ...]


@dataclass(frozen=True)
class Step:
    vertical: str
    concepts: tuple[str, ...]
    text: str
    words: tuple[str, ...] = ()  # si las hay, el nombre del producto debe tener alguna (normalizadas, `text.normalize`)
    avoid: tuple[str, ...] = ()  # el nombre no puede tener ninguna (normalizadas)

    def fits(self, name: str) -> bool:
        """Si el nombre dice alguna de sus `words` (si tiene) y ninguna de `avoid`, cada una al comienzo de una palabra
        del nombre normalizado: «vaso» calza «Vasos», no «Posavasos»; «tiramis» calza «Tiramisú»."""
        text = f" {normalize(name)}"
        says = [f" {word}" in text for word in self.words]
        return (not says or any(says)) and not any(f" {word}" in text for word in self.avoid)


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    emoji: str
    main: bool
    segments: tuple[str, ...]
    min_level: str
    ladder: tuple[Step, ...]
    trip: str | None = None  # id de un destino
    likes: str | None = None  # lo que sigue a «Por tu gusto por…» en el momento `perfil` («lo asiático»)


@cache
def load_destinations(path: Path = DATA_DIR / "destinos.toml") -> dict[str, Destination]:
    destinations: dict[str, Destination] = {}
    for raw in tomllib.loads(path.read_text(encoding="utf-8")).get("destino", ()):
        where = f"Destino {raw.get('id', '?')}"
        _check_keys(raw, {"id", "nombre", "texto", "hechos"}, set(), where)
        if raw["id"] in destinations:
            raise ValueError(f"{where}: id repetido")
        if len(raw["hechos"]) != FACTS:
            raise ValueError(f"{where}: lleva {FACTS} hechos, no {len(raw['hechos'])}")
        facts = []
        for fact in raw["hechos"]:
            _check_keys(fact, {"texto", "fuente", "url"}, set(), f"{where}, hecho")
            if not fact["url"].startswith("https://"):
                raise ValueError(f"{where}: la url de cada hecho debe ser https ({fact['url']})")
            facts.append(Fact(fact["texto"], fact["fuente"], fact["url"]))
        destinations[raw["id"]] = Destination(raw["id"], raw["nombre"], raw["texto"], tuple(facts))
    return destinations


@cache
def load_profiles(path: Path = DATA_DIR / "perfiles.toml") -> dict[str, Profile]:
    """Los perfiles en el orden del archivo, validados: ids de conceptos, verticales, segmentos y destinos que existen,
    y nada que las guardias de ofertas bloqueen."""
    concepts = load_taxonomy().concepts
    segments = {rule.id: rule for rule in load_segment_rules()[1]}
    destinations = load_destinations()
    profiles: dict[str, Profile] = {}
    for raw in tomllib.loads(path.read_text(encoding="utf-8")).get("perfil", ()):
        where = f"Perfil {raw.get('id', '?')}"
        _check_keys(
            raw,
            {"id", "nombre", "emoji", "segmentos", "nivel_minimo", "escalera"},
            {"principal", "viaje", "gusto"},
            where,
        )
        if "gusto" in raw and not (isinstance(raw["gusto"], str) and raw["gusto"].strip()):
            raise ValueError(f"{where}: «gusto» va como un texto no vacío")
        if raw["id"] in profiles:
            raise ValueError(f"{where}: id repetido")
        for segment in raw["segmentos"]:
            if segment not in segments:
                raise ValueError(f"{where}: segmento desconocido «{segment}»")
            if segments[segment].sensitive:
                raise ValueError(f"{where}: el segmento «{segment}» es sensible y no arma perfiles")
        if raw["nivel_minimo"] not in LEVELS:
            raise ValueError(f"{where}: nivel_minimo «{raw['nivel_minimo']}» no es uno de {', '.join(LEVELS)}")
        if raw.get("viaje") is not None and raw["viaje"] not in destinations:
            raise ValueError(f"{where}: viaje a un destino desconocido «{raw['viaje']}»")
        ladder = tuple(_step(entry, concepts, where) for entry in raw["escalera"])
        if len(ladder) < MIN_STEPS:
            raise ValueError(f"{where}: la escalera necesita al menos {MIN_STEPS} peldaños")
        profiles[raw["id"]] = Profile(
            id=raw["id"],
            name=raw["nombre"],
            emoji=raw["emoji"],
            main=raw.get("principal", False),
            segments=tuple(raw["segmentos"]),
            min_level=raw["nivel_minimo"],
            ladder=ladder,
            trip=raw.get("viaje"),
            likes=raw.get("gusto"),
        )
    main = [p.id for p in profiles.values() if p.main]
    if len(main) > 1:
        raise ValueError(f"Solo un perfil puede ser principal: {', '.join(main)}")
    return profiles


def _step(raw: dict, concepts: dict, where: str) -> Step:
    _check_keys(raw, {"vertical", "conceptos", "texto"}, {"palabras", "evitar"}, f"{where}, peldaño")
    vertical = raw["vertical"]
    if vertical not in VERTICALS:
        raise ValueError(f"{where}: vertical desconocida «{vertical}»")
    if not offerable_vertical(vertical):
        raise ValueError(f"{where}: el agente no ofrece productos de «{vertical}» por su cuenta")
    if not raw["conceptos"]:
        raise ValueError(f"{where}: un peldaño en «{vertical}» sin conceptos")
    for concept in raw["conceptos"]:
        if concept not in concepts:
            raise ValueError(f"{where}: concepto desconocido «{concept}»")
        if not is_offerable(concepts[concept]):
            raise ValueError(f"{where}: el agente no ofrece «{concept}» por su cuenta (offers/guards.py)")
    words = _words(raw, "palabras", where)
    avoid = _words(raw, "evitar", where)
    return Step(vertical, tuple(raw["conceptos"]), raw["texto"], words, avoid)


def _words(raw: dict, key: str, where: str) -> tuple[str, ...]:
    """Las `palabras` o `evitar` de un peldaño, normalizadas como el nombre con que se comparan: «café» calza «Bombones
    de Cafe» y «cotillón», «Cotillon». Un texto suelto (`palabras = "vaso"`) o una palabra vacía se notan al cargar: si
    no, calzaría letra por letra o con todo."""
    found = raw.get(key, [])
    if not isinstance(found, list):
        raise ValueError(f"{where}: «{key}» va como lista, no como texto")
    words = tuple(normalize(word) if isinstance(word, str) else "" for word in found)
    if "" in words:
        raise ValueError(f"{where}: «{key}» trae una palabra vacía o sin letras")
    return words


def _check_keys(raw: dict, required: set[str], optional: set[str], where: str) -> None:
    """Una clave mal escrita («concepto») o que falta se nota al cargar, no como un peldaño que nunca calza."""
    missing = sorted(required - raw.keys())
    if missing:
        raise ValueError(f"{where}: falta {', '.join(f'«{k}»' for k in missing)}")
    unknown = sorted(raw.keys() - required - optional)
    if unknown:
        raise ValueError(f"{where}: clave desconocida {', '.join(f'«{k}»' for k in unknown)}")


# ── qué perfiles tiene una persona ───────────────────────────────────────────


@dataclass(frozen=True)
class ActiveProfile:
    profile: Profile
    level: str  # el mayor de sus segmentos
    score: float  # la suma de sus segmentos
    reason: str  # «Pediste 🍣 sushi 2 veces, y buscaste 🥡 comida asiática 1 vez.»
    basis: tuple[dict, ...]  # sus segmentos y lo que cuenta el «por qué», con la forma de `reason.basis` de una oferta

    def to_dict(self) -> dict:
        return {
            "id": self.profile.id,
            "nombre": self.profile.name,
            "emoji": self.profile.emoji,
            "nivel": self.level,
            "principal": self.profile.main,
            "por_que": self.reason,
            "basis": list(self.basis),
        }


def active_profiles(conn: Connection, user_id: str | None) -> list[ActiveProfile]:
    """Los perfiles de la persona: los que tienen alguno de sus segmentos (no sensibles) en `nivel_minimo` o más. El
    nivel es el mayor de sus segmentos y el puntaje, la suma. El «por qué» cuenta sus pedidos y búsquedas en la ventana
    de esos segmentos (la mayor de los que tiene; hoy, 120 días). La `basis` tiene la forma de las señales de
    `personal.py`: la evidencia de sus segmentos (concepto, el peso de su nivel, `segmento:<id>`) y lo que cuenta el
    «por qué» (concepto, cuántas veces, `pedidos` o `busquedas`), solo de conceptos que el agente puede nombrar. El
    principal primero y después por puntaje (con empate, el orden del archivo). Vacío si no es del prototipo."""
    if not is_prototype_user(conn, user_id):
        return []
    profiles = load_profiles()
    rows = conn.execute(
        """SELECT s.segment_id, s.level, s.score, coalesce(s.evidence -> 'top', '[]'::jsonb)
           FROM user_segments s JOIN segment_defs d USING (segment_id)
           WHERE s.user_id = %s AND NOT d.sensitive AND s.segment_id = ANY(%s)""",
        (user_id, sorted({segment for p in profiles.values() for segment in p.segments})),
    ).fetchall()
    held = {segment: (level, float(score), top) for segment, level, score, top in rows}
    rules = {rule.id: rule for rule in load_segment_rules()[1]}
    active = []
    for profile in profiles.values():
        mine = [segment for segment in profile.segments if segment in held]
        level = max((held[segment][0] for segment in mine), key=LEVELS.index, default=None)
        if level is None or LEVELS.index(level) < LEVELS.index(profile.min_level):
            continue
        evidence = [
            Signal("concepto", item["id"], LEVEL_WEIGHT[held[segment][0]], f"segmento:{segment}")
            for segment in mine
            for item in held[segment][2]
            if item.get("kind") == "concepto" and _nameable(item["id"])
        ]
        wanted = _counted_concepts(profile, rules)
        days = max(rules[segment].window_days for segment in mine)
        counts = _counts(conn, user_id, wanted, days) if wanted else {}
        counted = [
            Signal("concepto", c, n, source) for c, by_source in counts.items() for source, n in by_source.items()
        ]
        score = round(sum(held[segment][1] for segment in mine), 3)
        basis = tuple(s.to_dict() for s in evidence + counted)
        active.append(ActiveProfile(profile, level, score, _reason(wanted, counts), basis))
    return sorted(active, key=lambda a: (not a.profile.main, -a.score))


def _nameable(concept_id: str) -> bool:
    """Si el agente puede nombrar el concepto en un «por qué» (ni +18, ni sensible, ni bebé, ni salud)."""
    concept = load_taxonomy().concepts.get(concept_id)
    return concept is not None and is_offerable(concept)


def _counted_concepts(profile: Profile, rules: dict) -> list[str]:
    """Los conceptos que miran los segmentos del perfil y que el agente puede nombrar (el carrete se activa también con
    cócteles y espumante, que no se nombran), en el orden de sus segmentos."""
    named = [c for segment in profile.segments for c in rules[segment].signals.get("concepts", ())]
    return [c for c in dict.fromkeys(named) if _nameable(c)]


def _counts(conn: Connection, user_id: str, concepts: list[str], days: int) -> dict[str, dict[str, int]]:
    """concepto → {"pedidos": pedidos distintos, "busquedas": búsquedas} de la persona en los últimos `days` días (la
    ventana de sus segmentos), sin lo de «Rappi hoy» (ahí la app no aprende)."""
    rows = conn.execute(
        """SELECT l.concept_id, 'pedidos', count(DISTINCT o.order_id)
           FROM app_orders o JOIN app_order_lines l USING (order_id)
           WHERE o.user_id = %(user)s AND o.mode = 'propuesta' AND l.concept_id = ANY(%(concepts)s)
             AND o.ts >= now() - make_interval(days => %(days)s)
           GROUP BY 1
           UNION ALL
           SELECT e.concept_id, 'busquedas', count(*)
           FROM app_events e
           WHERE e.user_id = %(user)s AND e.type = ANY(%(types)s) AND e.concept_id = ANY(%(concepts)s)
             AND coalesce(e.payload ->> 'mode', '') <> 'actual' AND e.ts >= now() - make_interval(days => %(days)s)
           GROUP BY 1""",
        {"user": user_id, "concepts": concepts, "days": days, "types": list(QUERY_EVENTS)},
    ).fetchall()
    counts: dict[str, dict[str, int]] = {}
    for concept_id, source, n in sorted(rows, key=lambda row: row[1] != "pedidos"):  # los pedidos primero
        counts.setdefault(concept_id, {})[source] = n
    return counts


def _reason(concepts: list[str], counts: dict[str, dict[str, int]]) -> str:
    """«Pediste 🍣 sushi 2 veces, y buscaste 🥡 comida asiática 1 vez.»: los `REASON_CONCEPTS` que más cuentan (los
    pedidos antes que las búsquedas); de un concepto pedido no se dicen sus búsquedas."""
    taxonomy = load_taxonomy().concepts
    ranked = sorted(
        counts, key=lambda c: (-counts[c].get("pedidos", 0), -counts[c].get("busquedas", 0), concepts.index(c))
    )[:REASON_CONCEPTS]

    def times(concept_id: str, n: int) -> str:
        concept = taxonomy[concept_id]
        return f"{concept.emoji} {concept.name.lower()} {n} {'vez' if n == 1 else 'veces'}"

    ordered = [times(c, counts[c]["pedidos"]) for c in ranked if counts[c].get("pedidos")]
    searched = [times(c, counts[c]["busquedas"]) for c in ranked if not counts[c].get("pedidos")]
    parts = [verb + _join(said) for verb, said in (("pediste ", ordered), ("buscaste ", searched)) if said]
    if not parts:
        return REASON_NEUTRAL
    text = ", y ".join(parts)
    return text[0].upper() + text[1:] + "."


def _join(items: list[str]) -> str:
    """«a, b y c»."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " y " + items[-1]


def person_city(conn: Connection, user_id: str | None) -> str:
    """La ciudad de los restaurantes de una escalera: la de la persona del prototipo (`app_users.city`) o, si no la
    tiene (la app no la pide), si es de otra fuente o si no hay persona, `config.PROFILE_CITY`."""
    if user_id is not None:
        row = conn.execute(
            "SELECT city FROM app_users WHERE user_id = %s AND source = 'prototype'", (user_id,)
        ).fetchone()
        if row and row[0] and row[0].strip():
            return row[0]
    return config.PROFILE_CITY


def city_places(city: str) -> frozenset[str]:
    """Las comunas de una ciudad, normalizadas como se comparan (`text.normalize`): las de `CITY_COMUNAS` si se llama
    así o si es una de ellas («Santiago», la ciudad de las personas simuladas, es Santiago de Chile); si no, la ciudad
    misma («Concepcion», como la escribe el scraper, es la comuna de Concepción)."""
    wanted = normalize(city)
    for name, comunas in CITY_COMUNAS.items():
        places = frozenset(normalize(comuna) for comuna in comunas)
        if wanted == normalize(name) or wanted in places:
            return places
    return frozenset({wanted})


def ordered_restaurants(conn: Connection, user_id: str | None) -> set[int]:
    """Los locales donde la persona ya pidió (sin «Rappi hoy»): el peldaño de restaurantes ofrece los que no conoce.
    Vacío si no es del prototipo."""
    if not is_prototype_user(conn, user_id):
        return set()
    rows = conn.execute(
        """SELECT DISTINCT store_id FROM menu_items
           WHERE item_id = ANY(ARRAY(SELECT l.entity_id FROM app_orders o JOIN app_order_lines l USING (order_id)
                                     WHERE o.user_id = %s AND o.mode = 'propuesta' AND l.entity_type = 'menu_item'
                                       AND l.entity_id ~ '^[0-9]+$')::bigint[])""",
        (user_id,),
    )
    return {store_id for (store_id,) in rows}


# ── la escalera ──────────────────────────────────────────────────────────────


# store_id → (su cadena, o el local si no tiene; si es una tienda de licores; su comuna): lo que da `_stores`.
StoreInfo = dict[int, tuple[tuple[str, int], bool, str]]


@dataclass
class LadderStep:
    step: Step
    products: list[Product]

    def to_dict(self) -> dict:
        return {
            "vertical": self.step.vertical,
            "prototype_vertical": SCREEN_VERTICALS.get(self.step.vertical),
            "texto": self.step.text,
            "products": [p.to_dict() for p in self.products],
        }


def ladder(
    conn: Connection,
    embedder: TextEmbedder | None,
    profile: Profile,
    exclude_stores: set[int] | None = None,
    city: str | None = None,
    spare: SpareConnector | None = None,
) -> list[LadderStep]:
    """Los peldaños del perfil que tienen productos, en su orden: de 1 a `STEP_PRODUCTS` por peldaño, sin repetir un
    nombre entre peldaños. Una lista vacía si quedan menos de `MIN_STEPS`: no hay escalera. `exclude_stores`
    (`ordered_restaurants`): los locales que el peldaño de restaurantes deja fuera, con las otras sucursales de su
    cadena. `city` (`person_city`; sin ella, `config.PROFILE_CITY`): los restaurantes son de sus comunas. Una búsqueda
    de oferta por peldaño (y una consulta por sus tiendas); cada consulta se embebe una vez, en un solo lote. Con
    `spare` (las conexiones extra de la API), los peldaños se buscan a la vez, como las verticales de `/search`
    (`grouped_search.search_each`, con su tope y sin tomar la reserva del pool); después se eligen sus productos en
    orden, así que la escalera es la misma que en serie."""
    queries = [_step_query(step) for step in profile.ladder]
    if embedder is not None:
        if not isinstance(embedder, MemoizedQueryEmbedder):
            embedder = MemoizedQueryEmbedder(embedder)
        embedder.embed_queries(list(dict.fromkeys(queries)))
    places = city_places(city or config.PROFILE_CITY)
    known = [set(exclude_stores or ()) if step.vertical == "restaurantes" else set() for step in profile.ladder]

    def search(connection: Connection, index: int) -> tuple[list[Product], StoreInfo]:
        return _step_search(connection, embedder, profile.ladder[index], queries[index], known[index])

    found = search_each(conn, list(range(len(profile.ladder))), search, spare)
    steps: list[LadderStep] = []
    shown: set[str] = set()
    for step, stores_known, (products, stores) in zip(profile.ladder, known, found, strict=True):
        if chosen := _step_products(step, products, stores, stores_known, shown, places):
            steps.append(LadderStep(step, chosen))
            shown |= {_name_key(p.name) for p in chosen}
    return steps if len(steps) >= MIN_STEPS else []


def _step_query(step: Step) -> str:
    """Lo que busca un peldaño: sus palabras, si tiene (es lo que el nombre debe decir); si no, por cada concepto su
    nombre (lo que mejor entiende la búsqueda vectorial) y sus primeras palabras clave que suman una palabra nueva (lo
    que la léxica encuentra en los nombres: sin embeddings, «Despensa asiática» no calzaba ningún producto). En
    restaurantes, solo las palabras clave (`STEP_QUERY_KEYWORDS`)."""
    if step.words:
        return " ".join(step.words)
    concepts = load_taxonomy().concepts
    chosen: list[str] = []
    for concept_id in step.concepts:
        concept = concepts[concept_id]
        named = step.vertical != "restaurantes"
        seen = {word.rstrip("s") for word in tokens(concept.name)} if named else set()
        chosen += [concept.name] if named else []
        kept = 0
        for keyword in concept.keywords:
            words = {word.rstrip("s") for word in tokens(keyword)}  # «rolls» no suma nada a «roll»
            if words - seen:
                chosen.append(keyword)
                seen |= words
                kept += 1
            if kept == STEP_QUERY_KEYWORDS:
                break
    return " ".join(chosen)


def _step_search(
    conn: Connection, embedder: TextEmbedder | None, step: Step, query: str, known: set[int]
) -> tuple[list[Product], StoreInfo]:
    """Lo que un peldaño lee de la base: su búsqueda de oferta y las tiendas de lo que encontró y de `known`. No depende
    de los otros peldaños: se puede buscar a la vez que ellos."""
    k = RESTAURANT_CANDIDATES if step.vertical == "restaurantes" else STEP_CANDIDATES
    outcome = search_products(conn, step.vertical, query, list(step.concepts), embedder, k=k, offer=True)
    stores = _stores(conn, {p.store_id for p in outcome.products if p.store_id is not None} | known)
    return outcome.products, stores


def _step_products(
    step: Step,
    found: list[Product],
    stores: StoreInfo,
    known: set[int],
    shown: set[str],
    city: frozenset[str],
) -> list[Product]:
    """De lo que encontró el peldaño (`_step_search`), los productos de sus conceptos que calzan sus palabras y que otro
    peldaño no mostró, primero los con foto y alternando sus conceptos (la despensa italiana no son cuatro pastas).
    Ninguno de una tienda de licores. Los platos, de un local en una comuna de `city` (`city_places`), uno por cadena
    (o local, si no tiene) y no de las que la persona ya conoce."""
    places = {stores[store_id][0] for store_id in known if store_id in stores}
    by_concept: dict[str, list[Product]] = {c: [] for c in step.concepts}
    for product in sorted(found, key=lambda p: p.img is None):  # estable: sigue el orden de la búsqueda
        if product.concept not in by_concept or not step.fits(product.name) or _name_key(product.name) in shown:
            continue
        place, liquor, comuna = stores.get(product.store_id, (("local", product.store_id), False, ""))
        if liquor or _liquor_store(product.store):
            continue
        if product.entity_type == "menu_item":
            if place in places or comuna not in city:
                continue
            places.add(place)
        by_concept[product.concept].append(product)
    mixed = [p for group in zip_longest(*by_concept.values()) for p in group if p is not None]
    return mixed[:STEP_PRODUCTS]


def _stores(conn: Connection, store_ids: set[int]) -> StoreInfo:
    """store_id → (su cadena, o el local si no tiene; si su nombre o su marca dicen licores o botillería; su comuna,
    `stores.city`, normalizada)."""
    if not store_ids:
        return {}
    rows = conn.execute(
        """SELECT s.store_id, s.brand_id, s.name, b.name, s.city
           FROM stores s LEFT JOIN brands b USING (brand_id)
           WHERE s.store_id = ANY(%s)""",
        (sorted(store_ids),),
    )
    return {
        store_id: (
            ("cadena", brand_id) if brand_id is not None else ("local", store_id),
            _liquor_store(name, brand),
            normalize(city or ""),
        )
        for store_id, brand_id, name, brand, city in rows
    }


def _liquor_store(*names: str | None) -> bool:
    return any(word in normalize(name) for name in names if name for word in LIQUOR_STORE_WORDS)


def _name_key(name: str) -> str:
    """Un nombre como lo compara la búsqueda al quitar repetidos (`agent.tools._dedupe`)."""
    return " ".join(name.lower().split())
