"""Mapa multivertical: qué productos y conceptos comparten las verticales del catálogo.

`rappi-ia multivertical` escribe una página autocontenida (sin internet) en docs/mapas/ y donde la sirve el panel
(dashboard-empresa/public/presentacion/):
productos compartidos entre verticales, el mapa radial de conceptos (cada uno junto a la vertical donde es más
típico, la misma regla del agente) y los productos y cadenas que están en más verticales.
"""

import json
from pathlib import Path

from psycopg import Connection

from .. import config
from ..agent.verticals import typical_verticals
from ..concepts.taxonomy import load_taxonomy

TEMPLATE = Path(__file__).resolve().parent / "multivertical.html"
OUTPUTS = (
    config.PROJECT_ROOT.parent / "docs" / "mapas" / "mapa-multivertical.html",
    config.PROJECT_ROOT.parent / "dashboard-empresa" / "public" / "presentacion" / "mapa-multivertical.html",
)
ORDER = ["supermercado", "conveniencia", "turbo", "licores", "chocolateria", "restaurantes", "farmacia", "mall"]
LABELS = {
    "supermercado": "Súper",
    "conveniencia": "Express",
    "turbo": "Turbo",
    "licores": "Licores",
    "chocolateria": "Chocolatería",
    "restaurantes": "Restaurantes",
    "farmacia": "Farmacia",
    "mall": "Rappi Mall",
}
MIN_ITEMS = 20  # una línea concepto → vertical necesita al menos estos productos
BRIDGE_MIN_VERTICALS = 5
TOP = 12

# Qué verticales comparte un producto se decide solo con las tiendas de una vertical, como el panel
# (v_cross_vertical_items_real): con la doble etiqueta de Lider, Express Lider y Unimarc, cada producto suyo contaría
# como vendido en Súper y en Express. Los totales (productos de cada vertical, tiendas de un producto) cuentan todas.
_SINGLE_VERTICAL_STORES = """SELECT store_id, min(vertical) AS vertical FROM v_store_verticals
                             GROUP BY store_id HAVING count(*) = 1"""
_PRODUCT_VERTICALS = f"""SELECT DISTINCT sp.master_product_id, sv.vertical FROM store_products sp
                         JOIN ({_SINGLE_VERTICAL_STORES}) sv USING (store_id)
                         WHERE sp.master_product_id IS NOT NULL"""


