"""Parsers de la portada de una tienda (`/tiendas/<id>-<slug>`) y de sus pasillos
(`/tiendas/<vertical>/<formato>/<id>-<slug>/sub_aisles?aisle_id=<id>`).

La portada trae algunos pasillos con sus primeros productos y los enlaces a los pasillos; cada pasillo, sus primeros
sub-pasillos con sus primeros productos. Lo demás lo carga el navegador desde /api, que robots.txt no permite: no se
pide. Los productos salen con las claves de antes (`product_id`, `real_price`, `in_stock`…), las que lee el resto del
pipeline.
"""

import html
import re
import unicodedata
from urllib.parse import urlsplit

from .astro import Page, ParseError, analytics, components, json_ld, parse_errors

_AISLE_LINK_RE = re.compile(r'<a href="([^"]*/sub_aisles\?aisle_id=(\d+))"[^>]*>(.*?)</a>', re.S)
_HEADING_RE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)


def slugify(text: str) -> str:
    """'Mantequillas y margarinas' -> 'mantequillas-y-margarinas' (igual que las URLs de Rappi)."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


@parse_errors
def parse_store(page: Page) -> dict:
    """Datos de la tienda: del buscador de la tienda (`SearchBarOverlay`), del evento VIEW_STORE_TYPE y del JSON-LD.
    Sin ciudad ni dirección: la página nueva no las trae, y un campo vacío no pisa lo guardado."""
    [overlay, *_] = components(page, "SearchBarOverlay") or [{}]
    view = analytics(page, "VIEW_STORE_TYPE")
    store_id = overlay.get("storeId") or view.get("STORE_ID")
    if not store_id:
        raise ParseError("Página de tienda sin datos de la tienda (SearchBarOverlay ni VIEW_STORE_TYPE)")
    ld = json_ld(page, "Store")
    geo = ld.get("geo") or {}
    return {
        "store_id": int(store_id),
        "name": overlay.get("storeName") or view.get("STORE_NAME") or ld.get("name") or "",
        "address": "",
        "city": "",
        "brand_id": overlay.get("brandId") or None,
        "brand_name": (ld.get("brand") or {}).get("name") or overlay.get("storeName") or "",
        "store_type": overlay.get("storeType") or view.get("STORE_TYPE") or "",
        "sub_group": view.get("VERTICAL_SUB_GROUP") or "",
        "lat": geo.get("latitude"),
        "lng": geo.get("longitude"),
        # Ruta canónica de la tienda, p. ej. "/tiendas/900025946-lider".
        "path": urlsplit(ld["url"]).path if ld.get("url") else page.path,
    }


@parse_errors
def parse_aisles(page: Page) -> list[dict]:
    """Pasillos enlazados desde la portada: [{aisle_id, name, friendly_url, product_count, path}]. La página no dice
    cuántos productos tiene cada uno (`product_count` None)."""
    aisles, seen = [], set()
    for match in _AISLE_LINK_RE.finditer(page.html):
        aisle_id = int(match.group(2))
        heading = _HEADING_RE.search(match.group(3))
        if aisle_id in seen or not heading:
            continue
        seen.add(aisle_id)
        name = html.unescape(re.sub(r"<[^>]+>", "", heading.group(1))).strip()
        aisles.append(
            {
                "aisle_id": aisle_id,
                "name": name,
                "friendly_url": slugify(name),
                "product_count": None,
                "path": html.unescape(match.group(1)),
            }
        )
    return aisles


@parse_errors
def parse_sub_aisles(page: Page) -> list[dict]:
    """Sub-pasillos de una página de pasillo, con sus productos: [{aisle_id, name, friendly_url, product_count,
    products}]. Ya no tienen página propia. Una página sin ninguno no es la del pasillo (p. ej. llegó un listado)."""
    if not _aisle_components(page):
        raise ParseError("Página de pasillo sin sub-pasillos (DynamicListAisle)")
    return [
        {
            "aisle_id": int(component["id"]),
            "name": component["title"],
            "friendly_url": slugify(component["title"]),
            "product_count": None,
            "products": [_product(item) for item in component.get("items") or [] if _is_product(item)],
        }
        for component in _aisle_components(page)
    ]


@parse_errors
def parse_products(page: Page) -> list[dict]:
    """Todos los productos de la página (portada o pasillo), en el formato de antes."""
    return [
        _product(item)
        for component in _aisle_components(page)
        for item in component.get("items") or []
        if _is_product(item)
    ]


def _aisle_components(page: Page) -> list[dict]:
    return [props["component"] for props in components(page, "DynamicListAisle")]


def _is_product(item: dict) -> bool:
    return item.get("type") == "cpg_product_item" and bool(item.get("id"))


def _image(url: str | None) -> str:
    """Sin los parámetros de tamaño y formato (`?e=webp&d=300x300…`): la misma URL que guardaba la página anterior."""
    return (url or "").split("?", 1)[0]


def _product(item: dict) -> dict:
    """Un producto de `DynamicListAisle` con las claves de la página anterior (las que guardan `save_products` y
    `store_products.raw`). No vienen `quantity`, `stock` ni `category_name`."""
    image_url = _image(item.get("imageURL"))
    step = item.get("discountStep") or {}
    return {
        "id": f"{item['storeId']}_{item['id']}",
        "product_id": str(item["id"]),
        "master_product_id": item.get("masterProductId"),
        "category_id": item.get("categoryId"),
        "name": item.get("name") or "",
        "description": item.get("description") or "",
        "presentation": item.get("presentation") or "",
        "trademark": item.get("trademark") or "",
        "unit_type": item.get("unitType") or "",
        "sale_type": item.get("saleType") or "",
        "product_type": item.get("productType") or "",
        "image": image_url.rsplit("/", 1)[-1] if image_url else "",
        "image_url": image_url,
        "images": [_image(url) for url in item.get("images") or []],
        "price": item.get("price"),
        "real_price": item.get("realPrice"),
        "balance_price": item.get("balancePrice"),
        "real_balance_price": item.get("realBalancePrice"),
        "pum": item.get("pum") or "",
        "discount": item.get("discount"),
        "have_discount": bool(item.get("haveDiscount")),
        "discount_type": item.get("discountType") or "",
        "have_complex_discounts": bool(item.get("haveComplexDiscounts")),
        "complex_discounts": item.get("complexDiscounts"),
        "discount_step": {
            "type": step.get("type") or "",
            "discount": step.get("discount") or 0,
            "min_units": step.get("minUnits") or 0,
            "label": step.get("label") or "",
            "price": step.get("price") or 0,
        },
        "in_stock": bool(item.get("inStock")),
        "is_available": bool(item.get("isAvailable")),
        "has_toppings": bool(item.get("hasToppings")),
        "is_sponsored": bool(item.get("isSponsored")),
        "requires_medical_prescription": bool(item.get("requiresMedicalPrescription")),
        "age_restriction": bool(item.get("ageRestriction")),
        "has_antismoking": bool(item.get("hasAntismoking")),
        "alcoholic_beverage": bool(item.get("alcoholicBeverage")),
        "attributes": item["attributes"] if isinstance(item.get("attributes"), dict) else {},
        "store_id": item["storeId"],
        "store_type": item.get("storeType") or "",
    }
