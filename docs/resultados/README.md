# Resultados en detalle

El resumen de las cifras está en el [README principal](../../README.md#resultados). Aquí va el detalle, con el tipo de dato de cada cifra (real, evaluación automática, estimación, simulación o dato compartido por Rappi) y el reporte de donde sale. Los reportes de cada fecha están en esta carpeta y no se reescriben: si dos reportes no coinciden, manda el más reciente con el mismo set.

## Motor multivertical (datos simulados: prueban la mecánica, no el efecto)

Corrida del 17-10-2026 (`rappi-ia motor`, semilla 7) sobre una copia del catálogo real y **3.000 personas simuladas**, con el generador recalibrado a la mezcla de la tabla de Rappi y tramos por fecha: entrenar, validar y probar (28 días cada uno de los dos últimos). Cambiar el generador mueve todas las cifras simuladas; no son mejoras del motor. Antes y después, tolerancias y semillas: [simulados-2026-10-17.md](simulados-2026-10-17.md). La historia de la etapa de QA (intentos descartados y ruido entre semillas) y de la escalera fina: [motor-2026-10-16.md](motor-2026-10-16.md).

| Qué | Métrica (tramo de prueba) | Valor | Tipo de dato |
|---|---|---|---|
| Próxima vertical | nDCG@8 | combinado 0,978 · solo afinidad 0,976 · popularidad 0,924 · orden fijo 0,918 (477 personas) | Simulado |
| Compra cruzada | precisión@3 | mezcla 0,129 · lo más pedido 0,129. En validación λ quedó en 0, así que hoy las reglas no cambian lo que se ofrece; las reglas solas, 0,030 en 134 personas | Simulado |
| Recompra | acierto ±7 días | 0,191 (de 110 predicciones), error mediano de 6 días | Simulado |
| Generador simulado | parecido a la tabla de Rappi (personas-mes) | distancia 23,3 → 18,2 (16-10, Turbo en las sugerencias) → 2,9 (17-10, recalibrado; 2,5 a 5,5 en 5 semillas, cada fila a menos de 2 puntos). Retención M+1 de Restaurantes 0,452 (Rappi 0,47); rest+turbo+retail, la más alta (0,916; Rappi 0,93) | Simulado, comparado con el dato compartido por Rappi |
| Paso de la escalera fina | acierto@1 entre quienes suman una vertical | paso 0,620 · la vertical que más se suma 0,479 (71 personas). El paso busca retención, no adivinar qué se suma solo; con el generador del 16-10 perdía (0,466 contra 0,638): con 71 personas de una semilla, ninguna de las dos es evidencia | Simulado: no es evidencia |

Cómo leerlo: la ventaja del combinado viene casi entera de la afinidad de cada persona, y el generador hace que cada persona repita sus verticales, así que en parte acierta por construcción; con el generador recalibrado hay más personas que solo piden en Restaurantes, y eso facilita adivinar la próxima vertical a todos los métodos, incluido el orden fijo. El generador se calibró con la tabla de Rappi y la trata como efecto, así que sus cifras no prueban que sumar verticales retenga. La agrupación de verticales en `rest`, `turbo` y `retail` es un supuesto propio. Detalle: [capa-de-datos.md](../capa-de-datos.md#motor-multivertical).

**Revisión sobre el catálogo real** ([QA del 16-10-2026](qa-motor-2026-10-16.md), en solo lectura, con 200 personas simuladas y las 44 del prototipo, medida antes de los ajustes de la etapa de QA, con λ > 0): las guardias (Farmacia, Licores, bebé, salud, conceptos sensibles, alcohol) dieron **0 casos en 2.851 productos ofrecidos**, y la ruta más lenta (`/recommendations`) respondió con p95 de 222 ms con el modelo de texto.

## Catálogo, conceptos y búsqueda

| Ámbito | Métrica | Valor | Tipo de dato | Fuente |
|---|---|---|---|---|
| Catálogo | Documentos de búsqueda | 253.945: 84.024 productos, 165.623 platos y 4.298 tiendas | Real (catálogo público) | Base `rappi`, descarga del 04-10-2026 (contada el 05-10) |
| Catálogo | Documentos con embedding | 100 % (`intfloat/multilingual-e5-base`, 768 dim, HNSW por vertical) | Real | Base `rappi`, 04-10-2026 |
| Capa 2 | Taxonomía | 136 conceptos (116 tipos de producto en 20 grupos) · 240 complementos curados (cada concepto que Mochi puede ofrecer tiene al menos dos) · 900 categorías, secciones de menú y cocinas con mapeo revisado | Curado a mano; mapa de categorías generado con LLM y versionado | `taxonomy.toml`, `complements.toml` y `category_map.csv`, contados el 16-10-2026 |
| Capa 2 | Precisión de la asignación | 86 % por regla de nombre, 88 % por mapeo y 88 % por vecinos, en una muestra nueva tras corregir las reglas (antes: 81, 82 y 57 %) | **Estimación** con jueces LLM | [antes](capas-precision-2026-10-06.md) · [después](capas-precision-2026-10-06-nueva-muestra.md) |
| Capa de datos | Atributos, marcas y grafo | 83 atributos sobre 79.617 ítems · 6.359 marcas · 23.534 productos canónicos · 32.105 aristas en 12 relaciones | Real, con reglas propias; atributos 92 % y marcas 97 a 99 % de precisión estimada | `make layers`, 06-10-2026 |
| Búsqueda | nDCG@10 | híbrido 0,905 · sin refuerzo por concepto 0,842 · vectorial 0,835 · léxico 0,765 · lo que ve la persona 0,917, con el set renovado el 22-10 (con el anterior, el híbrido daba 0,917; la regla nueva de «sin resultado» no lo cambia) | Evaluación automática | [reporte del 22-10](busqueda-2026-10-22.md) |
| Búsqueda | «Sin resultado» | precisión 1,00 (0 falsas alarmas en 131 positivas) · recall 0,93 (54 de 58). Con el mismo set y la regla anterior, 36 de 58 (0,62) | Evaluación automática | [reporte del 22-10](busqueda-2026-10-22.md) |
| Búsqueda | Errores de tipeo | 53 casos en las 8 verticales: en la búsqueda agrupada (la de la app) se recuperan 52 corrigiendo la consulta (34 sin corregir), y por vertical 51 (29); «sin resultado», precisión y nDCG@10 iguales a los de arriba | Evaluación automática | [reporte del 24-10](busqueda-2026-10-24.md) |
| Calidad | Tests (24-10-2026) | rappi-ia 2.973 · scraper 305 · prototipo 690 · panel 123 | Verificación local y CI | `make test` · `npm test` |

La búsqueda se evaluó con 131 consultas positivas en las 8 verticales y 58 negativas, con relevancia juzgada automáticamente por concepto ([`queries.json`](../../rappi-ia/src/rappi_ia/eval/queries.json), renovado el 22-10 contra el catálogo). Por tipo de consulta, el híbrido logra 0,970 en las exactas, 0,972 sin tildes y 0,709 en necesidades en lenguaje natural («algo para el carrete»), frente a 0,565 del léxico.

- **Sin concepto ni ocasión (22-10).** Una consulta que no nombra concepto ni ocasión y no calza todas sus palabras necesita un coseno de 0,85 para mostrar algo («sofá de tres cuerpos» en Turbo ya no trae pisco Tres Erres). Salvedad: 0,85 se calibró con estas mismas negativas (la más alta llega a 0,847), 20 de ellas se sumaron junto con la regla y las positivas sin concepto ni ocasión calzan todas sus palabras, así que no miden el costo; ese se midió aparte, en un barrido de frases de usuarios ([decisiones, 22-10](../decisiones.md#búsqueda-e-ia)).
- **Errores de tipeo (24-10).** Si nada calza todas las palabras, la búsqueda corrige la consulta con el vocabulario del catálogo y vuelve a buscar, y lo corregido se muestra solo si calza todas sus palabras: de 53 errores de tipeo ([`typos.json`](../../rappi-ia/src/rappi_ia/eval/typos.json)) la búsqueda agrupada recupera 52 (antes 34), y las negativas y el nDCG no cambian. Salvedad: sin diccionario, unas pocas palabras reales que el catálogo casi no tiene se corrigen mal por vertical («tengo resaca» → «reseca»: 8 de 3.024 búsquedas del barrido de frases), y el aviso deja buscar lo escrito tal cual.

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

Documentos al 04-10-2026 (segunda descarga semanal automática); «Con concepto», del 06-10. En tiendas es una muestra: la página pública muestra hasta 24 productos por sub-pasillo. Turbo quedó con los precios del 27-09 (ver [Límites](../../README.md#límites)).

## Reportes de esta carpeta

| Reporte | Qué mide |
|---|---|
| [busqueda-2026-10-24.md](busqueda-2026-10-24.md) | La corrección de errores de tipeo: set de 53 casos, lo que no cambia y la latencia |
| [busqueda-2026-10-22.md](busqueda-2026-10-22.md) | La evaluación vigente de la búsqueda (set de 131 positivas y 58 negativas) |
| [busqueda-2026-10-06.md](busqueda-2026-10-06.md), [busqueda-2026-10-04.md](busqueda-2026-10-04.md), [busqueda-2026-09-30.md](busqueda-2026-09-30.md) | Evaluaciones anteriores, con otros sets: no se comparan con las de arriba |
| [motor-2026-10-16.md](motor-2026-10-16.md) | La evaluación del motor por fechas, los intentos de la etapa de QA y la escalera fina |
| [qa-motor-2026-10-16.md](qa-motor-2026-10-16.md) | Las ofertas del motor sobre el catálogo real, en solo lectura |
| [simulados-2026-10-17.md](simulados-2026-10-17.md) | El generador simulado recalibrado con la tabla de Rappi: antes y después |
| [capas-precision-2026-10-06.md](capas-precision-2026-10-06.md), [capas-precision-2026-10-06-nueva-muestra.md](capas-precision-2026-10-06-nueva-muestra.md) | La precisión de conceptos, atributos y marcas con jueces LLM, antes y después de corregir las reglas |
