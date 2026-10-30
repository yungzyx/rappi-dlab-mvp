# Conversar con Mochi: 25 conversaciones antes y después (25-10-2026)

**Tipo de dato:** juicio propio (✅ bien, ⚠️ a medias, ❌ mal) de las respuestas reales de la API sobre `rappi_staging` (copia de la base del 22-10), no un juicio humano externo ni una métrica automática. Diseño: [docs/diseno/2026-10-25-mochi-conversacion-design.md](../diseno/2026-10-25-mochi-conversacion-design.md).

## Cómo se midió

- Set: [`eval/frases_usuarios/conversaciones.txt`](../../rappi-ia/src/rappi_ia/eval/frases_usuarios/conversaciones.txt), 25 conversaciones de 2 o 3 turnos como las seguiría una persona común (ocasiones, pedidos que se afinan, salud y guardias, cambios de tema). Se corren con `make probar-agente FRASES=src/rappi_ia/eval/frases_usuarios/conversaciones.txt`.
- **Antes:** la API de `main` con el turno anterior que mandaba la app (lo pedido, los conceptos, la vertical y lo mostrado). Es el mejor caso: en la app, "sin carne" escrito en el buscador buscaba en vez de preguntarle a Mochi.
- **Después:** la API de esta rama, con el `conversation` que devuelve cada respuesta.
- Una conversación vale lo que su peor turno: ❌ si algún turno muestra algo que no es lo pedido o pierde lo dicho antes (el tope, la talla, el síntoma), ⚠️ si algún turno es correcto pero pobre.

| | ✅ | ⚠️ | ❌ |
|---|---|---|---|
| Antes | 7 | 8 | 10 |
| Después | 21 | 4 | 0 |

## Las 25 conversaciones

| # | Conversación | Antes | Después |
|---|---|---|---|
| 1 | ¿qué llevo para un asado de 6? → ¿y algo más barato? → ¿y para tomar? | ❌ "más barato" traía albóndigas, carne molida y seitán, sin "para 6"; "para tomar", tres ginger ale | ✅ cortes de asado más baratos con "2,1 kg de carne"; bebidas, jugos y agua "para 6 personas" |
| 2 | algo para una once para 4 → sin lactosa → para 10 personas | ❌ quesos comunes como "sin lactosa"; con 10 personas perdía el "sin lactosa" | ✅ pan, quesos, manjar y mantequilla que dicen "sin lactosa", para 4 y después para 10 |
| 3 | una cena romántica para dos → menos de 20 lucas → otra opción | ⚠️ "otra opción" volvía a mostrar bombones de $44.990 | ✅ "otra opción" sigue bajo $20.000 y sin repetir |
| 4 | picoteo para ver el partido con amigos → más barato → somos 8 | ⚠️ "somos 8" perdía el orden y no decía para cuántos | ✅ más barato y "para 8 personas" |
| 5 | cumpleaños de mi hijo, somos 10 → algo dulce → más barato | ⚠️ solo decoración del Mall | ✅ torta, golosinas, bebida, decoración y juguete del súper |
| 6 | desayuno para dos → en el súper mejor → otra opción | ❌ "No encontré… Lo anoté" y RappiFavor (hay desayunos en restaurantes) | ⚠️ "En el súper no hay desayunos y brunch, pero en restaurantes sí" y "otra opción", otros desayunos; no propone lo del súper para armarlo |
| 7 | sushi → sin palta → más barato | ⚠️ calzaba "sin nori" y "sin arroz"; un "Sin Nori Adicional" de $1.010 como el más barato | ✅ sushi que no nombra la palta, y los más baratos de esos |
| 8 | pizza → sin carne → para 4 personas | ❌ "Pizza Carnivori" y de pepperoni como "sin carne" | ✅ pizzas vegetarianas y veggie, familiares para 4 |
| 9 | quiero un helado → sin lactosa → otra opción | ❌ helados de leche como "sin lactosa" | ⚠️ "No encontré helado sin lactosa" (en la muestra ningún nombre lo dice) con RappiFavor; "otra opción" repite lo mismo |
| 10 | cerveza → ¿y algo más barata? → sin alcohol | ✅ | ✅ |
| 11 | un vino bueno hasta 10 mil → otra opción → menos de 5 lucas | ⚠️ "otra opción" perdía el tope | ✅ |
| 12 | hamburguesa → con papas → en el súper mejor | ⚠️ en el súper, una sola (de betarraga) | ⚠️ igual: las hamburguesas congeladas del súper están rotuladas como carnes |
| 13 | pañales talla G → más baratos → de otra marca | ❌ "más baratos" perdía la talla (XG, P) | ⚠️ siempre talla G; "otra marca" trae otra marca y una ya vista antes |
| 14 | algo dulce → sin azúcar → menos de 3 lucas | ✅ | ✅ y repartido entre chocolates, golosinas, galletas, helados y torta |
| 15 | almuerzo barato → sin carne → otra opción | ❌ mechada, boloñesa y lasaña mixta como "sin carne" | ✅ un almuerzo vegetariano y uno vegano; "otra opción", una paella vegetariana |
| 16 | leche → sin lactosa → más barata | ✅ | ✅ |
| 17 | café en grano → menos de 8 mil → otra opción | ⚠️ "otra opción" perdía el tope | ✅ |
| 18 | algo para el resfrío → más barato | ❌ "más barato" traía sal de fruta y antiácidos | ✅ los mismos remedios que nombran el resfrío, del más barato |
| 19 | algo para el carrete → ¿y para tomar? → sin alcohol | ❌ "sin alcohol" llevaba a Licores (cervezas 0,0); tres ginger ale | ✅ bebidas, jugos y agua de Express; "sin alcohol" no cambia nada |
| 20 | tengo hambre → algo sin carne → para 3 personas | ❌ proteína de soya de Express; "para 3", un producto | ✅ pizza, hamburguesa, sushi, completo y pita veganos de restaurantes, para 3 |
| 21 | sushi → ¿qué es un poke? → más barato | ✅ | ✅ |
| 22 | pizza → tengo dolor de cabeza | ✅ | ✅ |
| 23 | cerveza → pañales talla G | ✅ | ✅ |
| 24 | un regalo para mi mamá → menos de 20 mil → otra opción | ⚠️ "otra opción" perdía el tope | ✅ |
| 25 | comida para perro → más barata → ¿y para gato? | ✅ | ✅ |

