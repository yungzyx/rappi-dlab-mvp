"""Catálogo de tiendas y productos: las tarjetas, la tienda con sus pasillos y el detalle, con precios vigentes.

Todo sobre el catálogo de `seed_demo`: las tiendas 9101 y 9102 son los dos súper de prueba; 9103 es una sucursal del
mismo formato que 9101 que solo salió en una corrida anterior; 9104 está descubierta, sin productos. El pasillo
«Despensa» de 9101 tiene exactamente 30 productos vigentes, y dos ofertas de 9101 no lo son: una de una corrida
anterior (atún) y una agotada (mermelada).
"""

import re

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from rappi_scraper.storage.search import build_search_documents

from rappi_ia.agent.tools import search_products
from rappi_ia.agent.verticals import LOGO_BASE_URL
from rappi_ia.api import app as api
from rappi_ia.catalog import cache as catalog_cache
from rappi_ia.catalog.stores import offer_price, product_detail, store_page, vertical_stores
from rappi_ia.demo.seed import DEMO_VERTICALS, seed_demo
from rappi_ia.events.store import catalog_prices

CENTRO, NORTE, OLD_BRANCH, DISCOVERED, PIZZERIA = 9101, 9102, 9103, 9104, 9801
PHARMACY_IN_SUPER = 9111  # Rappi la lista entre los súper (subvertical Farmacia): se abre desde su vertical
CARD_KEYS = {"id", "name", "logo", "eta", "products", "vertical"}
NOT_IN_CATALOG = "Esta tienda no está en el catálogo"


@pytest.fixture
def seeded(db):
    seed_demo(db)
    return db


@pytest.fixture
def client(seeded):
    def conn_override():
        yield seeded

    api.app.dependency_overrides[api.get_conn] = conn_override
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def all_products(conn, store_id: int) -> list[dict]:
    """Todos los productos de la tienda, pasillo por pasillo y página por página."""
    products = []
    for aisle in store_page(conn, store_id)["aisles"]:
        page = 1
        while True:
            reply = store_page(conn, store_id, aisle["id"], page)
            products += reply["products"]
            if not reply["has_more"]:
                break
            page += 1
    return products


def test_vertical_stores_lists_one_card_per_format_with_current_offers(seeded):
    cards = vertical_stores(seeded, "supermercado")

    # 9103 es del mismo formato que 9101 pero su última descarga es anterior; 9104 solo se descubrió. La farmacia que
    # Rappi lista entre los súper (9111) sí está, con sus dos ofertas, al final.
    assert [card["id"] for card in cards] == [CENTRO, NORTE, PHARMACY_IN_SUPER]
    assert all(set(card) == CARD_KEYS for card in cards)
    centro, norte, pharmacy = cards
    assert centro["name"] == "Supermercado de prueba Centro"
    assert centro["logo"] == f"{LOGO_BASE_URL}prueba-{CENTRO}.png"
    assert re.fullmatch(r"\d+ min", centro["eta"])
    assert centro["vertical"] == "supermercado"
    # Ofertas vigentes: el atún (corrida anterior) y la mermelada (agotada) no cuentan. Más ofertas primero. Norte
    # tiene además el nori y el matcha de la escalera del perfil asiático.
    assert (centro["products"], norte["products"], pharmacy["products"]) == (36, 35, 2)


def test_vertical_stores_limit_and_restaurants(seeded):
    assert len(vertical_stores(seeded, "supermercado", limit=1)) == 1
    assert [card["id"] for card in vertical_stores(seeded, "turbo")] == [9301, 9302]
    assert vertical_stores(seeded, "restaurantes") == []


def test_card_uses_the_brand_name_and_leaves_unknown_logo_and_eta_empty(seeded):
    seeded.execute("INSERT INTO brands (brand_id, name) VALUES (77, 'Marca de prueba')")
    seeded.execute("UPDATE stores SET brand_id = 77, raw = NULL WHERE store_id = %s", (CENTRO,))

    card = vertical_stores(seeded, "supermercado")[0]

    assert (card["id"], card["name"], card["logo"], card["eta"]) == (CENTRO, "Marca de prueba", None, None)

    # Un minutos que no es un número tampoco se muestra.
    seeded.execute('UPDATE stores SET raw = \'{"eta_value": "pronto"}\' WHERE store_id = %s', (CENTRO,))
    assert vertical_stores(seeded, "supermercado")[0]["eta"] is None


