# La capa de datos para otras herramientas

La base guarda lo que Rappi publica. Esta capa le suma **significado**: qué es cada producto, de qué marca, cuánto trae, qué atributos tiene, con qué se relaciona y qué tipo de persona lo compra. Está pensada para que la búsqueda, las recomendaciones, el panel y cualquier herramienta futura lean lo mismo sin repetir el trabajo.

Todo lo que ve una herramienta externa vive en el esquema **`capa`**: vistas con nombres y columnas estables, comentadas en español. Las tablas internas pueden cambiar; las vistas no.

## Qué contiene

| Pieza | Qué responde | Dónde se define |
|---|---|---|
| **Medidas** | "¿Cuánto trae?": cantidad, unidad base (g, ml, und), pack y total; marca las medidas que parecen un error de Rappi | `rappi_ia/layers/measures.py` |
| **Atributos** | "¿Qué es?": 83 atributos en 9 familias (sin gluten, vegano, familiar, premium, para perro…) con fuente y confianza | `concepts/attributes.toml` |
| **Marcas y producto canónico** | "¿De qué marca?" y "¿es el mismo producto en otra tienda o vertical?" | `concepts/brands.toml`, `layers/brands.py`, `layers/canonical.py` |
| **Grafo de conocimiento** | "¿Con qué se relaciona?": complementa, sustituye, es de la ocasión, se vende en, tiene el atributo, marca de, sinónimo… | `concepts/relations.toml`, `layers/graph.py` |
| **Segmentos de usuario** | "¿Qué tipo de persona es?": 144 segmentos por comportamiento en 12 familias, con puntaje, nivel y evidencia | `concepts/segments.toml`, `layers/segments.py` |
| **Motor multivertical** | "¿Qué vertical conviene sumarle?" y "¿qué le toca pedir de nuevo?": afinidad por vertical, transiciones, combinaciones de verticales con su retención, compra cruzada, tendencias y recompra | `rappi_ia/motor/`, `motor/combos.toml` |

Los conceptos (la taxonomía propia de 136 conceptos: 116 tipos de producto en 20 grupos, contados el 16-10-2026) vienen de la capa de IA y son el eje que une todo.

## Vistas de `capa`

