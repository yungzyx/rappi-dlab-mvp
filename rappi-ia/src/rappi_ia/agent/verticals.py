"""En qué vertical buscar un concepto: donde es más típico, no donde hay más ítems.

Restaurantes tiene unas 5 veces más ítems que el súper y casi todos sus locales listan bebidas, papas fritas o
schop; por cantidad ganaría casi cualquier concepto. Por eso se compara la participación del concepto en el
catálogo de cada vertical (ítems del concepto / ítems del vertical), y restaurantes solo compite cuando el
concepto se pide hecho (`prepared` en la taxonomía: comida preparada, postres, pastelería, helados, café).

Por participación, una vertical chica ganaba con un puñado de productos («pan» iba a chocolaterías con 46, y el súper
tiene 431). Por eso compiten primero las que tienen masa mínima (`MIN_ITEMS_TO_COMPETE` y `MIN_OFFER_SHARE`).
"""

from collections import defaultdict

from psycopg import Connection

# Participación de cada concepto en cada vertical, con restaurantes solo para lo que se pide hecho.
SHARES = """
    WITH total AS (SELECT vertical, sum(items) AS items FROM concept_assortment GROUP BY vertical)
    SELECT a.concept_id, a.vertical, a.items, t.items AS vertical_items
    FROM concept_assortment a
    JOIN total t USING (vertical)
    JOIN concepts c USING (concept_id)
    WHERE a.items > 0 AND (a.vertical <> 'restaurantes' OR c.prepared)"""

# Masa mínima para competir por participación: al menos estos productos y una cuarta parte de los que tiene la tienda
# con más oferta del concepto. Restaurantes no fija ese máximo: con ~5 veces más ítems dejaría fuera a las tiendas.
MIN_ITEMS_TO_COMPETE = 20
MIN_OFFER_SHARE = 0.25


def ranked_verticals(conn: Connection, concept_ids: list[str]) -> list[str]:
    """Verticales con oferta de los conceptos: primero las que tienen masa mínima, después el resto, cada grupo del
    más típico al menos típico. Si ninguna tiene masa mínima, de la de más oferta a la de menos."""
    contenders, rest = _rank(_offer(conn, concept_ids))
    return contenders + rest


def contending_verticals(conn: Connection, concept_ids: list[str]) -> list[str]:
    """Solo las verticales con masa mínima (o todas, si ninguna la tiene): las que compiten por la respuesta."""
    return _rank(_offer(conn, concept_ids))[0]


def typical_verticals(conn: Connection) -> dict[str, str]:
    """La vertical más típica de cada concepto (la primera de `ranked_verticals`), en una sola consulta."""
    offer: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for concept_id, vertical, items, vertical_items in conn.execute(SHARES):
        offer[concept_id].append((vertical, items, vertical_items))
    return {concept_id: _rank(rows)[0][0] for concept_id, rows in offer.items()}


def _offer(conn: Connection, concept_ids: list[str]) -> list[tuple[str, int, int]]:
    """(vertical, ítems de los conceptos, ítems de la vertical)."""
    return conn.execute(
        f"""SELECT vertical, sum(items)::integer, max(vertical_items)::integer FROM ({SHARES}) s
            WHERE concept_id = ANY(%s) GROUP BY vertical""",
        (concept_ids,),
    ).fetchall()


def _rank(offer: list[tuple[str, int, int]]) -> tuple[list[str], list[str]]:
    """(las que tienen masa mínima, el resto), por participación; si ninguna la tiene, todas por cantidad."""
    store_max = max((items for vertical, items, _ in offer if vertical != "restaurantes"), default=0)
    floor = max(MIN_ITEMS_TO_COMPETE, MIN_OFFER_SHARE * store_max)
    by_share = sorted(offer, key=lambda row: (-row[1] / row[2], row[0]))
    contenders = [row[0] for row in by_share if row[1] >= floor]
    if not contenders:
        return [row[0] for row in sorted(offer, key=lambda row: (-row[1], row[0]))], []
    return contenders, [row[0] for row in by_share if row[1] < floor]


LOGO_BASE_URL = "https://images.rappi.cl/marketplace/"  # el scraper guarda solo el archivo del logo
STORES_PER_VERTICAL = 2
MIN_ITEMS_ELSEWHERE = 20  # con pocos productos (p. ej. 10 pizzas en chocolaterías) no vale la pena mostrarla


def available_elsewhere(conn: Connection, concept_id: str, exclude: set[str], limit: int = 3) -> list[dict]:
    """Otras verticales con oferta del concepto, las de más oferta primero, con sus tiendas de más surtido.

    Aquí manda la cantidad ("¿dónde más lo encuentro?"), no la participación: una vertical chica donde el concepto
    pesa mucho no va antes que una grande con más productos. La elegibilidad (restaurantes solo para lo que se
    pide hecho) es la misma de `ranked_verticals`. Las tiendas salen de la vista materializada
    concept_store_assortment (migración 016): calcularlas en cada respuesta costaba hasta 2,5 s.
    """
    items = dict(
        conn.execute("SELECT vertical, items FROM concept_assortment WHERE concept_id = %s", (concept_id,)).fetchall()
    )
    eligible = [v for v in ranked_verticals(conn, [concept_id]) if v not in exclude and items[v] >= MIN_ITEMS_ELSEWHERE]
    verticals = sorted(eligible, key=lambda v: -items[v])[:limit]
    if not verticals:
        return []
    stores: dict[str, list[dict]] = {v: [] for v in verticals}
    rows = conn.execute(
        """SELECT vertical, store_name, logo FROM concept_store_assortment
           WHERE concept_id = %s AND vertical = ANY(%s)
           ORDER BY items DESC, store_name""",
        (concept_id, verticals),
    ).fetchall()
    # Una entrada por nombre (las sucursales se repiten) y sin repetir tienda entre verticales: las cadenas
    # grandes están en varias a la vez y la fila mostraría siempre las mismas.
    seen: set[str] = set()
    for vertical, name, logo in rows:
        if len(stores[vertical]) < STORES_PER_VERTICAL and name.lower() not in seen:
            seen.add(name.lower())
            stores[vertical].append({"name": name, "logo": LOGO_BASE_URL + logo if logo else None})
    for vertical, name, logo in rows:  # mejor una tienda repetida que una vertical sin tiendas
        if not stores[vertical]:
            stores[vertical].append({"name": name, "logo": LOGO_BASE_URL + logo if logo else None})
    return [{"vertical": v, "items": items.get(v, 0), "stores": stores[v]} for v in verticals]
