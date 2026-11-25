"""Parser de la página de un restaurante (`/restaurantes/<id>-<slug>`): datos y menú.

El menú son los carruseles `DynamicListRestaurantProductsCarousel`: uno por sección del menú (id positivo) y, arriba,
"Populares" (-3) y "Para Ti" (-13, armado para quien mira). Si la ubicación de despacho está fuera de la zona del
local, la página trae el menú entero en un solo carrusel "No disponible" (-404), sin secciones: no se toma, y el
restaurante sale sin platos (el pipeline prueba otra sucursal). Los datos del local vienen en el evento VIEW_STORE. La
página nueva no trae dirección, coordenadas, horarios, cocinas ni la descripción de cada plato (está en la página del
plato): esos campos quedan vacíos y no pisan lo guardado.
"""

from ..pricing import discount_pct
from .astro import Page, ParseError, analytics, canonical_path, components, json_ld, parse_errors

POPULAR_CAROUSEL = -3  # "Populares": marca los platos populares; no es una sección del menú


def _image(url: str | None) -> str:
    return (url or "").split("?", 1)[0]


@parse_errors
def parse_restaurant(page: Page) -> dict:
    view = analytics(page, "VIEW_STORE")
    if not view.get("STORE_ID"):
        raise ParseError("Página de restaurante sin datos del local (VIEW_STORE)")
    carousels = [props["component"] for props in components(page, "DynamicListRestaurantProductsCarousel")]
    popular = {
        int(entry["product"]["id"])
        for carousel in carousels
        if carousel.get("id") == POPULAR_CAROUSEL
        for entry in carousel.get("items") or []
    }

    sections, items = [], {}
    for carousel in (c for c in carousels if int(c["id"]) > 0):
        section_id = int(carousel["id"])
        sections.append({"section_id": section_id, "name": carousel.get("title") or "", "position": len(sections)})
        for entry in carousel.get("items") or []:
            p = entry["product"]
            pricing = p.get("pricing") or {}
            price = pricing.get("currentPrice")
            real_price = pricing.get("originalPrice") or price
            item = {
                "item_id": int(p["id"]),
                "section_id": section_id,
                "extra_section_ids": [],
                "name": (p.get("title") or "").strip(),
                "description": "",
                "image_url": _image(p.get("imageURL")),
                "is_popular": int(p["id"]) in popular,
                "has_toppings": bool(p.get("hasToppings")),
                "price": price,
                "real_price": real_price,
                "discount_pct": discount_pct(price, real_price),
                "is_available": bool(p.get("isEnabled")),
            }
            # Un plato en dos secciones: queda uno, con los datos de la última aparición y las demás secciones en
            # extra_section_ids (migración 040).
            if earlier := items.get(item["item_id"]):
                seen = [*earlier["extra_section_ids"], earlier["section_id"]]
                item["extra_section_ids"] = [s for s in seen if s != section_id]
            items[item["item_id"]] = item

    ld = json_ld(page, "Restaurant")
    store_id = int(view["STORE_ID"])
    return {
        "store": {
            "store_id": store_id,
            "name": view.get("STORE_NAME") or ld.get("name") or "",
            "brand_id": view.get("BRAND_ID"),
            "brand_name": view.get("BRAND_NAME") or view.get("STORE_NAME") or "",
            "store_type": view.get("STORE_TYPE") or "restaurant",
            "city": "",
            "address": "",
            "lat": None,
            "lng": None,
            "path": canonical_path(page) or f"/restaurantes/{store_id}",
        },
        "details": {
            "rating": view.get("RATING") or None,
            "review_count": view.get("RATINGS_AMOUNT"),
            "delivery_cost": view.get("SHIPPING_COST"),
            "eta": view.get("ETA") or "",
            "schedules": None,  # no viene: no pisa los horarios guardados
            "tags": [],
        },
        "cuisines": [],
        "sections": sections,
        "items": list(items.values()),
    }
