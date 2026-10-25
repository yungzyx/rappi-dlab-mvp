"""Parsers de páginas de tienda, pasillo y sub-pasillo (`/tiendas/<id>-<slug>[/<pasillo>[/<sub>]]`)."""

import re
import unicodedata

from .next_data import ParseError, components, page_props, parse_errors


def _storefront_entry(next_data: dict) -> tuple[str, dict]:
    """Entrada `fallback["storefront/<slug>"]`, presente en páginas de tienda, pasillo y sub-pasillo."""
    fallback = page_props(next_data).get("fallback") or {}
    for key, value in fallback.items():
        if key.startswith("storefront/"):
            return key, value
    # Qué página llegó en su lugar, solo por el nombre de cada clave ('store_information/<id>' o
    # '@"cpgs-catalog","market",0,'): sin ids, para que el reporte agrupe el error por texto.
    names = sorted({re.split(r'[/",]', key.lstrip('@"/'))[0] for key in fallback})
    raise ParseError(f"No se encontró fallback['storefront/...'] (claves: {', '.join(names) or 'ninguna'})")


def _storefront(next_data: dict) -> dict:
    return _storefront_entry(next_data)[1]


def slugify(text: str) -> str:
    """'Mantequillas y margarinas' -> 'mantequillas-y-margarinas' (igual que las URLs de Rappi)."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


@parse_errors
def parse_store(next_data: dict) -> dict:
    ctx = page_props(next_data).get("storeContext")
    if not ctx:
        raise ParseError("Página de tienda sin storeContext")
    key, _ = _storefront_entry(next_data)
    return {
        "store_id": ctx.get("store_id"),
        "name": ctx.get("name") or "",
        "address": ctx.get("address") or "",
        "city": ctx.get("city") or "",
        "brand_id": ctx.get("brand_id") or None,
        "brand_name": page_props(next_data).get("brandName") or ctx.get("name") or "",
        "store_type": ctx.get("store_type") or "",
        "sub_group": ctx.get("sub_group") or "",
        "lat": ctx.get("lat"),
        "lng": ctx.get("lng"),
        # Ruta canónica de la tienda, p. ej. "/tiendas/900025946-lider".
        "path": "/tiendas/" + key.removeprefix("storefront/"),
    }


@parse_errors
def parse_aisles(next_data: dict) -> list[dict]:
    """Pasillos de la tienda: [{aisle_id, name, friendly_url, product_count}]."""
    tree = _storefront(next_data).get("aisles_tree_response")
    return [
        {
            "aisle_id": c["resource"].get("id"),
            "name": c["resource"]["name"],
            "friendly_url": c["resource"]["friendly_url"],
            "product_count": c.get("product_count") or 0,
        }
        for c in components(tree)
        if (c.get("resource") or {}).get("friendly_url")
    ]


@parse_errors
def parse_sub_aisles(next_data: dict) -> list[dict]:
    """Sub-pasillos de una página de pasillo: [{aisle_id, name, friendly_url, product_count}].

    La lista completa viene en `sub_aisles_response_extras.aisle.categories` pero sin
    friendly_url; solo los primeros sub-pasillos renderizados lo traen, al resto se le
    genera desde el nombre.
    """
    storefront = _storefront(next_data)
    rendered = {
        c["resource"]["id"]: c["resource"].get("friendly_url")
        for c in components(storefront.get("sub_aisles_response"))
        if (c.get("resource") or {}).get("id")
    }
    extras = storefront.get("sub_aisles_response_extras") or {}
    categories = (extras.get("aisle") or {}).get("categories") or []
    return [
        {
            "aisle_id": cat.get("id"),
            "name": cat["name"],
            "friendly_url": rendered.get(cat.get("id")) or slugify(cat["name"]),
            "product_count": cat.get("product_count") or 0,
        }
        for cat in categories
        if cat.get("name")
    ]


@parse_errors
def parse_products(next_data: dict) -> list[dict]:
    """Todos los productos renderizados en la página (tienda, pasillo o sub-pasillo), tal como vienen."""
    products = []
    for key, response in _storefront(next_data).items():
        if not key.endswith("_response") or not isinstance(response, dict):
            continue
        for component in components(response):
            products.extend((component.get("resource") or {}).get("products") or [])
    return products
