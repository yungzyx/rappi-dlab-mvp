# Conversar con Mochi: diseño

Fecha: 25-10-2026. Que se pueda seguir hablando con Mochi después de la primera respuesta («¿y algo más barato?», «sin carne», «para 10 personas», «en el súper mejor», «otra opción»), sin LLM y sin que la API guarde una sesión.

## 1. Qué había

- `POST /agent/ask` ya aceptaba `previous` (lo pedido, los conceptos, la vertical y los productos mostrados) y `agent/understand.py` (`_follow_up`) leía un mensaje corto como seguimiento: «talla g» tras «pañales», «más barata», «de otra marca», «y en el súper?».
- La app guardaba ese turno y lo mandaba con cada pregunta, pero no invitaba a seguir: «sin carne» escrito en el buscador buscaba en vez de preguntar, y no había un lugar para responderle a Mochi.
- Lo que se perdía entre turnos (25 conversaciones de 2 o 3 turnos contra una copia de la base, antes del cambio: 7 bien, 8 a medias y 10 mal): el tope de precio («otra opción» después de «menos de 20 lucas» volvía a mostrar de $69.990), la cantidad de personas, el orden por precio, la talla, el síntoma («más barato» después de «algo para el resfrío» traía antiácidos) y la ocasión (un asado «más barato» traía albóndigas y seitán). «Sin carne» y «sin lactosa» no filtraban nada que no dijera «carne» o «lactosa» (una «Pizza Carnivori», helados de leche).

## 2. El estado de la conversación viaja con la app

La respuesta de `/agent/ask` trae `conversation`: lo que hay que mandar como `previous` en el próximo mensaje, o `null` si la respuesta no se sigue (un saludo, el consejo médico, una aclaración, un servicio). La app lo guarda tal cual y lo devuelve; la API no guarda nada entre mensajes y valida lo que recibe (tamaños; una ocasión o un concepto que no existe se ignora).

| Campo | Qué es |
|---|---|
| `query` | Lo pedido con sus detalles («pizza sin carne», «panales talla g»), sin el orden por precio ni «otra opción» |
| `concepts` | Los conceptos nombrados (vacío si fue una ocasión sin nombrar productos) |
| `occasion` | La ocasión («asado», «once»), si la hubo |
| `vertical` | Dónde respondió |
| `price_max`, `people`, `order` | El tope de precio, para cuántas personas y `barato` o `caro` |
| `symptom` | Habló de síntomas: el seguimiento sigue buscando lo que nombra el síntoma |
| `product_ids` | Lo ya mostrado; se acumula mientras se pida «otra opción» |

## 3. Cómo se combina un mensaje con el anterior

Un mensaje corto que no nombra nada nuevo (o que empieza con «con», «sin», «talla», «más»…) **sigue** el pedido anterior: hereda todo y cambia solo lo que dice.

| Se dice | Cambia |
|---|---|
| «más barato», «algo más económico», «uno más caro» | el orden (queda para los siguientes turnos) |
| «menos de 10 lucas», «hasta 20 mil» | el tope de precio |
| «para 10 personas», «somos 8» | la cantidad de personas (y la carne del asado) |
| «sin carne», «sin lactosa», «sin palta» | se suma a lo que no va |
| «en el súper mejor», «y en la farmacia?» | la vertical |
| «otra opción», «de otra marca», «ninguno me gustó» | sin lo ya mostrado, con el mismo tope, personas y exclusiones |

**Tema nuevo:** un mensaje que nombra otro producto, ocasión o síntoma («tengo dolor de cabeza» después de una pizza, «pañales talla G» después de cerveza) o pregunta por un plato («¿qué es un poke?») parte de cero. Si empieza con «y» («¿y para tomar?» después de un asado de 6), es la misma junta: conserva solo la cantidad de personas.

