"""Métricas del panel: valores exactos en un escenario armado a mano e invariantes sobre datos simulados."""

from datetime import UTC, date, datetime, timedelta

import pytest
from rappi_scraper.storage.search import build_search_documents

from conftest import add_dish, add_price, add_product, add_store
from rappi_ia.agent.tools import suggest_complement
from rappi_ia.agent.verticals import ranked_verticals
from rappi_ia.analytics import queries
from rappi_ia.concepts.pipeline import build_concepts
from rappi_ia.concepts.store import seed_taxonomy
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.demo.seed import seed_demo
from rappi_ia.events import store as events
from rappi_ia.events.synth import generate

T0 = datetime(2026, 9, 1, 12, tzinfo=UTC)


def _order(db, user, day, vertical="licores", concept="cerveza", cart=None, source="prototype"):
    events.record_order(
        db,
        user,
        f"s-{day}",
        cart or f"c-{user}-{day}",
        vertical,
        [{"entity_type": "catalog_item", "entity_id": "1", "concept_id": concept, "unit_price": 1000}],
        source=source,
        ts=T0 + timedelta(days=day),
    )


def test_kpis_rhythm_risk_and_cart_abandonment_are_exact(db):
    seed_taxonomy(db, load_taxonomy())
    # u1 pide cada 7 días y dejó de pedir (ritmo 7 → en riesgo pasado máx(14, 21) = 21 días).
    for day in (0, 7, 14):
        _order(db, "u1", day)
    # u2 pide en dos verticales; u3 un solo pedido (sin segunda compra).
    _order(db, "u2", 30, "licores")
    _order(db, "u2", 33, "supermercado", "snacks-salados")
    _order(db, "u3", 34)
    # Dos carros: uno pagado (c-u2-30) y otro abandonado hace más de 24 h.
    events.record(
        db,
        [
            events.Event("u2", "s-30", "cart_add", ts=T0 + timedelta(days=30), cart_id="c-u2-30"),
            events.Event("u3", "s-10", "cart_add", ts=T0 + timedelta(days=10), cart_id="c-perdido"),
            events.Event("u3", "s-36", "search", ts=T0 + timedelta(days=36), unmet=True, query="kebab"),
            events.Event("u3", "s-36", "search", ts=T0 + timedelta(days=36), unmet=False, query="cerveza"),
            # Búsqueda local del prototipo: no sabe si Rappi lo tiene (unmet NULL) y no diluye la tasa.
            events.Event("u3", "s-36", "search", ts=T0 + timedelta(days=36), query="pizza"),
        ],
    )
    db.commit()

    k = queries.kpis(db, "prototype")

    assert k["as_of"] == T0 + timedelta(days=36)  # u1 lleva 22 días sin pedir (> 21)
    assert k["abandono_carrito_pct"] == 50.0
    assert k["busquedas_sin_resultado_pct"] == 50.0
    assert k["multi_vertical_pct"] == 33.3  # de u1, u2 y u3 (todos pidieron en 60 días), solo u2 en 2 verticales
    status = dict(
        db.execute(
            "WITH " + queries._RHYTHM.strip() + " SELECT user_id, status FROM risk", {"source": "prototype"}
        ).fetchall()
    )
    assert status["u1"] == "en_riesgo" and status["u3"] == "sin_segunda_compra"
    assert queries.kpis(db, "synthetic")["usuarios_activos"] == 0  # las fuentes no se mezclan


def test_a_cart_split_in_two_verticals_is_one_purchase(db, monkeypatch):
    """Pizza más bebidas de Licores son dos pedidos de un mismo carro, pero una sola compra: quien no volvió en 50
    días sigue «sin segunda compra», no «perdido». En la retención multi-vertical cuenta como 1 compra."""
    seed_taxonomy(db, load_taxonomy())
    _order(db, "u1", 0, "restaurantes", "pizza", cart="c-1")
    _order(db, "u1", 0, "licores", "cerveza", cart="c-1")
    _order(db, "u2", 0, "restaurantes", "pizza", cart="c-2")
    _order(db, "u2", 0, "licores", "cerveza", cart="c-2")
    _order(db, "u2", 10, "licores", "cerveza")  # 3 pedidos, 2 compras
    events.record(db, [events.Event("u3", "s", "app_open", ts=T0 + timedelta(days=50))])
    db.commit()

    status = dict(
        db.execute(
            "WITH " + queries._RHYTHM.strip() + " SELECT user_id, status FROM risk", {"source": "prototype"}
        ).fetchall()
    )
    assert status["u1"] == "sin_segunda_compra"
    assert [r["estado"] for r in queries.at_risk(db, "prototype")] == ["en_riesgo"]  # solo u2 (ritmo 10 días)
    k = queries.kpis(db, "prototype")
    assert (k["en_riesgo"], k["perdidos"]) == (1, 0)

    events.record(db, [events.Event("u3", "s", "app_open", ts=T0 + timedelta(days=130))])
    monkeypatch.setattr(queries, "MIN_GROUP_USERS", 1)
    strata = {r["estrato"] for r in queries.multi_vertical_retention(db, "prototype")}
    assert strata == {"1–2 compras"}  # u2 hizo 3 pedidos: el estrato dice lo que cuenta


