# Resultados en detalle

El resumen de las cifras está en el [README principal](../../README.md#resultados). Aquí va el detalle, con el tipo de dato de cada cifra (real, evaluación automática, estimación, simulación o dato compartido por Rappi) y el reporte de donde sale. Los reportes de cada fecha están en esta carpeta y no se reescriben: si dos reportes no coinciden, manda el más reciente con el mismo set.

## Motor multivertical (datos simulados: prueban la mecánica, no el efecto)

Corrida del 04-11-2026 (`rappi-ia motor`, semilla 7; [simulados-2026-11-04.md](simulados-2026-11-04.md)) sobre una copia del catálogo real y **3.000 personas simuladas**, con el generador recalibrado a la mezcla de la tabla de Rappi (17-10) y tramos por fecha: entrenar, validar y probar (28 días cada uno de los dos últimos). Cambiar el generador mueve todas las cifras simuladas; no son mejoras del motor. Antes y después, tolerancias y semillas: [simulados-2026-10-17.md](simulados-2026-10-17.md). La historia de la etapa de QA (intentos descartados y ruido entre semillas) y de la escalera fina: [motor-2026-10-16.md](motor-2026-10-16.md).

| Qué | Métrica (tramo de prueba) | Valor | Tipo de dato |
|---|---|---|---|
| Próxima vertical | nDCG@8 | combinado 0,980 · solo afinidad 0,978 · popularidad 0,924 · orden fijo 0,918 (505 personas) | Simulado |
| Compra cruzada | precisión@3 | mezcla 0,129 · lo más pedido 0,129. En la corrida del 04-11 λ quedó en 1 por 2 aciertos de 1.509 en validación; desde el 05-11 un λ mayor tiene que ganar al menos 5, y con estos simulados queda en 0. Las reglas solas llegan a 17 personas (0,118): en la prueba la mezcla no cambia lo que acierta | Simulado |
| Recompra | acierto ±7 días | 0,214 (de 103 predicciones), error mediano de 6,5 días | Simulado |
| Generador simulado | parecido a la tabla de Rappi (personas-mes) | distancia 23,3 → 18,2 (16-10, Turbo en las sugerencias) → 2,9 (17-10, recalibrado; 2,5 a 5,5 en 5 semillas, cada fila a menos de 2 puntos). Retención M+1 de Restaurantes 0,452 (Rappi 0,47); rest+turbo+retail, la más alta (0,916; Rappi 0,93) | Simulado, comparado con el dato compartido por Rappi |
| Paso de la escalera fina | acierto@1 entre quienes suman una vertical | paso 0,540 · la vertical que más se suma 0,595 (74 personas). El paso busca retención, no adivinar qué se suma solo; el 17-10 ganaba (0,620 contra 0,479, 71 personas): con menos de 100 personas de una semilla, ninguna de las dos es evidencia: 55 de 74 reciben la misma vertical y la diferencia la deciden 14 personas (5 contra 9, McNemar p = 0,42) | Simulado: no es evidencia |

Cómo leerlo: la ventaja del combinado viene casi entera de la afinidad de cada persona, y el generador hace que cada persona repita sus verticales, así que en parte acierta por construcción; con el generador recalibrado hay más personas que solo piden en Restaurantes, y eso facilita adivinar la próxima vertical a todos los métodos, incluido el orden fijo. El generador se calibró con la tabla de Rappi y la trata como efecto, así que sus cifras no prueban que sumar verticales retenga. La agrupación de verticales en `rest`, `turbo` y `retail` es un supuesto propio. Detalle: [capa-de-datos.md](../capa-de-datos.md#motor-multivertical).

**Revisión sobre el catálogo real** ([QA del 16-10-2026](qa-motor-2026-10-16.md), en solo lectura, con 200 personas simuladas y las 44 del prototipo, medida antes de los ajustes de la etapa de QA, con λ > 0): las guardias (Farmacia, Licores, bebé, salud, conceptos sensibles, alcohol) dieron **0 casos en 2.851 productos ofrecidos**, y la ruta más lenta (`/recommendations`) respondió con p95 de 222 ms con el modelo de texto.

## Mochi: preguntar y seguir la conversación (juicio propio, no humano externo)

Respuestas reales de la API sobre `rappi_staging` (copia del 22-10), juzgadas a mano: bien, a medias o mal.

| Set | Antes | Después | Reporte |
|---|---|---|---|
| 25 conversaciones de 2 o 3 turnos (`conversaciones.txt`) | 7 bien, 8 a medias, 10 mal | 21 bien, 4 a medias, 0 mal | [25-10-2026](mochi-conversacion-2026-10-25.md) |
| 40 preguntas en texto libre (`preguntas-libres.txt`) | 34 bien, 6 a medias (24-10) | 40 bien | [25-10-2026](mochi-conversacion-2026-10-25.md#las-40-preguntas-libres-preguntas-librestxt) |

**Desde el 05-11-2026, una medida que se repite** (`rappi-ia eval-mochi`, [reporte](mochi-2026-11-05.md)): el primer turno de 140 frases (las 33 necesidades de `queries.json`, las 40 preguntas libres, las 25 conversaciones y un set apartado de 42 frases que no se usa para ajustar), sobre `rappi_staging` en solo lectura. **Evaluación automática:** ningún texto contradice lo que muestra (0 de 127 que anuncian un concepto u ocasión), ninguno dice "En X no hay…", ningún producto repetido, 5,8 productos en promedio y 3 respuestas con menos de 4 (las tres a propósito). **Juicio LLM, no humano** (25 necesidades): nDCG@6 0,846 y P@3 "sirve" 0,720 en Mochi contra 0,838 y 0,693 en los 6 primeros de `/search`: no se distinguen (IC 95 % de la diferencia en nDCG, −0,030 a 0,054).

## Catálogo, conceptos y búsqueda

| Ámbito | Métrica | Valor | Tipo de dato | Fuente |
|---|---|---|---|---|
| Catálogo | Documentos de búsqueda | 253.945: 84.024 productos, 165.623 platos y 4.298 tiendas | Real (catálogo público) | Base `rappi`: contado el 05-10 sobre la descarga del 04-10-2026; las descargas posteriores no se recontaron |
| Catálogo | Documentos con embedding | 100 % (`intfloat/multilingual-e5-base`, 768 dim, HNSW por vertical) | Real | Base `rappi`, 04-10-2026 |
| Capa 2 | Taxonomía | 136 conceptos (116 tipos de producto en 20 grupos) · 240 complementos curados (cada concepto que Mochi puede ofrecer tiene al menos dos) · 900 categorías, secciones de menú y cocinas con mapeo revisado | Curado a mano; mapa de categorías generado con LLM y versionado | `taxonomy.toml`, `complements.toml` y `category_map.csv`, contados el 16-10-2026 |
| Capa 2 | Precisión de la asignación | 86 % por regla de nombre, 88 % por mapeo y 88 % por vecinos, en una muestra nueva tras corregir las reglas (antes: 81, 82 y 57 %) | **Estimación** con jueces LLM | [antes](capas-precision-2026-10-06.md) · [después](capas-precision-2026-10-06-nueva-muestra.md) |
| Capa de datos | Atributos, marcas y grafo | 83 atributos sobre 79.617 ítems · 6.359 marcas · 23.534 productos canónicos · 32.105 aristas en 12 relaciones | Real, con reglas propias; atributos 92 % y marcas 97 a 99 % de precisión estimada | `make layers`, 06-10-2026 |
| Búsqueda | nDCG@10 | híbrido 0,905 · sin refuerzo por concepto 0,842 · vectorial 0,835 · léxico 0,765 · lo que ve la persona 0,917, con el set renovado el 22-10 (con el anterior, el híbrido daba 0,917; la regla nueva de "sin resultado" no lo cambia) | Evaluación automática | [reporte del 22-10](busqueda-2026-10-22.md) |
| Búsqueda | Juicio LLM (no humano) | 200 pares de la planilla, dos jueces ciegos: 95 % de los 3 primeros útiles (66 % "sirve"); juez por concepto contra el juicio LLM: acuerdo 70,5 %, κ 0,32 | [juicio-llm-busqueda-2026-10-25.md](juicio-llm-busqueda-2026-10-25.md) |
| Búsqueda | Juez de tres niveles: lo que ve la persona | nDCG@10 0,906 → 0,952 · P@3 "sirve" 0,750 → 0,811 · útil@3 0,943 → 0,981 · lo mostrado que no sirve 7,3 % → 4,0 %. Necesidades 0,798 → 0,910; Rappi Mall 0,831 → 0,957. Juez por concepto, lo que ve la persona: 0,917 → 0,941 | Juicio LLM, no humano: 88 consultas, los 200 pares del 25-10 más 794 juzgados a ciegas (56 de 60 controles iguales, κ 0,90) | [busqueda-2026-10-25.md](busqueda-2026-10-25.md) |
| Búsqueda | "Sin resultado" | precisión 1,00 (0 falsas alarmas en 131 positivas) · recall 0,93 (54 de 58). Con el mismo set y la regla anterior, 36 de 58 (0,62) | Evaluación automática | [reporte del 22-10](busqueda-2026-10-22.md) |
| Búsqueda | Errores de tipeo | 53 casos en las 8 verticales: en la búsqueda agrupada (la de la app) se recuperan 53 corrigiendo la consulta (37 sin corregir), por vertical 52 (30) y Mochi 51 (31); "sin resultado" igual al de arriba | Evaluación automática | [reporte del 24-10](busqueda-2026-10-24.md) · [25-10](busqueda-2026-10-25.md) · [04-11](tipeo-2026-11-04.md) |
| Calidad | Tests | Los conteos vigentes están en una sola fuente: [README.md#resultados](../../README.md#resultados) | CI de main | `make test` · `npm test` |

La búsqueda se evaluó con 131 consultas positivas en las 8 verticales y 58 negativas, con relevancia juzgada automáticamente por concepto ([`queries.json`](../../rappi-ia/src/rappi_ia/eval/queries.json), renovado el 22-10 contra el catálogo). Por tipo de consulta, el híbrido logra 0,970 en las exactas, 0,972 sin tildes y 0,709 en necesidades en lenguaje natural ("algo para el carrete"), frente a 0,565 del léxico.

- **Sin concepto ni ocasión (22-10).** Una consulta que no nombra concepto ni ocasión y no calza todas sus palabras necesita un coseno de 0,85 para mostrar algo ("sofá de tres cuerpos" en Turbo ya no trae pisco Tres Erres). Salvedad: 0,85 se calibró con estas mismas negativas (la más alta llega a 0,847), 20 de ellas se sumaron junto con la regla y las positivas sin concepto ni ocasión calzan todas sus palabras, así que no miden el costo; ese se midió aparte, en un barrido de frases de usuarios ([decisiones, 22-10](../decisiones.md#búsqueda-e-ia)).
- **Necesidades, Rappi Mall y la cola (25-10).** Una ocasión en la búsqueda de una vertical ("algo para la once" en Turbo) se busca por sus conceptos, como en la agrupada y en Mochi; en el concepto nombrado va primero lo que dice lo pedido en su nombre; sin concepto, si al menos 3 productos lo dicen en su nombre, lo demás tiene que ser de su concepto o muy cercano; y "ropa de bebé" pide ropa. Con el juez de tres niveles (juicio LLM, no humano) el nDCG@10 sube en 21 consultas y baja en 7 (diferencia media +0,046, IC 95 % 0,015 a 0,084). Salvedad: la ocasión reemplaza las palabras de la consulta ("cosas para el bebé recién nacido" trae pañales de todas las tallas) y el nombre primero sube packs y mezclas que dicen las palabras ([reporte](busqueda-2026-10-25.md)).
- **Errores de tipeo (24-10).** Si nada calza todas las palabras, la búsqueda corrige la consulta con el vocabulario del catálogo y vuelve a buscar, y lo corregido se muestra solo si calza todas sus palabras: de 53 errores de tipeo ([`typos.json`](../../rappi-ia/src/rappi_ia/eval/typos.json)) la búsqueda agrupada recupera 52 (antes 34; 53 desde los cambios del 25-10), y las negativas y el nDCG no cambian. Salvedad: sin diccionario, unas pocas palabras reales que el catálogo casi no tiene se corrigen mal por vertical ("tengo resaca" → "reseca": 8 de 3.024 búsquedas del barrido de frases), y el aviso deja buscar lo escrito tal cual.

## Catálogo por vertical

| Vertical | Tiendas | Productos | Con concepto |
|---|---:|---:|---:|
| Supermercado | 320 | 29.403 | 99,8 % |
| Conveniencia | 38 | 7.848 | 100 % |
| Turbo | 18 | 2.642 | 100 % |
| Rappi Mall | 359 | 32.761 | 99,7 % |
| Farmacia | 16 | 4.726 | 99,8 % |
| Licores | 79 | 5.519 | 100 % |
| Chocolatería | 24 | 1.125 | 100 % |
| Restaurantes | 3.444 | 165.623 platos | 94,7 % |

Documentos contados el 05-10 sobre la descarga del 04-10-2026 (segunda descarga semanal automática); las descargas posteriores no se recontaron. "Con concepto", del 06-10. En tiendas es una muestra: la página pública muestra hasta 24 productos por sub-pasillo. Turbo quedó con los precios del 27-09 (ver [Límites](../../README.md#límites)).

## Reportes de esta carpeta

| Reporte | Qué mide |
|---|---|
| [mochi-2026-11-05.md](mochi-2026-11-05.md) | Mochi con revisiones automáticas (sin juez) y el juez de tres niveles (juicio LLM, no humano), con un set apartado; la búsqueda repuntuada con los juicios nuevos y las listas del 05-11 para `make eval-check` |
| [simulados-2026-11-04.md](simulados-2026-11-04.md) | Los simulados regenerados con el sobre de eventos y las reformulaciones: el panel y el motor |
| [tipeo-2026-11-04.md](tipeo-2026-11-04.md) | Los errores de tipeo en la búsqueda y en Mochi: la medida vigente |
| [mochi-conversacion-2026-10-25.md](mochi-conversacion-2026-10-25.md) | Las conversaciones con Mochi y las 40 preguntas libres, antes y después |
| [prueba-usuarios-PLANTILLA.md](prueba-usuarios-PLANTILLA.md) | La plantilla del reporte de la prueba con usuarios (todavía sin reporte) |
| [busqueda-2026-10-25.md](busqueda-2026-10-25.md) | Necesidades, Rappi Mall y la cola de la búsqueda, medidos con el juez de tres niveles (juicio LLM, no humano) |
| [juicio-llm-busqueda-2026-10-25.md](juicio-llm-busqueda-2026-10-25.md) | El juicio LLM de los 200 pares de la planilla contra el juez por concepto |
| [busqueda-2026-10-24.md](busqueda-2026-10-24.md) | La corrección de errores de tipeo: set de 53 casos, lo que no cambia y la latencia |
| [busqueda-2026-10-22.md](busqueda-2026-10-22.md) | La evaluación vigente de la búsqueda (set de 131 positivas y 58 negativas) |
| [busqueda-2026-10-06.md](busqueda-2026-10-06.md), [busqueda-2026-10-04.md](busqueda-2026-10-04.md), [busqueda-2026-09-30.md](busqueda-2026-09-30.md) | Evaluaciones anteriores, con otros sets: no se comparan con las de arriba |
| [motor-2026-10-16.md](motor-2026-10-16.md) | La evaluación del motor por fechas, los intentos de la etapa de QA y la escalera fina |
| [qa-motor-2026-10-16.md](qa-motor-2026-10-16.md) | Las ofertas del motor sobre el catálogo real, en solo lectura |
| [simulados-2026-10-17.md](simulados-2026-10-17.md) | El generador simulado recalibrado con la tabla de Rappi: antes y después |
| [capas-precision-2026-10-06.md](capas-precision-2026-10-06.md), [capas-precision-2026-10-06-nueva-muestra.md](capas-precision-2026-10-06-nueva-muestra.md) | La precisión de conceptos, atributos y marcas con jueces LLM, antes y después de corregir las reglas |