def add_branch(
    conn, store_id: int, store_type: str, with_aisle: bool, product_id: int = 91001, price: int = 1990
) -> None:
    """Una sucursal más del súper de prueba con una oferta en la corrida actual (como las de una descarga)."""
    conn.execute(
        'INSERT INTO stores (store_id, name, store_type, raw) VALUES (%s, %s, %s, \'{"image": "x.png"}\')',
        (store_id, f"Sucursal de prueba {store_id}", store_type),
    )
    conn.execute("INSERT INTO store_verticals (store_id, vertical) VALUES (%s, 'supermercado')", (store_id,))
    if with_aisle:
        conn.execute("INSERT INTO aisles (store_id, aisle_id, name) VALUES (%s, 100, 'Despensa')", (store_id,))
    sku = f"sku-{product_id}"
    conn.execute(
        "INSERT INTO store_products (store_id, sku, master_product_id, aisle_id) VALUES (%s, %s, %s, %s)",
        (store_id, sku, product_id, 100 if with_aisle else None),
    )
    run_id = conn.execute("SELECT max(run_id) FROM scrape_runs WHERE kind = 'stores'").fetchone()[0]
    conn.execute(
        "INSERT INTO price_snapshots (run_id, store_id, sku, price, in_stock) VALUES (%s, %s, %s, %s, true)",
        (run_id, store_id, sku, price),
    )


def test_a_store_whose_offers_have_no_aisle_is_neither_listed_nor_opened(seeded):
    """Las tiendas importadas de un CSV antiguo tienen productos pero no pasillos: su página saldría vacía."""
    add_branch(seeded, 9105, "prueba_9105", with_aisle=False)

    assert [card["id"] for card in vertical_stores(seeded, "supermercado")] == [CENTRO, NORTE, PHARMACY_IN_SUPER]
    assert store_page(seeded, 9105) is None


def test_a_format_downloaded_in_two_branches_has_one_card_the_one_with_more_offers(seeded):
    add_branch(seeded, 9105, "prueba_9102", with_aisle=True)  # el formato del súper Norte, con una sola oferta

    assert [(card["id"], card["products"]) for card in vertical_stores(seeded, "supermercado")] == [
        (CENTRO, 36),
        (NORTE, 35),
        (PHARMACY_IN_SUPER, 2),
    ]
    assert store_page(seeded, 9105)["store"]["products"] == 1  # la otra sucursal sigue abierta por su id


def test_store_page_lists_aisles_with_current_counts_biggest_first(seeded):
    page = store_page(seeded, CENTRO)

    # Los subpasillos no son pasillos: sus productos cuentan en el pasillo. «Mermeladas» solo tiene una oferta
    # agotada, así que no aparece.
    assert [(a["name"], a["products"]) for a in page["aisles"]] == [
        ("Despensa", 30),
        ("Snacks y Dulces", 2),
        ("Bebidas", 2),
        ("Cuidado del bebé", 1),
        ("Cervezas", 1),
    ]
    assert all(set(a) == {"id", "name", "products"} for a in page["aisles"])
    assert page["aisles"] == sorted(page["aisles"], key=lambda a: (-a["products"], a["id"]))
    assert page["aisle"] == page["aisles"][0]
    assert set(page["store"]) == CARD_KEYS and page["store"]["id"] == CENTRO
    assert sum(a["products"] for a in page["aisles"]) == page["store"]["products"] == 36