def test_purged_searches_without_concept_do_not_become_a_null_opportunity(db):
    """La purga de 90 días borra el texto: sin concepto ni consulta no hay nada que mostrar (antes, fila «null»)."""
    seed_taxonomy(db, load_taxonomy())
    events.record(
        db,
        [
            events.Event(f"u{i}", f"s{i}", "search", ts=T0, vertical="licores", unmet=True, query="kombucha")
            for i in range(5)
        ],
    )
    events.purge_old_queries(db, days=1)
    db.commit()

    assert queries.opportunities(db, "prototype") == []


def test_where_it_exists_follows_the_rule_the_agent_uses(db):
    """El panel no pide que Mochi ofrezca algo donde Mochi no lo haría: 3 «comidas peruanas» en farmacia (un
    laxante mal etiquetado) no son oferta, y la cerveza no se busca en restaurantes porque no se pide hecha."""
    seed_taxonomy(db, load_taxonomy())
    db.execute("DROP MATERIALIZED VIEW concept_assortment")
    db.execute("CREATE TABLE concept_assortment (concept_id text, vertical text, items integer)")
    with db.cursor() as cur:
        cur.executemany(
            "INSERT INTO concept_assortment VALUES (%s, %s, %s)",
            [
                ("peruana", "restaurantes", 1727),
                ("peruana", "farmacia", 3),
                ("peruana", "supermercado", 3),
                ("cerveza", "restaurantes", 931),
                ("cerveza", "supermercado", 262),
                ("cerveza", "farmacia", 1),
            ],
        )
    events.record(
        db,
        [
            events.Event(f"u{i}", f"s{i}", "search", ts=T0, vertical=vertical, concept_id=concept, unmet=True)
            for i in range(5)
            for vertical, concept in [("restaurantes", "peruana"), ("licores", "cerveza")]
        ],
    )
    db.commit()

    rows = {r["concept_id"]: r for r in queries.opportunities(db, "prototype")}

    assert rows["peruana"]["existe_en"] is None
    assert rows["peruana"]["accion"] == "Oportunidad: sumar comercios o categoría"
    assert rows["cerveza"]["existe_en"] == "supermercado"
    assert rows["cerveza"]["accion"] == "Existe en otro vertical: que el agente lo ofrezca ahí"


def test_cart_abandonment_follows_the_definition(db):
    """§5: carros con productos; abandonado si su último evento de carro (agregar, quitar, pagar) fue hace > 24 h
    y no tiene pedido; una vez por carro, en la semana de su último evento."""
    seed_taxonomy(db, load_taxonomy())
    _order(db, "u1", 30, cart="c-pagado")
    day = lambda d: T0 + timedelta(days=d)  # noqa: E731
    events.record(
        db,
        [
            events.Event("u1", "s", "cart_add", ts=day(30), cart_id="c-pagado"),
            events.Event("u2", "s", "cart_add", ts=day(10), cart_id="c-perdido"),
            events.Event("u3", "s", "cart_add", ts=day(10), cart_id="c-vaciado"),  # lo vació: no es un carro
            events.Event("u3", "s", "cart_remove", ts=day(10), cart_id="c-vaciado"),
            events.Event("u4", "s", "cart_add", ts=day(5), cart_id="c-pagando"),  # fue a pagar hace < 24 h
            events.Event("u4", "s", "checkout_start", ts=day(35.9), cart_id="c-pagando"),
            events.Event("u6", "s", "cart_add", ts=day(10), cart_id="c-vaciado-de-una"),  # "Vaciar carro": 1 evento
            events.Event("u6", "s", "cart_add", ts=day(10), cart_id="c-vaciado-de-una"),
            events.Event("u6", "s", "cart_remove", ts=day(10), cart_id="c-vaciado-de-una", payload={"qty": 2}),
            events.Event("u7", "s", "cart_add", ts=day(10), cart_id="c-qty-rara", payload={"qty": "muchas"}),
            events.Event("u5", "s", "cart_add", ts=day(35.95), cart_id="c-reciente"),
            events.Event("u5", "s", "search", ts=day(36), query="x"),
        ],
    )
    db.commit()

    # c-perdido y c-qty-rara (qty no numérica = 1 unidad) de 5 carros con productos
    assert queries.kpis(db, "prototype")["abandono_carrito_pct"] == 40.0
    weekly = {r["semana"]: r["abandono_carrito_pct"] for r in queries.weekly(db, "prototype")}
    assert weekly[date(2026, 8, 31)] is None  # c-pagando cuenta en su última semana, no en la de su primer evento
    assert weekly[date(2026, 9, 7)] == 100.0  # c-perdido y c-qty-rara (los vaciados no cuentan)


