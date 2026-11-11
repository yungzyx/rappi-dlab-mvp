# Prueba con usuarios del MVP: AAAA-MM-DD

> Plantilla. Copiarla como `prueba-usuarios-AAAA-MM-DD.md`, llenar cada sección y borrar estas notas. El guion, el consentimiento y cómo se arma cada resumen están en [prueba-usuarios.md](../prueba-usuarios.md). Aquí no va ningún nombre, id (`proto-…`) ni dato que identifique a alguien: cada persona es P1 a P5, y los resúmenes de `rappi-ia resumen-prueba` y las hojas del observador se quedan fuera de git.

**Tipo de dato:** prueba moderada con N personas en una sesión guiada, sobre dlab-mvp.com (uso del MVP, población `prototype`). Describe lo que hicieron y dijeron; no mide retención ni efecto, y sus cifras no se comparan con la tabla de Rappi ni con las simuladas.

## Cómo se hizo

| Qué | Valor |
|---|---|
| Fecha y lugar | AAAA-MM-DD, … |
| Versión de la app | commit `…` de `main` que servía dlab-mvp.com |
| Equipo | teléfono / notebook, navegador … |
| `OFFERS_CONTROL_PCT` | 0 ("Grupo de control: 0 %" en `chequeo-sesion.sh` antes de cada participante) |
| Roles | moderador, observador (sin nombres) |
| Desvíos del guion | … (o "ninguno") |

## Participantes

Solo lo que sirve para leer los resultados, sin datos personales.

| | Usa apps de delivery | Qué pide por app (verticales) | Notas |
|---|---|---|---|
| P1 | | | |
| P2 | | | |
| P3 | | | |
| P4 | | | |
| P5 | | | |

## Tareas

En cada celda: sola, con ayuda o no, y entre paréntesis el tiempo aproximado (por ejemplo, "con ayuda (3 min)").

| Tarea | P1 | P2 | P3 | P4 | P5 | Qué pasó |
|---|---|---|---|---|---|---|
| 1. Buscar con un error de tipeo | | | | | | … |
| 2. "Algo para la once" | | | | | | … |
| 3. Agrega algo al carro y vuelve al inicio | | | | | | … |
| 4. "¿Por qué?" y decidir | | | | | | … |
| 5. Ocultar a Mochi y traerlo de vuelta | | | | | | … |
| 6. Pedir hasta el seguimiento | | | | | | … |

## Lo que dejó cada sesión (de los resúmenes)

Copiado del resumen de cada persona (`rappi-ia resumen-prueba`). La duración es la de la sesión en la app, del primer al último evento.

| | P1 | P2 | P3 | P4 | P5 |
|---|---|---|---|---|---|
| Duración | | | | | |
| Búsquedas (sin resultado / corregidas) | | | | | |
| Ofertas de Mochi mostradas | | | | | |
| … aceptadas / rechazadas / se fue sola / sin respuesta | | | | | |
| Abrió el "¿Por qué?" | | | | | |
| Abrió la vertical o la búsqueda desde la oferta (Ver/Abrir) | | | | | |
| Productos agregados desde una oferta | | | | | |
| Verticales abiertas | | | | | |
| Verticales con pedido | | | | | |
| ¿Abrió o pidió en otra vertical que la primera? ¿Por qué camino? (acceso de la Home, oferta de Mochi, buscador; del "Recorrido por verticales") | | | | | |
| Ocultó a Mochi (y lo trajo de vuelta) | | | | | |
| Pedidos (cancelados) | | | | | |

## Las ofertas y su "¿Por qué?"

Una fila por oferta que la persona miró en las tareas 3 y 4. El texto del "¿Por qué?" lo copió el observador: la app no lo guarda.

| | Momento y concepto (del resumen) | Lo que la persona creyó antes de leer | Texto del "¿Por qué?" | ¿Coincide? ¿Le pareció razonable? | ¿La aceptó? Su motivo |
|---|---|---|---|---|---|
| P1 | … | … | … | … | … |

## Cuestionario

De 1 (muy en desacuerdo) a 5 (muy de acuerdo). Con 5 personas se muestran los valores de cada una, la mediana y el rango, no un promedio ni porcentajes.

| Afirmación | P1 | P2 | P3 | P4 | P5 | Mediana (rango) |
|---|---|---|---|---|---|---|
| 1. Entendí por qué Mochi me ofrecía lo que me ofrecía | | | | | | |
| 2. Lo que Mochi me ofreció era algo que podría querer | | | | | | |
| 3. Mochi me estorbó mientras usaba la app (al revés: 5 es malo) | | | | | | |
| 4. Me dieron ganas de pedir en una categoría que no uso | | | | | | |
| 5. Encontré lo que buscaba aunque lo escribiera mal | | | | | | |

