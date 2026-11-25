"""El juicio a mano de la muestra de búsqueda guardado en la base (tabla `search_judgments`, migración 063).

Es la misma muestra que la planilla CSV (`planilla-busqueda-ids.json`, ver `sheets.py`), juzgada a ciegas en "Juzgar la
búsqueda" del panel: cada par muestra la consulta y lo que se mostró (nombre, tienda o local, vertical, precio, foto y
categoría), sin el método, la posición ni lo que dijo un juez automático. Un juicio vigente por par y juez; volver a
juzgar lo reemplaza. `rappi-ia eval-human --desde-base` los lee en lugar de la planilla.
"""

import json
import random
import re
from pathlib import Path

from psycopg import Connection

from ..catalog.stores import IN_DEMO_CITY, demo_places
from .sheets import DEFAULT_SEED, SEARCH_IDS_FILE, VERDICTS, category_names

LEVELS = {level: label for label, level in VERDICTS.items()}  # 2 → "sirve"
JUDGE = re.compile(r"^[A-Za-z0-9_-]{0,16}$")  # lo mismo que el CHECK de la tabla
MIN_PRICE = 10  # como agent/tools.py: un precio de relleno ($0, $1) es desconocido


class UnknownPair(LookupError):
    """El id no es un par de la muestra."""


def sample(path: Path | None = None) -> list[dict]:
    """Los pares de la muestra, en un orden barajado fijo (semilla de la muestra): ni por id, ni por vertical, ni por
    posición."""
    document = json.loads((path or SEARCH_IDS_FILE).read_text(encoding="utf-8"))
    pairs = sorted(document["pares"], key=lambda p: p["id"])
    random.Random(document.get("semilla", DEFAULT_SEED)).shuffle(pairs)
    return pairs


def pairs_to_judge(conn: Connection, judge: str, path: Path | None = None) -> dict:
    """Lo que ve quien juzga: por par, la consulta y lo que se mostró, y su juicio vigente (o None). Nunca el método,
    la posición, el estrato ni `relevante_auto`. Un par cuyo producto ya no está en el catálogo de esta base no se
    puede juzgar: no va y se cuenta en `fuera_del_catalogo`."""
    pairs = sample(path)
    shown = _shown(conn, pairs)
    given = load(conn, judge)
    rows = [
        {
            "id": p["id"],
            "consulta": p["consulta"],
            "vertical": p["vertical"],
            **shown[key],
            "juicio": given.get(p["id"]),
        }
        for p in pairs
        if (key := (p["entity_type"], p["entity_id"], p["vertical"])) in shown
    ]
    return {"juez": judge, "muestra": len(pairs), "fuera_del_catalogo": len(pairs) - len(rows), "pares": rows}


def save(conn: Connection, pair_id: str, level: int, judge: str, path: Path | None = None) -> None:
    """Guarda (o reemplaza) el juicio del par para ese juez."""
    if pair_id not in {p["id"] for p in sample(path)}:
        raise UnknownPair(pair_id)
    conn.execute(
        """INSERT INTO search_judgments (pair_id, judge, level) VALUES (%s, %s, %s)
           ON CONFLICT (pair_id, judge) DO UPDATE SET level = EXCLUDED.level, updated_at = now()""",
        (pair_id, judge, level),
    )


def progress(conn: Connection, judge: str, path: Path | None = None) -> dict:
    """Cuántos pares de la muestra lleva juzgados ese juez, por valor, y cuántos cada juez."""
    ids = [p["id"] for p in sample(path)]
    in_sample = set(ids)
    given = {pair: level for pair, level in load(conn, judge).items() if pair in in_sample}
    per_judge = conn.execute(
        """SELECT judge, count(*) FROM search_judgments WHERE pair_id = ANY(%s)
           GROUP BY judge ORDER BY judge""",
        (ids,),
    ).fetchall()
    return {
        "juez": judge,
        "muestra": len(ids),
        "juzgados": len(given),
        "por_valor": {label: sum(level == value for level in given.values()) for value, label in LEVELS.items()},
        "jueces": [{"juez": name, "juzgados": n} for name, n in per_judge],
    }


