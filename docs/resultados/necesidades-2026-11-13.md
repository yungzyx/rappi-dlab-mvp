<!-- Reporte del 13-11-2026: las búsquedas por necesidad "X para Y" (Fase 6b del plan MVP 4.3). Medido sobre
     rappi_staging en una sesión de solo lectura, con el código de main en d252c4c (antes) y el de la rama (después).
     Comandos: `rappi-ia eval-necesidades` (set eval/necesidades.json), `make eval-check` (`eval-graded --revisar` y
     `eval-mochi --revisar`) y `rappi-ia eval-typos`. Ver docs/decisiones.md (13-11-2026). -->

# Búsquedas por necesidad: "X para Y" pide X (13-11-2026)

El [juicio de Claude del 11-11](juicio-claude-busqueda-2026-11-11.md) encontró tres necesidades que la búsqueda no
resolvía: "bebida para mezclar con pisco" (Licores) traía piscos, "algo dulce para el café de la tarde" (súper) traía
cafés y "algo para ver una película" (Express) traía un set de cocina de juguete y un bingo. Este reporte explica por
qué, qué cambia y cómo queda medido.

**Los juicios de este reporte son de un juez LLM o por concepto, no humanos.**

## Por qué fallaban

Se reprodujeron las tres sobre `rappi_staging`, en `/search` de su vertical y en `/agent/ask`. La hipótesis del plan
(que la detección de concepto se queda con el sustantivo del complemento) explica dos; la tercera es otra cosa.

- **"bebida para mezclar con pisco".** La consulta nombra dos conceptos: "bebida" (gaseosas) y "pisco". Los dos
  quedaban pedidos con el mismo peso, y las palabras de la consulta, con "pisco" adentro, llenaban los candidatos
  léxicos y vectoriales de piscos: en los 20 primeros no había ninguna bebida. El foco por concepto aceptaba los dos, así
  que se mostraban piscos. Con solo el concepto de las gaseosas y la misma consulta, quedaba 1 bebida; buscando
  "bebida", 10. Mochi hacía lo mismo y además ponía el aviso +18.
- **"algo dulce para el café de la tarde".** "algo dulce" sí se entendía como la ocasión antojo, pero un concepto
  nombrado manda sobre la ocasión, y el café estaba nombrado en el complemento: se buscaban cafés.
- **"algo para ver una película".** No nombra concepto: es la ocasión "Panorama en casa" (snacks, gaseosas, juegos de
  mesa, videojuegos y helados). `/search` la buscaba con todos sus conceptos y con una consulta hecha de sus nombres
  ("Snacks salados Bebidas gaseosas Juegos de mesa Videojuegos"). Express casi no vende juegos de mesa (11 productos) ni
  videojuegos (8), y uno de esos 8 es un set de cocina de juguete que Rappi categoriza "Videojuegos" y cuyo documento
  dice poco más que eso: quedaba primero en el vectorial (coseno 0,868) y con el refuerzo del concepto. El bingo entraba
  por "juegos". Mochi no fallaba: reparte la ocasión solo entre lo que la vertical vende de verdad (20 productos o más).

## Qué cambia

- **"X para Y" o "X con Y" pide X** (`concepts/need.py`). Un concepto nombrado después de "para" o "con" es el para
  qué de lo pedido si los complementos curados (`complements.toml`) dicen que va con algo nombrado antes, en cualquier
  sentido. Entonces se busca solo lo de antes del conector ("bebida"), más el texto de la arista Y → X si lo trae
  ("salsa para la pasta" busca también "salsa de tomate pomodoro…"), y el para qué no es un concepto pedido. Sin arista
  no cambia nada: "comida para gato" (un solo concepto), "pilas para control", "shampoo para perro", "arroz con leche",
  "pizza con piña", "café para llevar". "de" no es conector: "galletas de chocolate" dice cómo son las galletas.
- **Lo pedido puede ser una ocasión.** En "algo dulce para el café", lo pedido es el antojo, solo con sus conceptos que
  van con el café, del que más al que menos: pastelería, galletas y chocolates (sin helados ni golosinas, que no tienen
  arista con el café).
- **Sin nada +18 si el alcohol es solo el para qué.** "bebida para mezclar con pisco" no muestra nada +18, aunque la
  tienda marque así una tónica. "pisco con bebida" pide el pisco y lo muestra, como siempre.
- **En `/search`, una ocasión se busca con lo que la vertical vende** (`agent/tools.occasion_in`): sus conceptos con 20
  productos o más en esa vertical (si ninguno, todos), la misma regla de Mochi. "algo para ver una película" en Express
  busca snacks, gaseosas y helados.
- La regla es la misma en `/search` de una vertical, en la agrupada y en Mochi (`agent/understand.py`). Las guardias
  miran todo lo nombrado (`detect_concepts` no cambia): "Lo que sea" y "Lo más buscado" siguen viendo el pisco.
- La demo sin conexión la replica en corto (`search.js: needOf`, con las aristas en `meta.complements` desde la
  próxima muestra): sin la ocasión como lo pedido ni el texto de la arista.