def test_store_page_opens_on_the_aisle_with_most_offers_not_the_lowest_id(seeded):
    """Rappi no guarda la posición de los pasillos y su id no es un orden que sirva: en la base real Turbo abría en
    «Autopartes» y Lider en «Cuidado del Bebé». Turbo Centro tiene «Snacks y Dulces» (id 200) con una oferta y
    «Bebidas» (id 300) con cuatro."""
    page = store_page(seeded, 9301)

    # Más ofertas primero; con las mismas, el id.
    assert [(a["name"], a["products"]) for a in page["aisles"]] == [
        ("Bebidas", 4),
        ("Snacks y Dulces", 1),
        ("Helados", 1),
        ("Hielo", 1),
        ("Cervezas", 1),
    ]
    assert page["aisle"]["name"] == "Bebidas" and len(page["products"]) == 4
    assert [a["id"] for a in page["aisles"]] == [300, 200, 600, 700, 800]


def test_store_page_prices_are_the_stores_own_and_current(seeded):
    def snacks(store_id):
        page = store_page(seeded, store_id, aisle_id=_aisle_id(seeded, store_id, "Snacks y Dulces"))
        return {p["name"]: p for p in page["products"]}

    centro, norte = snacks(CENTRO), snacks(NORTE)

    # El precio es el de cada tienda, y el último: Centro bajó el suyo desde la corrida anterior ($1.790).
    assert centro["Papas fritas clásicas 180 g (prueba)"]["price_value"] == 1990
    assert centro["Papas fritas clásicas 180 g (prueba)"]["price"] == "$1.990"
    assert norte["Papas fritas clásicas 180 g (prueba)"]["price_value"] == 2090
    assert set(norte["Papas fritas clásicas 180 g (prueba)"]) == {
        "id", "entity_type", "entity_id", "name", "vertical", "concept", "price", "price_value", "before",
        "discount", "store", "img", "age_restricted", "store_id", "presentation",
    }  # fmt: skip
    papas = centro["Papas fritas clásicas 180 g (prueba)"]
    assert (papas["id"], papas["entity_type"], papas["entity_id"]) == ("cat-91001", "catalog_item", "91001")
    assert (papas["store"], papas["store_id"], papas["presentation"]) == (
        "Supermercado de prueba Centro",
        CENTRO,
        "180 g",
    )
    assert (papas["vertical"], papas["concept"], papas["age_restricted"]) == ("supermercado", "snacks-salados", False)

    # Ni la oferta de una corrida anterior ni la agotada aparecen en ningún pasillo.
    names = {p["name"] for p in all_products(seeded, CENTRO)}
    assert len(names) == 36
    assert not {n for n in names if "Atún" in n or "Mermelada" in n}
    # Lo +18 sigue marcado.
    beer = next(p for p in all_products(seeded, CENTRO) if p["entity_id"] == "94001")
    assert beer["age_restricted"] is True


def test_store_page_paginates_without_repeating_or_skipping(seeded):
    first = store_page(seeded, CENTRO)
    second = store_page(seeded, CENTRO, first["aisle"]["id"], page=2)

    assert first["aisle"]["name"] == "Despensa" and first["aisle"]["products"] == 30
    assert (len(first["products"]), first["page"], first["has_more"]) == (24, 1, True)
    assert (len(second["products"]), second["page"], second["has_more"]) == (6, 2, False)
    ids = [p["id"] for p in first["products"] + second["products"]]
    assert len(ids) == len(set(ids)) == 30
    names = [p["name"] for p in first["products"] + second["products"]]
    by_name = [name for (name,) in seeded.execute("SELECT n FROM unnest(%s::text[]) n ORDER BY n", (names,))]
    assert names == by_name  # el orden alfabético es el de la base, no el de Python
    assert store_page(seeded, CENTRO, first["aisle"]["id"], page=3)["products"] == []


def test_store_page_orders_products_with_the_same_name_by_id(seeded):
    """El catálogo repite nombres entre presentaciones: las páginas desempatan por producto, así ninguna repite ni se
    salta uno."""
    seeded.execute(
        """UPDATE catalog_items SET name = 'Producto repetido (prueba)'
           WHERE master_product_id IN (SELECT master_product_id FROM store_products
                                       WHERE store_id = %s AND aisle_id = 100)""",
        (CENTRO,),
    )

    first = store_page(seeded, CENTRO)
    second = store_page(seeded, CENTRO, first["aisle"]["id"], page=2)

    ids = [int(p["entity_id"]) for p in first["products"] + second["products"]]
    assert ids == sorted(ids) and len(set(ids)) == 30


