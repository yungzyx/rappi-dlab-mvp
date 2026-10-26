"""Preferencias explícitas de la persona con el agente: su dieta, sus alergias y sus cocinas y tiendas favoritas. Se
eligen entre opciones en la hoja «Mis preferencias» del buscador con Mochi (sin escribir); si una frase como «soy
vegetariano» o «mi tienda favorita es…» llega por el buscador, también se entiende. Tabla
`agent_preferences` (migración 045); las opciones de dieta y alergias, en offers/preferencias.toml.

Reglas:
- La dieta y las alergias solo filtran lo que el agente muestra (respuestas, sugerencias y ofertas), por el nombre del
  producto y solo en lo que es comida. Nunca son la razón (`reason`) de una oferta y no entran a segmentos, perfiles de
  gusto, el motor ni el panel de negocio: una alergia es un dato de salud. Como el filtro mira el nombre, el agente lo
  dice cuando muestra comida (`notice`).
- Las cocinas y tiendas favoritas solo ordenan lo que ya se iba a mostrar: no agregan productos ni eligen una vertical,
  así que Licores y Farmacia siguen subiendo solo por señales propias de la persona.
- Solo en «Propuesta»: «Rappi hoy» no las guarda ni las usa.

Mientras el agente responde un turno o arma una oferta, las de la persona quedan puestas (`applied`) y
`agent.tools.search_products` filtra con ellas antes de cortar los resultados (`active().keep`). Lo que llega por otro
camino (la recompra, los peldaños de un perfil) lo filtra quien arma la respuesta (`keep_dicts`). El buscador de la app
(`/search` con `user_id`) usa el mismo filtro, solo con la dieta y las alergias (`only_filters`): no ordena por las
favoritas, y la respuesta dice cuando filtró (`preferences_notice`).
"""

import re
import tomllib
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from psycopg import Connection

from ..concepts.taxonomy import load_taxonomy
from ..text import normalize

DATA_FILE = Path(__file__).resolve().parent / "preferencias.toml"
FILTER_KINDS = ("dieta", "alergia")
ORDER_KINDS = ("cocina", "tienda")
KINDS = (*FILTER_KINDS, *ORDER_KINDS)
MAX_PREFERENCES = 30  # por persona: más que todas las opciones de dieta, alergia y cocina juntas
MAX_VALUE = 64


@dataclass(frozen=True)
class Rule:
    """Una opción de dieta o alergia (offers/preferencias.toml)."""

    id: str
    kind: str
    name: str
    without: str  # lo que el agente dice que saca («carne»)
    phrases: tuple[str, ...]
    concepts: frozenset[str] = frozenset()
    words: re.Pattern | None = None
    unless: re.Pattern | None = None

    def drops(self, said: str, concept: str | None) -> bool:
        """¿Saca este producto? `said` es su nombre normalizado."""
        if self.unless and self.unless.search(said):
            return False
        return concept in self.concepts or bool(self.words and self.words.search(said))


@dataclass(frozen=True)
class Options:
    rules: dict[str, Rule]
    food_groups: frozenset[str]
    cuisines: tuple[str, ...]  # conceptos que se pueden marcar como cocina favorita


@lru_cache
def load_options(path: Path = DATA_FILE) -> Options:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    taxonomy = load_taxonomy()
    rules = {}
    for raw in data.get("preferencia", ()):
        if raw["tipo"] not in FILTER_KINDS:
            raise ValueError(f"Preferencia {raw['id']}: tipo {raw['tipo']!r} (se espera dieta o alergia)")
        unknown = [c for c in raw.get("conceptos", ()) if c not in taxonomy.concepts]
        if unknown:
            raise ValueError(f"Preferencia {raw['id']}: conceptos desconocidos {unknown}")
        words = [normalize(w) for w in raw.get("palabras", ())]
        rules[raw["id"]] = Rule(
            id=raw["id"],
            kind=raw["tipo"],
            name=raw["nombre"],
            without=raw["sin"],
            phrases=tuple(normalize(p) for p in raw["frases"]),
            concepts=frozenset(raw.get("conceptos", ())),
            words=re.compile(rf"\b(?:{'|'.join(map(re.escape, words))})\b") if words else None,
            unless=re.compile(raw["salvo"]) if raw.get("salvo") else None,
        )
    unknown = [c for c in data["cocinas"] if c not in taxonomy.concepts]
    if unknown:
        raise ValueError(f"Cocinas desconocidas: {unknown}")
    return Options(rules, frozenset(data["grupos_comida"]), tuple(data["cocinas"]))


