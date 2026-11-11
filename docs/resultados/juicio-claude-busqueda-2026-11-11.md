# Juicio de Claude de la búsqueda (11-11-2026)

200 pares nuevos de la búsqueda actual, juzgados con "sirve", "a medias" o "no sirve". La muestra está en `rappi-ia/src/rappi_ia/eval/planilla-busqueda-ids-2026-11-11.json`. Cada par es una consulta en una vertical y un producto que la búsqueda mostró en una posición, con la misma estratificación y la misma semilla (7) que la muestra del 11-10.

**No es un juicio humano.** Lo hizo Claude; el del 25-10 también fue un juicio de LLM. Sirve para medir la búsqueda de hoy y al juez por concepto con un juez que no depende de los conceptos, pero no reemplaza el juicio de personas. La planilla para personas de la muestra del 11-10 sigue disponible con `rappi-ia jev-planillas` y `rappi-ia eval-human`. Para esta muestra, `eval-human` todavía no lee la planilla fechada: unos juicios de personas se comparan con `eval/judgments.sheet_report` sobre `planilla-busqueda-ids-2026-11-11.json`.

## Método

- **La muestra:**
  - se armó con `rappi-ia jev-planillas --fecha 2026-11-11` sobre `rappi_staging`, en una sesión de solo lectura;
  - usa la búsqueda de `main` del 11-11 (`e3da7d7`) sobre el catálogo de `rappi_staging`: la corrida 9, cerrada el 18-10, más parte de la corrida 11 del 24-10 (89 tiendas), que sigue abierta;
  - no pisa la muestra anterior;
  - comparte 62 pares con la del 11-10, porque el id sale de la vertical, la consulta y el producto.
- **Dos jueces Claude independientes**, con instrucciones redactadas distinto, juzgaron los 200 pares a ciegas: solo vieron la consulta, la vertical, la posición, el nombre, la categoría y la tienda. Ninguno vio el veredicto del juez por concepto (`relevante_auto`) ni el del otro.
- **Acuerdo entre los dos:** 194 de 200 (κ "sirve" 0,96; κ de tres niveles 0,93). Al ser el mismo modelo, ese acuerdo es más alto que el que tendrían dos personas.
- **Los 6 desacuerdos** los decidió un tercero con la misma regla. Por ejemplo, una tostada envasada para "pan para el desayuno" queda "a medias", y un café saborizado para "algo dulce para el café de la tarde", "no sirve".
- **Resultados:** los juicios finales están en `rappi-ia/src/rappi_ia/eval/juicio-claude-2026-11-11.json` (por id de par), junto con los de cada juez y el desempate, para poder recalcular el acuerdo. La comparación usa el mismo cálculo que `rappi-ia eval-human` (`eval/judgments.sheet_report`).

## Resultados

**Lo que muestra la búsqueda** (entre paréntesis, el juicio del 25-10 sobre la muestra del 11-10):

| | n | "Sirve" | Útil ("sirve" o "a medias") |
|---|---:|---:|---:|
| Posiciones 1 a 3 | 119 | 75 % (66 %) | 94 % (95 %) |
| Posiciones 4 a 10 | 81 | 64 % (52 %) | 95 % (86 %) |
| Consulta exacta | 71 | 77 % (70 %) | 97 % (100 %) |
| Sin tildes | 52 | 73 % (63 %) | 100 % (96 %) |
| Necesidad | 77 | 62 % (49 %) | 88 % (80 %) |

| Vertical | n | "Sirve" | Útil |
|---|---:|---:|---:|
| Restaurantes | 25 | 88 % | 100 % |
| Chocolatería | 18 | 78 % | 100 % |
| Licores | 24 | 75 % | 83 % |
| Turbo | 26 | 73 % | 100 % |
| Supermercado | 28 | 68 % | 86 % |
| Conveniencia (Express) | 27 | 67 % | 89 % |
| Rappi Mall | 24 | 67 % | 100 % |
| Farmacia | 28 | 54 % | 100 % |

En total: 141 "sirve", 48 "a medias" y 11 "no sirve".

**El juez por concepto contra este juicio:** acuerdo 79 % (antes 70,5 %), κ 0,40 (antes 0,32) y κ ponderado 0,43 (antes 0,40). Por posición: 81 % en el top 3 y 77 % en 4 a 10.

- En **37 pares** el juez por concepto da por relevante algo que este juicio no llama "sirve": 36 son "a medias" y 1, "no sirve".
- En **5 pares** pasa lo contrario: el juez por concepto los da por no relevantes y sirven.
- **En los 62 pares que se repiten** entre las dos muestras, el juicio coincide en 58.

**Los 11 "no sirve"** se concentran en pocas consultas: 9 son de necesidad y 2, exactas.

- "bebida para mezclar con pisco" (Licores): devuelve piscos y un destilado sin alcohol, no bebidas para mezclar (4 pares).
- "algo dulce para el café de la tarde" (Supermercado): devuelve cafés, no algo dulce (3 pares).
- "algo para ver una película" (necesidad) y "notebook gamer" (exacta), en Express: un set de cocina de juguete y un bingo (3 pares).
- "iphone 15 pro max" (exacta, Supermercado): una mica para iPhone 13 Pro (1 par).

## Qué significa

- **La búsqueda parece mejorar desde el 11-10.** "Sirve" sube en todos los estratos y el que más sube es el de las necesidades, de 49 % a 62 %. Pero la comparación es indicativa, no una medición controlada: son muestras distintas (comparten 62 pares), el catálogo también cambió y los jueces tuvieron instrucciones distintas. En ningún estrato la diferencia es significativa por sí sola (en necesidades, z ≈ 1,6).
- **El juez por concepto sigue siendo generoso,** aunque menos. Mide "es del mismo concepto", no "es lo que se buscaba": casi todo lo que da de más es "a medias".
- **Lo débil son tres consultas de necesidad.** En dos, la búsqueda se queda con una palabra de la consulta (pisco, café) en vez de lo que la persona necesita; en "algo para ver una película", Express devuelve juguetes.

## Próximos pasos

- Que una persona juzgue una submuestra (por ejemplo, 40 de estos 200 pares) para medir cuánto coincide el juicio de Claude con el humano, comparando con `sheet_report` sobre la muestra fechada.
- Revisar las tres consultas de necesidad que fallan ("bebida para mezclar con pisco", "algo dulce para el café de la tarde" y "algo para ver una película" en Express).