def test_same_pair_can_be_learned_from_both_sources(db, monkeypatch):
    seed_taxonomy(db, load_taxonomy())
    db.execute(
        """INSERT INTO concept_edges (from_concept, to_concept, method, weight, support, data_source)
           VALUES ('cerveza', 'snacks-salados', 'coocurrencia', 0.5, 40, 'synthetic')"""
    )
    for user, concepts in [("u1", ["cerveza", "snacks-salados"]), ("u2", ["cerveza", "snacks-salados"])]:
        for i, concept in enumerate(concepts):
            _order(db, user, i, concept=concept)
    _order(db, "u3", 0, concept="lacteos")
    monkeypatch.setattr(queries, "MIN_SUPPORT", 1)

    assert queries.learn_edges(db, "prototype") >= 1  # antes: UniqueViolation con la arista simulada
    sources = db.execute(
        """SELECT data_source FROM concept_edges
           WHERE from_concept = 'cerveza' AND to_concept = 'snacks-salados' ORDER BY 1"""
    ).fetchall()
    assert sources == [("prototype",), ("synthetic",)]


def test_catalog_coverage_compares_the_same_stores_and_units(db):
    add_store(db, 1, "licores", "Botillería con pasillos")
    add_store(db, 2, "licores", "Botillería sin pasillos")
    db.execute(
        """INSERT INTO aisles (store_id, aisle_id, parent_aisle_id, name, product_count_declared)
           VALUES (1, 1, NULL, 'Cervezas', 4)"""
    )
    for pid in range(2):
        add_product(db, 100 + pid, f"Cerveza {pid}", 1)
    for pid in range(5):
        add_product(db, 200 + pid, f"Vino {pid}", 2)  # tienda sin pasillos declarados: fuera de la cobertura
    db.commit()

    [licores] = queries.catalog_health(db)["cobertura"]
    assert (licores["tiendas"], licores["declarados"], licores["obtenidos"]) == (1, 4, 2)


def test_nudge_taps_are_not_mixed_with_suggestions_added_to_the_cart(db, monkeypatch):
    """En el aviso "aceptar" es abrir el chat; en el chat y en "Para ti" es agregar al carro."""
    seed_taxonomy(db, load_taxonomy())
    at = T0 + timedelta(days=1)
    rows = [("suggestion_shown", "aviso")] * 10 + [("suggestion_accepted", "aviso")] * 8
    rows += [("suggestion_shown", "chat")] * 6 + [("suggestion_shown", "para-ti")] * 4
    rows += [("suggestion_accepted", "chat")] * 3
    events.record(
        db,
        [
            events.Event(
                "u1", "s", t, ts=at, concept_id="snacks-salados", vertical="supermercado", payload={"origen": origin}
            )
            for t, origin in rows
        ],
    )
    db.commit()
    [row] = queries.suggestions(db, "prototype")
    assert (row["mostradas"], row["aceptadas"], row["aceptacion_pct"]) == (10, 3, 30.0)


def test_prototype_suggestions_show_from_the_first_one_without_a_rate_on_a_small_sample(db):
    """En una demo en vivo el panel debe mostrar la sugerencia recién vista; el % recién con 10 mostradas.
    Los datos simulados mantienen el mínimo de 10 para aparecer."""
    seed_taxonomy(db, load_taxonomy())
    at = T0 + timedelta(days=1)

    def shown(user, n, accepted=0):
        rows = [("suggestion_shown", n), ("suggestion_accepted", accepted)]
        return [
            events.Event(user, "s", t, ts=at, concept_id="gaseosas", vertical="licores", payload={"origen": "chat"})
            for t, count in rows
            for _ in range(count)
        ]

    events.record(db, shown("u1", 2, accepted=1), source="prototype")
    events.record(db, shown("u2", 3), source="synthetic")
    db.commit()
    [row] = queries.suggestions(db, "prototype")
    assert (row["mostradas"], row["aceptadas"], row["aceptacion_pct"]) == (2, 1, None)
    assert queries.suggestions(db, "synthetic") == []