def judges(conn: Connection) -> list[str]:
    return [name for (name,) in conn.execute("SELECT DISTINCT judge FROM search_judgments ORDER BY judge")]


def load(conn: Connection, judge: str) -> dict[str, int]:
    """{id de par: 2, 1 o 0} de ese juez: lo mismo que `sheets.read_search_sheet` devuelve de la planilla."""
    return dict(conn.execute("SELECT pair_id, level FROM search_judgments WHERE judge = %s", (judge,)).fetchall())


def _shown(conn: Connection, pairs: list[dict]) -> dict[tuple[str, str, str], dict]:
    """(tipo, id, vertical) → nombre, tienda, precio, imagen y categoría. Un producto lleva la oferta vigente más
    barata de una tienda de su vertical, con las de la ciudad de la demo primero (como la búsqueda); un plato, su local
    y su último precio. Sin oferta vigente, sin tienda ni precio."""
    found: dict[tuple[str, str, str], dict] = {}
    products = [(p["entity_id"], p["vertical"]) for p in pairs if p["entity_type"] == "catalog_item"]
    dishes = {p["entity_id"]: p["vertical"] for p in pairs if p["entity_type"] == "menu_item"}
    if products:
        for pid, vertical, name, presentation, image, store, price in conn.execute(
            f"""SELECT ci.master_product_id::text, q.vertical, ci.name, ci.presentation, NULLIF(ci.image_url, ''),
                       o.store, o.price
                FROM unnest(%(ids)s::bigint[], %(verticals)s::text[]) AS q(id, vertical)
                JOIN catalog_items ci ON ci.master_product_id = q.id
                LEFT JOIN LATERAL (
                    SELECT btrim(coalesce(b.name, s.name)) AS store, l.price
                    FROM store_products sp
                    JOIN v_latest_offers l ON l.store_id = sp.store_id AND l.sku = sp.sku
                    JOIN stores s ON s.store_id = sp.store_id
                    LEFT JOIN brands b ON b.brand_id = s.brand_id
                    WHERE sp.master_product_id = ci.master_product_id AND l.current AND l.in_stock IS NOT FALSE
                      AND EXISTS (SELECT 1 FROM v_store_verticals v
                                  WHERE v.store_id = s.store_id AND v.vertical = q.vertical)
                    ORDER BY {IN_DEMO_CITY} DESC, l.price, s.store_id
                    LIMIT 1) o ON true""",  # noqa: S608 (constante)
            {
                "ids": [int(pid) for pid, _ in products],
                "verticals": [vertical for _, vertical in products],
                "places": demo_places(),
            },
        ):
            found[("catalog_item", pid, vertical)] = _card(name, store, price, image, presentation)
    if dishes:
        for iid, name, image, store, price in conn.execute(
            """SELECT mi.item_id::text, mi.name, NULLIF(mi.image_url, ''), s.name, mp.price
               FROM menu_items mi JOIN stores s USING (store_id)
               LEFT JOIN latest_menu_prices mp ON mp.item_id = mi.item_id
               WHERE mi.item_id = ANY(%s::bigint[])""",
            ([int(i) for i in dishes],),
        ):
            found[("menu_item", iid, dishes[iid])] = _card(name, store, price, image, None)
    categories = category_names(conn, pairs)
    for (etype, eid, _), card in found.items():
        card["categoria"] = categories.get((etype, eid))
    return found


def _card(name, store, price, image, presentation) -> dict:
    return {
        "nombre": name,
        "presentacion": presentation or None,
        "tienda": store,
        "precio": float(price) if price is not None and price >= MIN_PRICE else None,
        "imagen": image,
    }
