# Juicio LLM de la búsqueda (25-10-2026)

Los 200 pares de la planilla de búsqueda (`rappi-ia/src/rappi_ia/eval/planilla-busqueda-ids.json`: una consulta en una vertical y un producto que la búsqueda mostró en una posición, estratificados por vertical, tipo de consulta y posición) juzgados con «sirve», «a medias» o «no sirve».

**No es un juicio humano.** Sirve para medir al juez por concepto con un juez independiente de la búsqueda, pero no reemplaza el juicio de personas: la planilla para personas sigue disponible con `rappi-ia jev-planillas` y `rappi-ia eval-human`.

## Método

- **Dos jueces LLM independientes** (el mismo modelo, con instrucciones redactadas distinto) juzgaron los 200 pares a ciegas: solo vieron la consulta, la vertical, la posición, el nombre, la categoría y la tienda. Ninguno vio el veredicto del juez por concepto (`relevante_auto`) ni el del otro.
- **Acuerdo entre los dos:** 193 de 200 (κ «sirve» 0,96; κ ponderado 0,95). Al ser el mismo modelo, ese acuerdo es más alto que el que tendrían dos personas: no mide la dificultad de la tarea.
- **Los 7 desacuerdos** los decidió un tercero, con la misma regla. Por ejemplo, el cabezal de repuesto para «cepillo de dientes eléctrico» queda «a medias», y la vela para «algo dulce para un cumpleaños», «no sirve».
- Los juicios finales están en `rappi-ia/src/rappi_ia/eval/juicio-llm-2026-10-25.json` (por id de par). La comparación usa el mismo cálculo que `rappi-ia eval-human` (`eval/judgments.sheet_report`).
- La muestra de pares es del 11-10-2026: es anterior a los cambios de la búsqueda del 21 al 24-10 (#125, #129 y #135), que sacaron justamente parte de lo que aquí sale «no sirve».

## Resultados

**Lo que muestra la búsqueda:**

| | n | «Sirve» | Útil («sirve» o «a medias») |
|---|---:|---:|---:|
| Posiciones 1 a 3 | 115 | 66 % | 95 % |
| Posiciones 4 a 10 | 85 | 52 % | 86 % |
| Consulta exacta («leche descremada») | 70 | 70 % | 100 % |
| Sin tildes | 51 | 63 % | 96 % |
| Necesidad («algo para la once») | 79 | 49 % | 80 % |

| Vertical | n | «Sirve» | Útil |
|---|---:|---:|---:|
| Restaurantes | 25 | 80 % | 100 % |
| Express | 28 | 68 % | 86 % |
| Supermercado | 27 | 67 % | 89 % |
| Licores | 23 | 65 % | 83 % |
| Turbo | 25 | 56 % | 96 % |
| Chocolatería | 18 | 56 % | 89 % |
| Farmacia | 28 | 50 % | 96 % |
| Rappi Mall | 26 | 38 % | 88 % |

**El juez por concepto contra el juicio LLM:** acuerdo 70,5 %, κ 0,32 (binario, «sirve» contra el resto) y κ ponderado 0,40. Por posición: 72 % en el top 3 y 68 % en 4 a 10.

- En **54 pares** el juez por concepto da por relevante algo que el juicio LLM no llama «sirve»: **51 son «a medias»** (mismo concepto, pero otro formato, otra marca, un repuesto o una versión infantil) y 3, «no sirve».
- En **5 pares** pasa lo contrario: el juez por concepto los da por no relevantes y sirven.

## Qué significa

- **El juez por concepto es generoso.** Mide «es del mismo concepto», no «es lo que se buscaba». Por eso el nDCG@10 de 0,905 del README es optimista, y la ventaja del híbrido (que recibe un refuerzo por ese mismo concepto) sigue sin probarse.
- **La búsqueda es útil casi siempre en lo primero que se ve:** 95 % de los tres primeros resultados sirven o sirven a medias.
- **Lo más débil son las necesidades** («algo para ver una película» en Express traía un kit para auto) **y Rappi Mall**, donde «sirve» es 38 %: el catálogo del Mall es amplio y los conceptos, gruesos.

## Próximos pasos

- Juzgar con personas una submuestra (por ejemplo, 40 pares al azar de estos 200) para medir cuánto coincide el juicio LLM con el humano.
- Recalcular el nDCG@10 con un juez de tres niveles (este juicio LLM o el de personas) en vez del juez por concepto.
- Rehacer la muestra con la búsqueda actual: esta es anterior a #125, #129 y #135.
