"""Listado público de tiendas de Rappi Chile (S3): ID, marca, ciudad y coordenadas de cada tienda."""

from urllib.parse import urlparse


def normalize_stores(metadata: dict) -> list[dict]:
    """Aplana `storesById` y limpia campos (algunas ciudades vienen con espacios)."""
    stores = []
    for raw in (metadata.get("storesById") or {}).values():
        if not raw.get("url") or raw.get("lat") is None or raw.get("lng") is None:
            continue
        stores.append(
            {
                "store_id": raw["storeId"],
                "brand": (raw.get("brandName") or "").strip(),
                "name": (raw.get("storeName") or "").strip(),
                "city": (raw.get("city") or "").strip(),
                "address": (raw.get("address") or "").strip(),
                "lat": raw["lat"],
                "lng": raw["lng"],
                "path": urlparse(raw["url"]).path,
                "reviews": (raw.get("review") or {}).get("total") or 0,
            }
        )
    return stores
