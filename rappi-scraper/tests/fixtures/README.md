# Fixtures de los tests

Páginas públicas de rappi.cl guardadas el 26-09-2026 **solo para probar los parsers** del scraper.

- Están reducidas al bloque `<script id="__NEXT_DATA__">`, que es lo único que leen los tests: no incluyen el resto del HTML, ni CSS, JS o trackers de la página.
- No son un respaldo del catálogo: son una página de muestra por tipo.
- Los tests las cargan con `load_page(nombre)` en [`../conftest.py`](../conftest.py), que extrae el JSON de `__NEXT_DATA__`. `FakeClient` sirve `store`, `aisle` y `subaisle` según la profundidad de la ruta pedida, y simula tiendas caídas, errores pasajeros y un sitio que bloquea (`blocked`: 403 a todo).
- Si Rappi cambia la estructura de sus páginas y los tests siguen pasando con estas, pero el scraper falla con páginas nuevas, hay que guardar una página actual del mismo tipo (reducida igual) y ajustar `src/rappi_scraper/scraping/*_parser.py` (ruta desde `rappi-scraper/`).

| Archivo | Tipo de página | Ruta de Next.js (campo `page`) |
|---|---|---|
| `store.html` | Portada de una tienda de supermercado, con sus pasillos | `/ssg/[friendly_url]` |
| `store_mall.html` | Portada de una tienda de Rappi Mall | `/ssg/[friendly_url]` |
| `aisle.html` | Pasillo de una tienda (lácteos y huevos), con sus sub-pasillos | `/ssg/[friendly_url]/[aisle_friendly_url]` |
| `subaisle.html` | Sub-pasillo de una tienda (yogurt), con sus productos | `/ssg/[friendly_url]/[aisle_friendly_url]/[subaisle_friendly_url]` |
| `listing_market.html` | Listado de tiendas del tipo market (`/tiendas/tipo/market`) | `/store/tipo/[parent_store_friendly_url]` |
| `listing_mall.html` | Listado de tiendas de Rappi Mall (`/tiendas/tipo/rappimall-parent`) | `/store/tipo/[parent_store_friendly_url]` |
| `restaurant.html` | Página de un restaurante, con su menú | `/restaurantes/ssg/[id]` |
| `brand_chain.html` | Página de una cadena de restaurantes, con sus sucursales | `/brands/[brand]` |

`robots.txt` es el de `https://www.rappi.cl/robots.txt` tal como estaba el 24-10-2026. `tests/unit/test_robots.py` comprueba con él que todo lo que pide el scraper está permitido; si Rappi lo cambia, se guarda el nuevo aquí y el test dice si algo dejó de estarlo.
