"""Parser de los listados de tiendas por vertical (`/tiendas/tipo/<v>`, que redirige a `/tiendas/supermercado`, …).

El listado trae las primeras filas de tiendas (`DynamicListHorizontalStoreScroller`, una por grupo: "Mercados",
"Tiendas Express"…); el resto lo carga el navegador desde /api, que robots.txt no permite: no se pide.
"""

from .astro import Page, components, parse_errors


@parse_errors
def parse_vertical_listing(page: Page) -> list[dict]:
    """Tiendas del listado, una vez cada una, con el nombre de su grupo en `landing_classification`."""
    stores: dict[int, dict] = {}
    for props in components(page, "DynamicListHorizontalStoreScroller"):
        group = props["component"]
        for raw in group.get("stores") or []:
            store_id = int(raw["id"])
            stores.setdefault(
                store_id,
                {
                    "store_id": store_id,
                    "name": raw.get("name") or "",
                    "store_type": raw.get("storeType") or "",
                    "subvertical": "",
                    "landing_classification": group.get("title") or "",
                    "path": raw.get("href") or f"/tiendas/{store_id}",
                    "filters": [],
                },
            )
    return list(stores.values())