def test_cohorts_stop_at_the_last_finished_week(db, monkeypatch):
    """La semana en curso no es 0% de retención: queda fuera (celda vacía en el panel)."""
    monkeypatch.setattr(queries, "MIN_GROUP_USERS", 1)
    seed_taxonomy(db, load_taxonomy())
    _order(db, "u1", 0)  # martes 01-09: cohorte del lunes 31-08
    _order(db, "u1", 3)
    monday = datetime(2026, 9, 7, 8, tzinfo=UTC)  # corte: lunes 07-09 a las 8 (semana 1 recién empieza)
    events.record(db, [events.Event("u1", "s", "app_open", ts=monday)])
    db.commit()
    assert [(r["semana"], r["retencion_pct"]) for r in queries.cohorts(db, "prototype")] == [(0, 100.0)]


def test_funnel_counts_orders_whose_search_was_in_another_vertical(db):
    """La sugerencia cruzada lleva la compra a otra vertical: buscar en restaurantes y pedir en licores es un pedido
    de licores. Navegar sin chatear (view_store, que el prototipo manda sin vertical) también es entrada; ver una
    sugerencia sin aceptarla no mete a la sesión en el embudo de esa vertical."""
    seed_taxonomy(db, load_taxonomy())
    line = [{"entity_type": "catalog_item", "entity_id": "1", "concept_id": "cerveza", "unit_price": 1000}]
    events.record(
        db,
        [
            events.Event("u1", "s1", "chat", ts=T0, vertical="restaurantes", query="pizza"),
            events.Event("u1", "s1", "suggestion_shown", ts=T0, vertical="turbo", concept_id="gaseosas"),
            events.Event("u1", "s1", "cart_add", ts=T0, vertical="licores", cart_id="c1"),
            events.Event("u1", "s1", "checkout_start", ts=T0, vertical="licores", cart_id="c1"),
            events.Event("u2", "s2", "view_store", ts=T0),
            events.Event("u2", "s2", "cart_add", ts=T0, vertical="supermercado", cart_id="c2"),
            events.Event("u2", "s2", "checkout_start", ts=T0, vertical="supermercado", cart_id="c2"),
        ],
    )
    events.record_order(db, "u1", "s1", "c1", "licores", line, ts=T0)
    events.record_order(db, "u2", "s2", "c2", "supermercado", line, ts=T0)
    db.commit()

    funnel = {r["vertical"]: r for r in queries.funnel(db, "prototype")}

    assert funnel["licores"] == {"vertical": "licores", "buscan": 1, "agregan": 1, "pagan": 1, "piden": 1}
    assert funnel["supermercado"]["piden"] == 1
    assert funnel["restaurantes"]["buscan"] == 1 and funnel["restaurantes"]["agregan"] == 0
    assert "turbo" not in funnel
    orders = db.execute("SELECT count(*) FROM app_orders WHERE source = 'prototype'").fetchone()[0]
    assert sum(r["piden"] for r in funnel.values()) == orders


def test_adding_from_a_list_without_searching_also_enters_the_funnel(db):
    """El «+» de una lista (la pantalla de una vertical, Ofertas, «Para ti») solo manda cart_add: quien entra a
    Súper desde la Home, agrega una cerveza y paga sin buscar ni chatear también llega a la vertical."""
    seed_taxonomy(db, load_taxonomy())
    line = [{"entity_type": "catalog_item", "entity_id": "1", "concept_id": "cerveza", "unit_price": 1000}]
    events.record(
        db,
        [
            events.Event("u1", "s1", "app_open", ts=T0),
            events.Event("u1", "s1", "cart_add", ts=T0, vertical="supermercado", cart_id="c1"),
            events.Event("u1", "s1", "checkout_start", ts=T0, vertical="supermercado", cart_id="c1"),
        ],
    )
    events.record_order(db, "u1", "s1", "c1", "supermercado", line, ts=T0)
    db.commit()

    funnel = queries.funnel(db, "prototype")

    assert funnel == [{"vertical": "supermercado", "buscan": 1, "agregan": 1, "pagan": 1, "piden": 1}]
    orders = db.execute("SELECT count(*) FROM app_orders WHERE source = 'prototype'").fetchone()[0]
    assert sum(r["piden"] for r in funnel) == orders