| Vista | Una fila es… | Para qué sirve |
|---|---|---|
| `capa.items` | un ítem (producto o plato) en una vertical | Punto de entrada: nombre, concepto, marca, canónico, medida y precio |
| `capa.item_attributes` | un atributo de un ítem | Filtrar por "sin gluten", "vegano", "familiar"… con fuente y evidencia |
| `capa.item_unit_prices` | el precio por kilo, litro o unidad de un ítem | Comparar precios de verdad (un sobre de 15 g es barato en la góndola y caro por gramo) |
| `capa.unit_price_ratios` | un ítem frente a la mediana de su concepto | Detectar precios mal cargados |
| `capa.item_brands` | la marca de un ítem | Marcas unidas ("Coca-Cola" = "COCA COLA") y marcas propias de tienda |
| `capa.canonical_products` | un producto canónico | El mismo producto con distintos ids de Rappi o en varias verticales |
| `capa.knowledge_edges` | una arista del grafo | Relaciones entre conceptos, atributos, marcas, verticales y segmentos (sin lo aprendido de datos simulados) |
| `capa.segment_defs` | un segmento | Su definición y su regla |
| `capa.user_segments` | un segmento de una persona | A qué segmentos pertenece cada persona (sin los sensibles) |
| `capa.segment_sizes` | un segmento, semana y nivel | Cuántas personas hay en cada segmento (los sensibles solo con 5 o más) |
| `capa.user_vertical_affinity` | un vertical de una persona | Cuánto le interesa cada vertical, con sus pedidos y señales (personal) |
| `capa.vertical_transitions` | un paso de un vertical a otro, por fuente | Qué vertical pide la gente después de otro |
| `capa.combo_stats` | una combinación de verticales, por fuente y `nivel` | La tabla de Rappi medida con los datos propios, en dos niveles (`grueso`: grupos; `fino`: verticales una por una): personas-mes, pedidos, gasto y retención al mes siguiente |
| `capa.combo_steps` | un paso de una combinación a otra al mes siguiente, por fuente y `nivel` | Qué pasa con quien usa "rest" (o "restaurantes") el mes siguiente |
| `capa.cross_sell_rules` | una regla "quien pide A en un vertical pide B en otro", por fuente | Compra cruzada con confianza y lift |
| `capa.trends` | un vertical, concepto o producto, por fuente | Lo más pedido y lo que sube (4 semanas contra las 4 anteriores) |
| `capa.replenishment` | un concepto que una persona recompra | Cada cuántos días y cuándo le toca de nuevo (personal) |
| `capa.layer_runs` | una corrida de una capa | De dónde viene cada dato: qué reglas, cuándo y cuántas filas |
| `capa.v_carros_abandonados` | un carro abandonado (personal) | Carros con algo adentro, sin pedido 60 minutos después de su último evento, y si llegaron a pagar |
| `capa.v_embudo_sesion` | una sesión (personal) | Si vio una lista, tocó algo, agregó al carro, fue a pagar y pidió, con su modo y sus variantes |
| `capa.v_ctr_posicion` | un lugar de una lista, por fuente, modo y pantalla | Impresiones, clics y CTR por posición (sin conceptos sensibles): el sesgo de posición |
| `capa.v_eventos_amplitude` | un evento (personal) | Nuestros eventos con los nombres y el sobre del plan de tracking de Rappi ([equivalencias](#impresiones-experimentos-y-vistas-derivadas)) |

Cada vista y cada columna tienen comentario: `\d+ capa.items` en `psql` los muestra.

### Ejemplos

Los diez productos sin gluten más baratos por kilo en supermercado:

```sql
SELECT i.name, i.brand_name, p.price_per_kg
FROM capa.items i
JOIN capa.item_attributes a USING (entity_type, entity_id)
JOIN capa.item_unit_prices p USING (entity_type, entity_id, vertical)
WHERE a.attribute_id = 'sin-gluten' AND i.vertical = 'supermercado' AND p.price_per_kg IS NOT NULL
ORDER BY p.price_per_kg LIMIT 10;
```

En qué verticales se vende un concepto y qué lo sustituye:

```sql
SELECT relation, to_kind, to_id, round(weight::numeric, 2) AS peso
FROM capa.knowledge_edges
WHERE from_kind = 'concept' AND from_id = 'cafe' AND relation IN ('se_vende_en', 'sustituye', 'complementa')
ORDER BY relation, weight DESC;
```

Cuántas personas simuladas tiene cada segmento de comida en la última foto semanal (los datos de `synthetic` son simulados):

```sql
SELECT segment_name, level, users
FROM capa.segment_sizes
WHERE family = 'comida' AND source = 'synthetic' AND week = (SELECT max(week) FROM capa.segment_sizes)
ORDER BY users DESC LIMIT 10;
```

## Cómo se arma

`make layers` en `rappi-ia/` corre las capas en este orden (unos 70 segundos con el catálogo completo). `make post-refresh` lo incluye después de cada descarga semanal, junto con conceptos, embeddings, evaluación y datos simulados:

1. `measures`: tamaño, unidad y pack de cada ítem.
2. `brands`: marca canónica de cada ítem.
3. `canonical`: el mismo producto entre ids y verticales.
4. `attributes`: atributos (usan medidas y marcas).
5. `relations`: grafo de conocimiento.
6. `segments`: segmentos de cada persona, una vez por fuente (`synthetic` y `prototype`), con la foto semanal.
7. `motor`: el motor multivertical, una vez por fuente (ver abajo). También se evalúa por fechas y escribe `data/eval/motor-{fuente}.md`.

Cada paso corre en una transacción, es **idempotente** (correrlo dos veces deja lo mismo) y deja una fila en `layer_runs` (las capas, solo si terminan: una que falla se deshace con su transacción y no deja fila; el motor, en cambio, deja también su corrida en curso y la que falla, marcada `failed`) con la versión de las reglas (la fecha más una huella de su contenido: dos corridas con la misma huella usaron exactamente las mismas reglas). `make layer-report` genera `data/eval/capas.md`: cobertura por atributo y vertical, fuentes, medidas dudosas, marcas, canónicos, distribución de segmentos y una muestra de 20 ítems por atributo para revisar a ojo.

## Motor multivertical

Responde dos preguntas por persona: **qué vertical conviene sumarle** y **qué concepto le toca pedir de nuevo**. Vive en `rappi-ia/src/rappi_ia/motor/` (`model.py` son funciones puras; `data.py` lee la base; `build.py` escribe las tablas; `predict.py` responde por persona; `evaluate.py` mide) y se corre con `make motor` (o `rappi-ia motor [--source synthetic|prototype] [--sin-evaluar]`; `make layers` lo corre al final, y con él `make post-refresh`). Es otra capa más: deja su corrida en `layer_runs` con la fuente, los pesos y la evaluación. A diferencia de las otras capas, confirma primero una fila `running` (ya con su fuente, por si se corta) y, si falla, deja la fila marcada `failed` (con la fuente y la clase del error). Las tablas de población van en una sola transacción (si falla antes de confirmarla, no cambia nada); las de cada persona, después, en lotes con el mismo candado por persona que "Olvidar" y el recálculo después de un pedido: a quien olvidaron a mitad de la corrida, o la purga está borrando, la salta sin tocar sus filas, y relee los datos de cada persona dentro del candado, así no deshace un "Olvidar" de un concepto.

| Tabla y vista | Qué guarda | Cómo se calcula |
|---|---|---|
| `user_vertical_affinity` | Cuánto le interesa cada vertical a una persona | Suma de señales de los últimos 180 días, cada una con su peso por 0,5 elevado a (días / 30): pedido 5, agregar al carro 1,5, abrir el vertical (`vertical_open`) 1, ver una tienda 1, buscar 0,5, ver un ítem 0,3. Guarda también los pedidos y señales de la ventana |
| `vertical_transitions` | Qué vertical pide una persona después de otro | Pedidos consecutivos de la misma persona, con suavizado de Laplace (+1) sobre los 8 verticales. Un carro repartido en dos verticales (mismo `cart_id`) no es una transición |
| `combo_stats` | La tabla de Rappi medida con los datos propios | Por persona y mes calendario (hora de Santiago), la combinación usada, en dos niveles (columna `nivel`): `grueso`, los grupos (`rest`, `turbo`, `retail`, en ese orden, unidos por "+"), y `fino`, los verticales del catálogo uno por uno (`restaurantes+turbo+supermercado+mall…`, en el orden de `FINE_ORDER`; solo con pedidos: RappiFavor y RappiTravel no aparecen). Para cada una: % de personas-mes y de pedidos, pedidos y gasto por persona-mes y retención al mes siguiente, medida solo en los meses cuyo mes siguiente está completo (`retention_n`). Quien lea el nivel grueso debe filtrar `nivel = 'grueso'`: los dos comparten tabla y algunos nombres (`turbo`) |
| `combo_steps` | De qué combinación pasan a cuál al mes siguiente | Sobre los mismos meses con mes siguiente completo, en los dos niveles; quien no vuelve pasa a "ninguna" |
| `cross_sell_rules` | "Quien pide A en X pide B en Y" | B dentro de los 14 días después de A, en otro vertical **y en otro carro**; al menos 10 personas y lift sobre 1,2. Las líneas de B que vinieron de una sugerencia del agente no cuentan, ni los conceptos sensibles |
| `trends` | Lo más pedido y lo que sube | Las 4 semanas que terminan en el último pedido contra las 4 anteriores, por vertical, concepto y producto (los 50 más pedidos de cada vertical). `growth` = (ahora − antes) / max(antes, 5); sin conceptos sensibles |
| `replenishment` | Qué concepto recompra una persona y cuándo le toca | Al menos 3 días de compra distintos e intervalos regulares (variación ≤ 0,6); intervalo mediano y fecha del próximo. Sin conceptos sensibles |

Solo cuentan los pedidos confirmados: uno cancelado (`app_orders.status = 'cancelado'`, evento `order_cancelled`, migración 050) no entra a ninguna de estas tablas, ni a la recompra, el "volver", los segmentos o el panel de negocio (tampoco su `order_placed`, que sigue en `app_events`), y cancelarlo recalcula a la persona como un pedido nuevo, llegue la cancelación por `/events` o por el beacon. Un pedido cancelado no se califica.

### Población y persona

- **Población** (`vertical_transitions`, `combo_stats`, `combo_steps`, `cross_sell_rules`, `trends`): cada fila lleva `data_source` (`synthetic` o `prototype`) y las dos nunca se mezclan en un mismo cálculo. Cada corrida reemplaza las filas de su fuente. La predicción por persona lee la población que diga `config.MOTOR_POBLACION` (variable de entorno `MOTOR_POBLACION`; por defecto `synthetic`, porque con pocas personas del prototipo no hay patrón que aprender). Mientras sea `synthetic`, lo que el motor recomienda sale de patrones simulados y así se declara; con personas reales del prototipo se cambia en una variable.
- **Persona** (`user_vertical_affinity`, `replenishment`): se arman solo con los pedidos y señales de esa persona y se van con ella (`ON DELETE CASCADE`: "Olvidar" las borra). Sus vistas traen `source` (`synthetic` o `prototype`, de `app_users.source`, como `capa.user_segments`), y la de recompra no trae conceptos sensibles. Para una persona del prototipo se recalculan solas después de cada `POST /orders` (en segundo plano) y de "Olvidar"; a las simuladas las arma `make motor`. La afinidad que usa la predicción se calcula en vivo con las señales de la persona, así que no depende de cuándo corrió el motor.
- **Ranking de verticales**: puntaje = a × afinidad (normalizada, suma 1) + b × P(vertical | último vertical pedido) + c × popularidad (cuota de pedidos de los últimos 28 días). Con a = 1, `rappi-ia motor` elige b y c en una grilla por nDCG@8 en un tramo de validación y los guarda en la corrida; sin 84 días de pedidos o sin nadie a quién validar conserva los de la corrida anterior de la fuente (los de partida, 1 / 0,3 / 0,1, si no hay).

### Guardias

- **Farmacia y Licores solo suben por señales propias de la persona**: no reciben peso de transiciones ni de popularidad, así que ningún patrón de otras personas los empuja.
- **Ningún concepto sensible** (los marcados `sensitive`, ver Privacidad) entra a compra cruzada, tendencias de concepto y de producto ni recompra.
- Lo que pasa en "Rappi hoy" no enseña: solo entran pedidos `mode = 'propuesta'` y ningún evento con `payload.mode = 'actual'`.

### La tabla de Rappi como punto de partida

`motor/combos.toml` guarda la tabla de combinaciones que compartió el equipo de Rappi (cohortes de enero a junio de 2026, Chile): para cada combinación de grupos, personas, % de personas y de pedidos, pedidos y gasto por persona y retención al mes siguiente. Es una **correlación, no un efecto**: quien pide mucho usa más verticales y además vuelve más. El motor la toma como punto de partida para decidir qué grupo sumarle a una persona (el que más sube la retención esperada), y mezcla esa retención con la aprendida de la población, que pesa lo que pesan sus personas frente a 100 "personas" de Rappi, y solo cuando la combinación tiene al menos 30.

La tabla viene con una agrupación gruesa de Rappi (`rest`, `turbo`, `retail`). La asignación de los verticales del proyecto a esos grupos es un **supuesto propio**: `retail` junta supermercado, conveniencia, farmacia, licores, mall y chocolatería; RappiFavor, que no tiene catálogo, queda fuera.

### La escalera fina

La escalera no se detiene en los tres grupos: razona con las verticales una por una (`combos.FINE_ORDER`: las 8 del catálogo, más RappiFavor y RappiTravel). La retención esperada de una combinación fina (`expected_fine_retention`) parte de la gruesa de sus grupos (la tabla de Rappi mezclada con lo aprendido, como arriba) y aplica un **supuesto propio**, no de Rappi (`[rendimiento_decreciente]` en `combos.toml`): cada vertical extra dentro de un grupo reduce la parte que no vuelve, la j-ésima en `reduccion_base · decaimiento^(j−2)` (la 2.ª un 10 %, la 3.ª un 5 %, la 4.ª un 2,5 %…), y cada servicio usado, en `servicio` (5 %). Queda 1 − (1 − gruesa)·Π(1 − f): sube siempre que se suma algo dentro de un grupo, nunca llega a 1 y no tiene tope. Farmacia y Licores cuentan para el grupo (son uso propio de la persona), pero nunca son paso. Solo con servicios, RappiFavor parte de la fila "favor" de Rappi y RappiTravel solo no tiene base. Con al menos 30 personas de una combinación fina (`combo_stats`, `nivel = 'fino'`) y de su grupo, lo aprendido fino solo corrige la diferencia dentro del grupo; el nivel lo pone la combinación gruesa: la estimación aprendida es la gruesa mezclada más (fina aprendida − gruesa aprendida del grupo), y pesa n/(n + 100) frente a la esperada con el supuesto; sin gruesa aprendida, se mezcla tal cual. Un objetivo del mismo grupo sin fina aprendida parte de la combinación actual y solo le aplica la reducción del supuesto, así que una corrección aprendida no detiene la escalera. Así, con datos reales el supuesto se reemplaza solo.

El paso (`next_fine_step`) es la vertical que más sube esa retención, entre las que el agente puede ofrecer y en el orden de preferencia de la persona (`next_verticals`), que desempata; RappiFavor y RappiTravel solo si ninguna vertical del catálogo suma. Lo aprendido no da vuelta la tabla de Rappi por poco: si el paso que más suma con lo aprendido es uno que la tabla sola (con el supuesto, sin lo aprendido) pone después de otro que también suma, solo gana si suma al menos 2 puntos más de retención esperada (`[margen_tabla]` en `combos.toml`, otro **supuesto propio**); si no, el paso es el de la tabla y la `basis` lo rotula `+supuesto`. Dentro de un grupo la tabla no ordena, así que ahí decide lo aprendido. Sin el margen, a quien solo pide Restaurantes la escalera le proponía Express antes que Turbo por una décima de punto de retención simulada. La combinación de la persona es la de sus pedidos de los últimos 30 días y los servicios que abrió (`service_opened`); sin pedidos en 30 días, la de 90, y sin pedidos en 90 no hay paso.

**Sobre `synthetic`, la retención fina aprendida es circular:** el generador simula la supervivencia con la misma retención fina esperada (`events/synth.py`, SUPUESTOS), así que lo que el motor aprende de los simulados repite el supuesto con ruido. No es evidencia de que sumar una vertical dentro de un grupo retenga.

### Cómo se usa en las ofertas

`motor/recommend.py` arma las recomendaciones conectadas con tres tablas de población: `trends` (lo más pedido por vertical y concepto) y `cross_sell_rules` (las reglas "quien pide A en X pide B en Y"), mezcladas en `cross_picks`: `popularidad × (1 + λ·max(0, lift − 1))`. El λ se elige en validación (`rappi-ia motor`; uno mayor reemplaza al menor solo si suma al menos 5 aciertos más) y queda en la corrida; con λ = 0 la mezcla es solo lo más pedido, y sin corrida vale 1. `combo_stats` (los dos niveles) junto a la tabla de Rappi y el supuesto deciden qué vertical sumarle a la persona (`motor/predict.py:target_step`, [la escalera fina](#la-escalera-fina)); la oferta `vertical_por_probar` y el complemento del carro los leen. El OnTop de Turbo (momento `ontop`) usa `cross_picks` solo en Turbo, con su plazo y su envío como supuestos (`rappi+supuesto`). La `basis` de la oferta declara la fuente del paso: `rappi`, `rappi+supuesto`, `rappi+poblacion:<fuente>` o `rappi+supuesto+poblacion:<fuente>`, según si pesaron el supuesto y lo aprendido de la población. Todo se limita a la población que diga `MOTOR_POBLACION`, y ningún concepto sensible entra.

### Qué esperar de las cifras

`rappi-ia motor` mide el modelo por fechas (entrenar, validar y probar) contra líneas base y escribe un informe por fuente en `rappi-ia/data/eval/motor-{fuente}.md`; la última corrida sobre datos simulados está en [resultados/simulados-2026-11-04.md](resultados/simulados-2026-11-04.md), y [resultados/motor-2026-10-16.md](resultados/motor-2026-10-16.md) queda como la anterior, con el detalle de las etapas. El paso de la escalera fina se mide aparte: entre quienes suman una vertical en la prueba (sin contar Farmacia ni Licores), si el paso calculado antes de la prueba es una de las que sumó, contra la vertical que más personas sumaron en los 28 días anteriores; el informe dice además cuántas personas deciden la diferencia (solo acierta el paso, solo la línea base) y su McNemar exacto. La recompra se mide contra la mediana de los intervalos del concepto en la población (en las mismas predicciones, con su McNemar, y como regla simple: 3 días de compra o más, sin filtro de variación) y contra el intervalo propio sin el filtro (la cobertura que cuesta `REPLENISH_MAX_CV`). "¿Volvemos a…?" (`offers/winback.py`) se mide como quién calificaba el día en que empieza la prueba y qué parte vuelve al concepto o a la vertical en esos 28 días, contra lo que tenía el mismo atraso y no calificaba (ponderado por semana de atraso); sin grupo al que no se le ofrezca, no mide el efecto de invitar. Sobre `synthetic` mide la mecánica, no el efecto, porque el generador ya supone que sumar verticales retiene (ver [decisiones.md](decisiones.md#datos-simulados-y-panel)).

## Datos simulados y datos reales

- Los productos, precios, atributos, marcas y el grafo del catálogo son **reales** (de rappi.cl).
- Las personas y sus eventos son **simulados** (`source = 'synthetic'`) o del prototipo (`'prototype'`). Los simulados muestran la mecánica, no evidencia: las vistas de `capa` marcan la fuente y `capa.knowledge_edges` oculta lo aprendido de ellos. Nunca se mezclan fuentes en un mismo cálculo. Las tablas del motor sí muestran lo aprendido de `synthetic` (cada fila lleva su `data_source`), a diferencia de `capa.knowledge_edges`; lo que se aprende de ahí se declara y se rotula como simulado.

## Eventos de la app y su sobre

Los eventos de la app (`app_events`) llevan, desde la migración 043, el mismo sobre que los de la app de Rappi: con eso un clic se une con la respuesta que lo originó y se puede medir por pantalla y por posición. La comparación con Rappi y la tabla de equivalencias están en [investigacion/app-rappi-2026-10-25.md](investigacion/app-rappi-2026-10-25.md#3-equivalencias-de-eventos).

| Columna | Qué es | Quién la pone |
|---|---|---|
| `client_event_id` | Id del evento (uuid). Un lote reintentado no lo duplica: `(user_id, client_event_id)` es único y la inserción hace `ON CONFLICT DO NOTHING` | La app |
| `client_ts` | Hora del evento en la app. Se guarda solo si está a menos de 24 horas de la llegada; `ts` sigue siendo la llegada | La app |
| `seq` | Orden del evento en su sesión (0 el primero) | La app |
| `surface` | Pantalla donde estaba lo que se tocó, se vio o se agregó: `home`, `search`, `store`, `vertical`, `restaurants`, `turbo`, `deals`, `favorites`, `list`, `agent`, `cart`, `checkout`, `tracking` u `orders` | La app |
| `origin` | Bloque o lista: `accesos`, `accesos-grandes`, `resultados`, `pasillo`, `menu`, `cerca-de-ti`, `restaurantes-rapidos`, `mejor-evaluados`, `tiendas-populares`, `para-ti`, `agent-<momento>`, `agent-ask`… | La app |
| `position` | Lugar en la lista (0 el primero): el orden en que la API la devolvió (en la búsqueda, de corrido entre los grupos) o el de la fila tal como se ve (los accesos de la Home) | La app |
| `request_id` | Id de la respuesta de la API de donde salió lo que se tocó. En `search` es el id de la búsqueda | La API lo da; la app lo repite |

- **`request_id`**: `/search`, `/agent/offer`, `/agent/ask`, `/recommendations`, `/profile/{id}/verticales` y `/catalog/home` lo devuelven en su cuerpo. Es el mismo id de la línea del request en el log y de su cabecera `X-Request-ID` (`api/logs.py`), así que también une el evento con el log. La API simulada de la demo sin conexión devuelve uno propio (`offline-…`).
- **El origen de antes**: hasta la migración 043 el origen de las sugerencias iba en `payload.origen`. Las filas viejas lo siguen teniendo ahí, y un cliente de antes que lo mande así llena igual la columna (`events/store.py`, `_origin`). Quien lea el origen lee `coalesce(origin, payload ->> 'origen')`: así lo hacen `offers/winback.py`, `agent/tools.py`, `analytics/queries.py` y `make mvp-check`.
- **La búsqueda** guarda además `payload.alcance` (`global` o `vertical`; `tienda` queda para cuando haya búsqueda dentro de la tienda) y `payload.fuente` (`tipeada`, `sugerencia` o `correccion`: lo buscado tal cual desde el aviso de corrección).
- **`recommendation_click`**: abrir un producto (en su hoja o en su tienda) que vino de Mochi (`agent-*`) o de "Para ti" (`para-ti`), una vez por pestaña, respuesta y producto. Suma al interés como estaba definido en `WEIGHTS` (2).
- **En la app**, un solo lugar arma el sobre: `prototipo-app/src/api/attribution.js`. Las pantallas marcan sus listas con `placeList` (cada elemento queda con su `placement`) y los eventos lo leen con `placementFields`; `envelope` arma los campos de un evento suelto y omite lo que la API rechazaría. Las fases siguientes del plan usan este mismo ayudante.
- **Después del pedido** (migración 044): `order_rated` es la calificación de un pedido entregado (`payload.stars` de 1 a 5 y, con 3 o menos, `payload.reasons`: `tarde`, `faltante`, `mal_estado`, `equivocado`, `repartidor` u `otro`; el pedido es su carro, `cart_id`). En modo `propuesta` también queda en los pedidos de ese carro (`app_orders.rating`, `rating_reasons`, `rated_at`) y una de 3 o menos pausa 30 días la recompra, el "volver" y el "Pedir por mí" de sus conceptos y tiendas (`offers/winback.py:paused`, supuesto propio; "Pedir por mí" lo deja para revisar antes); en "Rappi hoy" queda solo como evento. `reorder` es "Pídelo de nuevo": el carro armado con un pedido anterior (`payload.available` y `payload.unavailable`, cuántas líneas seguían o no a la venta en su tienda, y `payload.kept` si había productos en el carro y se mantuvieron), con `origin` `pidelo-de-nuevo`; cada línea agregada es además un `cart_add` de ese origen. Las líneas de pedido guardan su tienda (`app_order_lines.store_id`). La disponibilidad sale de `POST /catalog/availability` (`v_latest_offers` y `latest_menu_prices`).
- **Flujos del pedido** (migración 050): `order_cancelled` es la cancelación de un pedido por la persona (`payload.reason`: `direccion`, `pago`, `demora`, `productos`, `ya_no` u `otro`; `payload.stage`: `antes_de_tienda`, `en_tienda` o `programado`; `payload.fee` con `basis` `supuesto` si tuvo un costo de ejemplo; el pedido es su carro, `cart_id`, y su tienda, `payload.store_id`, o sin tienda su vertical). En los dos modos deja el pedido `app_orders.status = 'cancelado'` con `cancelled_at` y `cancel_reason`; un pedido cancelado no cuenta para el motor ni la recompra. `order_rated` también elige su pedido por `payload.store_id`. Un pedido puede traer su franja programada (`scheduled_for`) y su tipo de entrega (`delivery_type`: `basica`, `sin_prisa` o `prioritaria`; los montos son de ejemplo), y cada línea de Súper o Turbo qué hacer si se agota (`app_order_lines.substitution`: `sustituto`, `elijan` o `reembolso`). El agotado en vivo, el atraso y la ayuda son de demostración y no se guardan.
- **Mochi y la Home** (migración 052): `vertical_reorder_shown` es la explicación de Mochi al mover los accesos de la Home (el acceso que más subió en `vertical`, su lugar nuevo en `position`, el de antes en `payload.antes`, `origin` `agent-reorden` y el `request_id` de `/profile/{id}/verticales`); no enseña al motor. `agent_visibility` es ocultar a Mochi o traerlo de vuelta (`payload.visible`; `origin` `menu-mochi` o `cuenta`) y también silenciarlo por hoy o despertarlo (`payload.quiet` true o false, con `visible` en true porque sigue a la vista; `origin` `menu-mochi` o, al tocar su pestañita, `pestana-silencio`; sin migración). En Amplitude, un silencio sale como `MVP_AGENT_VISIBILITY` con `VISIBLE` true y, desde la migración 058, `QUIET` (true al silenciar, false al volver a hablar); ocultar y mostrar no lo llevan. El panel los cuenta en "¿Mochi molesta?" (`/analytics/presencia`); el "Panel de la demo" de la demo sin conexión también manda `agent_visibility`, con `origin` `panel-demo`.
- **El "¿Por qué?" de las ofertas** (migración 053): la mostrada (`suggestion_shown`) lleva en `payload.basis` de qué sale su "¿Por qué?", los tipos de `reason.basis` (`recompra`, `busqueda`, `perfil`…, sin repetir y hasta 4), y `offer_why_open` es abrir ese "¿Por qué?" (el origen de la oferta, el concepto de su razón en `concept_id` y los mismos tipos en `payload.basis`). Solo los tipos, nunca el texto ni los ids: pueden traer lo que la persona escribió, y el payload no pasa por la redacción ni la purga de las consultas. No enseña al motor. El porqué de los accesos movidos de la Home no es una oferta y no se anota. Lo lee `rappi-ia resumen-prueba` ([prueba-usuarios.md](prueba-usuarios.md)).
- **La pregunta in-app de la H3** (migración 057): `survey_shown` (la app mostró la pregunta), `survey_answer` (la respuesta) y `survey_dismissed` (la cerró sin responder). Todos llevan `payload.question` (`p1`, "¿Encontraste lo que buscabas?", o `p3`, "¿Confías en las sugerencias de Mochi?"), `payload.trigger` (`busqueda`: tocó un resultado; `carro`: agregó algo de lo que encontró; `abandono`: buscó sin tocar nada; `porque`: la p3, tras abrir un "¿Por qué?") y `payload.mochi` (si Mochi estaba a la vista); la respuesta, `payload.answer` (`si`, `en_parte` o `no` en la p1; un entero de 1 a 5 en la p3). La búsqueda que la originó va en `request_id` y la pantalla en `surface`. Solo códigos, sin texto libre: la API rechaza el lote con una pregunta, una respuesta o un motivo fuera de la lista (`events/store.py`: `SURVEY_*`). Viven en `app_events` (sin tabla nueva): "Borrar mis datos" y la purga de inactivas se los llevan con la persona. No enseñan al motor. El panel los lee con `/analytics/encuesta` y la pregunta, sus topes y cuándo sale están en [diseno-ia.md](diseno-ia.md#la-pregunta-de-la-h3).
- **El reintento**: la app reintenta un lote que no llegó (sin red, sin respuesta, 429 o 5xx), con una cola de 200 eventos como tope; uno que la API rechazó (400, 403, 422) no. Tras "Olvidar", lo que estaba en camino no vuelve a la cola.

`app_sessions` guarda una fila por sesión (30 minutos sin actividad la cierran): `started_at`, `app_version`, `platform`, `mode` (`propuesta` o `actual` al empezar) y `entry` (`directa`, `enlace` o `push`). Nace con el primer evento de la sesión que llega, sea de la app o del servidor (una pregunta a Mochi), y los lotes siguientes de la app solo completan lo que faltaba. Es una tabla de personas: está en `PERSON_TABLES` (`rappi_ia/delivery.py`), se borra con la persona ("Olvidar" y la purga de inactivas, en cascada) y el generador simulado la llena para sus sesiones. El generador también llena `client_event_id` (un uuid5 de la persona, la sesión y el orden: la misma semilla da los mismos ids), `client_ts` y `seq`.

## Impresiones, experimentos y vistas derivadas

Desde las migraciones 047 y 048, los eventos dicen también **qué se vio**, **en qué variante estaba la persona** y **cómo estaba el catálogo**, y cuatro vistas de `capa` los leen. El diseño y su porqué están en [decisiones.md](decisiones.md#datos-simulados-y-panel) (25-10-2026).

- **`list_view` y `app_event_items`**: lo que una lista dejó a la vista. La app cuenta un elemento cuando queda visible al menos la mitad, una vez por pestaña, lista (pantalla, lista y `request_id`) y lugar, y manda lo visto de cada lista en un evento por segundo, con hasta 20 elementos (`prototipo-app/src/api/impressions.js` y `hooks/useImpressions.js`). El evento lleva `surface`, `origin` y `request_id` de la lista, y en `position` la mayor posición vista; cada elemento, su lugar, qué es (`catalog_item`, `menu_item`, `store` o `vertical`), su id, su concepto y su vertical. Listas que lo cuentan: los accesos y las listas de tiendas de la Home, los resultados del buscador (productos y tiendas), los pasillos y el menú de una tienda, la lista de Restaurantes, la grilla de Turbo, y lo que muestra Mochi (sus mensajes, el kit, la recompra y el OnTop). En "Rappi hoy" los elementos van sin concepto. `app_event_items` es tabla de personas (`PERSON_TABLES`), se va con el evento ("Olvidar", en cascada; olvidar un concepto borra sus elementos) y `rappi-ia purge` la borra a los 90 días (`purge_old_impressions`): queda el `list_view`.
- **Experimentos** (`experiments`, `experiment_assignments`): cada persona tiene una variante por experimento, asignada una vez y estable, con su población (un trigger exige la de `app_users`: nunca se mezclan). `modo_app` (`propuesta` o `actual`) es el modo de su primera sesión y **no es al azar**: lo elige quien presenta, así que comparar variantes describe y no mide un efecto. `ofertas_control` (`tratamiento` o `control`) sí es al azar: un hash estable del id, en `POST /session` o la primera vez que pide una oferta. Viene apagado (`OFFERS_CONTROL_PCT=0`); encendido, a la variante `control` no se le muestran los momentos de `POST /agent/offer` que la app pide sin que la persona los pida (`HOLDOUT_MOMENTS`: carrito, sin resultado, próximo pedido, vertical por probar, recompra, volver y OnTop, en la Home, la búsqueda y el seguimiento): la API responde 204 con la cabecera `X-Offer-Withheld: 1` y registra la **impresión contrafactual** `offer_withheld` en su sesión (`session_id` de la oferta), con su pantalla (`surface`) y lo que habría mostrado en `app_event_items`; la misma oferta (origen, concepto y vertical) se anota una vez por sesión, como la app cuenta una mostrada. En `tratamiento` la API anota la misma oferta, que sí muestra, como `offer_eligible` (migración 056), con la misma regla y sus elementos: la parte expuesta se cuenta igual en los dos grupos, con un hecho del servidor y no con la `suggestion_shown` de la app. Lo que la app filtra después (lo rechazado en la sesión, `wasRefused`) no cambia esa cuenta. Lo que la persona pide se muestra siempre: un plan, un perfil, "¿Me falta algo?" del checkout (el momento `checkout`, que solo se pide al tocarlo) y lo que pide en el buscador (`surface` `agent`: "Repite lo de siempre", "¿Con qué acompaño…?", "¿Qué puedo probar?"). Tampoco se retienen "Para ti" (`/recommendations`), la sugerencia cruzada de las respuestas de Mochi (`/agent/ask`) ni el orden de la Home: si el control los deja de ver está por decidir. Con una recompra retenida, la Home no pide "¿Volvemos a…?", que en tratamiento no se habría mostrado. El eco: `app_sessions.variants` guarda las variantes de la persona al empezar cada sesión. El generador simulado pone a todos en `modo_app = propuesta` y no simula el grupo de control. El panel los muestra en la pestaña Experimentos (`/analytics/experimentos`, [diseno-ia.md](diseno-ia.md#5-panel-para-la-empresa-vale-la-pena)), por variante y dentro de una sola población.
- **El catálogo al registrar** (`payload.catalogo`): en `view_store`, `view_item` y `cart_add` la API fija el precio (`precio`), la oferta (`precio_lista` y `descuento_pct`, si hay), la disponibilidad de un plato (`disponible`) y si la tienda estaba abierta (`abierta`, con `horario`: `horario` publicado o estado de la `descarga`), de `v_latest_offers` en la tienda del evento (`payload.store_id`, que manda la app) y de `latest_menu_prices` (`rappi_ia/events/catalog_context.py`). Lo pone siempre el servidor.
- **Vistas** (migración 048): `capa.v_carros_abandonados` (un carro con algo adentro cuyo último evento fue hace más de 60 minutos, sin pedido del mismo carro en esa hora; el panel sigue contando el de 24 horas), `capa.v_embudo_sesion` (vio → tocó → carro → pago → pedido, por sesión; cada paso se marca aunque falte el anterior, y un pedido que después se canceló no cuenta, desde la migración 051), `capa.v_ctr_posicion` (de lo visto en un lugar, lo que se tocó en la misma sesión desde el mismo `surface`, `origin`, `position` y `request_id`; abrir la hoja de un producto que no viene de una recomendación no deja evento y no cuenta) y `capa.v_eventos_amplitude`. El panel las lee con `/analytics/ctr-posicion` y `/analytics/embudo-sesion`.

`capa.v_eventos_amplitude` traduce cada evento al plan de tracking de la app de Rappi (docs/investigacion/app-rappi-2026-10-25.md):

| Nuestro evento | `event_type` (Rappi) | Nota |
|---|---|---|
| `app_open` | `APP_LAUNCH` | |
| `search` | `LOCAL_SEARCH`, o `LOCAL_SEARCH_NULL_RESULTS` si `unmet` | |
| `ask` (y `chat`, el nombre de antes) | `RECEIVE_MESSAGE_CHAT_V2` | |
| `view_store` | `VIEW_STORE` | Rappi separa el clic (`SELECT_STORE`) de la vista |
| `view_item` | `VIEW_PRODUCT_DESCRIPTION` | |
| `cart_add` | `ADD_TO_CART` | Rappi pone el origen en el nombre (`ADD_TO_CART_AISLE`…); aquí va en `SOURCE` |
| `checkout_start` | `PROCEED_TO_CHECKOUT` | |
| `order_placed` | `ORDER_PLACED_CONFIRMED_BACK` | Lo crea el servidor, como el `_BACK` de Rappi |
| `list_view`, `suggestion_shown` | `VIEW_COMPONENT` | Lo visto, en `PRODUCT_ID_LIST` y `STORE_ID_LIST` |
| `suggestion_accepted` | `SELECT_PRODUCT` | |
| `recommendation_click` | `SELECT_STORE` (una tienda) o `SELECT_PRODUCT` | |
| `service_shown` / `service_opened` | `home_placement_content_view` / `home_placement_content_click` | |
| `vertical_open` | `SELECT_STORE_TYPE` | |
| `order_rated` | `RATE_STAR_TAP` | |
| `cart_remove`, `suggestion_dismissed`, `reorder`, `offer_withheld`, `offer_eligible`, `order_cancelled`, `vertical_reorder_shown`, `agent_visibility`, `offer_why_open`, `survey_shown`, `survey_answer`, `survey_dismissed` | `MVP_CART_REMOVE`, `MVP_SUGGESTION_DISMISSED`, `MVP_REORDER`, `MVP_OFFER_WITHHELD`, `MVP_OFFER_ELIGIBLE`, `MVP_ORDER_CANCELLED`, `MVP_VERTICAL_REORDER_SHOWN`, `MVP_AGENT_VISIBILITY`, `MVP_OFFER_WHY_OPEN`, `MVP_SURVEY_SHOWN`, `MVP_SURVEY_ANSWER`, `MVP_SURVEY_DISMISSED` | Sin equivalente (`equivalente = false`: desde la migración 051 sale del prefijo `MVP_`, así un evento nuevo sin traducción no queda como equivalente). Desde la 055, `KIND` separa en `MVP_SUGGESTION_DISMISSED` la oferta que se fue sola (`expirada`, que no es un rechazo) y el "Después" de "¿Volvemos a…?" (`volver` o `vuelta`) del rechazo, que no lo lleva; `VISIBLE` dice en `MVP_AGENT_VISIBILITY` si se ocultó a Mochi (`false`) o se trajo de vuelta (`true`), y desde la 058 `QUIET` separa de eso el silencio por hoy (`true`) y el volver a hablar (`false`). `KIND` también sale en la mostrada (ver abajo) |

Y el sobre: `uuid` (`client_event_id`, o uno fijo derivado de `event_id` en los eventos del servidor), `sequence_number` (`seq`), `session_id` y `session_start_ms` (el inicio de la sesión en milisegundos, que es el `session_id` de Amplitude), `timestamp` (`client_ts` o la llegada, en milisegundos), `user_id`, `platform`, `version_name`; en `event_properties`, en mayúsculas: `CONTEXT` (`surface`), `SOURCE` y `COMPONENT_NAME` (`origin`), `COMPONENT_INDEX` (`position`), `VERTICAL`, `STORE_ID`, `PRODUCT_ID`, `REQUEST_ID`, `CART_ID`, `PRODUCT_VALUE`, `TOTAL`, `RESULTS`, `PRICE`, `OFFER_VALUE` y `OPEN` (de `payload.catalogo`), `PRODUCT_ID_LIST`, `STORE_ID_LIST`, `LAST_POSITION_VIEWED`, `KIND` (`payload.kind`), `VISIBLE` (`payload.visible`) y `QUIET` (`payload.quiet`); en `user_properties`, `EXPERIMENTS` (las variantes) y `APP_MODE`. La consulta y los conceptos no van.

`KIND` (migración 055) sale en todo evento que traiga `payload.kind`, no solo en los rechazos. En `MVP_SUGGESTION_DISMISSED` vale `expirada` (la oferta se fue sola) o `volver`/`vuelta` (el "Después" de "¿Volvemos a…?"); un rechazo no lo lleva. En `VIEW_COMPONENT` de una `suggestion_shown` vale `lo_mas_pedido` (la fila "Lo más pedido" de "Para ti") o `volver`/`vuelta` (la invitación mostrada). Para contar los "Después" hay que filtrar también por `event_type = 'MVP_SUGGESTION_DISMISSED'`: con solo `KIND IN ('volver', 'vuelta')` también entran las invitaciones mostradas.

## Privacidad

- Los segmentos que tocan salud o vida privada (sin gluten, sin lactosa, sin azúcar, bajo sodio, sin frutos secos, bebé, embarazo, adulto mayor, salud sexual, farmacia, uso continuo, tabaco y vapeo) están marcados `sensitive` y se **nombran por lo que la persona compra**, nunca por una condición ("compra sin gluten", no "celíaco").
- `capa.user_segments` no trae filas de segmentos sensibles, y la evidencia de un segmento común no nombra lo que mira uno sensible (si "cazaofertas" listara los pañales comprados, sería el mismo dato por otra puerta). `capa.segment_sizes` muestra un segmento sensible una sola vez, sin separar por nivel, y solo si tiene 5 o más personas y el resto de su fuente también son 5 o más (con 9 personas del prototipo, ninguno aparece). Las filas por persona de los sensibles quedan en la tabla interna; hoy ninguna otra pieza las lee.
- Esto es una **convención de la capa, no una frontera de seguridad**: no hay un rol de solo lectura, y quien tenga las credenciales de la base lee también las tablas internas.
- Los segmentos sensibles no generan aristas `afin_a` ni se usan para sugerir.
- "Olvidar" borra a la persona (y con ella sus segmentos e historia); olvidar un concepto recalcula sus segmentos sin él.
- Las preferencias que la persona elige en "Mis preferencias" (`agent_preferences`, migración 045: dieta, alergias, cocinas y tiendas favoritas) no entran a la capa: ni a segmentos, perfiles de gusto, motor ni panel, y lo dicho no queda como consulta en `app_events`. Solo filtran y ordenan lo que Mochi muestra ([diseno-ia.md](diseno-ia.md#preferencias-resumen-y-estado-del-pedido)), también "Para ti" dentro de una tienda; la dieta y las alergias filtran además el buscador de la propuesta. Es una tabla de personas (`PERSON_TABLES`) y se va con "Olvidar" y la purga; desde la migración 051 un trigger exige que su población sea la de la persona, como en `experiment_assignments` y `agent_autonomy`.
- El permiso de "Pedir por mí" (`agent_autonomy`, migración 049: las tiendas elegidas y el tope) tampoco entra a la capa: solo decide si Mochi pide solo "lo de siempre" ([diseno-ia.md](diseno-ia.md#pedir-por-mí)). Los pedidos que hace así son pedidos de la persona y entran como cualquier otro; su `order_placed` lleva el origen `agent-autopedido`. Es una tabla de personas (`PERSON_TABLES`) y se va con "Olvidar" y la purga.
- Una sola persona no crea una relación en el grafo: `co_busqueda` exige sesiones de 5 o más personas distintas.

## Calidad medida

La cobertura dice cuánto se etiquetó, no si está bien. `rappi-ia layer-sample [--seed N]` arma una muestra fija de lo que la capa afirma: 10 ítems por atributo y regla, 3 por atributo declarado por Rappi, 140 marcas y 440 conceptos repartidos por método. En git van solo los ids y las afirmaciones (`rappi-ia/src/rappi_ia/eval/capas-muestra*.json`, con sus juicios en `capas-juicios*.json`); los nombres y descripciones para juzgar quedan en `rappi-ia/data/eval/`, fuera de git. `rappi-ia layer-precision [--seed N]` calcula la precisión por regla con el mínimo que se puede asegurar (límite de Wilson al 95 %), la cifra si los "dudoso" fueran errores, y lista las reglas bajo 80 %.

Se midió dos veces con jueces de modelos de lenguaje (10 jueces independientes por muestra): con las reglas originales (semilla 7) y, después de corregirlas, con una muestra nueva de otros ítems (semilla 11), para no medir con los mismos casos que guiaron los cambios.

| Qué | Antes | Después, muestra nueva | Después, si los dudosos fueran errores |
|---|---|---|---|
| Conceptos por regla de nombre | 81 % | 86 % | 83 % |
| Conceptos por mapeo de categoría, sección o cocina | 82 % | 88 % | 85 % |
| Conceptos por vecinos (embeddings) | 57 % | 88 % | 84 % |
| Atributos por reglas propias | 92 % | 92 % | 86 % |
| Atributos declarados por Rappi | 86 % | 86 % | 67 % |
| Marcas deducidas del nombre / declaradas | 99 % / 97 % | 98 % / 97 % | 97 % / 95 % |

Las correcciones: los vecinos solo deciden con 80 % de acuerdo; la cocina del local cuenta solo con un mapeo muy confiable ("Asiática" ya no es sushi y "Combos" no dice el plato); la proteína del nombre de un plato le gana a una sección genérica; un ingrediente en el nombre de un plato ("Macarrón Frutilla") no lo vuelve fruta; una sección sin mapeo que nombra un plato ("Empanadas de Horno") sí da concepto; y se acotaron reglas de atributos que calzaban fuera de su ámbito. Los atributos no mejoraron fuera de muestra: esas correcciones atacaron errores puntuales. El costo: los restaurantes con concepto bajaron de 98,2 % a 94,7 %. Los agregados siguen el diseño de la muestra (prioriza reglas propias y platos), no la proporción de cada fuente en la base.

## Cómo agregar algo

| Quiero… | Qué hago |
|---|---|
| Un atributo nuevo | Una entrada en `attributes.toml` con sus frases (y, si sirve, el campo de Rappi que lo declara); un test con frases positivas y negativas |
| Un segmento nuevo | Una entrada en `segments.toml` combinando piezas (conceptos, atributos, palabras de consulta, horas, métricas…); el cargador valida que todo exista. Ver la cabecera del archivo para las piezas |
| Una relación curada | Una arista en `relations.toml` (los tipos y existencia de los nodos se validan) |
| Una vista para otra herramienta | Una migración que cree la vista en `capa` con `COMMENT` en la vista y en cada columna; un test lo exige |

Cambiar las reglas basta con volver a correr `make layers`: no hay que tocar código ni la base a mano.

## Límites que conviene conocer

- Los atributos salen de lo que Rappi declara y de frases en el nombre: dicen "el nombre dice sin gluten", no que el producto lo sea. La fuente y la confianza van en cada fila.
- `capa.canonical_products.verticals` se infla con tiendas que Rappi etiqueta en dos verticales.
- `co_busqueda` sale vacía mientras no haya sesiones reales con varios conceptos (el simulador genera un concepto por sesión).
- Los umbrales de los segmentos se calibraron con datos simulados: habrá que ajustarlos cuando haya uso real.
- `capa.segment_sizes` no impide deducir a una persona comparando dos semanas (un total sensible que sube de 5 a 6 cuando se sabe que se sumó una sola persona); el umbral de 5 es el de la spec; el panel de negocio usa 20.
- `capa.layer_runs` solo guarda las corridas terminadas de las capas de atributos a segmentos; una que falla no deja fila. El motor es la excepción: deja la corrida `running` y la `failed`.
- Las dos vistas personales del motor (`capa.user_vertical_affinity` y `capa.replenishment`) traen `source`, pero esa persona sigue siendo un id seudónimo y, como el resto de la capa, una convención y no una frontera de seguridad; la afinidad incluye también Farmacia y Licores, de la propia persona.
- Con pocas personas, la compra cruzada puede salir vacía (hacen falta 10 con el mismo patrón) y la recompra pide al menos 3 compras del concepto.