def is_food(concept: str | None, entity_type: str | None) -> bool:
    """Un plato, algo sin concepto (podría ser comida) o un concepto de los grupos de comida."""
    if entity_type == "menu_item" or concept is None:
        return True
    found = load_taxonomy().concepts.get(concept)
    return found is not None and found.parent in load_options().food_groups


def _get(product, key: str):
    return product.get(key) if isinstance(product, dict) else getattr(product, key, None)


@dataclass(frozen=True)
class Preferences:
    """Las preferencias de una persona, listas para filtrar y ordenar. Vacía (falsa) si no tiene."""

    filters: tuple[Rule, ...] = ()
    cuisines: tuple[str, ...] = ()
    stores: tuple[str, ...] = ()  # nombres normalizados

    def __bool__(self) -> bool:
        return bool(self.filters or self.cuisines or self.stores)

    def keeps(self, product) -> bool:
        """Un `Product` o su `to_dict()`: ¿queda con la dieta y las alergias de la persona?"""
        if not self.filters or not is_food(_get(product, "concept"), _get(product, "entity_type")):
            return True
        said = normalize(_get(product, "name") or "")
        return not any(rule.drops(said, _get(product, "concept")) for rule in self.filters)

    def keep(self, products: list) -> list:
        return [p for p in products if self.keeps(p)]

    def rank(self, products: list) -> list:
        """Lo de sus cocinas y tiendas favoritas primero, sin sacar ni agregar nada (orden estable)."""
        if not (self.cuisines or self.stores):
            return products
        return sorted(products, key=lambda p: not self._favorite(p))

    def _favorite(self, product) -> bool:
        if _get(product, "concept") in self.cuisines:
            return True
        store = normalize(_get(product, "store") or "")
        return any(store == s or store.startswith(f"{s} ") for s in self.stores)

    def only_filters(self) -> "Preferences":
        """Solo la dieta y las alergias: lo que usa el buscador (`/search`), que filtra pero no ordena."""
        return Preferences(filters=self.filters)

    def notice(self, products: Iterable, dropped: int = 0) -> str | None:
        """Lo que el agente dice al mostrar comida con dieta o alergias puestas: filtra por el nombre. Con `dropped`
        (lo que el filtro sacó, en `/search`) lo dice aunque no haya quedado nada que mostrar."""
        if not self.filters:
            return None
        if not dropped and not any(is_food(_get(p, "concept"), _get(p, "entity_type")) for p in products):
            return None
        said = _join([rule.without for rule in self.filters])
        return f"Por tus preferencias, saqué lo que dice tener {said}; revisa los ingredientes en la tienda."


_ACTIVE: ContextVar[Preferences | None] = ContextVar("agent_preferences", default=None)


@contextmanager
def applied(preferences: Preferences | None) -> Iterator[None]:
    """Mientras dura, `active()` son estas preferencias (las del turno del agente o de la oferta que se arma)."""
    token = _ACTIVE.set(preferences or None)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def active() -> Preferences | None:
    return _ACTIVE.get()


def keep_dicts(preferences: Preferences | None, products: list[dict]) -> list[dict]:
    """Productos ya armados (`to_dict()`), filtrados y ordenados con las preferencias."""
    return preferences.rank(preferences.keep(products)) if preferences else products


# ── Base ─────────────────────────────────────────────────────────────────────
def saved(conn: Connection, user_id: str | None) -> list[tuple[str, str]]:
    """(tipo, valor) de la persona: dieta, alergias, cocinas y tiendas, cada tipo en el orden en que los dijo."""
    if not user_id:
        return []
    return conn.execute(
        """SELECT kind, value FROM agent_preferences WHERE user_id = %s
           ORDER BY array_position(%s::text[], kind), created_at, value""",
        (user_id, list(KINDS)),
    ).fetchall()


def build(items: Iterable[tuple[str, str]]) -> Preferences:
    options = load_options()
    items = list(items)
    return Preferences(
        filters=tuple(options.rules[v] for k, v in items if k in FILTER_KINDS and v in options.rules),
        cuisines=tuple(v for k, v in items if k == "cocina"),
        stores=tuple(normalize(v) for k, v in items if k == "tienda"),
    )


def load(conn: Connection, user_id: str | None) -> Preferences:
    return build(saved(conn, user_id))


