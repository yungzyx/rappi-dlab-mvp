"""El motor de los perfiles de gusto (`offers/profiles.py`): qué perfiles tiene una persona (`active_profiles`) y la
escalera de cada uno (`ladder`), sobre el catálogo de prueba (`seed_demo`) más unos productos de estas pruebas: lo que
una escalera nunca debe mostrar."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from psycopg.types.json import Jsonb
from test_query_budget import CountingConnection

from rappi_ia import config
from rappi_ia.agent.tools import search_products
from rappi_ia.concepts.store import refresh_assortment
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.db import connect
from rappi_ia.demo import seed
from rappi_ia.embeddings.base import HashEmbedder
from rappi_ia.embeddings.text_store import embed_search_documents
from rappi_ia.events import store as events
from rappi_ia.layers.segments import build_segments, load_segment_rules
from rappi_ia.offers import profiles as profiles_module
from rappi_ia.offers.guards import alcohol_in_name, unofferable_subverticals
from rappi_ia.offers.profiles import (
    MIN_STEPS,
    REASON_NEUTRAL,
    STEP_PRODUCTS,
    Profile,
    Step,
    active_profiles,
    ladder,
    load_profiles,
    ordered_restaurants,
    person_city,
)

NOW = datetime.now(UTC)
ROLL_CALIFORNIA, ROLL_SALMON, SUSHI_STORE = "98005", "98006", 9802  # los dos rolls del catálogo, del mismo local

# Productos solo de estas pruebas, con un concepto que un peldaño ofrece: el soju (alcohol en «Gaseosas», como en la
# base real), los globos de un sex shop y lo que solo calza una palabra a medias (posavasos) o calza la palabra sin ser
# lo que promete el peldaño (un limpiador «en pasta», un juego de pizza de juguete).
SOJU, CUPS, COASTERS, PIZZA_CUTTER, POT_CLEANER, TOY_PIZZA, SHOP_BALLOONS = (
    93901,
    96901,
    96902,
    96903,
    96904,
    96905,
    96103,
)
PARTY = "Otros Decoración para fiestas"
# fmt: off
EXTRA_PRODUCTS = [
    (SOJU, "Soju uva verde 360 ml (prueba)", "Gaseosas", False, {"turbo": (2990, None)}),
    (CUPS, "Vasos de cartón para fiesta x 10 (prueba)", PARTY, False, {"mall": (1990, None)}),
    (COASTERS, "Posavasos de corcho x 4 (prueba)", PARTY, False, {"mall": (2490, None)}),
    (PIZZA_CUTTER, "Cortador de pizza (prueba)", "Utensilios de Cocina", False, {"mall": (3990, None)}),
    (POT_CLEANER, "Limpia ollas en pasta 500 g (prueba)", "Utensilios de Cocina", False, {"mall": (2990, None)}),
    (TOY_PIZZA, "Juego de pizza de madera Melissa & Doug (prueba)", "Utensilios de Cocina", False,
     {"mall": (19990, None)}),
]
# fmt: on
BALLOONS = (SHOP_BALLOONS, "Globos de colores x 10 (prueba)", "Bombas y Globos", 2990, 2990)
# Dos locales de sushi más: 9809, otro restaurante; 9810, una sucursal de la misma cadena que 9802 (`CHAIN`).
OTHER_SUSHI, CHAIN_BRANCH, CHAIN = 9809, 9810, 9890
EXTRA_RESTAURANTS = [
    ((OTHER_SUSHI, "Sushi de prueba - Providencia"), (["Sushi"], {"Rolls": [(98901, "Roll tempura (prueba)", 7990)]})),
    (
        (CHAIN_BRANCH, "Sushi y hamburguesas de prueba - Ñuñoa"),
        (["Sushi"], {"Rolls": [(98902, "Roll acevichado (prueba)", 8490)]}),
    ),
]
# Una tienda de Turbo que se llama «Licores»: la única que vende este hielo.
LIQUOR_ICE = "Hielo en bolsa 1 kg (prueba)"
LIQUOR_STORE = (9311, "Turbo Licores de prueba", "turbo", None, [(93902, LIQUOR_ICE, "Hielo", 990, 990)])


@pytest.fixture
def catalog(db, monkeypatch):
    """El catálogo de prueba con los productos de estas pruebas, sus embeddings y los conceptos asignados."""
    monkeypatch.setattr(seed, "_PRODUCTS", [*seed._PRODUCTS, *EXTRA_PRODUCTS])
    shops = [(*shop[:4], [*shop[4], BALLOONS]) if shop[3] == "Sex shop" else shop for shop in seed._NOT_PUSHED_STORES]
    monkeypatch.setattr(seed, "_NOT_PUSHED_STORES", (*shops, LIQUOR_STORE))
    restaurants = (*seed._STORES["restaurantes"], *(store for store, _ in EXTRA_RESTAURANTS))
    monkeypatch.setitem(seed._STORES, "restaurantes", restaurants)
    monkeypatch.setattr(seed, "_MENUS", [*seed._MENUS, *(menu for _, menu in EXTRA_RESTAURANTS)])
    monkeypatch.setattr(seed, "_DETAILS", [*seed._DETAILS, *[(4.5, 40, "30 min", 990)] * len(EXTRA_RESTAURANTS)])
    for aisle_id, category in ((2100, PARTY), (2200, "Bombas y Globos")):  # pasillos propios, como los demás
        monkeypatch.setitem(seed._AISLE_OF_CATEGORY, category, (aisle_id, None))
        monkeypatch.setitem(seed._AISLE_NAMES, aisle_id, (category, None))
    seed.seed_demo(db)
    db.execute("INSERT INTO brands (brand_id, name) VALUES (%s, 'Cadena de sushi de prueba')", (CHAIN,))
    db.execute("UPDATE stores SET brand_id = %s WHERE store_id IN (%s, %s)", (CHAIN, SUSHI_STORE, CHAIN_BRANCH))
    embedder = HashEmbedder()
    embed_search_documents(db, embedder)
    # La capa de conceptos ya pasa el soju de «Gaseosas» a licores (assign.py); aquí vuelve a gaseosas, como estaba en
    # la base real, para probar la segunda red: la guardia de ofertas por el nombre.
    soju = "SELECT concept_id FROM item_concepts WHERE entity_type = 'catalog_item' AND entity_id = %s"
    assert db.execute(soju, (str(SOJU),)).fetchone()[0] == "licores"
    db.execute(
        "UPDATE item_concepts SET concept_id = 'gaseosas' WHERE entity_type = 'catalog_item' AND entity_id = %s",
        (str(SOJU),),
    )
    refresh_assortment(db)
    db.commit()
    extra = [str(p) for p in (SOJU, CUPS, COASTERS, PIZZA_CUTTER, POT_CLEANER, TOY_PIZZA, SHOP_BALLOONS)]
    concepts = dict(
        db.execute(
            """SELECT entity_id, concept_id FROM item_concepts
               WHERE entity_type = 'catalog_item' AND entity_id = ANY(%s)""",
            (extra,),
        ).fetchall()
    )
    # Cada uno tiene el concepto de un peldaño: si no sale, es por la regla que se prueba, no por su concepto.
    assert concepts == {
        str(SOJU): "gaseosas",
        str(CUPS): "decoracion",
        str(COASTERS): "decoracion",
        str(PIZZA_CUTTER): "cocina-menaje",
        str(POT_CLEANER): "cocina-menaje",
        str(TOY_PIZZA): "cocina-menaje",
        str(SHOP_BALLOONS): "decoracion",
    }
    return embedder


def _order(db, user, session, entity_type, entity_id, concept, vertical, days_ago=1):
    events.record_order(
        db, user, session, f"c-{session}", vertical,
        [{"entity_type": entity_type, "entity_id": entity_id, "concept_id": concept, "unit_price": 6990}],
        ts=NOW - timedelta(days=days_ago),
    )  # fmt: skip


def _search(db, user, session, concept, query, days_ago=1, source="prototype"):
    event = events.Event(user, session, "search", ts=NOW - timedelta(days=days_ago), concept_id=concept, query=query)
    events.record(db, [event], source=source)


def _sushi_lover(db, user="u-sushi"):
    """Dos pedidos de sushi en el local de los rolls y una búsqueda de ramen, en tres sesiones: el segmento
    `asiatica` (y `japonesa`) en nivel medio."""
    _order(db, user, "s1", "menu_item", ROLL_CALIFORNIA, "sushi", "restaurantes", days_ago=3)
    _order(db, user, "s2", "menu_item", ROLL_SALMON, "sushi", "restaurantes", days_ago=2)
    _search(db, user, "s3", "asiatica", "ramen")
    build_segments(db, "prototype", user, commit=False)
    return user


def _give_segment(db, user, segment_id, level, score=6.0, source="prototype"):
    """Un segmento puesto a mano (sin eventos): para probar niveles y fuentes sin depender de las reglas."""
    events.ensure_user(db, user, source)
    db.execute(
        """INSERT INTO segment_defs (segment_id, name, family, sensitive, rule, rules_version)
           VALUES (%s, %s, 'prueba', false, '{}', 'test') ON CONFLICT DO NOTHING""",
        (segment_id, segment_id),
    )
    db.execute(
        """INSERT INTO user_segments (user_id, segment_id, score, level, signals, evidence)
           VALUES (%s, %s, %s, %s, 3, %s)""",
        (user, segment_id, score, level, Jsonb({"top": []})),
    )


# ── qué perfiles tiene una persona ───────────────────────────────────────────


def test_a_sushi_lover_has_the_asian_profile_and_its_reason_counts_what_they_did(catalog, db):
    user = _sushi_lover(db)
    levels = dict(db.execute("SELECT segment_id, level FROM user_segments WHERE user_id = %s", (user,)).fetchall())
    assert levels.get("asiatica") == "medio"

    [found] = active_profiles(db, user)

    assert (found.profile.id, found.level, found.profile.main) == ("asiatico", "medio", True)
    assert found.reason == "Pediste 🍣 sushi 2 veces, y buscaste 🥡 comida asiática 1 vez."
    assert {"kind": "concepto", "id": "sushi", "score": 2, "source": "pedidos"} in found.basis
    assert {"kind": "concepto", "id": "asiatica", "score": 1, "source": "busquedas"} in found.basis
    # La evidencia de sus segmentos, como en offers/personal.py: el concepto, el peso de su nivel y «segmento:<id>».
    assert {"kind": "concepto", "id": "sushi", "score": 2.0, "source": "segmento:asiatica"} in found.basis
    mine = set(levels) & set(found.profile.segments)
    assert {s["source"] for s in found.basis} == {"pedidos", "busquedas"} | {f"segmento:{seg}" for seg in mine}
    assert {s["kind"] for s in found.basis} == {"concepto"}
    assert found.to_dict() == {
        "id": "asiatico",
        "nombre": "Amante de lo asiático",
        "emoji": "🥢",
        "nivel": "medio",
        "principal": True,
        "por_que": found.reason,
        "basis": list(found.basis),
    }


def test_the_reason_only_counts_the_profile_window(catalog, db):
    user = _sushi_lover(db)
    _order(db, user, "s0", "menu_item", ROLL_CALIFORNIA, "sushi", "restaurantes", days_ago=200)  # fuera de los 120 días

    assert active_profiles(db, user)[0].reason.startswith("Pediste 🍣 sushi 2 veces")


def test_the_reason_counts_proposal_orders_and_searches_only(catalog, db):
    """Ni los pedidos de «Rappi hoy», ni lo que no es una búsqueda (agregar al carro), ni una búsqueda de «Rappi hoy»
    o de hace 200 días."""
    user = _sushi_lover(db)
    events.record_order(
        db, user, "s4", "c-s4", "restaurantes",
        [{"entity_type": "menu_item", "entity_id": ROLL_CALIFORNIA, "unit_price": 6990}], mode="actual",
    )  # fmt: skip
    db.execute(  # aunque la línea traiga concepto, un pedido de «Rappi hoy» no cuenta
        """UPDATE app_order_lines l SET concept_id = 'sushi' FROM app_orders o
           WHERE o.order_id = l.order_id AND o.user_id = %s AND o.mode = 'actual'""",
        (user,),
    )
    later = [
        events.Event(user, "s5", "cart_add", ts=NOW, concept_id="asiatica", cart_id="c5"),
        events.Event(user, "s6", "search", ts=NOW, concept_id="asiatica", query="wok", payload={"mode": "actual"}),
        events.Event(user, "s7", "search", ts=NOW - timedelta(days=200), concept_id="asiatica", query="wok"),
    ]
    events.record(db, later)

    assert active_profiles(db, user)[0].reason == "Pediste 🍣 sushi 2 veces, y buscaste 🥡 comida asiática 1 vez."


def test_each_profile_counts_its_reason_in_the_window_of_its_own_segments(catalog, db, monkeypatch):
    version, rules = load_segment_rules()
    short = [replace(rule, window_days=30) if rule.id == "cafetero" else rule for rule in rules]
    monkeypatch.setattr(profiles_module, "load_segment_rules", lambda: (version, short))
    _give_segment(db, "u1", "cafetero", "medio")
    _give_segment(db, "u1", "sushi", "medio")
    _order(db, "u1", "s1", "catalog_item", "91004", "cafe", "supermercado", days_ago=10)
    _order(db, "u1", "s2", "catalog_item", "91004", "cafe", "supermercado", days_ago=60)  # fuera de sus 30 días
    _order(db, "u1", "s3", "menu_item", ROLL_SALMON, "sushi", "restaurantes", days_ago=60)

    reasons = {p.profile.id: p.reason for p in active_profiles(db, "u1")}

    assert reasons == {"asiatico": "Pediste 🍣 sushi 1 vez.", "cafe": "Pediste ☕ café 1 vez."}


def test_a_low_level_a_synthetic_person_or_no_segments_has_no_profile(catalog, db):
    _give_segment(db, "u-bajo", "sushi", "bajo")
    _give_segment(db, "u-sim", "sushi", "alto", source="synthetic")
    events.ensure_user(db, "u-sin-segmentos")
    _search(db, "u-sin-segmentos", "s1", "sushi", "sushi")

    for user in ("u-bajo", "u-sim", "u-sin-segmentos", "nadie", None):
        assert active_profiles(db, user) == [], user


def test_a_sensitive_segment_never_makes_a_profile(catalog, db):
    _give_segment(db, "u1", "sushi", "alto")
    db.execute("UPDATE segment_defs SET sensitive = true WHERE segment_id = 'sushi'")

    assert active_profiles(db, "u1") == []


def test_forgetting_removes_the_profile(catalog, db):
    user = _sushi_lover(db)
    assert [p.profile.id for p in active_profiles(db, user)] == ["asiatico"]

    events.forget(db, user, "sushi")  # sin los pedidos de sushi, sus segmentos se recalculan sin perfil
    assert active_profiles(db, user) == []

    _sushi_lover(db, "u-otra")
    events.forget(db, "u-otra")  # olvidar a la persona entera
    assert active_profiles(db, "u-otra") == []


def test_the_main_profile_goes_first_then_by_score(catalog, db):
    _give_segment(db, "u1", "cafetero", "alto", score=30.0)
    _give_segment(db, "u1", "tiene-perro", "medio", score=6.0)
    _give_segment(db, "u1", "pizzero", "medio", score=9.0)
    _give_segment(db, "u1", "sushi", "medio", score=5.0)
    _give_segment(db, "u1", "china", "bajo", score=2.0)

    found = active_profiles(db, "u1")

    assert [(p.profile.id, p.level, p.score) for p in found] == [
        ("asiatico", "medio", 7.0),  # el nivel es el mayor de sus segmentos y el puntaje, la suma
        ("cafe", "alto", 30.0),
        ("italiano", "medio", 9.0),
        ("mascotas", "medio", 6.0),
    ]
    assert all(p.reason == REASON_NEUTRAL for p in found)  # sin pedidos ni búsquedas que contar


def test_the_party_reason_never_names_alcohol(catalog, db):
    """`fiestero` se activa con cócteles y espumante: el «por qué» del carrete cuenta solo lo que se puede ofrecer."""
    user = "u-fiesta"
    _order(db, user, "s1", "catalog_item", "94008", "espumante", "licores", days_ago=3)
    _order(db, user, "s2", "catalog_item", "94008", "espumante", "licores", days_ago=2)
    _search(db, user, "s3", "cocteles", "mojito")
    build_segments(db, "prototype", user, commit=False)

    [party] = active_profiles(db, user)
    assert party.profile.id == "carrete"
    assert party.reason == REASON_NEUTRAL
    assert [s for s in party.basis if s["kind"] == "concepto"] == []

    _order(db, user, "s4", "catalog_item", "93002", "hielo", "turbo")
    build_segments(db, "prototype", user, commit=False)

    [party] = active_profiles(db, user)
    assert party.reason == "Pediste 🧊 hielo 1 vez."
    assert {s["id"] for s in party.basis if s["kind"] == "concepto"} == {"hielo"}
    adult = {c.id for c in load_taxonomy().concepts.values() if c.age_restricted}
    named = {s["id"] for s in party.basis}
    assert not named & adult and not any(word in party.reason.lower() for word in ("espumante", "cóctel", "mojito"))


# ── la escalera ──────────────────────────────────────────────────────────────


def _names(steps):
    return {p.name for step in steps for p in step.products}


def test_the_asian_ladder_on_the_test_catalog(catalog, db):
    steps = ladder(db, catalog, load_profiles()["asiatico"])

    assert [s.step.vertical for s in steps] == ["restaurantes", "turbo", "conveniencia", "supermercado", "chocolateria"]
    for step in steps:
        assert 1 <= len(step.products) <= STEP_PRODUCTS, step.step.vertical
        assert all(p.concept in step.step.concepts and p.vertical == step.step.vertical for p in step.products)
        assert len({p.name for p in step.products}) == len(step.products)  # sin repetir nombres
    assert [p.name for p in steps[-1].products] == ["Chocolate blanco con matcha 100 g (prueba)"]
    # Un plato por local: el peldaño ofrece lugares que no conoce.
    restaurants = steps[0].products
    assert len({p.store_id for p in restaurants}) == len(restaurants)
    assert steps[0].to_dict()["vertical"] == "restaurantes"
    assert set(steps[0].to_dict()) == {"vertical", "prototype_vertical", "texto", "products"}


def test_a_ladder_skips_empty_steps_and_needs_two(catalog, db):
    sushi = Step("restaurantes", ("sushi",), "Sushi")
    nothing = Step("turbo", ("alimento-gato",), "Nada por aquí")  # el catálogo de prueba no vende comida de gato
    ice = Step("turbo", ("hielo",), "Hielo")
    profile = Profile("prueba", "Prueba", "🧪", False, ("sushi",), "medio", (sushi, nothing, ice))

    steps = ladder(db, catalog, profile)
    assert [s.step for s in steps] == [sushi, ice]

    lonely = Profile("prueba", "Prueba", "🧪", False, ("sushi",), "medio", (sushi, nothing))
    assert MIN_STEPS == 2
    assert ladder(db, catalog, lonely) == []  # con menos de dos peldaños no hay escalera


def test_the_restaurants_step_leaves_out_places_already_ordered_from(catalog, db):
    user = _sushi_lover(db)
    assert ordered_restaurants(db, user) == {SUSHI_STORE}
    assert ordered_restaurants(db, None) == set()
    asian = load_profiles()["asiatico"]

    with_sushi = ladder(db, catalog, asian)
    assert with_sushi[0].step.vertical == "restaurantes"
    # Un plato por cadena: 9802 y 9810 son la misma.
    stores = [p.store_id for p in with_sushi[0].products]
    assert len(stores) == 2 and OTHER_SUSHI in stores and len({SUSHI_STORE, CHAIN_BRANCH} & set(stores)) == 1

    steps = ladder(db, catalog, asian, exclude_stores=ordered_restaurants(db, user))
    # Sin el local donde pidió ni la otra sucursal de su cadena; el otro restaurante de sushi sigue.
    assert steps[0].step.vertical == "restaurantes"
    assert [p.store_id for p in steps[0].products] == [OTHER_SUSHI]
    assert len(steps) >= MIN_STEPS


def test_the_ladder_searched_in_parallel_is_the_same_as_in_series(catalog, db, test_url):
    """Con conexiones extra (`spare`, las del pool en `/agent/offer`), los peldaños se buscan a la vez, cada uno en su
    conexión, y la escalera es la misma que en serie: los mismos peldaños, productos y orden, también sin repetir un
    nombre entre peldaños y sin los locales donde la persona ya pidió (eso se decide después, en orden). Si no sobra
    ninguna (None), en serie con la del request."""
    user = _sushi_lover(db)
    db.commit()
    lent = []

    @contextmanager
    def spare():
        with connect(test_url) as conn:
            lent.append(conn)
            yield conn

    @contextmanager
    def none_free():
        yield None

    cases = [(profile, {}) for profile in load_profiles().values()]
    cases.append((load_profiles()["asiatico"], {"exclude_stores": ordered_restaurants(db, user)}))
    with_steps = 0
    for profile, options in cases:
        serial = [step.to_dict() for step in ladder(db, catalog, profile, **options)]
        for connector in (spare, none_free):
            parallel = ladder(db, catalog, profile, **options, spare=connector)
            assert [step.to_dict() for step in parallel] == serial, (profile.id, options, connector.__name__)
        with_steps += bool(serial)
    assert with_steps >= 4  # no se comparan escaleras vacías
    assert lent  # sí buscó en otras conexiones


def test_the_restaurants_step_only_shows_places_in_the_city(catalog, db, monkeypatch):
    """Un restaurante guarda su comuna (`stores.city`). Sin ciudad, la escalera usa PROFILE_CITY (Santiago de Chile):
    sale la cadena de Maipú y no el local de Viña del Mar (en la base real salían Viña, Copiapó y Chillán). Con otra
    ciudad, solo los de ahí."""
    db.execute("UPDATE stores SET city = 'Viña del Mar' WHERE store_id = %s", (OTHER_SUSHI,))
    db.execute("UPDATE stores SET city = 'Maipú' WHERE store_id IN (%s, %s)", (SUSHI_STORE, CHAIN_BRANCH))
    asian = load_profiles()["asiatico"]

    def places(**city):
        steps = ladder(db, catalog, asian, **city)
        assert steps[0].step.vertical == "restaurantes"
        return {p.store_id for p in steps[0].products}

    assert len(places()) == 1 and places() <= {SUSHI_STORE, CHAIN_BRANCH}  # la cadena, una vez
    assert places(city="Viña del Mar") == {OTHER_SUSHI}
    monkeypatch.setattr(config, "PROFILE_CITY", "Viña del Mar")
    assert places() == {OTHER_SUSHI}


def test_the_city_of_a_ladder_is_the_person_one_or_the_default(catalog, db):
    """La de la persona del prototipo (`app_users.city`); sin ella (la app no la pide), de otra fuente o sin persona,
    PROFILE_CITY."""
    events.ensure_user(db, "u-vina")
    events.ensure_user(db, "u-sin-ciudad")
    events.ensure_user(db, "u-sim", "synthetic", city="Valparaíso")
    db.execute("UPDATE app_users SET city = 'Viña del Mar' WHERE user_id = 'u-vina'")

    assert person_city(db, "u-vina") == "Viña del Mar"
    for user in ("u-sin-ciudad", "u-sim", "nadie", None):
        assert person_city(db, user) == config.PROFILE_CITY == "Santiago de Chile", user


def test_step_words_match_the_start_of_a_word_and_avoid_what_the_step_does_not_promise(catalog, db):
    profiles = load_profiles()
    party = {s.step.vertical: s for s in ladder(db, catalog, profiles["carrete"])}
    italian = {s.step.vertical: s for s in ladder(db, catalog, profiles["italiano"])}

    assert [p.name for p in party["mall"].products] == ["Vasos de cartón para fiesta x 10 (prueba)"]
    assert [p.name for p in italian["mall"].products] == ["Cortador de pizza (prueba)"]


def test_a_ladder_never_offers_from_a_liquor_store(catalog, db):
    """«Turbo Licores» vende hielo, y una oferta común lo puede traer; una escalera de perfil no lo trae de ahí."""
    assert LIQUOR_ICE in {
        p.name for p in search_products(db, "turbo", "hielo", ["hielo"], catalog, offer=True).products
    }

    party = ladder(db, catalog, load_profiles()["carrete"])

    assert party[0].step.vertical == "turbo"
    assert LIQUOR_ICE not in {p.name for s in party for p in s.products}
    assert not [p.store for s in party for p in s.products if "licor" in (p.store or "").lower()]


def test_no_ladder_offers_adult_products_or_products_from_blocked_stores(catalog, db):
    blocked = {
        store_id
        for (store_id,) in db.execute(
            "SELECT store_id FROM store_verticals WHERE subvertical = ANY(%s)", (unofferable_subverticals(),)
        )
    }
    # Sin las guardias, la búsqueda sí los encuentra: el soju es una gaseosa y los globos, decoración.
    assert "Soju uva verde 360 ml (prueba)" in {
        p.name for p in search_products(db, "turbo", "soju", ["gaseosas"], catalog).products
    }
    assert "Globos de colores x 10 (prueba)" in {
        p.name for p in search_products(db, "mall", "globos", ["decoracion"], catalog).products
    }

    ladders = {profile.id: ladder(db, catalog, profile) for profile in load_profiles().values()}
    offered = [p for steps in ladders.values() for s in steps for p in s.products]

    assert offered
    for profile_id, steps in ladders.items():
        assert all(1 <= len(s.products) <= STEP_PRODUCTS for s in steps), profile_id
        names = [p.name for s in steps for p in s.products]
        assert len(set(names)) == len(names), profile_id  # ni repetido entre peldaños (las papas del súper y Express)
    assert alcohol_in_name("menu_item", "Roll tempura (prueba)", "sushi") is False
    adult = {c.id for c in load_taxonomy().concepts.values() if c.age_restricted}
    assert not [p.name for p in offered if p.age_restricted or p.concept in adult]
    assert not [p.name for p in offered if alcohol_in_name(p.entity_type, p.name, p.concept)]
    assert not [p.name for p in offered if p.store_id in blocked]
    assert not {"Soju uva verde 360 ml (prueba)", "Globos de colores x 10 (prueba)"} & {p.name for p in offered}


# Con la caché del catálogo caliente, un peldaño cuesta unas 10 consultas: su búsqueda de oferta y una por sus tiendas
# (50 en los cinco del asiático).
LADDER_QUERY_BUDGET = 10 * 5


def test_a_ladder_costs_a_bounded_number_of_queries(catalog, db):
    asian = load_profiles()["asiatico"]
    ladder(db, catalog, asian)  # llena la caché del catálogo (conteos, lexemas y df)
    counting = CountingConnection(db)

    ladder(counting, catalog, asian)

    assert len(counting.statements) <= LADDER_QUERY_BUDGET, f"{len(counting.statements)} consultas"