def test_store_page_for_another_aisle_and_for_an_aisle_the_store_does_not_have(seeded):
    drinks = _aisle_id(seeded, CENTRO, "Bebidas")

    page = store_page(seeded, CENTRO, drinks)

    assert page["aisle"]["name"] == "Bebidas"
    assert sorted(p["name"] for p in page["products"]) == [
        "Gaseosa cola 1,5 L (prueba)",
        "Jugo de naranja 1 L (prueba)",
    ]
    assert page["has_more"] is False
    # Un pasillo sin ofertas vigentes (o de otra tienda) no trae productos.
    nothing = store_page(seeded, CENTRO, aisle_id=999_999)
    assert (nothing["aisle"], nothing["products"], nothing["has_more"]) == (None, [], False)
    assert len(nothing["aisles"]) == 5
    for aisle in (-1, 2**70):  # ni uno negativo ni uno fuera de bigint rompen la consulta
        assert store_page(seeded, CENTRO, aisle_id=aisle)["aisle"] is None


def test_unknown_or_empty_store_is_404_with_spanish_detail(seeded, client):
    for store_id in (999_999, OLD_BRANCH, DISCOVERED, PIZZERIA):
        assert store_page(seeded, store_id) is None, store_id
        reply = client.get(f"/catalog/stores/{store_id}")
        assert reply.status_code == 404 and reply.json() == {"detail": NOT_IN_CATALOG}, store_id

    assert client.get("/catalog/stores/9223372036854775808").status_code == 404
    assert client.get("/catalog/stores/abc").status_code == 422
    assert client.get(f"/catalog/stores/{CENTRO}?page=0").status_code == 422


def test_product_detail_for_catalog_item_and_dish(seeded):
    papas = product_detail(seeded, "catalog_item", "91001")

    # La oferta vigente más barata de todas las tiendas: Centro ($1.990), no Norte ni Express ni Turbo.
    assert (papas["id"], papas["name"], papas["price_value"], papas["price"]) == (
        "cat-91001",
        "Papas fritas clásicas 180 g (prueba)",
        1990,
        "$1.990",
    )
    assert (papas["store"], papas["store_id"], papas["vertical"], papas["presentation"]) == (
        "Supermercado de prueba Centro",
        CENTRO,
        "supermercado",
        "180 g",
    )
    assert papas["img"] == "https://imagenes.prueba.invalid/productos/91001.png"

    pizza = product_detail(seeded, "menu_item", "98001")
    assert (pizza["id"], pizza["entity_type"], pizza["name"], pizza["price_value"]) == (
        "menu-98001",
        "menu_item",
        "Pizza pepperoni familiar (prueba)",
        12990,
    )
    assert (pizza["store"], pizza["store_id"], pizza["vertical"], pizza["presentation"]) == (
        "Pizzería de prueba Centro",
        PIZZERIA,
        "restaurantes",
        None,
    )


def test_product_detail_is_none_without_a_current_offer_or_for_nonsense_ids(seeded):
    for entity_type, entity_id in [
        ("catalog_item", "91201"),  # solo tiene una oferta de una corrida anterior
        ("catalog_item", "91202"),  # agotada
        ("catalog_item", "1"),
        ("catalog_item", "no-es-un-numero"),
        ("catalog_item", "99999999999999999999"),
        ("menu_item", "1"),
        ("store", "9101"),
    ]:
        assert product_detail(seeded, entity_type, entity_id) is None, (entity_type, entity_id)


# El precio de una línea de pedido antes de la consulta única de catalog_prices: una consulta por línea.
OLD_STORE_PRICE = """
SELECT min(l.price)
FROM store_products sp
JOIN v_latest_offers l ON l.store_id = sp.store_id AND l.sku = sp.sku
WHERE sp.store_id = %(store_id)s AND sp.master_product_id = %(id)s AND l.current AND l.in_stock IS NOT FALSE
  AND l.price >= 10"""