def valid(kind: str, value: str) -> bool:
    """¿Es una opción que se puede guardar? Las tiendas se validan contra el catálogo al decirlas (`find_store`)."""
    options = load_options()
    if kind in FILTER_KINDS:
        return value in options.rules and options.rules[value].kind == kind
    if kind == "cocina":
        return value in options.cuisines
    return kind == "tienda" and 0 < len(value) <= MAX_VALUE


def add(conn: Connection, user_id: str, items: Iterable[tuple[str, str]], source: str = "prototype") -> int:
    """Guarda las que falten (la persona ya tiene que existir: `events.ensure_user`). Devuelve cuántas son nuevas."""
    rows = [(user_id, k, v, source) for k, v in dict.fromkeys(items) if valid(k, v)]
    room = MAX_PREFERENCES - len(saved(conn, user_id))
    added = 0
    for row in rows[: max(room, 0)]:
        added += conn.execute(
            """INSERT INTO agent_preferences (user_id, kind, value, source) VALUES (%s, %s, %s, %s)
               ON CONFLICT DO NOTHING""",
            row,
        ).rowcount
    return added


def remove(conn: Connection, user_id: str, items: Iterable[tuple[str, str]]) -> int:
    removed = 0
    for kind, value in items:
        removed += conn.execute(
            "DELETE FROM agent_preferences WHERE user_id = %s AND kind = %s AND value = %s", (user_id, kind, value)
        ).rowcount
    return removed


def replace_all(conn: Connection, user_id: str, items: Iterable[tuple[str, str]], source: str = "prototype") -> None:
    clear(conn, user_id)
    add(conn, user_id, items, source)


def clear(conn: Connection, user_id: str) -> int:
    return conn.execute("DELETE FROM agent_preferences WHERE user_id = %s", (user_id,)).rowcount


def forget_concept(conn: Connection, user_id: str, concept_id: str) -> int:
    """«Olvidar» un concepto también lo saca de sus cocinas favoritas."""
    return remove(conn, user_id, [("cocina", concept_id)])


def find_store(conn: Connection, said: str) -> str | None:
    """El nombre de la tienda o cadena del catálogo que nombró la persona («jumbo» → «Jumbo»), o None. Como en la
    tarjeta del producto: la marca de la tienda o, sin marca, su nombre."""
    wanted = normalize(said)
    if len(wanted) < 3:
        return None
    row = conn.execute(
        """WITH names AS (
               SELECT DISTINCT btrim(coalesce(b.name, s.name)) AS name FROM stores s
               LEFT JOIN brands b ON b.brand_id = s.brand_id
           ), said AS (
               SELECT name, btrim(regexp_replace(lower(unaccent(name)), '[^a-z0-9]+', ' ', 'g')) AS norm FROM names
           )
           SELECT name FROM said WHERE norm = %(said)s OR norm LIKE %(said)s || ' %%'
           ORDER BY length(name), name LIMIT 1""",
        {"said": wanted},
    ).fetchone()
    return row[0] if row else None


# ── Lo que se muestra ────────────────────────────────────────────────────────
def label(kind: str, value: str) -> str:
    if kind in FILTER_KINDS:
        rule = load_options().rules.get(value)
        return rule.name if rule else value
    if kind == "cocina":
        concept = load_taxonomy().concepts.get(value)
        return concept.label if concept else value
    return value


def describe(items: Iterable[tuple[str, str]]) -> list[dict]:
    """[{ tipo, valor, nombre }] para la app."""
    return [{"tipo": k, "valor": v, "nombre": label(k, v)} for k, v in items]


MAX_STORE_OPTIONS = 8  # tiendas de sus pedidos que la hoja ofrece marcar


def ordered_stores(conn: Connection, user_id: str) -> list[str]:
    """Las tiendas donde la persona ya pidió en «Propuesta» (la más reciente primero, hasta MAX_STORE_OPTIONS), como las
    nombra `find_store`: la marca de la tienda o, sin marca, su nombre. Son las que la hoja ofrece marcar como
    favoritas: así se eligen sin escribirlas."""
    rows = conn.execute(
        """SELECT name FROM (
               SELECT btrim(coalesce(b.name, s.name)) AS name, max(o.ts) AS last
               FROM app_orders o JOIN app_order_lines l USING (order_id)
               JOIN stores s ON s.store_id = l.store_id LEFT JOIN brands b ON b.brand_id = s.brand_id
               WHERE o.user_id = %s AND o.mode = 'propuesta' AND o.status = 'confirmado' AND l.store_id IS NOT NULL
               GROUP BY 1
           ) ordered ORDER BY last DESC, name LIMIT %s""",
        (user_id, MAX_STORE_OPTIONS),
    ).fetchall()
    return [name for (name,) in rows]


