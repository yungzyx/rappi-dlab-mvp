"""Mapa multivertical: qué productos y conceptos comparten las verticales (rappi_ia_test)."""

import json
import re

from rappi_scraper.storage.search import build_search_documents

from conftest import add_dish, add_product, add_store
from rappi_ia.agent import verticals
from rappi_ia.analytics import multivertical
from rappi_ia.concepts.pipeline import build_concepts


def _catalog(db):
    add_store(db, 1, "supermercado", "Unimarc")
    add_store(db, 2, "licores", "Botillería")
    add_store(db, 3, "conveniencia", "Unimarc")  # la misma cadena en Express
    add_store(db, 4, "restaurantes", "Sanguchería")
    add_product(db, 100, "Cerveza Escudo Lata 470 cc", 1, "Cervezas")
    for store in (2, 3):  # la misma cerveza también en Licores y Express
        db.execute(
            "INSERT INTO store_products (store_id, sku, master_product_id) VALUES (%s, %s, 100)", (store, f"b{store}")
        )
    add_product(db, 101, "Papas fritas Lays 180 g", 1, "Snacks salados")
    add_product(db, 102, "Cerveza Kunstmann Torobayo", 2, "Cervezas")
    add_product(db, 103, "Agua mineral Cachantun 1,6 L", 3, "Aguas")
    add_dish(db, 500, "Hamburguesa clásica", 4, "Hamburguesas")
    db.commit()
    build_search_documents(db)
    build_concepts(db)


def test_collect_counts_products_shared_between_verticals(db):
    _catalog(db)
    data = multivertical.collect(db)

    shared = {(a, b): n for a, b, n in data["shared"]}
    assert shared == {
        ("conveniencia", "licores"): 1,
        ("conveniencia", "supermercado"): 1,
        ("licores", "supermercado"): 1,
    }
    assert dict(data["spread"]) == {1: 3, 3: 1}  # 3 productos en una vertical, la cerveza en tres
    assert data["products"]["restaurantes"] == 1  # los platos se cuentan aparte: no se comparten
    beer = next(c for c in data["concepts"] if c["id"] == "cerveza")
    assert beer["home"] == "licores" and beer["items"]["supermercado"] == 1
    assert [name for name, *_ in data["bridges"]] == []  # ninguno llega a 5 verticales
    assert data["chains"] == [["Unimarc", ["supermercado", "conveniencia"], 2]]  # 2+ verticales, en orden del mapa
    # Servicios sin catálogo, con sus ganchos: van al mapa aunque no tengan productos.
    services = {s["id"]: s for s in data["services"]}
    assert services["rappitravel"]["hooks"] == ["dermocosmetica", "ropa", "accesorios-moda"]
    assert services["rappifavor"]["hooks"] == [] and services["rappifavor"]["name"] == "RappiFavor"


def test_a_store_listed_in_two_verticals_does_not_make_its_products_shared(db, monkeypatch):
    """Como el panel (v_cross_vertical_items_real): la doble etiqueta de Lider o Unimarc no cruza verticales,
    pero sus productos y sucursales sí cuentan (como en «Calidad del catálogo»)."""
    _catalog(db)
    add_store(db, 8, "supermercado", "Lider")
    db.execute("INSERT INTO store_verticals (store_id, vertical) VALUES (8, 'conveniencia')")
    add_product(db, 104, "Arroz grado 1 Tucapel 1 kg", 8, "Arroz")  # solo en la tienda con doble etiqueta
    add_product(db, 105, "Hielo en bolsa 2 kg", 2, "Hielo")  # en Licores y en el Lider
    for sku, product in (("b8", 100), ("h8", 105)):
        db.execute("INSERT INTO store_products (store_id, sku, master_product_id) VALUES (8, %s, %s)", (sku, product))
    db.commit()
    monkeypatch.setattr(multivertical, "BRIDGE_MIN_VERTICALS", 3)
    data = multivertical.collect(db)

    assert {(a, b): n for a, b, n in data["shared"]} == {
        ("conveniencia", "licores"): 1,
        ("conveniencia", "supermercado"): 1,
        ("licores", "supermercado"): 1,
    }
    assert dict(data["spread"]) == {1: 4, 3: 1}  # el arroz no cuenta como «en 2 verticales»; el hielo, solo en Licores
    assert data["products"]["supermercado"] == 4  # cerveza y papas de la tienda 1, arroz y hielo del Lider
    assert data["products"]["conveniencia"] == 4  # cerveza y agua de la tienda 3, arroz y hielo del Lider
    # La cerveza está en 4 sucursales (también el Lider); el hielo llega a 3 verticales solo por la doble etiqueta.
    assert data["bridges"] == [["Cerveza Escudo Lata 470 cc", ["supermercado", "conveniencia", "licores"], 4]]