## El set nuevo: 30 necesidades (`eval/necesidades.json`, `rappi-ia eval-necesidades`)

23 de la forma "X para Y" (con las tres del juicio) y 7 controles que no se pueden romper. Cada caso dice qué conceptos
sirven, cuáles no se pueden mostrar y si puede mostrar alcohol. Pasa si muestra al menos 3 productos, de los 5 primeros
al menos 3 son de lo que sirve, ninguno de los 6 primeros es de lo que no se puede mostrar y, sin alcohol pedido, nada
+18. Se mide en `/search` de la vertical, en el primer grupo de la búsqueda agrupada y en Mochi.

| | /search | Agrupada | Mochi |
|---|---|---|---|
| "X para Y" (23), antes | 7 | 5 | 8 |
| "X para Y" (23), después | **22** | **21** | **22** |
| Controles (7), antes y después | 7 | 7 | 7 |

Siguen sin pasar:

- **"leche para el café"** (en las tres): no hay arista entre el café y los lácteos, así que la regla no aplica y se
  muestran cafés con leche. Se deja así a propósito: agregar la arista para que pase sería ajustar el set.
- **"algo para picar con la cerveza" en la agrupada:** ahora se busca exactamente "algo para picar", y esa búsqueda ya
  ponía primero Express con un solo producto. Es una debilidad de "algo para picar", no del para qué.

## Lo que no podía empeorar

- **`make eval-check` pasa.** Los productos nuevos que muestra la rama (36 pares) se juzgaron a ciegas con el criterio
  de la planilla, mezclados al azar (semilla 7) con 40 pares ya juzgados como control: un juez Claude independiente,
  que no sabía del cambio ni cuáles eran control, coincidió en **38 de 40** (κ "sirve" 1,0; los dos desacuerdos son
  "a medias" contra "no sirve"). De los 36 nuevos: 32 "sirve", 4 "a medias" y ninguno "no sirve". Quedan en
  `eval/juicio-llm-complemento.json`, solo con ids. Con los mismos juicios para el antes y el después:

| Juez de tres niveles (juicio LLM) | Antes | Después |
|---|---|---|
| `/search`, 88 consultas: nDCG@10 | 0,925 | **0,943** |
| `/search`: P@3 "sirve" · útil@3 | 0,822 · 0,981 | **0,837 · 0,996** |
| `/search`: lo mostrado que no sirve | 4,1 % | **2,8 %** |
| `/search`, necesidades (25): nDCG@10 · P@3 | 0,850 · 0,720 | **0,913 · 0,773** |
| Mochi, 25 necesidades: nDCG@6 · P@3 · útil@3 | 0,849 · 0,760 · 0,947 | **0,894 · 0,800 · 0,987** |

  En `/search` cambian 4 de 88 consultas: suben las tres del juicio ("algo dulce para el café de la tarde" 0,471 →
  1,0; "bebida para mezclar con pisco" 0,165 → 0,924; "algo para ver una película" 0,714 → 1,0) y baja "regalo para mi
  polola" en el Mall (0,906 → 0,890, P@3 igual): al buscar la ocasión solo con lo que el Mall vende, salen el vino y el
  espumante (2 productos cada uno) y entra la joyería; una bolsa de regalo ("a medias") pasa al primer lugar y los dos
  perfumes que iban primero salen de los 10, aunque de los 10 sirven 9 (antes, 8). Diferencia media +0,018 (IC 95 % por
  bootstrap pareado, 0,000 a 0,041). En Mochi cambian 2 de 25, las dos para arriba (+0,045, IC 0,000 a 0,118). Con 3 y
  2 consultas que cambian, el intervalo no dice más que eso.
- **Las revisiones automáticas de Mochi** (145 frases) quedan iguales: ningún texto contradice lo mostrado, ningún "No
  hay" falso, ningún repetido, 5,8 productos en promedio y las mismas 3 respuestas cortas.
- **Tipeo (`rappi-ia eval-typos`), igual:** 55 de 57 corrigiendo en `/search`, 55 en la agrupada y 54 en Mochi; las
  negativas, 54 de 58; la tabla caso por caso es la misma. Una consulta reescrita ("X para Y" o una ocasión) no se
  corrige: lo pedido ya se entendió.

## Salvedades

- El set nuevo se juzga por concepto: dice si se busca lo pedido, no si cada producto sirve. "snack para la cerveza"
  pasa con snacks poco cerveceros (la arista no trae su texto), y "tónica para el gin" muestra una tónica sabor tomate.
- Los juicios nuevos son de un juez LLM, como los anteriores; el juicio humano de una submuestra sigue pendiente.
- Con un error de tipeo, la regla vale después de corregir: `/search` lee lo corregido igual que lo escrito
  ("bebida para mezclar con piscco" y "bebidda para mezclar con pisco" muestran bebidas). Si la corrección no arregla
  lo pedido, se busca como antes: "bebda para el pisco" no se corrige y muestra piscos.