**Ocasiones:** el seguimiento de una ocasión sigue siendo la ocasión (el asado «más barato» son cortes de asado más baratos, no cualquier carne), y sus resultados se reparten entre sus conceptos (un cumpleaños: torta, golosinas, bebidas, decoración y juguetes, no solo decoración).

**Lo que no va («sin»):** si es un régimen (carne, lactosa, gluten, azúcar, alcohol), el nombre del producto tiene que decirlo (sin carne: «vegetariana», «vegana», «veggie», «vegetal»): no se sabe si un helado común tiene lactosa. Si nada lo dice, Mochi lo dice y no muestra otra cosa. Si es un ingrediente («sin palta»), queda fuera lo que lo nombra. «Sin alcohol» sobre bebidas que no tienen alcohol no cambia nada (y nunca lleva a Licores).

**Otra vertical sin el producto:** «en el súper mejor» para algo que el súper no vende (desayunos listos) lo dice y dice dónde hay; no se anota como demanda no satisfecha (existe en Rappi).

## 4. En la app

Debajo de la respuesta de Mochi (si trajo productos y no es de salud), chips de un toque para refinarla: «Más barato», «Otra opción», «Sin carne» (en restaurantes, si no lo dice ya) y, con una ocasión o una cantidad de personas, «Para N personas» (N = las de ahora más 2). Arriba de la respuesta, lo pedido: «Pediste «asado de 6» · «más barato»». Las guardias no cambian: los chips no ofrecen nada que Mochi no ofrecería por su cuenta, y bajo una respuesta de salud no hay chips.

**Desde el 26-10-2026 no hay campo «Sigue con Mochi»** ([decisión](../decisiones.md#agente-mochi)): Mochi no tiene chat. Cada chip manda la frase que `_follow_up` ya entiende con el `previous` de siempre, así que la API no cambió; un refinamiento sin chip («menos de 10 lucas», «en el súper mejor») se puede escribir en el buscador y tocar «Pídele a Mochi», que sigue la respuesta anterior.

## 5. Demo sin conexión

La API simulada (`prototipo-app/src/api/offline/`) sigue los mismos seguimientos sobre la muestra grabada: reordena por precio, aplica el tope, quita lo ya mostrado, filtra «sin X» por el nombre, cambia de vertical si la muestra tiene productos ahí y dice la cantidad de personas. Lo que no puede (una pregunta nueva que la muestra no grabó, un «sin X» que ningún producto de la muestra dice) lo dice.

## 6. Las seis preguntas que quedaron a medias (24-10)

| Pregunta | Antes | Ahora |
|---|---|---|
| cumpleaños de mi hijo, somos 10 | solo decoración del Mall | el súper, repartido entre torta, golosinas, bebidas, decoración y juguetes |
| me duele la guata | analgésicos (dicen «dolor») | una parte del cuerpo no trae analgésicos genéricos: «no encontré un remedio para eso, pregúntale al químico farmacéutico» y algo para cuidarse |
| tengo la garganta irritada | analgésicos que nombran la garganta entre veinte usos | igual: para una molestia localizada el nombre o la categoría del remedio tiene que nombrarla |
| quiero algo picante | una mezcla del súper (salsa, ramen instantáneo, chicharrón) | un antojo sin concepto («algo picante») se busca primero en restaurantes, con lo que lo dice en el nombre |
| ¿qué lleva una paella? | arroz, una paila, pulpo, una hallulla | la ficha dice dónde buscar el plato (`vertical`): paellas de restaurantes |
| algo para que mi guagua duerma | pañales | no recomienda nada para que duerma (eso lo ve su pediatra) y muestra lo de la hora de dormir que no es salud (chupete nocturno, crema para antes de dormir) |

## 7. Fuera

Un historial de chat (se ve la última respuesta y lo dicho), deshacer un refinamiento («con carne de nuevo»), recordar la conversación entre sesiones y entender con un LLM: las reglas alcanzan para estos seguimientos y la demo no puede depender de la red.