def test_order_prices_in_one_query_match_the_line_by_line_prices(seeded):
    """catalog_prices pide los precios de todas las líneas con tienda en una consulta: da los mismos precios que la
    consulta por línea de antes, en cada par (producto, tienda) del catálogo de prueba y en los casos sin precio
    (corrida anterior, agotado, otra tienda, ids inválidos), y deja fuera las mismas líneas."""
    pairs = seeded.execute(
        "SELECT DISTINCT master_product_id::text, store_id FROM store_products WHERE master_product_id IS NOT NULL"
    ).fetchall()
    lines = [{"entity_type": "catalog_item", "entity_id": item, "store_id": store, "qty": 1} for item, store in pairs]
    lines += [
        {"entity_type": "catalog_item", "entity_id": "91001", "store_id": CENTRO, "qty": 2},  # repetida
        {"entity_type": "catalog_item", "entity_id": "91001", "store_id": DISCOVERED},  # tienda que no lo vende
        {"entity_type": "catalog_item", "entity_id": "1", "store_id": CENTRO},  # no está en el catálogo
        {"entity_type": "catalog_item", "entity_id": "no-es-un-numero", "store_id": CENTRO},
        {"entity_type": "catalog_item", "entity_id": "99999999999999999999", "store_id": CENTRO},
        {"entity_type": "catalog_item", "entity_id": "91001"},  # sin tienda: el de la ficha
        {"entity_type": "menu_item", "entity_id": "98001", "store_id": PIZZERIA},
        {"entity_type": "menu_item", "entity_id": "98001", "store_id": CENTRO},  # un plato es de un solo local
    ]

    def old_price(line):
        if line["entity_type"] == "catalog_item" and line.get("store_id") is not None:
            if not line["entity_id"].isdigit() or int(line["entity_id"]) > 2**63 - 1:
                return None
            price = seeded.execute(OLD_STORE_PRICE, {"id": int(line["entity_id"]), "store_id": line["store_id"]})
            price = price.fetchone()[0]
            return float(price) if price is not None else None
        return offer_price(seeded, line["entity_type"], line["entity_id"], line.get("store_id"))

    expected = [{**line, "unit_price": p} for line in lines if (p := old_price(line)) is not None]
    priced, skipped = catalog_prices(seeded, lines)

    assert priced == expected
    assert skipped == len(lines) - len(expected)
    # No es una comparación vacía: hay precios, líneas sin oferta vigente y los dos casos que van uno por uno.
    unpriced = {(line["entity_id"], line.get("store_id")) for line in lines} - {
        (line["entity_id"], line.get("store_id")) for line in priced
    }
    assert {("91201", CENTRO), ("91202", CENTRO), ("91001", DISCOVERED), ("98001", CENTRO)} <= unpriced
    assert {("91001", None), ("98001", PIZZERIA)} <= {(line["entity_id"], line.get("store_id")) for line in priced}
    assert len(priced) > 20


def test_product_endpoint(client):
    papas = client.get("/catalog/products/catalog_item/91001")
    pizza = client.get("/catalog/products/menu_item/98001")

    assert papas.status_code == 200 and papas.json()["id"] == "cat-91001"
    assert pizza.status_code == 200 and pizza.json()["store_id"] == PIZZERIA
    for path in ("catalog_item/91201", "menu_item/1", "catalog_item/x", "store/9101"):
        reply = client.get(f"/catalog/products/{path}")
        assert reply.status_code == 404 and reply.json() == {"detail": "Este producto no está en el catálogo"}, path