def test_a_chain_is_one_row_whatever_its_case_and_counts_each_branch_once(db):
    _catalog(db)
    add_store(db, 10, "supermercado", "Cadena")
    add_store(db, 11, "supermercado", "Cadena")
    db.execute("INSERT INTO store_verticals (store_id, vertical) VALUES (11, 'conveniencia')")  # doble etiqueta
    add_store(db, 12, "farmacia", " CADENA ")
    db.commit()
    data = multivertical.collect(db)

    assert data["chains"][0] == ["Cadena", ["supermercado", "conveniencia", "farmacia"], 3]  # 3 sucursales, no 4
    assert [name for name, *_ in data["chains"]] == ["Cadena", "Unimarc"]


def test_products_without_master_id_are_not_a_product(db):
    _catalog(db)
    for store in (1, 2):  # store_products sin master_product_id en Súper y en Licores
        db.execute("INSERT INTO store_products (store_id, sku) VALUES (%s, 'sin-master')", (store,))
    db.commit()
    data = multivertical.collect(db)

    assert dict(data["spread"]) == {1: 3, 3: 1}
    assert data["products"]["supermercado"] == 2 and data["products"]["licores"] == 2


def test_concept_total_counts_a_product_once_whatever_its_verticals(db):
    _catalog(db)
    beer = next(c for c in multivertical.collect(db)["concepts"] if c["id"] == "cerveza")

    assert beer["items"] == {"supermercado": 1, "licores": 2, "conveniencia": 1}
    assert beer["total"] == 2  # Escudo (en 3 verticales) y Kunstmann: 2 productos, no 4


def test_render_embeds_the_data_in_a_self_contained_page(db):
    _catalog(db)
    page = multivertical.render(multivertical.collect(db))

    assert "/*__DATA__*/" not in page
    data = json.loads(re.search(r"const DATA = (\{.*?\});\n", page, re.S).group(1))
    assert data["catalogTotal"] == 4
    assert not re.search(r"""<(script|link)[^>]+(src|href)=["']https?://""", page)  # funciona sin internet
    # El radio de cada concepto y la columna «Productos» usan su total de productos distintos, no la suma por vertical.
    assert "const total = (c) => c.total;" in page
    assert "Object.values(c.items).reduce" not in page


def test_names_from_the_catalog_cannot_break_out_of_the_page(db, tmp_path):
    """Los nombres vienen de rappi.cl: un «</script>» no puede cortar el script ni inyectar HTML."""
    _catalog(db)
    for store_id, vertical in ((6, "supermercado"), (7, "licores")):  # cadena en 2 verticales: sale en el mapa
        add_store(db, store_id, vertical, "Botillería </script><img src=x onerror=alert(1)>")
    db.commit()

    path = tmp_path / "carpeta-nueva" / "mapa.html"  # la carpeta no existe todavía
    multivertical.write(db, path)
    page = path.read_text(encoding="utf-8")
    assert "</script><img" not in page
    data = json.loads(re.search(r"const DATA = (\{.*?\});\n", page, re.S).group(1))
    assert data["chains"][0][0] == "Botillería </script><img src=x onerror=alert(1)>"  # el dato llega intacto


def test_typical_vertical_is_the_first_ranked_one(db):
    _catalog(db)
    homes = verticals.typical_verticals(db)
    for concept in {c for (c,) in db.execute("SELECT DISTINCT concept_id FROM concept_assortment WHERE items > 0")}:
        ranked = verticals.ranked_verticals(db, [concept])
        assert homes.get(concept) == (ranked[0] if ranked else None), concept


def test_the_page_says_the_date_of_the_last_finished_download(db):
    """La fecha estaba escrita a mano en la plantilla: el mapa regenerado con el catálogo del 04-10 decía 30-09."""
    _catalog(db)
    db.execute(
        "INSERT INTO scrape_runs (kind, status, finished_at) VALUES ('stores', 'done', '2026-10-04 22:22-03'),"
        " ('restaurants', 'running', NULL)"
    )
    page = multivertical.render(multivertical.collect(db))
    assert "04-10-2026." in page and "30-09-2026" not in page


def test_the_concept_map_carries_substitutes_and_never_together_pairs(db):
    from rappi_ia.layers.graph import build_relations

    _catalog(db)
    build_relations(db)
    data = multivertical.collect(db)

    substitutes = {frozenset(pair) for *pair, _w in data["substitutes"]}
    assert frozenset(("cafe", "te")) in substitutes and len(substitutes) == len(data["substitutes"])  # una vez por par
    conflicts = {tuple(pair) for pair in data["conflicts"]}
    assert ("cerveza", "panales") in conflicts and (
        "cigarrillos",
        "alimentacion-bebe",
    ) in conflicts  # grupo → conceptos
    page = multivertical.render(data)
    assert 'id="showSubs"' in page and 'id="showConf"' in page