def test_session_conversion_counts_each_session_once(db):
    """Quien acepta una sugerencia cruzada cuenta en dos verticales del embudo: sumar las filas da una tasa por
    (sesión, vertical). El titular usa la de la API, que cuenta cada sesión una vez."""
    seed_taxonomy(db, load_taxonomy())
    line = [{"entity_type": "catalog_item", "entity_id": "1", "concept_id": "cerveza", "unit_price": 1000}]
    events.record(
        db,
        [
            events.Event("u1", "s1", "chat", ts=T0, vertical="restaurantes", query="pizza"),
            events.Event("u1", "s1", "suggestion_accepted", ts=T0, vertical="licores", concept_id="cerveza"),
            events.Event("u1", "s1", "cart_add", ts=T0, vertical="restaurantes", cart_id="c1"),
            events.Event("u1", "s1", "cart_add", ts=T0, vertical="licores", cart_id="c1"),
            events.Event("u1", "s1", "checkout_start", ts=T0, vertical="restaurantes", cart_id="c1"),
            events.Event("u1", "s1", "checkout_start", ts=T0, vertical="licores", cart_id="c1"),
            events.Event("u2", "s2", "chat", ts=T0, vertical="restaurantes", query="sushi"),
        ],
    )
    events.record_order(db, "u1", "s1", "c1", "restaurantes", line, ts=T0)
    events.record_order(db, "u1", "s1", "c1", "licores", line, ts=T0)
    db.commit()

    funnel = queries.funnel(db, "prototype")
    assert (sum(r["piden"] for r in funnel), sum(r["buscan"] for r in funnel)) == (2, 3)  # 66,7 % por vertical
    assert queries.kpis(db, "prototype")["conversion_sesiones_pct"] == 50.0  # 1 de 2 sesiones
    assert queries.kpis(db, "synthetic")["conversion_sesiones_pct"] is None


def test_invalid_source_is_rejected(db):
    with pytest.raises(ValueError):
        queries.kpis(db, "real")


def _simulated_catalog(db):
    add_store(db, 1, "supermercado", "Súper")
    add_store(db, 2, "licores", "Botillería")
    add_store(db, 3, "conveniencia", "Express")
    rows = [(100 + i, f"Papas fritas marca {i} 180 g", 1, "Snacks salados", 1990) for i in range(5)]
    rows += [(200 + i, f"Cerveza marca {i} lata 470 cc", 2, "Cervezas", 1290) for i in range(5)]
    rows += [(300 + i, f"Cerveza marca {i} express", 3, "Cervezas", 1390) for i in range(5)]
    rows += [(400 + i, f"Leche entera marca {i} 1 L", 1, "Leche natural", 1090) for i in range(5)]
    for pid, name, store, category, price in rows:
        add_product(db, pid, name, store, category)
        add_price(db, store, pid, price)
    # Una pizzería: dos de cada tres simulados piden solo en Restaurantes (la mezcla de Rappi).
    add_store(db, 4, "restaurantes", "Pizzería")
    db.execute("INSERT INTO scrape_runs (run_id, kind, status) VALUES (999, 'restaurants', 'done')")
    dishes = [(600 + i, f"Pizza napolitana {i}", "Pizzas") for i in range(3)]
    dishes += [(610 + i, f"Hamburguesa clásica {i}", "Hamburguesas") for i in range(3)]
    for item_id, name, section in dishes:
        add_dish(db, item_id, name, 4, section)
        db.execute("INSERT INTO menu_price_snapshots (run_id, item_id, price) VALUES (999, %s, 6990)", (item_id,))
    db.commit()
    build_search_documents(db)
    build_concepts(db)
    return db, None


@pytest.fixture
def simulated(db):
    _simulated_catalog(db)
    counts = generate(db, users=120, weeks=20, seed=3, until=date(2026, 9, 27))
    return db, counts


def test_synthetic_data_is_reproducible_and_marked(simulated):
    db, counts = simulated
    assert counts == generate(db, users=120, weeks=20, seed=3, until=date(2026, 9, 27))
    sources = {r[0] for r in db.execute("SELECT DISTINCT source FROM app_events")}
    assert sources == {"synthetic"}


def test_funnel_is_monotonic_and_cohorts_are_percentages(simulated, monkeypatch):
    db, _ = simulated
    funnel = queries.funnel(db, "synthetic")
    for row in funnel:
        assert row["buscan"] >= row["agregan"] >= row["pagan"] >= row["piden"]
    # Cada pedido simulado entra al embudo, también los de la vertical sugerida (antes se perdían).
    orders = db.execute("SELECT count(*) FROM app_orders WHERE source = 'synthetic'").fetchone()[0]
    assert sum(r["piden"] for r in funnel) == orders
    monkeypatch.setattr(queries, "MIN_GROUP_USERS", 1)  # los datos de prueba tienen cohortes chicas
    cohorts = queries.cohorts(db, "synthetic")
    assert all(0 <= r["retencion_pct"] <= 100 for r in cohorts)
    assert cohorts[0]["semana"] == 0 and cohorts[0]["retencion_pct"] == 100.0  # semana 0 = la del primer pedido
    first = [r["semana"] for r in cohorts if r["cohorte"] == cohorts[0]["cohorte"]]
    assert first == list(range(len(first)))  # semanas consecutivas: las de 0% también vienen


