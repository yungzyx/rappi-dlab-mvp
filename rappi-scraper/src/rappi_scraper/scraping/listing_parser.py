"""Parsers de listados: tiendas por vertical (`/tiendas/tipo/<v>`) y cadenas de restaurantes."""

from .next_data import ParseError, page_props


def _catalog_block(next_data: dict) -> dict:
    fallback = page_props(next_data).get("fallback") or {}
    for key, value in fallback.items():
        if "cpgs-catalog" in key:
            return value
    raise ParseError("Listado sin fallback['cpgs-catalog']")


def parse_vertical_listing(next_data: dict) -> list[dict]:
    """Tiendas de un listado de vertical.

    Junta dos fuentes: los grupos (`storeGroups`, con nombre y tipo de tienda) y los
    filtros (`filters`, solo IDs), porque algunos filtros traen tiendas que no están
    en ningún grupo (p. ej. Moda o Vapes en Rappi Mall).
    """
    stores: dict[int, dict] = {}
    for group in _catalog_block(next_data).get("storeGroups") or []:
        for raw in group.get("stores") or []:
            store_id = int(raw["storeId"])
            stores.setdefault(
                store_id,
                {
                    "store_id": store_id,
                    "name": raw.get("name") or "",
                    "store_type": raw.get("storeType") or "",
                    "subvertical": raw.get("subvertical") or "",
                    "landing_classification": group.get("landing_classification") or "",
                    "path": "/tiendas/" + raw["friendlyURL"] if raw.get("friendlyURL") else f"/tiendas/{store_id}",
                    "filters": [],
                },
            )

    for listing_filter in page_props(next_data).get("filters") or []:
        for raw_id in listing_filter.get("stores") or []:
            store_id = int(raw_id)
            entry = stores.setdefault(
                store_id,
                {
                    "store_id": store_id,
                    "name": "",
                    "store_type": "",
                    "subvertical": "",
                    "landing_classification": "",
                    "path": f"/tiendas/{store_id}",
                    "filters": [],
                },
            )
            entry["filters"].append(listing_filter.get("name") or listing_filter.get("id") or "")
    return list(stores.values())


def parse_brand_chain(next_data: dict) -> dict:
    """Página de cadena de restaurantes (`/restaurantes/delivery/<id>-<slug>`)."""
    brand = page_props(next_data).get("brand")
    if not brand:
        raise ParseError("Página de cadena sin pageProps.brand")
    return {
        "brand_id": brand["id"],
        "name": brand.get("name") or "",
        "stores": [
            {
                "store_id": int(s["storeId"]),
                "name": s.get("name") or "",
                "path": s.get("friendlyUrl") or f"/restaurantes/{s['storeId']}",
                "address": s.get("address") or "",
            }
            for s in brand.get("stores") or []
        ],
    }