def collect(conn: Connection) -> dict:
    # Con todas las tiendas, como «Calidad del catálogo» en el panel.
    products = dict(conn.execute("SELECT vertical, count(*) FROM v_item_verticals GROUP BY 1").fetchall())
    products["restaurantes"] = conn.execute("SELECT count(*) FROM menu_items").fetchone()[0]
    as_of = conn.execute(
        "SELECT to_char(max(finished_at) AT TIME ZONE 'America/Santiago', 'DD-MM-YYYY') FROM scrape_runs"
        " WHERE status = 'done'"
    ).fetchone()[0]
    shared = conn.execute(
        f"""WITH pv AS ({_PRODUCT_VERTICALS})
            SELECT a.vertical, b.vertical, count(*) FROM pv a JOIN pv b USING (master_product_id)
            WHERE a.vertical < b.vertical GROUP BY 1, 2 ORDER BY 1, 2"""
    ).fetchall()
    spread = conn.execute(
        f"""SELECT n, count(*) FROM (
                SELECT master_product_id, count(*) AS n FROM ({_PRODUCT_VERTICALS}) pv GROUP BY 1
            ) x GROUP BY 1 ORDER BY 1"""
    ).fetchall()
    groups = dict(conn.execute("SELECT concept_id, name FROM concepts WHERE parent_id IS NULL").fetchall())
    items_by_concept: dict[str, dict[str, int]] = {}
    for cid, vertical, items in conn.execute(
        "SELECT concept_id, vertical, items FROM concept_assortment WHERE items > 0"
    ):
        items_by_concept.setdefault(cid, {})[vertical] = items
    # `items` cuenta cada producto una vez por vertical; el total del concepto lo cuenta una sola vez.
    totals = dict(conn.execute("SELECT concept_id, count(*) FROM item_concepts GROUP BY 1").fetchall())
    homes = typical_verticals(conn)
    concepts = []
    for cid, name, emoji, parent, sensitive in conn.execute(
        "SELECT concept_id, name, emoji, parent_id, sensitive FROM concepts WHERE parent_id IS NOT NULL ORDER BY 1"
    ):
        items = items_by_concept.get(cid)
        if not items:
            continue
        home = homes.get(cid) or max(items, key=items.get)
        concepts.append(
            {
                "id": cid,
                "name": name,
                "emoji": emoji,
                "group": groups[parent],
                "sensitive": sensitive,
                "home": home,
                "items": items,
                "total": totals.get(cid, 0),
            }
        )
    complements = conn.execute(
        "SELECT from_concept, to_concept, weight FROM concept_edges WHERE method = 'curado' ORDER BY 1, 2"
    ).fetchall()
    # Del grafo de conocimiento (relations.toml): sustitutos una vez por par y «nunca junto» de grupo a concepto,
    # abierto a cada concepto del grupo (alcohol → cerveza, vino…) para dibujarlo entre puntos del mapa.
    substitutes = conn.execute(
        """SELECT from_id, to_id, weight FROM knowledge_edges
           WHERE relation = 'sustituye' AND method = 'curado' AND from_kind = 'concept' AND to_kind = 'concept'
             AND from_id < to_id ORDER BY 1, 2"""
    ).fetchall()
    conflicts = conn.execute(
        """SELECT DISTINCT c.concept_id, e.to_id FROM knowledge_edges e
           JOIN concepts c ON c.parent_id = e.from_id
           WHERE e.relation = 'conflicto' AND e.from_kind = 'group' AND e.to_kind = 'concept' ORDER BY 1, 2"""
    ).fetchall()
    bridges = conn.execute(
        f"""SELECT ci.name, array_agg(DISTINCT sv.vertical) FILTER (WHERE sv.vertical IS NOT NULL),
                   count(DISTINCT sp.store_id)
            FROM catalog_items ci
            JOIN store_products sp USING (master_product_id)
            LEFT JOIN ({_SINGLE_VERTICAL_STORES}) sv USING (store_id)
            GROUP BY ci.master_product_id, ci.name HAVING count(DISTINCT sv.vertical) >= %s
            ORDER BY count(DISTINCT sv.vertical) DESC, count(DISTINCT sp.store_id) DESC, ci.name LIMIT %s""",
        (BRIDGE_MIN_VERTICALS, TOP),
    ).fetchall()
    # Una cadena es su nombre sin importar mayúsculas (Unimarc y UNIMARC), con el nombre que más usan sus sucursales;
    # cada sucursal cuenta una vez aunque esté en dos verticales.
    chains = conn.execute(
        """SELECT mode() WITHIN GROUP (ORDER BY trim(s.name)), array_agg(DISTINCT sv.vertical),
                  count(DISTINCT s.store_id)
           FROM stores s
           JOIN store_verticals sv USING (store_id) WHERE trim(s.name) <> ''
           GROUP BY lower(trim(s.name)) HAVING count(DISTINCT sv.vertical) >= 2
           ORDER BY count(DISTINCT sv.vertical) DESC, 3 DESC, 1 LIMIT %s""",
        (TOP,),
    ).fetchall()
    in_order = lambda verticals: sorted(verticals, key=ORDER.index)  # noqa: E731
    return {
        "as_of": as_of,
        "order": ORDER,
        "labels": LABELS,
        "minItems": MIN_ITEMS,
        "products": products,
        "catalogTotal": conn.execute("SELECT count(*) FROM catalog_items").fetchone()[0],
        "shared": [[a, b, n] for a, b, n in shared],
        "spread": [[n, c] for n, c in spread],
        "concepts": concepts,
        "complements": [[a, b, float(w)] for a, b, w in complements],
        "substitutes": [[a, b, float(w)] for a, b, w in substitutes],
        "conflicts": [[a, b] for a, b in conflicts],
        "bridges": [[name, in_order(v), n] for name, v, n in bridges],
        "chains": [[name, in_order(v), n] for name, v, n in chains],
        # Servicios sin catálogo (RappiTravel, RappiFavor): se enganchan a conceptos, no tienen productos.
        "services": [
            {
                "id": s.id,
                "name": s.name,
                "emoji": s.emoji,
                "pitch": s.pitch,
                "hooks": list(dict.fromkeys(h.concept for h in s.hooks)),
            }
            for s in load_taxonomy().services.values()
        ],
    }


def render(data: dict) -> str:
    # «</» escapado: un nombre del catálogo con «</script>» no puede cerrar el script (JSON lo lee igual).
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8").replace("__FECHA__", data.get("as_of") or "sin fecha de descarga")
    return page.replace("/*__DATA__*/null", payload)


def write(conn: Connection, *paths: Path) -> dict:
    """Escribe la página en cada ruta (por defecto, OUTPUTS) y devuelve los datos."""
    data = collect(conn)
    page = render(data)
    for path in paths or OUTPUTS:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page, encoding="utf-8")
    return data