def test_some_synthetic_sessions_find_products_and_leave_without_adding(simulated):
    """Solo se iban sin agregar las búsquedas sin resultado: en las verticales sin demanda no satisfecha el embudo
    marcaba exactamente 100 % de «buscan» a «agregan»."""
    db, _ = simulated
    found, left = db.execute(
        """SELECT count(*), count(*) FILTER (WHERE NOT EXISTS (
                      SELECT 1 FROM app_events a WHERE a.session_id = e.session_id AND a.type = 'cart_add'))
           FROM app_events e WHERE e.type IN ('search', 'chat') AND e.results > 0"""
    ).fetchone()
    assert 0 < left < found * 0.3


def test_the_multi_vertical_retention_compares_both_groups_with_the_default_history(db, monkeypatch):
    """Es la hipótesis del proyecto y no se veía: con 20 semanas solo ~130 usuarios tenían 120 días de historia y
    casi todos eran multi-vertical (todas las personas compraban en varias). Ningún estrato tenía los dos grupos.
    Con el catálogo de la demo: los simulados piden sobre todo en Restaurantes y Turbo (la mezcla de Rappi), y el
    catálogo chico de arriba solo tiene Súper, Licores y Express."""
    seed_demo(db)
    monkeypatch.setattr(queries, "MIN_GROUP_USERS", 5)  # catálogo de prueba chico: grupos chicos
    generate(db, seed=3, users=1500, until=date(2026, 9, 27))  # 1.500 personas, como cuando era el valor por defecto
    rows = queries.multi_vertical_retention(db, "synthetic")
    groups = {}
    for row in rows:
        groups.setdefault(row["estrato"], set()).add(row["grupo"])
    assert any(g == {"multi-vertical", "un vertical"} for g in groups.values()), rows


SERVICE_TS = datetime(2026, 9, 27, 12, tzinfo=UTC)


def test_services_count_offers_openings_and_accepted_hooks(db):
    """RappiTravel y RappiFavor no tienen catálogo: su enganche se mide por eventos propios (ofrecido y abierto) y por
    los ganchos del catálogo que se aceptan con su origen."""
    seed_taxonomy(db, load_taxonomy())
    travel = {"servicio": "rappitravel"}
    events.record(
        db,
        [
            events.Event("u1", "s1", "service_shown", ts=SERVICE_TS, payload=travel),
            events.Event("u1", "s1", "service_opened", ts=SERVICE_TS, payload=travel),
            events.Event("u2", "s2", "service_shown", ts=SERVICE_TS, payload=travel),
            events.Event(
                "u1",
                "s1",
                "suggestion_shown",
                ts=SERVICE_TS,
                concept_id="dermocosmetica",
                vertical="farmacia",
                payload={"origen": "rappitravel"},
            ),
            events.Event(
                "u1",
                "s1",
                "suggestion_accepted",
                ts=SERVICE_TS,
                concept_id="dermocosmetica",
                vertical="farmacia",
                payload={"origen": "rappitravel"},
            ),
            events.Event("u3", "s3", "service_shown", ts=SERVICE_TS, payload={"servicio": "rappifavor"}),
            # Abrirlo desde un acceso de la Home no mide al agente: se cuenta aparte.
            events.Event("u4", "s4", "service_opened", ts=SERVICE_TS, payload={**travel, "desde": "home"}),
            events.Event(
                "u3", "s3", "service_opened", ts=SERVICE_TS, payload={"servicio": "rappifavor", "desde": "home"}
            ),
        ],
        source="prototype",
    )
    rows = {r["servicio"]: r for r in queries.services(db, "prototype")}
    assert rows["rappitravel"] == {
        "servicio": "rappitravel",
        "nombre": "✈️ RappiTravel",
        "ofrecido": 2,
        "abierto": 1,
        "desde_home": 1,
        "ganchos_mostrados": 1,
        "ganchos_aceptados": 1,
    }
    favor = rows["rappifavor"]
    assert (favor["ofrecido"], favor["abierto"], favor["desde_home"]) == (1, 0, 1)


def test_synthetic_sessions_also_use_the_services(simulated):
    """Sin eventos de servicios, la fila de RappiTravel y RappiFavor del panel quedaba en cero con datos simulados."""
    db, _ = simulated
    rows = {r["servicio"]: r for r in queries.services(db, "synthetic")}
    travel, favor = rows["rappitravel"], rows["rappifavor"]
    assert travel["ofrecido"] > travel["abierto"] > 0
    assert travel["ganchos_mostrados"] == 0  # su gancho es de Farmacia: el agente no lo ofrece por su cuenta
    assert favor["ofrecido"] > favor["abierto"] > 0  # se ofrece cuando no encuentran lo que buscan