def test_catalog_endpoints_accept_prototype_vertical_ids(client):
    backend = client.get("/catalog/verticals/supermercado/stores").json()
    prototype = client.get("/catalog/verticals/grocery/stores").json()

    assert prototype == backend
    assert backend["vertical"] == "supermercado"
    assert [card["id"] for card in backend["stores"]] == [CENTRO, NORTE, PHARMACY_IN_SUPER]
    assert client.get("/catalog/verticals/express/stores").json()["vertical"] == "conveniencia"
    assert client.get("/catalog/verticals/liquor/stores?limit=1").json()["stores"][0]["id"] == 9401
    assert client.get("/catalog/verticals/restaurantes/stores").json() == {"vertical": "restaurantes", "stores": []}
    # `pet` es del prototipo y no tiene vertical en el catálogo.
    reply = client.get("/catalog/verticals/pet/stores")
    assert reply.status_code == 404 and reply.json() == {"detail": "Esta vertical no está en el catálogo"}
    assert client.get("/catalog/verticals/grocery/stores?limit=0").status_code == 422


def test_store_endpoint_returns_the_page(client):
    first = client.get(f"/catalog/stores/{CENTRO}").json()
    aisle = first["aisle"]["id"]
    second = client.get(f"/catalog/stores/{CENTRO}?aisle={aisle}&page=2").json()

    assert (len(first["products"]), first["has_more"]) == (24, True)
    assert (len(second["products"]), second["has_more"], second["page"]) == (6, False, 2)


def search_found(conn, query: str, vertical: str = "supermercado", k: int = 6):
    """Lo que encuentra la búsqueda (la ruta de precios de /agent/ask y /search) con los documentos recién hechos."""
    build_search_documents(conn)
    return search_products(conn, vertical, query, None, None, k=k).products


def assert_price_is_the_shown_stores(conn, product: dict, cache: dict | None = None) -> None:
    """Con `store_id`, el precio, el precio anterior y el descuento del producto son los que esa tienda tiene para él
    (los de su página): el precio y la tienda que se muestran nunca se contradicen."""
    if product["store_id"] is None or product["entity_type"] != "catalog_item":
        return
    cache = {} if cache is None else cache
    if product["store_id"] not in cache:
        cache[product["store_id"]] = {p["id"]: p for p in all_products(conn, product["store_id"])}
    on_its_page = cache[product["store_id"]][product["id"]]
    for key in ("price", "price_value", "before", "discount", "store"):
        assert product[key] == on_its_page[key], (product["id"], key)


def test_a_product_only_sold_in_a_store_that_cannot_be_opened_has_no_store_id(seeded):
    """Su oferta es de una tienda sin pasillos (de un CSV antiguo): «Ver tienda» no tendría adónde ir."""
    seeded.execute("INSERT INTO catalog_items (master_product_id, name) VALUES (91301, 'Yerba antigua (prueba)')")
    add_branch(seeded, 9105, "prueba_9105", with_aisle=False, product_id=91301, price=1500)

    detail = product_detail(seeded, "catalog_item", "91301")
    found = next(p for p in search_found(seeded, "yerba antigua") if p.entity_id == "91301").to_dict()

    for product in (detail, found):
        # Sin tienda que se abra, vale la oferta vigente más barata: su precio y el nombre de su tienda.
        assert (product["store_id"], product["store"], product["price_value"]) == (
            None,
            "Sucursal de prueba 9105",
            1500,
        )
    assert detail["vertical"] == "supermercado"


def test_the_store_name_of_a_searched_product_has_no_stray_spaces_like_the_catalog(seeded):
    """La base real tiene tiendas como «Fenix Minimarket » y «A3D »: /catalog ya recorta el nombre, y la búsqueda (la
    ruta de /agent/ask y /search) tiene que mostrar el mismo."""
    seeded.execute("UPDATE stores SET name = ' Supermercado de prueba Centro  ' WHERE store_id = %s", (CENTRO,))

    detail = product_detail(seeded, "catalog_item", "91001")
    found = next(p for p in search_found(seeded, "papas fritas") if p.entity_id == "91001").to_dict()

    assert detail["store"] == found["store"] == "Supermercado de prueba Centro"

    seeded.execute("INSERT INTO brands (brand_id, name) VALUES (77, 'Marca de prueba  ')")
    seeded.execute("UPDATE stores SET brand_id = 77 WHERE store_id = %s", (CENTRO,))

    assert next(p for p in search_found(seeded, "papas fritas") if p.entity_id == "91001").to_dict()["store"] == (
        "Marca de prueba"
    )