## Las 40 preguntas libres (`preguntas-libres.txt`)

El 24-10 quedaron 34 bien, 6 a medias y ninguna mal ([decisiones](../decisiones.md)). Con esta rama, las 6 a medias:

| Pregunta | Antes | Ahora |
|---|---|---|
| cumpleaños de mi hijo, somos 10 | solo decoración del Mall | ✅ el súper, repartido: torta, decoración, golosinas, juguete y bebida |
| me duele la guata | analgésicos (dicen "dolor") | ✅ "No encontré en Farmacia un remedio para eso, y no te puedo recomendar uno: pregúntale al químico farmacéutico" y algo para cuidarse |
| tengo la garganta irritada | dos analgésicos que nombran la garganta entre veinte usos | ✅ lo mismo: ningún remedio la nombra en su nombre o categoría |
| quiero algo picante | una mezcla del súper (salsa, ramen instantáneo, chicharrón) | ✅ platos picantes de restaurantes (ramen, alitas, picante de mariscos), sin salsas ni agregados |
| ¿qué lleva una paella? | arroz, una paila, pulpo, una hallulla | ✅ paellas de restaurantes |
| algo para que mi guagua duerma | pañales | ✅ "no te puedo recomendar remedios ni nada que se tome: eso lo ve su pediatra" y lo de la hora de dormir (chupete nocturno, crema para antes de dormir) |

Lo demás cambia por el reparto de las ocasiones entre sus conceptos: "algo para una once para 4", "qué compro para un picnic", "tengo hambre", "qué puedo cenar con 8 mil" y "algo para comer por menos de 5 lucas" muestran varios tipos de producto en vez de seis del mismo; "¿qué es el ceviche?" muestra solo los ceviches (antes, también cubos de pescado). Ninguna empeoró.

## Lo que sigue a medias

- Una vertical que no vende lo pedido (desayunos en el súper) lo dice, pero no propone con qué armarlo.
- "Sin lactosa" o "sin gluten" dependen de que el nombre lo diga: un helado de agua no tiene lactosa y Mochi no lo sabe.
- "De otra marca" salta los productos ya vistos, no sus marcas.
- Los problemas de rótulo del catálogo siguen ahí (hamburguesas congeladas como carnes, pañales de adulto entre los de talla G).