def test_synthetic_carts_are_also_abandoned_after_starting_payment(simulated):
    """El inicio de pago se emitía solo junto con el pedido, así que «pagan» era siempre igual a «piden». Ahora una
    parte de los carros abandonados alcanza a iniciar el pago, y el resto se va antes."""
    db, _ = simulated
    carts = dict(
        db.execute(
            """SELECT type, count(DISTINCT cart_id) FROM app_events
               WHERE type IN ('cart_add', 'checkout_start', 'order_placed') GROUP BY 1"""
        ).fetchall()
    )
    assert carts["cart_add"] > carts["checkout_start"] > carts["order_placed"]


def test_synthetic_suggestions_go_to_the_vertical_the_agent_would_choose(db):
    """El generador sorteaba la vertical entre todas las que tienen 1 ítem del concepto: «Cerveza · Farmacia»
    encabezaba la tabla de sugerencias. Ahora usa el orden de Mochi (`ranked_verticals`) y sus guardias de ofertas:
    la cerveza (el primer complemento de la pizza y de las papas) nunca se sugiere."""
    for store_id, vertical in [(2, "supermercado"), (3, "conveniencia"), (4, "farmacia"), (5, "mall"), (7, "licores")]:
        add_store(db, store_id, vertical, vertical.title())
    add_store(db, 6, "restaurantes", "Pizzería")
    rows = [(200 + i, f"Gaseosa cola marca {i} 1,5 L", 2, "Gaseosas") for i in range(25)]
    rows += [(300 + i, f"Gaseosa cola marca {i} express", 3, "Gaseosas") for i in range(5)]
    rows += [(350 + i, f"Papas fritas marca {i} 180 g", 3, "Snacks salados") for i in range(5)]
    rows += [(400, "Gaseosa cola 500 cc farmacia", 4, "Gaseosas")]
    rows += [(500 + i, f"Gaseosa de regalo {i}", 5, "Gaseosas") for i in range(2)]
    rows += [(700 + i, f"Cerveza marca {i} lata 470 cc", 7, "Cervezas") for i in range(25)]
    rows += [(750 + i, f"Cerveza marca {i} express", 3, "Cervezas") for i in range(5)]
    for pid, name, store, category in rows:
        add_product(db, pid, name, store, category)
        add_price(db, store, pid, 1990)
    db.execute("INSERT INTO scrape_runs (run_id, kind, status) VALUES (999, 'restaurants', 'done')")
    for item_id, name, section in [(600, "Pizza napolitana", "Pizzas"), (601, "Pizza pepperoni", "Pizzas")] + [
        (610 + i, f"Cerveza Kunstmann schop {i}", "Bebidas") for i in range(3)
    ]:
        add_dish(db, item_id, name, 6, section)
        db.execute("INSERT INTO menu_price_snapshots (run_id, item_id, price) VALUES (999, %s, 6990)", (item_id,))
    db.commit()
    build_search_documents(db)
    build_concepts(db)

    generate(db, users=150, weeks=20, seed=3, until=date(2026, 9, 27))

    shown = dict(
        db.execute(
            """SELECT concept_id || ' · ' || vertical, count(*) FROM app_events
               WHERE type = 'suggestion_shown' GROUP BY 1"""
        ).fetchall()
    )
    assert not [key for key in shown if key.startswith("cerveza · ")], shown
    verticals = {key.split(" · ")[1]: n for key, n in shown.items() if key.startswith("gaseosas · ")}
    assert verticals, shown  # el escenario genera sugerencias de gaseosas (desde las papas y la pizza)
    assert not set(verticals) & {"farmacia", "licores", "mall", "restaurantes"}
    assert max(verticals, key=verticals.get) == ranked_verticals(db, ["gaseosas"])[0] == "supermercado"


def test_the_synthetic_catalog_marks_what_the_agent_would_not_offer(db):
    """`load_catalog` marca, por vertical, el producto que solo vende una tienda Farmacia (aunque esté en el súper) y
    el que dice bebé en su nombre: el generador no los sugiere (offers/guards.py)."""
    from rappi_ia.events.synth import load_catalog

    add_store(db, 2, "supermercado", "Súper")
    add_store(db, 8, "supermercado", "Farmacia de barrio")
    db.execute("UPDATE store_verticals SET subvertical = 'Farmacia' WHERE store_id = 8")
    for pid, name, store in [
        (200, "Gaseosa cola 1,5 L", 2),
        (201, "Gaseosa cola de farmacia 1,5 L", 8),
        (202, "Gaseosa para bebé 1,5 L", 2),
    ]:
        add_product(db, pid, name, store, "Gaseosas")
        add_price(db, store, pid, 1990)
    db.execute("INSERT INTO store_products (store_id, sku, master_product_id) VALUES (2, 'sku-201', 201)")
    add_price(db, 2, 201, 1990)
    add_product(db, 203, "Gaseosa naranja 1,5 L", 8, "Gaseosas")  # solo en la tienda Farmacia
    add_price(db, 8, 203, 1990)
    db.commit()
    build_search_documents(db)
    build_concepts(db)

    catalog = load_catalog(db)

    loaded = {eid for options in catalog.items.values() for _etype, eid, _price in options}
    assert {"200", "201", "202", "203"} <= loaded
    assert {eid for _v, _etype, eid in catalog.unofferable} == {"202", "203"}  # la 201 también la vende el súper