def test_a_product_sold_cheaper_in_a_store_that_cannot_be_opened_shows_the_price_of_one_that_can(seeded, client):
    add_branch(seeded, 9105, "prueba_9105", with_aisle=False, product_id=91001, price=990)  # más barata que 1.990
    seeded.execute(  # el Centro lo vende con precio anterior: también ese viene de la tienda que se muestra
        """UPDATE price_snapshots SET real_price = 2500
           WHERE store_id = %s AND sku = 'sku-91001' AND run_id = (SELECT max(run_id) FROM scrape_runs
                                                                    WHERE kind = 'stores')""",
        (CENTRO,),
    )

    detail = product_detail(seeded, "catalog_item", "91001")
    found = next(p for p in search_found(seeded, "papas fritas") if p.entity_id == "91001").to_dict()

    for product in (detail, found):
        # No los $990 de la tienda que no se abre: el precio, el anterior y el descuento son los del Centro.
        assert (product["store_id"], product["store"]) == (CENTRO, "Supermercado de prueba Centro")
        assert (product["price_value"], product["price"]) == (1990, "$1.990")
        assert (product["before"], product["discount"]) == ("$2.500", "-20%")
        assert client.get(f"/catalog/stores/{product['store_id']}").status_code == 200
        assert_price_is_the_shown_stores(seeded, product)
    assert client.get("/catalog/products/catalog_item/91001").json()["price_value"] == 1990


def test_the_store_id_of_a_product_is_the_cheapest_store_when_it_can_be_opened(seeded):
    detail = product_detail(seeded, "catalog_item", "91001")
    found = next(p for p in search_found(seeded, "papas fritas") if p.entity_id == "91001").to_dict()

    assert (detail["store_id"], detail["price_value"]) == (CENTRO, 1990)
    assert (found["store_id"], found["price_value"]) == (CENTRO, 1990)


def test_whenever_a_product_has_a_store_id_its_price_is_that_stores(seeded):
    """Todo el catálogo de prueba, con una oferta más barata en una tienda que no se abre: detalle y búsqueda."""
    add_branch(seeded, 9105, "prueba_9105", with_aisle=False, product_id=91001, price=990)
    cache: dict = {}
    with_store = 0

    for (product_id,) in seeded.execute("SELECT master_product_id FROM catalog_items ORDER BY 1").fetchall():
        detail = product_detail(seeded, "catalog_item", str(product_id))
        if detail is not None:
            assert_price_is_the_shown_stores(seeded, detail, cache)
            with_store += detail["store_id"] is not None
    searched = 0
    for vertical in DEMO_VERTICALS[:-1]:  # menos restaurantes, que no tienen páginas de tienda
        for product in search_found(seeded, "prueba", vertical, k=60):
            assert_price_is_the_shown_stores(seeded, product.to_dict(), cache)
            searched += product.store_id is not None

    assert with_store > 40 and searched > 40  # no es una comprobación vacía


def test_search_products_carry_the_store_and_presentation(seeded):
    products = search_products(seeded, "supermercado", "papas fritas", None, None).products

    papas = next(p for p in products if p.entity_id == "91001").to_dict()
    assert (papas["store_id"], papas["presentation"]) == (CENTRO, "180 g")


def _aisle_id(conn, store_id: int, name: str) -> int:
    return next(a["id"] for a in store_page(conn, store_id)["aisles"] if a["name"] == name)


