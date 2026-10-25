"""Parser de la página de un restaurante (`/restaurantes/<id>-<slug>`): datos, cocinas y menú."""

from ..pricing import discount_pct
from .next_data import ParseError, page_props, parse_errors

IMAGE_BASE_URL = "https://images.rappi.cl/products/"


def _restaurant_block(next_data: dict) -> dict:
    fallback = page_props(next_data).get("fallback") or {}
    for key, value in fallback.items():
        if key.startswith('@"restaurant/') and isinstance(value, dict):
            return value
    raise ParseError("Página sin fallback['@\"restaurant/...']")


def _section_id(corridor: dict, position: int) -> int:
    """El pasillo del menú no trae ID propio; se toma el `corridorId` de sus platos."""
    for product in corridor.get("products") or []:
        if product.get("corridorId"):
            return int(product["corridorId"])
    return -(position + 1)  # sección sin platos: ID sintético estable dentro del restaurante


@parse_errors
def parse_restaurant(next_data: dict) -> dict:
    r = _restaurant_block(next_data)
    location = r.get("location") or [None, None]  # viene como [lng, lat]
    rating = r.get("ratingData") or {}
    cuisines = sorted({t.strip() for t in (r.get("tags") or []) if t and t.strip()})

    sections, items = [], {}
    for position, corridor in enumerate(r.get("corridors") or []):
        section_id = _section_id(corridor, position)
        sections.append({"section_id": section_id, "name": corridor.get("name") or "", "position": position})
        for p in corridor.get("products") or []:
            price, real_price = p.get("price"), p.get("realPrice")
            item = {
                "item_id": int(p["id"]),
                "section_id": section_id,
                "extra_section_ids": [],
                "name": (p.get("name") or "").strip(),
                "description": (p.get("description") or "").strip(),
                "image_url": IMAGE_BASE_URL + p["image"] if p.get("image") else "",
                "is_popular": bool(p.get("isPopular")),
                "has_toppings": bool(p.get("hasToppings")),
                "price": price,
                "real_price": real_price,
                "discount_pct": discount_pct(price, real_price),
                "is_available": bool(p.get("isAvailable")),
            }
            # Rappi repite el plato en «Más vendidos» y en su sección: queda uno, con los datos de la última aparición
            # y las demás secciones en extra_section_ids (migración 040).
            if earlier := items.get(item["item_id"]):
                seen = [*earlier["extra_section_ids"], earlier["section_id"]]
                item["extra_section_ids"] = [s for s in seen if s != section_id]
                item["is_popular"] = item["is_popular"] or earlier["is_popular"]
            items[item["item_id"]] = item

    return {
        "store": {
            "store_id": int(r["id"]),
            "name": r.get("name") or "",
            "brand_id": r.get("brandId"),
            "brand_name": r.get("brandName") or r.get("name") or "",
            "store_type": r.get("storeType") or "restaurant",
            "city": r.get("city") or "",
            "address": r.get("address") or "",
            "lat": location[1],
            "lng": location[0],
            "path": page_props(next_data).get("canonicalPath") or f"/restaurantes/{r['id']}",
        },
        "details": {
            "rating": rating.get("score") or r.get("rating") or None,
            "review_count": rating.get("total_reviews"),
            "delivery_cost": r.get("deliveryPrice"),
            "eta": r.get("eta") or "",
            "schedules": r.get("schedules") or [],
            "tags": r.get("tags") or [],
        },
        "cuisines": cuisines,
        "sections": sections,
        "items": list(items.values()),
    }
