# Consultar la base `rappi` con SQL

La base es un **PostgreSQL 17 local** (Homebrew), no un archivo: sus datos viven en `/opt/homebrew/var/postgresql@17` y se consultan con SQL. No está en GitHub; para llevarla a otro Mac, ver [docs/instalacion.md](../instalacion.md).

[consultas.sql](consultas.sql) tiene 24 consultas probadas contra la base (todas de solo lectura, menos de 3 s), agrupadas en catálogo y precios, restaurantes, entre verticales y conceptos, y técnicas.

## Conectarse

Con TablePlus, Beekeeper Studio o la extensión "PostgreSQL" de VS Code:

| Campo | Valor |
|---|---|
| Host | `127.0.0.1` |
| Puerto | `5432` |
| Usuario | tu usuario de macOS |
| Contraseña | vacía |
| Base | `rappi` |

- **Solo lectura:** en la conexión, agrega como comando de inicio (TablePlus: *Bootstrap commands*) `SET default_transaction_read_only = on;`. Así un `DELETE` o `UPDATE` por error se rechaza.
- **Desde la Terminal:** `psql rappi` (en un Mac nuevo, primero deja `psql` en el PATH: ver [instalacion.md](../instalacion.md), paso 3). `\dt` lista las tablas, `\d tabla` muestra sus columnas, `\timing on` mide cada consulta y `\q` sale.

## Qué hay en cada tabla

| Tema | Tablas y vistas |
|---|---|
| Tiendas | `stores` (nombre, cadena, ciudad), `store_verticals` (vertical de cada tienda), `brands` |
| Catálogo | `catalog_items` (producto: nombre, marca, presentación), `categories`, `store_products` (qué tienda vende qué producto) |
| Precios | `price_snapshots` (historial), `latest_prices` (el último precio de cada oferta) y `store_last_snapshot` (el último snapshot de cada tienda y la última corrida de su formato), que mantienen triggers. Vistas: `v_latest_prices` (último precio), `v_latest_offers` (último precio y si está vigente), `v_price_compare` (un producto en cada tienda) |
| Restaurantes | `menu_items` (platos: `section_id` es la última sección del menú donde aparece y `extra_section_ids`, las otras, p. ej. «Más vendidos»), `menu_sections`, `menu_price_snapshots`, `restaurant_details` (nota, reseñas), `restaurant_cuisines` |
| Conceptos | `concepts` (taxonomía de Mochi), `item_concepts` (concepto de cada producto o plato), `concept_edges` (complementos), `concept_assortment` (surtido por concepto y vertical) |
| Búsqueda | `search_documents` (un documento por producto, plato o tienda, por vertical) |
| Usuarios y eventos | `app_users`, `app_events`, `app_orders`, `app_order_lines`: **simulados** (`source = 'synthetic'`) o del prototipo |
| Capa de datos | esquema `capa` (vistas estables; ver [capa-de-datos.md](../capa-de-datos.md)) |

## Buenas costumbres

- **`LIMIT` siempre** al listar filas: hay tablas con cientos de miles.
- **Nunca `SELECT *`** en `stores` o `store_products` (la columna `raw` es el JSON completo de la página), ni la columna `embedding` (768 números por fila).
- **Primero las vistas** (`v_…`): ya resuelven uniones difíciles, como "el último precio". Excepción: `v_vertical_summary` tarda unos 6 s (más de 20 s antes de la migración 017); la consulta 1.1 hace lo mismo en menos de 1 s.
- **Texto sin tildes:** `es_unaccent(columna) ILIKE es_unaccent('%cafe%')` encuentra "Café".
- **Consulta lenta:** anteponle `EXPLAIN (ANALYZE, BUFFERS)` para ver dónde se va el tiempo (consulta 4.5).
- **Exportar un resultado:** `\copy (SELECT …) TO '~/Desktop/archivo.csv' WITH (FORMAT csv, HEADER)` en `psql` (consulta 4.6), o el botón de exportar de la app.