def options(stores: Iterable[str] = ()) -> list[dict]:
    """Lo que el panel ofrece marcar: las dietas, las alergias, las cocinas y las tiendas `stores` (las de sus pedidos,
    `ordered_stores`)."""
    found = load_options()
    rules = [(rule.kind, rule.id) for rule in found.rules.values()]
    return describe([*rules, *(("cocina", c) for c in found.cuisines), *(("tienda", s) for s in stores)])


# ── Lo que llega escrito por el buscador ─────────────────────────────────────
@dataclass(frozen=True)
class Command:
    """Lo que pidió la persona sobre sus preferencias: `agregar`, `quitar`, `mostrar` u `olvidar`. `store` es lo que
    dijo de una tienda (se busca en el catálogo al guardar); `cuisine_text`, lo dicho de una cocina (lo lee el
    entendedor con sus conceptos)."""

    action: str
    items: tuple[tuple[str, str], ...] = ()
    store: str | None = None
    cuisine_text: str | None = None


LEADS = re.compile(r"^(?:(?:oye|bueno|ok|hola)\s+)*(?:(?:recuerda que|acuerdate que|anota que|toma nota|yo)\s+)?")
CLEAR = re.compile(
    r"^(?:olvida|olvidate de|borra|borrame|elimina|quita|limpia|resetea)\s+(?:todas\s+)?(?:mis|las)\s+preferencias\b"
)
SHOW = re.compile(
    r"^(?:(?:muestrame|dime|ensename|ver|revisa|cuales son|que son)\s+)?(?:mis\s+preferencias|que preferencias"
    r"(?:\s+(?:tengo|guardaste|recuerdas))?)\s*$"
)
FAVORITE_CUISINE = re.compile(
    r"^(?:mi|mis)\s+(?:comida|comidas|cocina|cocinas)\s+favoritas?\s+(?:es|son)\s+(.+)$"
    r"|^(?:me gusta|me gustan|me encanta|me encantan)\s+(?:la\s+)?(?:comida|cocina)\s+(.+)$"
    r"|^(?:agrega|anota|suma)\s+(.+?)\s+(?:a|en)\s+mis\s+favorit[oa]s$"
)
FAVORITE_STORE = re.compile(
    r"^(?:mi|mis)\s+(?:tienda|tiendas|super|supermercado|local|restaurante|restaurant)\s+favorit[oa]s?\s+(?:es|son)\s+"
    r"(.+)$|^prefiero\s+(?:pedir|comprar)\s+en\s+(.+)$"
)
ARTICLE = re.compile(r"^(?:el|la|los|las)\s+")
UNSAY = ("soy ", "tengo ", "alergi", "intolerante")  # «ya no soy vegetariano» quita; «ya no como carne» agrega


def read_command(text: str) -> Command | None:
    """La orden sobre las preferencias de un mensaje, o None si no es una. Las frases van al comienzo del mensaje
    (después de «recuerda que», «yo»…): «sushi sin maní» es un pedido, no una alergia."""
    said = normalize(text)
    if CLEAR.match(said):
        return Command("olvidar")
    if SHOW.match(said):
        return Command("mostrar")
    body = LEADS.sub("", said, count=1)
    removing = False
    if body.startswith("ya no "):
        rest = body.removeprefix("ya ")
        unsay = rest.removeprefix("no ")
        removing = unsay.startswith(UNSAY)
        body = unsay if removing else rest
    found = _rules_said(body)
    if found:
        return Command("quitar" if removing else "agregar", tuple((rule.kind, rule.id) for rule in found))
    if removing:
        return None
    if match := FAVORITE_STORE.match(body):
        return Command("agregar", store=ARTICLE.sub("", next(g for g in match.groups() if g)))
    if match := FAVORITE_CUISINE.match(body):
        return Command("agregar", cuisine_text=next(g for g in match.groups() if g))
    return None


def _rules_said(body: str) -> list[Rule]:
    """Las dietas y alergias dichas: la primera al comienzo («soy vegetariano y alérgico al maní» son dos)."""
    rules = load_options().rules.values()
    if not any(body == p or body.startswith(f"{p} ") for rule in rules for p in rule.phrases):
        return []
    return [rule for rule in rules if any(re.search(rf"(?:^|\s){re.escape(p)}(?:\s|$)", body) for p in rule.phrases)]


def _join(items: list[str]) -> str:
    items = list(dict.fromkeys(items))
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} o {items[-1]}"
