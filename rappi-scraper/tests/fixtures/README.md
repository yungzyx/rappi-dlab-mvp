# Fixtures de los tests

Páginas públicas de rappi.cl guardadas el 25-11-2026, con el sitio ya en Astro, **solo para probar los parsers** del scraper.

- Cada archivo es la página y sus islas de contenido (lo que devuelve `RappiClient.get_page`), reducidas a lo que leen los parsers: el JSON-LD, los eventos de analítica, los enlaces a los pasillos y unos pocos componentes `<astro-island>` con 2 o 3 productos o platos cada uno. Sin el resto del HTML, CSS, JS ni trackers.
- No son un respaldo del catálogo: son una página de muestra por tipo.
- Los tests las cargan con `load_page(nombre)` en [`../conftest.py`](../conftest.py). `FakeClient` sirve `aisle` para las rutas de pasillo (`…/sub_aisles?aisle_id=N`) y `store` para las demás, y simula tiendas caídas, errores pasajeros y un sitio que bloquea (`blocked`: 403 a todo). `with_section` le suma una sección al menú de un restaurante.
- Si Rappi cambia la estructura de sus páginas y los tests siguen pasando con estas, pero el scraper falla con páginas nuevas, hay que guardar una página actual del mismo tipo (reducida igual) y ajustar `src/rappi_scraper/scraping/*_parser.py` (ruta desde `rappi-scraper/`).

| Archivo | Página | Isla |
|---|---|---|
| `store.html` | Portada de Lider (900025946): sus 10 pasillos enlazados y 2 bloques de productos | `StoreContent` |
| `store_small.html` | Portada de una tienda sin pasillos enlazados (900090302) | `StoreContent` |
| `aisle.html` | Pasillo Lácteos y Huevos de Lider, con 3 sub-pasillos | `AisleDetailContent` |
| `restaurant.html` | Restaurante Rincón Venezolano (384): "Para Ti", "Populares" y 3 secciones del menú | `SingleRestaurantDetail` |
| `listing_market.html` | Listado de supermercados (`/tiendas/tipo/market`, que redirige a `/tiendas/supermercado`): 2 grupos | `CPGStoresContent` |

`robots.txt` es el de `https://www.rappi.cl/robots.txt` tal como estaba el 25-11-2026. `tests/unit/test_robots.py` comprueba con él que todo lo que pide el scraper (también las islas) está permitido; si Rappi lo cambia, se guarda el nuevo aquí y el test dice si algo dejó de estarlo.