def test_offer_of_a_skipped_aisle_is_current_everywhere(seeded):
    """Una corrida nueva baja el Centro sin poder leer el subpasillo de las papas ni el pasillo del atún: las papas
    siguen vigentes con su precio de la bajada anterior del formato (la del Centro) en la búsqueda, el detalle, el
    precio del pedido, el agente, la página y la tarjeta de la tienda (una sola definición, v_latest_offers). El atún,
    cuyo último precio es de antes de esa bajada anterior, no revive en ninguna."""
    papas_aisle, papas_sub, papas_price = seeded.execute(
        """SELECT sp.aisle_id, sp.sub_aisle_id, ps.price
           FROM store_products sp JOIN latest_prices ps USING (store_id, sku)
           WHERE sp.store_id = %s AND sp.sku = 'sku-91001'""",
        (CENTRO,),
    ).fetchone()
    tuna_aisle = seeded.execute(
        "SELECT aisle_id FROM store_products WHERE store_id = %s AND sku = 'sku-91201'", (CENTRO,)
    ).fetchone()[0]
    skipped = [papas_sub, tuna_aisle]
    before = vertical_stores(seeded, "supermercado")[0]
    # La bajada anterior del formato fue la del Centro: el scraper deja su job terminado (la siembra no deja jobs).
    previous = seeded.execute("SELECT max(run_id) FROM price_snapshots WHERE store_id = %s", (CENTRO,)).fetchone()[0]
    seeded.execute(
        """INSERT INTO scrape_jobs (run_id, job_key, job_type, payload, status, result)
           VALUES (%s, 'type:prueba_9101', 'store_group', '{}', 'done', %s)""",
        (previous, Jsonb({"store_id": CENTRO, "products": 1, "pasillos_omitidos": []})),
    )
    run = seeded.execute(
        "INSERT INTO scrape_runs (kind, status) VALUES ('stores', 'done') RETURNING run_id"
    ).fetchone()[0]
    seeded.execute(
        """INSERT INTO price_snapshots (run_id, store_id, sku, price, real_price, discount_pct, in_stock, scraped_at)
           SELECT %(run)s, lp.store_id, lp.sku, lp.price, lp.real_price, lp.discount_pct, lp.in_stock,
                  lp.scraped_at + interval '1 hour'
           FROM latest_prices lp JOIN store_products sp USING (store_id, sku)
           WHERE lp.store_id = %(store)s
             AND lp.run_id = (SELECT max(run_id) FROM price_snapshots WHERE store_id = %(store)s)
             AND sp.aisle_id <> ALL(%(skipped)s) AND coalesce(sp.sub_aisle_id, 0) <> ALL(%(skipped)s)""",
        {"run": run, "store": CENTRO, "skipped": skipped},
    )
    seeded.execute(
        """INSERT INTO scrape_jobs (run_id, job_key, job_type, payload, status, result)
           VALUES (%s, 'type:prueba_9101', 'store_group', '{}', 'done', %s)""",
        (run, Jsonb({"store_id": CENTRO, "products": 1, "pasillos_omitidos": skipped})),
    )
    assert seeded.execute(
        "SELECT run_id < %s FROM latest_prices WHERE store_id = %s AND sku = 'sku-91001'", (run, CENTRO)
    ).fetchone()[0]  # el último precio de las papas es de la corrida anterior

    build_search_documents(seeded)
    searched = seeded.execute(
        "SELECT (metadata->>'precio_min')::int FROM search_documents"
        " WHERE entity_id = '91001' AND vertical = 'supermercado'"
    ).fetchone()[0]
    detail = product_detail(seeded, "catalog_item", "91001")
    agent = next(p for p in search_products(seeded, "supermercado", "papas fritas", None, None).products
                 if p.entity_id == "91001")  # fmt: skip
    page = store_page(seeded, CENTRO, papas_aisle, page_size=100)

    assert searched == papas_price
    assert (detail["price_value"], detail["store_id"]) == (papas_price, CENTRO)
    assert offer_price(seeded, "catalog_item", "91001", CENTRO) == papas_price
    assert (agent.price_value, agent.store_id) == (papas_price, CENTRO)
    assert "91001" in {p["entity_id"] for p in page["products"]}
    catalog_cache.clear()
    assert vertical_stores(seeded, "supermercado")[0] == before  # mismas ofertas vigentes en la tarjeta

    assert product_detail(seeded, "catalog_item", "91201") is None
    assert offer_price(seeded, "catalog_item", "91201", CENTRO) is None
    assert seeded.execute("SELECT count(*) FROM search_documents WHERE entity_id = '91201'").fetchone()[0] == 0