Preguntas abiertas, con las palabras de cada persona (citas cortas):

1. **¿Qué crees que hace Mochi y de dónde saca lo que te ofrece?**
   - P1: "…"
2. **¿Hubo un momento en que Mochi te molestó o te confundió? ¿Cuál?**
   - P1: "…"
3. **Si usaras esto de verdad, ¿pedirías algo en una categoría que hoy no usas? ¿Qué te haría hacerlo?**
   - P1: "…"

## Criterios

Los de [prueba-usuarios.md](../prueba-usuarios.md#criterios-fijados-antes-de-la-primera-sesión), con el umbral fijado antes de la primera sesión: no se cambia aquí. "n de 5 observado" cuenta a quienes mostraron la señal; si llega al umbral, se dispara el cambio.

| Pregunta | Señal | Umbral | n de 5 observado | ¿Llega al umbral? (se dispara el cambio) | Cambio que se dispara |
|---|---|---|---|---|---|
| ¿Se entiende el "¿Por qué?"? | En la tarea 4, lo que creía antes de leer no coincide con el texto, o dice que no lo entiende; o marca 1 o 2 en la afirmación 1 | 3 de 5 | | | Reescribir la plantilla del texto del "¿Por qué?" de ese momento |
| ¿Se nota la oferta? | Entre quienes tuvieron la oferta en la Home (momento "carrito" en el resumen): en la tarea 3 no la vio o se fue sola. A quien la Home no se la mostró no se cuenta: va a "Problemas encontrados" | 2 de quienes la tuvieron en la Home (anotar "n de m") | | | Revisar dónde y cuánto rato se muestra el globo con oferta en la Home |
| ¿Se entiende qué pasa al aceptarla? | En la tarea 4 se sorprende de lo que pasó al tocar el "+" de un producto o "Ver …", o dice que no sabía que el "+" lo agregaba al carro | 2 de 5 | | | Cambiar cómo se ve o se rotula el "+" de los productos del globo |
| ¿Se puede rechazar sin problema? | No encuentra "Ahora no" o "Después", o pide ayuda para decir que no | 2 de 5 | | | Hacer más visible el botón de rechazar |
| ¿Mochi estorba? | Marca 4 o 5 en la afirmación 3, o lo cuenta en la pregunta abierta 2 | 2 de 5 | | | Revisar cuántas veces y cuándo habla Mochi en la Home |
| ¿Se puede ocultar y traer de vuelta? | En la tarea 5 no lo trae de vuelta sin ayuda | 1 de 5 | | | Mover o rotular "Mostrar a Mochi" |
| ¿Se entiende la corrección del tipeo? | En la tarea 1 no ve "Mostrando resultados para…", o marca 1 o 2 en la afirmación 5 | 2 de 5 | | | Revisar el aviso de la corrección en los resultados |
| ¿Lleva a mirar otra vertical? | No abre otra vertical por un acceso de la Home ni por una oferta de Mochi (recorrido del resumen) | 4 de 5 | | | Revisar, antes de una prueba más grande, si la oferta de vertical por probar aparece y se entiende; no se concluye nada de efecto ni de retención |

## Problemas encontrados

De más a menos grave. Gravedad: alta (impide la tarea), media (la demora o confunde), baja (molesta).

| Problema | Quiénes (n de N) | Gravedad | Dónde (pantalla o tarea) | Qué cambiar |
|---|---|---|---|---|
| … | … de N | … | … | … |

## Qué se puede decir

Respuestas a las tres preguntas de la prueba, siempre como "n de N" y con las citas que las apoyan.

1. **¿La Home dinámica y Mochi llevaron a probar otra vertical?** …
2. **¿Se entendió el "¿Por qué?"?** …
3. **¿Se entendieron las ofertas?** …

## Qué no se puede decir

Esta prueba no mide retención (una sesión, pedidos de mentira), no muestra un efecto de Mochi (sin grupo de control, con tareas que piden buscar, decidir sobre una oferta y pedir, y con alguien mirando) y no representa a quienes usan Rappi (N personas elegidas por conveniencia). Sus cifras no se juntan con las simuladas ni se comparan con la tabla de Rappi, que además es una correlación.

## Próximos pasos

- Qué se arregla antes de la próxima ronda: …
- Qué se vuelve a probar, y con quiénes: …
