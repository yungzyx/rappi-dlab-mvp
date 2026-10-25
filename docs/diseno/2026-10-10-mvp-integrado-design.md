# MVP integrado: base de datos, RAG, Mochi, buscador, ofertas y juego conectados

> Especificación · 10-10-2026 · Construido en 7 etapas, del 10 al 11-10-2026.
> Lo que cambió después: el juego y el pasaporte salieron el 16-10-2026 ([diseño del motor](2026-10-16-motor-multivertical-design.md)), Mochi responde por `POST /agent/ask` en vez de `/chat` y no tiene voz ni foto ([decisiones](../decisiones.md#agente-mochi)). Las partes del juego quedan como registro del diseño original.

## 1. Para qué

Hoy el repo tiene un buen cerebro y una buena cara que casi no se hablan:

- El **RAG** está en Postgres y en la API de rappi-ia. Incluye catálogo, conceptos, embeddings, grafo de complementos, «También en» y la capa de datos con atributos, marcas y segmentos.
- La **app** (Mochi, el buscador, las ofertas y el juego) funciona casi entera con reglas locales sobre un catálogo transcrito de capturas. Solo usan la API la respuesta de Mochi en `/chat`, el perfil y el registro de eventos. El HTML suelto del escritorio no llega a la API.

El repo pasa a contener **un MVP funcional** donde todo está conectado:

- **Mochi** es la cara que genera cercanía.
- **El RAG** es su segundo cerebro.
- **Jev** mejora ese cerebro fuera de línea.
- **El catálogo** que se ve, el que Mochi ofrece y el que se pide es uno solo.
- **Lo que hace la persona** vuelve a la base y cambia lo que Mochi le ofrece después.

### Decisiones de partida (10-10-2026)

| Tema | Decisión |
|---|---|
| Productos en las pantallas | Catálogo real de la base (imagen y precio de Postgres) |
| Sin API | API obligatoria: la app muestra «sin conexión»; se eliminan las reglas locales de Mochi |
| Alcance extra | Jev en el proceso semanal y el panel de negocio conectado. Voz y foto quedan fuera |
| Arquitectura | Enfoque A: una sola API (rappi-ia) extendida; la app es solo cliente |

### Criterios de éxito (del MVP completo)

1. **Un comando** (`make mvp`) levanta la base (si está instalada), aplica migraciones y arranca la API, la app y el panel. La app abre en el prototipo final, conectada.
2. **Ningún producto, kit, complemento, dato curioso ni desafío sale de un archivo local de la app.** Todo viene de la API. Los módulos locales (`data/catalog.js`, `screens/*/data.js`, `assistant/brain.js`, `assistant/tags.js`, `screens/home/live/script.js`, `game/knowledge.json`, `data/verticales.json`) dejan de existir.
3. **Un recorrido completo funciona contra la base real y queda en eventos:**
   1. buscar;
   2. ver una oferta de Mochi;
   3. agregar al carrito;
   4. pedir;
   5. jugar una ronda;
   6. ver el uso en el panel (fuente «prototipo»).
4. **Las guardias siguen igual.** Mochi nunca propone por su cuenta Farmacia, salud, bebé ni alcohol. Los segmentos sensibles nunca se usan para ofrecer. La búsqueda no se personaliza.
5. **Cada etapa termina con tests verdes en CI**, revisión en el navegador y una revisión de código independiente.

## 2. Arquitectura

```
rappi.cl ─(domingos, scraper)→ Postgres «rappi»  ←─ Jev (fuera de línea, etapa 7)
                                   │ catálogo · conceptos · embeddings · capa · conocimiento · juego · eventos
                                   ▼
                      API rappi-ia :8000  (RAG + agente Mochi + catálogo + ofertas + juego + perfil)
                          ▲                         ▲
            app :5174 (Rappi hoy / Prototipo final)   panel :5175 (eventos reales y simulados, separados)
```

- **Una base** (`rappi`) con **un solo historial de migraciones**, en `rappi-scraper/src/rappi_scraper/storage/migrations/` como hoy. Las tablas nuevas tienen comentarios en español.
- **Una API** (rappi-ia, FastAPI). Se agregan routers por dominio: `catalog`, `mochi` (ofertas), `game`, junto a los que ya existen (`chat`, `search`, `profile`, `events`, `orders`, `analytics`). La lógica vive en módulos de dominio (`rappi_ia/catalog/`, `rappi_ia/offers/`, `rappi_ia/game/`); los routers solo traducen HTTP.
- **La app** (prototipo-app) es solo cliente. `src/api/` concentra todas las llamadas, con tiempo límite y errores tipados.
  - Las pantallas no llaman a `fetch` directo.
  - «Rappi hoy» sigue existiendo, con el catálogo real y sin Mochi.
- **El usuario seudónimo** que ya existe para los eventos une búsqueda, carrito, pedidos, juego y perfil. No hay cuentas.
- **Se pierde el HTML suelto del escritorio como demo.** Para mostrar el MVP hay que correr `make mvp`. Las imágenes vienen del CDN público de Rappi, así que la demo necesita internet.

## 3. Contrato de la API

### Producto (forma única en todas las respuestas)

```json
{ "id": "catalog_item:123", "entity_type": "catalog_item", "name": "…", "price": 4990,
  "previous_price": 5990, "image": "https://images.rappi.cl/…", "vertical": "supermercado",
  "store": { "id": 900, "name": "…" }, "concept": "cerveza" }
```

- `entity_type` es `catalog_item` o `menu_item`.
- `price` sale siempre de SQL, nunca del embedding.
- `previous_price` solo viene cuando hay una baja real (`v_price_changes`).

### Catálogo (`/catalog`, solo lectura)

| Endpoint | Para qué |
|---|---|
| `GET /catalog/verticals/{v}/stores` | Tiendas de una vertical: imagen, tiempo estimado, cuántos productos tiene |
| `GET /catalog/stores/{id}?aisle=&page=` | Tienda con sus pasillos y sus productos, por páginas |
| `GET /catalog/restaurants?cuisine=` | Restaurantes |
| `GET /catalog/restaurants/{id}/menu` | Menú por secciones |
| `GET /catalog/deals?vertical=` | Ofertas: bajas de precio reales |
| `GET /catalog/products/{entity_type}/{id}` | Detalle |

La ciudad queda fija en Santiago (Región Metropolitana) para la demo; el filtro por ciudad sigue pendiente aparte.

### Búsqueda

`GET /search`, que ya existe, ahora agrupa por vertical y devuelve `sin_resultado` y `also_in`. La app consulta a los 250 ms de la última tecla. «Preguntar a Mochi» usa `POST /chat`, que ya existe.

### Ofertas de Mochi

`POST /mochi/offer`, con cuerpo `{ moment, user_id, …contexto }`:

| `moment` | Contexto | Qué decide el motor (`rappi_ia/offers/`) |
|---|---|---|
| `plan` | `occasion?` | El kit de una de las 15 ocasiones de `taxonomy.toml`: un producto por concepto, de la vertical donde es típico |
| `carrito` | línea agregada | Un complemento en otra vertical (grafo «complementa»), o nada |
| `checkout` | carrito | El mismo motor, **solo cuando la persona lo pide** |
| `sin_resultado` | consulta | La vertical que sí lo tiene («También en») |
| `proximo_pedido` | pedido entregado | Un complemento de lo pedido |
| `vertical_por_probar` | — | La primera vertical sin sello; la etapa 5 la ordena por afinidad |

- **Respuesta:** `{ moment, text, products[], vertical, reason, actions[] }`. Si no hay nada bueno que ofrecer, devuelve **204** y Mochi se queda callado.
- **Textos:** plantillas en español con tests. Claude solo redacta en `/chat`, como hoy, y es opcional.
- **Guardias:** viven en el servidor y tienen tests. Nunca se propone por cuenta propia Farmacia, salud, bebé ni alcohol (ni Licores).
- **Eventos:** cada oferta mostrada o aceptada se registra (`mochi_offer_shown`, `mochi_offer_accepted`, con `moment` en el payload).

### Juego

| Endpoint | Para qué |
|---|---|
| `GET /game/cards?vertical=` | Tarjetas de conocimiento con su fuente |
| `GET /game/challenge?vertical=&seed=` | Desafío del catálogo armado en vivo |
| `GET /game/state/{user_id}` · `PUT /game/state/{user_id}` | Progreso guardado por usuario |

### Errores

- Lo que bloquea la pantalla (catálogo, carrito, pedido, ronda) muestra «sin conexión» con un botón para reintentar.
- Si falla una oferta, Mochi no dice nada.
- Ninguna parte de la app tiene respaldo local.

## 4. Etapas

Cada etapa se integra a `main` por separado, con sus tests.

### Etapa 1: base del MVP

- `make mvp` en la raíz:
  - revisa que Postgres responda y que la base `rappi` exista; si no, explica cómo cargarla;
  - aplica migraciones;
  - arranca la API (:8000), la app (:5174) y el panel (:5175).
- `make mvp-check` levanta la API sobre `rappi_ia_test` con el catálogo de prueba, más la app, y recorre el flujo con Playwright. Crece con cada etapa.
- El cliente de la API (`src/api/`) tiene tiempo límite, errores tipados y usuario compartido. Una pantalla «sin conexión» reemplaza el respaldo local.
- **Catálogo de prueba inventado:** unas pocas tiendas y productos por vertical, con nombres de prueba, nunca copiados del catálogo descargado. Lo usan los tests de integración y `mvp-check`.
- **Contrato:** los tests de integración del backend escriben respuestas de ejemplo en `prototipo-app/src/api/fixtures/`. Los tests de la app las usan, y el CI revisa que estén al día.
- **Hecho cuando:** sin API, la app muestra «sin conexión», no reglas locales; `make mvp` y `make mvp-check` funcionan; README y `docs/instalacion.md` reemplazan «Sin base de datos (unos 2 minutos)» por `make mvp`.

### Etapa 2: catálogo real

- Endpoints de `/catalog` y pantallas que los usan: verticales, tiendas, restaurantes y menús, Turbo, ofertas, detalle, carrito y pedido.
- Las imágenes vienen de la base: 71.831 productos y 179.353 platos, todos con imagen.
- Los tiles de la Home llevan a verticales reales.
- Los pedidos van a `/orders` con ids reales.
- Se van los catálogos transcritos (`screens/*/data.js`, `data/catalog.js`, `data/home.js` en lo que es catálogo).
- **Hecho cuando:** cada producto visible tiene un id de la base; un pedido aparece en `app_orders` con `source = 'prototype'`.

### Etapa 3: buscador y Mochi sobre el RAG

- El buscador usa `/search`, agrupado y con «sin resultado».
- Mochi responde con `/chat`.
- Todos los momentos de ofertas usan `/mochi/offer`: kits de la Home, comentario del carrito, «¿Me falta algo?», «sin resultados», «armar el próximo», la vertical por probar y Mochi flotante.
- Se van `brain.js`, `tags.js`, `script.js`, `emptySearch.js`, `discover.js` y `CheckoutSuggestion` local.
- **Hecho cuando:** cada oferta tiene un test del motor (incluidas las guardias) y otro de pantalla con las respuestas de ejemplo; los eventos de ofertas llegan a la base.

### Etapa 4: conocimiento y juego en el RAG

- **Tarjetas en la base:**
  - las 108 tarjetas viven en `rappi-ia` como archivo versionado (contenido propio, no descargado);
  - `rappi-ia knowledge` las carga en `knowledge_cards` y `knowledge_card_concepts`;
  - la carga se puede repetir sin duplicar y corre dentro de `post-refresh`.
  
  La liga con conceptos se hace por reglas (palabras clave del concepto), con una revisión a mano registrada. La validación del contenido pasa a pytest.
- **Desafíos en vivo:** se arman desde `concept_assortment`, `concept_edges` y `knowledge_edges` (lo típico, qué combina, qué nunca va junto). Se van `verticales.json` y `scripts/extraer-datos.mjs`.
- **Progreso por usuario** en la base (`game_state`): sellos, tarjetas, XP, racha. Las reglas del juego (XP, niveles, misión, armar la ronda) siguen en la app, que ya tiene sus tests.
- **«¿Sabías que…?» en Mochi:** `/chat` agrega `did_you_know` cuando el concepto buscado tiene una tarjeta no vista. Mostrarla cuenta como descubierta.
- **Hecho cuando:**
  - un progreso guardado en el navegador se migra una vez al servidor;
  - la ronda funciona con datos de la base;
  - Mochi muestra un dato ligado a lo buscado.

### Etapa 5: personalización con la capa

- **Entradas:** el perfil por eventos, `user_segments` y las marcas compradas (`item_brands`). Los segmentos del usuario se recalculan después de cada pedido; hoy solo se recalculan los domingos.
- **Salidas:**
  - `vertical_por_probar` se ordena por afinidad;
  - `plan` ordena las ocasiones por interés;
  - el complemento prefiere la marca que compras cuando existe.
  
  Cada oferta trae `reason`, que la app muestra como «por qué».
- **Guardias con test:**
  - los segmentos sensibles (salud, alergias, edad; columna `sensitive` en `segment_defs`) nunca se usan para ofrecer;
  - la búsqueda no se personaliza;
  - «Olvidar» borra perfil, segmentos y estado del juego.
- **Hecho cuando:** dos usuarios de prueba con historias distintas reciben ofertas distintas, y la razón de cada una se puede rastrear.

### Etapa 6: panel conectado

- El panel ya separa las fuentes `synthetic` y `prototype`. Suma métricas de lo nuevo:
  - ofertas mostradas y aceptadas por momento;
  - rondas y tarjetas del juego;
  - búsquedas sin resultado.
- El uso real se rotula «uso del MVP, pocas personas: no es evidencia». Nunca se mezcla con lo simulado.
- **Hecho cuando:** el recorrido de `mvp-check` se ve en el panel con la fuente «prototipo».

### Etapa 7: Jev en el proceso semanal

1. **Sin clave:**
   - las planillas para juzgar: 200 pares de búsqueda (`eval-sample` / `eval-human`) y 100 categorías;
   - el cliente fino de Jev, opcional, en `rappi_ia/jev.py`, probado con un `FakeJev`;
   - la caché `eval_judgments`.
2. **Con la clave de TypeSafe y las planillas juzgadas:** el piloto (menos de 1 US$), con los criterios de [jev.md](../jev.md).
   - Juez de búsqueda: κ ≥ 0,6 y mayor que la del juez por concepto.
   - Etiquetado de categorías: precisión ≥ 90 % y cobertura ≥ 50 %.
3. **Si pasa:**
   - `map-categories` va antes de `concepts` en `post-refresh`;
   - el juez se guarda en caché;
   - Jev puede ligar tarjetas a conceptos;
   - el diagrama `rag-datos` se regenera con Jev.

   Sin clave, todo sigue igual. Jev nunca reordena resultados en vivo.
- **Queda a cargo del responsable del proyecto:** juzgar las planillas, crear la cuenta en TypeSafe y poner `TYPESAFE_API_KEY`. Lo demás queda listo antes.

## 5. Pruebas y revisión

- **Backend:** pytest, unitario e integración contra `rappi_ia_test` (los tests se niegan a usar otra base). Cada endpoint nuevo tiene un test de forma y otro de reglas.
- **App:** vitest con las respuestas de ejemplo del contrato. Las reglas del juego conservan sus tests.
- **De punta a punta:** `make mvp-check` con Playwright sobre la base de prueba.
- **Por etapa:**
  1. TDD;
  2. `make test` y `make lint` (rappi-scraper y rappi-ia);
  3. `npm test` y `npm run lint` (app y panel);
  4. revisión en el navegador a 375 × 812 y en escritorio;
  5. una revisión de código independiente, con los arreglos críticos e importantes hechos con un test que falle primero;
  6. CI en verde antes de integrar.
- **Documentación por etapa:** README, `docs/demo.md`, `docs/decisiones.md`, `docs/instalacion.md` y los diagramas que cambien.

## 6. Reglas que no cambian

- Código en inglés; lo que ve el usuario, en español.
- No se suben datos descargados a GitHub. El catálogo de prueba es inventado.
- Nunca dos descargas a la vez contra rappi.cl (candado `scraper.lock`). `make mvp` no descarga nada.
- `build_search_documents` borra lo que no regenera, así que las tablas nuevas (conocimiento, juego) son propias.
- Datos de usuarios: solo `source = 'synthetic'` o `'prototype'`; las métricas simuladas nunca se presentan como evidencia.

## 7. Fuera de alcance

- Voz y foto de Mochi (`/chat/voice` y `/chat/photo` existen, pero no se conectan).
- Cuentas de usuario, pagos reales y despliegue en la nube.
- Filtro por ciudad (la demo usa Santiago).
- Jev en vivo, o reordenando resultados.

## 8. Riesgos

| Riesgo | Mitigación |
|---|---|
| Endpoints de catálogo lentos sobre 250 mil ítems | Paginación, índices existentes, medir p95 en `mvp-check` (meta: < 300 ms local) |
| La app y la API se desalinean | Respuestas de ejemplo generadas por el backend; el CI revisa que estén al día |
| Imágenes del CDN de Rappi no cargan sin internet | Imagen de reemplazo neutra; la demo se hace con internet |
| Segmentos recalculados en cada pedido son lentos | Recalcular solo los del usuario, en segundo plano; medir |
| Cambios grandes difíciles de revisar | Una etapa por vez, con commits separados por pieza |
| Jev no pasa el piloto | Se reporta «lo medimos y no alcanzó»; todo sigue sin Jev |