def test_at_risk_uses_pseudonyms_and_no_sensitive_concepts(simulated):
    db, _ = simulated
    for row in queries.at_risk(db, "synthetic", limit=200):
        assert row["usuario"].startswith("u-") and len(row["usuario"]) == 10
        assert "syn-" not in row["usuario"]
        assert row["estado"] in {"en_riesgo", "perdido"}


def test_synthetic_events_are_text_only_and_the_agent_ones_are_ask(simulated):
    db, _ = simulated
    modalities = db.execute("SELECT DISTINCT modality FROM app_events WHERE source = 'synthetic'").fetchall()
    assert {m for (m,) in modalities} == {"texto", None}  # None: los eventos que no son consultas
    types = {t for (t,) in db.execute("SELECT DISTINCT type FROM app_events WHERE source = 'synthetic'")}
    assert "ask" in types and "chat" not in types


def test_learned_synthetic_edges_are_never_used_by_the_agent(simulated):
    db, _ = simulated
    n = queries.learn_edges(db, "synthetic")
    assert n == db.execute("SELECT count(*) FROM concept_edges WHERE method = 'coocurrencia'").fetchone()[0]
    db.execute("DELETE FROM concept_edges WHERE method = 'curado'")
    db.commit()
    # Sin aristas curadas, las aprendidas de datos simulados no alcanzan para sugerir nada.
    assert suggest_complement(db, ["cerveza"], "licores", None) is None


def test_opportunities_come_only_from_unmet_searches(simulated):
    db, _ = simulated
    for row in queries.opportunities(db, "synthetic"):
        assert row["usuarios"] >= 5 and row["busquedas"] >= row["usuarios"]
        assert row["accion"]


RETENTION_T0 = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _retention_order(db, user, day, vertical, cart=None):
    events.record_order(
        db,
        user,
        f"s-{user}-{day}",
        cart or f"c-{user}-{day}",
        vertical,
        [{"entity_type": "catalog_item", "entity_id": "1", "unit_price": 1000}],
        ts=RETENTION_T0 + timedelta(days=day),
    )


def test_multi_vertical_retention_is_exact(db, monkeypatch):
    """La hipótesis del proyecto, con números a mano: ventana de 60 días, retención entre los días 61 y 120,
    solo usuarios con 120 días de historia, estratos por compras y el mínimo de usuarios por grupo."""
    for user in ("m1", "m2"):  # dos verticales en los primeros 60 días, vuelven el día 70
        (
            _retention_order(db, user, 0, "supermercado"),
            _retention_order(db, user, 10, "licores"),
            _retention_order(db, user, 70, "supermercado"),
        )
    _retention_order(db, "s1", 0, "supermercado"), _retention_order(db, "s1", 10, "supermercado")
    _retention_order(db, "s1", 70, "licores")  # la segunda vertical llega tarde: sigue siendo «un vertical»
    _retention_order(db, "s2", 0, "supermercado"), _retention_order(db, "s2", 10, "supermercado")  # no vuelve
    for user in ("x1", "x2"):  # 6 compras: estrato «6+»
        for day in range(0, 60, 10):
            _retention_order(db, user, day, "supermercado")
    _retention_order(db, "n1", 150, "supermercado")  # sin 120 días de historia: fuera
    events.record(db, [events.Event("z", "s", "app_open", ts=RETENTION_T0 + timedelta(days=200))])

    assert queries.multi_vertical_retention(db, "prototype") == []  # grupos de 2 < MIN_GROUP_USERS (privacidad)
    monkeypatch.setattr(queries, "MIN_GROUP_USERS", 2)
    rows = {
        (r["estrato"], r["grupo"]): (r["usuarios"], r["retencion_pct"])
        for r in queries.multi_vertical_retention(db, "prototype")
    }
    assert rows == {
        ("1–2 compras", "multi-vertical"): (2, 100.0),
        ("1–2 compras", "un vertical"): (2, 50.0),
        ("6+ compras", "un vertical"): (2, 0.0),
    }


def test_services_never_mix_simulated_and_prototype_events(db):
    travel = {"servicio": "rappitravel"}
    events.record(db, [events.Event("u1", "s1", "service_shown", payload=travel)], source="synthetic")
    rows = {r["servicio"]: r for r in queries.services(db, "prototype")}
    assert rows["rappitravel"]["ofrecido"] == 0
