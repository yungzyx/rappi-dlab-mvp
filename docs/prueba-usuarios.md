# Prueba con usuarios del MVP

Guion para probar el MVP con personas en dlab-mvp.com: qué se quiere saber, cómo invitar y pedir el consentimiento, las 6 tareas, el cuestionario, cómo anotar a cada participante y qué se puede concluir. Hasta hoy toda la evidencia del proyecto es simulada o de jueces LLM ([README.md#resultados](../README.md#resultados)); esta prueba es la primera con personas. No es la de [probar-agente.md](probar-agente.md), que manda frases escritas por el equipo a la API.

El resumen de cada persona lo arma `rappi-ia resumen-prueba` (solo lee la base), y el reporte final se escribe con la [plantilla](resultados/prueba-usuarios-PLANTILLA.md).

## 1. Objetivo

El objetivo del proyecto es la retención: que una persona combine más verticales. La tabla de Rappi (Restaurantes + Turbo + Retail retiene 93 % en M+1) es una correlación entre quienes ya combinan; no dice que empujar a alguien a otra vertical lo retenga. Esta prueba no busca eso. Busca responder, con lo que se ve en una sesión:

1. **¿La Home dinámica y Mochi llevan a probar otra vertical?** Si la persona abre o pide en una vertical distinta de la primera que usó, y si fue por un acceso de la Home, una oferta de Mochi o por su cuenta.
2. **¿Se entiende el "¿Por qué?"?** Si lo que la persona cree que es el motivo de una oferta coincide con el texto del "¿Por qué?", y si ese texto le parece razonable.
3. **¿Se entienden las ofertas?** Qué cree que ofrece Mochi, qué pasa si la acepta y si la puede rechazar sin problema.

De paso, la búsqueda con errores de tipeo y si Mochi molesta (ocultarlo y traerlo de vuelta).

## 2. Participantes y consentimiento

- **Cuántas:** 5 personas para la primera ronda, que hayan pedido por una app de delivery en el último mes. Que no sean del equipo ni hayan visto la demo. Mejor si son distintas entre sí: una que solo pide comida, otra que hace el súper por app, alguien que casi no usa apps.
- **Sin datos personales:** la app no pide cuenta, nombre, correo ni teléfono; la dirección y la tarjeta del checkout son de ejemplo (no se escribe ninguna) y ningún pedido se cobra ni se entrega. Cada participante es un id seudónimo (`proto-…`) que da la API, y todo lo que hace queda con `source = 'prototype'`, que nunca se mezcla con la población simulada (`synthetic`). En las notas, cada persona es P1 a P5: su nombre no se escribe en ninguna parte, ni junto al id.
- **Lo que escriba en el buscador se guarda** (sin correos, RUT, teléfonos, tarjetas ni direcciones, que se redactan antes) hasta que se borra al terminar las sesiones del día (sección 6). Se le pide que no escriba datos suyos.
- **Respaldos:** el equipo que sirve la demo respalda la base cada noche a las 03:30 y guarda los 3 respaldos más nuevos. Por eso `olvidar` se corre el mismo día, antes de esa hora (sección 6). Si se atrasa, una copia de seguridad puede guardar lo de la sesión hasta 3 días más, hasta que rota.
- **Sin grabación:** no se graba pantalla ni voz. El observador anota lo que la persona dice.

Antes de empezar, el moderador lee esto y espera un sí:

> Estamos probando un prototipo del programa dLab, desarrollado junto con Rappi Chile; no es la app oficial. Queremos ver si se entiende, no evaluarte a ti: si algo no funciona, es culpa del prototipo. Los pedidos son de mentira, nadie te cobra ni te llega nada. No necesitas dar tu nombre ni ningún dato tuyo; por favor no los escribas en la app. Guardamos lo que haces en la app con un número al azar, sin tu nombre, y lo borramos al terminar, después de anotar un resumen. No grabamos ni la pantalla ni tu voz. Puedes parar cuando quieras. ¿Te parece bien?

Se lee antes de abrir la pestaña privada (sección 6): al abrir dlab-mvp.com la app ya crea un id y guarda eventos. Si dice que no, no se abre la pestaña ni hay sesión. Si para en medio, se borran sus datos igual (sección 6).

## 3. Antes de la primera sesión

- **Equipo:** un teléfono del equipo con el navegador (o un notebook con la vista de teléfono), en dlab-mvp.com. La puerta de acceso (usuario y clave) la escribe el moderador, nunca la persona.
- **Modo:** si el sitio se construyó sin `VITE_DEMO` (lo normal, ver [despliegue.md](despliegue.md)), siempre abre en el prototipo con Mochi ("Propuesta") y no tiene el interruptor de la demo. Si se construyó con `VITE_DEMO=1`, tiene el interruptor (tecla D y la fila de Cuenta) y el navegador recuerda el último modo: antes de cada sesión, dejarlo en "Prototipo final ✨", no en "Rappi hoy".
- **Grupo de control apagado:** `OFFERS_CONTROL_PCT` en 0 (lo de siempre). El chequeo de antes de cada participante (abajo) lo muestra ("Grupo de control: 0 %") y no da "Listo para la sesión" si no está en 0. Lo calcula como la API, de `~/rappi-tunel/tunel.env` o, si no lo define, del `.env` de `rappi-ia` de la copia que se sirve. Es el valor con que arranca la API, que lo toma al reiniciarse: si alguien lo cambió hace poco, reiniciar la API (`launchctl kickstart -k gui/$(id -u)/cl.rappidlab.api`). Si no está apagado, a una persona le pueden retener las ofertas de Mochi y la tarea 3 no se puede hacer; el resumen lo diría en "Experimentos: … ofertas_control = control".
- **Comandos:** `rappi-ia resumen-prueba` y `rappi-ia olvidar` corren en el equipo que sirve la demo, con el `.env` que apunta a su base (en el Mac de [deploy/macos](../deploy/macos/README.md), desde `rappi-ia/` de esa copia y con su `.venv`).
- **Roles:** un moderador (lee las consignas, no ayuda) y un observador (anota). Pedirle a la persona que piense en voz alta.
- **Hojas:** una [hoja del observador](prueba-hoja-observador.md) impresa por participante, más una para la corrida en seco.
- **Despliegues en pausa**, desde antes de la corrida en seco: en el Mac que sirve la demo, `touch ~/rappi-tunel/pausa-actualizar`. Mientras exista, `actualizar.sh` no despliega (anota "Pausado" cada 15 minutos) y lo que se fusione a `main` no llega a la demo. Sin la pausa, un despliegue reinicia la API (unos segundos sin Mochi), puede recargar la pestaña del participante (pierde lo que Mochi recordaba de la sesión) y, si trae migraciones, deja un respaldo con lo de la sesión. Se quita recién después del `olvidar` del día (sección 6); si las sesiones siguen otro día, se vuelve a crear antes.
- **Una corrida en seco** con alguien del equipo, en una pestaña privada como las de verdad (sección 6). Al terminarla, con los mismos dos pasos del final de la sección 6: `resumen-prueba --desde <hora en que empezó la corrida>` da su id (anotarlo) y `olvidar` con ese id la borra. Así no queda en el servidor aunque las sesiones de verdad sean otro día.
- **Justo antes de cada participante** (no una vez al día), en el Mac que sirve la demo, desde su copia del repo: `deploy/macos/chequeo-sesion.sh`. Solo lee: dice si la API está lista, la swap, el disco libre, la fecha del catálogo, si los despliegues están en pausa y el grupo de control, y hace 8 búsquedas con su tiempo y el máximo (no cuentan como visitas en el resumen diario). Termina en "Listo para la sesión" o en "Revisar antes de la sesión", con lo que falta. Si una búsqueda pasó de 1 s, correrlo otra vez: la primera después de un rato sin uso suele ser la lenta, y la API tiene dos procesos, así que las 8 pueden caer en uno solo. Si sigue lento, avisar a quien opera la demo antes de recibir a la persona.

## 4. Guion: 6 tareas (unos 25 minutos)

Antes de la tarea 1, el moderador cierra el aviso de privacidad y la guía de la primera visita (sección 6, paso 2): mientras la guía está abierta, Mochi no muestra la oferta de la tarea 3. Se lee cada consigna tal cual. Si la persona se traba más de 2 minutos, el moderador pregunta "¿qué buscarías?" y, si sigue, da la pista y lo anota como "con ayuda". El observador anota por tarea, en la [hoja del observador](prueba-hoja-observador.md): si la completó (sola, con ayuda o no), el tiempo aproximado y lo que dijo.

| # | Consigna | Qué mirar | Qué deja el resumen |
|---|---|---|---|
| 1 | "Busca unos Doritos. Escríbelo rápido, como te salga; si te sale bien, escribe 'doritoz'." | Si ve el aviso "Mostrando resultados para…" y si le parece bien que corrija. Otro error que el buscador corrige: "mantequlla" ([reporte del 24-10](resultados/busqueda-2026-10-24.md)) | La búsqueda con `corregida a "doritos"`, o "sin resultado" si no la corrigió |
| 2 | "Ahora pídele a Mochi algo para la once." | Si entiende que el buscador también es Mochi, qué espera que pase y si las tarjetas y los chips le sirven | Lo escrito, como pedido a Mochi ("Mochi") y, si también buscó, en el buscador, con cuántos resultados |
| 3 | "Agrega algo al carro y vuelve al inicio." Agrega desde el buscador o desde una tienda, y vuelve a la Home (también vale cerrar el buscador de Mochi). Ahí Mochi muestra la oferta en un globo: un texto, los productos que ofrece como tarjetas con "+", "¿Por qué?", "Ver …" y "Ahora no". Apenas aparece, el moderador lee la consigna 4 sin esperar: si nadie la toca, la oferta se va sola a los 30 s, y el "¿Por qué?" abierto detiene la cuenta. El globo "Moví … al primer lugar…" no es la oferta: es la Home que reordenó sus accesos. Puede salir antes, después o en vez de la oferta (si Mochi no tiene oferta para lo agregado, o al volver a la Home después de las tareas 1 o 2), y no se pregunta por él | Si nota la oferta. Si en la Home no aparece oferta: en el checkout, que toque "¿Me falta algo?" (ahí no aparece por su cuenta; también trae "¿Por qué?" y la consigna 4 se hace igual; solo tiene "Agregar": no hay botón para rechazar ni se va sola) | La oferta mostrada, con su momento, concepto y vertical |
| 4 | "Antes de tocar nada: ¿por qué crees que Mochi te propuso eso? Ahora toca '¿Por qué?'." Después de que lo lea: "Ahora decide qué haces con lo que te propone, y cuéntanos por qué." | Lo que la persona cree antes de leer, si el texto coincide o le sorprende, y su decisión con su motivo, dicho con sus palabras: si agrega un producto con su "+", si toca "Ver …" (abre la búsqueda con lo ofrecido) o "Ahora no" (la rechaza). El observador copia el texto del "¿Por qué?" y anota el botón que tocó | Que abrió el "¿Por qué?" (`offer_why_open`), de qué oferta y de qué sale (el texto no se guarda), y si la oferta se aceptó, se rechazó ("Ahora no" del carro, "Después" de la vertical por probar) o se fue sola; si tocó "Ver …" o "Abrir …", el recorrido lo muestra como "Mochi (momento)" |
| 5 | "Imagina que Mochi te molesta: escóndelo. Ahora tráelo de vuelta." | Si encuentra el menú de Mochi ("Ocultar"), y "Mostrar a Mochi" en Cuenta para traerlo | "Ocultó a Mochi: sí", con la hora y desde dónde (`menu-mochi`, `cuenta`) |
| 6 | "Haz un pedido de algo que pedirías de verdad, de la tienda que quieras, hasta ver por dónde viene." | Dónde duda en el checkout, si mira la sugerencia de Mochi antes de pagar, si llega al seguimiento | El pedido (vertical, total, líneas que salieron de una oferta, estado) y su vertical en "Con pedido" |

Después de la tarea 6, una pregunta abierta antes del cuestionario: "¿Hay algo que te haya llamado la atención?".

## 5. Preguntas al final

Cinco afirmaciones de 1 a 5 (1 = muy en desacuerdo, 5 = muy de acuerdo). El moderador las lee, sin explicarlas, y el observador anota el número en la [hoja](prueba-hoja-observador.md).

1. Entendí por qué Mochi me ofrecía lo que me ofrecía.
2. Lo que Mochi me ofreció era algo que podría querer.
3. Mochi me estorbó mientras usaba la app. (Al revés que las otras: un 5 es malo.)
4. Me dieron ganas de pedir en una categoría que no uso (súper, farmacia, licores, Turbo…).
5. Encontré lo que buscaba aunque lo escribiera mal.

Tres preguntas abiertas:

1. ¿Qué crees que hace Mochi y de dónde saca lo que te ofrece?
2. ¿Hubo un momento en que Mochi te molestó o te confundió? ¿Cuál?
3. Si usaras esto de verdad, ¿pedirías algo en una categoría que hoy no usas? ¿Qué te haría hacerlo?

## 6. Cómo anotar a cada participante

Una persona nueva por participante: **una pestaña privada (de incógnito) nueva para cada una**. Empieza sin nada guardado en el navegador, y la API le da un id nuevo. La app no muestra el id y en un teléfono no se puede leer, así que los resúmenes y el borrado se hacen al final, en el equipo que sirve la demo, con los ids que salen del resumen por hora. Así no hay que ir a la terminal entre una persona y otra.

Para cada participante:

1. **Consentimiento** (sección 2), antes de abrir la pestaña: si dice que no, no se abre y no queda nada en la base.
2. **Pestaña privada nueva**, con el chequeo de la sección 3 en "Listo para la sesión". En el teléfono, cerrar todas las pestañas privadas (en Chrome comparten lo guardado mientras quede una abierta) y abrir una nueva en dlab-mvp.com; la puerta de acceso la escribe el moderador. Anotar la hora (HH:MM) en la [hoja](prueba-hoja-observador.md) de P*n*. Antes de pasarle el teléfono, el moderador cierra el aviso de privacidad con "Entendido" (en una pestaña privada nueva sale siempre), espera el saludo de Mochi (unos 7 s) y, cuando aparece la guía de la primera visita, la cierra con "Saltar". Si no la cierra, la guía sale en medio de la tarea 1 y la oferta de la tarea 3 espera a que termine.
3. **Tareas y cuestionario** (secciones 4 y 5). Que la persona no toque "Borrar mis datos" ni "Olvidar" de Mochi en medio: borran lo hecho hasta ahí. Si pide que se borre en ese momento, "Borrar mis datos" (Cuenta) lo hace en el servidor, y esa persona queda sin resumen.
4. **Cerrar la pestaña privada.**

Al terminar las sesiones del día, en el equipo que sirve la demo (sección 3), el mismo día y antes de las 03:30, cuando corre el respaldo nocturno (sección 2):

1. **Los resúmenes**, desde la hora del primer participante:

   ```bash
   cd rappi-ia
   .venv/bin/python -m rappi_ia resumen-prueba --desde 2026-11-03T15:00 --salida ~/prueba-usuarios/2026-11-03
   ```

   Escribe un Markdown por persona del prototipo creada desde esa hora (`proto-….md`), con la hora en que se creó al comienzo. La de P*n* es la que coincide con la hora de su hoja y con lo que hizo; si sale alguna de más (una pestaña que se abrió de más, o alguien que entró a la demo en ese rato), ver el paso 2. Renombrar el archivo a `P1.md` y anotar su id en la hoja de P1.
2. **Borrar** los ids que listó `resumen-prueba --desde …` en la ventana de las sesiones: los de P1 a P5 y cualquiera que no se sepa de quién es. Solo se deja uno del que se sepa quién es y que no es de la prueba (la corrida en seco ya se borró al terminarla, sección 3):

   ```bash
   .venv/bin/python -m rappi_ia olvidar proto-… proto-…
   ```

   Dice cuántos eventos, pedidos y sesiones tiene cada una y pide confirmación ("s"). Borra lo mismo que "Borrar mis datos" de la app (DELETE /profile): la persona entera, con sus eventos, búsquedas, pedidos, sesiones y preferencias, y su afinidad y su recompra del motor, en cascada. Solo acepta personas del prototipo: si un id es de una simulada o no existe, no borra a ninguna. Con esto se cumple lo dicho en el consentimiento: se borra al terminar, después de anotar el resumen.
3. **Reanudar los despliegues**, solo después de `olvidar`: `rm ~/rappi-tunel/pausa-actualizar` (si las sesiones siguen otro día, se puede dejar). La vuelta siguiente de `actualizar.sh` despliega lo que se haya fusionado entretanto. Si un respaldo se tomó entre una sesión y el borrado (un `pre-migracion_*.dump` o un `nocturno_*.dump` en `~/rappi-tunel/respaldos/` de esas horas), anotarlo y mandarlo a la Papelera.

Los resúmenes y las [hojas](prueba-hoja-observador.md) se quedan fuera de git (`~/prueba-usuarios/`, no en el repositorio). Al reporte en `docs/resultados/` solo van las cifras por participante, las respuestas y citas cortas sin nada que identifique a nadie.

### Qué trae el resumen y qué no

| Sección | Qué cuenta | De dónde sale |
|---|---|---|
| Experimentos | `modo_app` y, si estaba encendido, `ofertas_control` | `experiment_assignments` |
| Sesiones | cada sesión (30 minutos sin actividad la cierran) con su inicio, duración, modo y eventos; el total cuenta una vez las que se superponen | `app_sessions` y la hora de sus eventos |
| Búsquedas | lo escrito en el buscador (`search`) y lo que se le pidió a Mochi (`ask`), con resultados; marca "sin resultado", "corregida a…" y "buscó tal cual" | `app_events` |
| Ofertas de Mochi | cada oferta mostrada (origen `agent-<momento>` o el "Para ti" de su tarjeta) con su momento, de qué sale su "¿Por qué?" (sus pedidos, lo que buscó, su perfil…), concepto y vertical, y si se aceptó (se agregó algo al carro), se rechazó ("Ahora no" del carro o "Después" de la vertical por probar, "¿Repetimos?" y "¿Volvemos a…?"), se fue sola (el globo de la Home se fue a los 30 s sin que tocara nada: `suggestion_dismissed` con `payload.kind` "expirada", que no es un rechazo) o quedó sin respuesta registrada | `suggestion_shown` (con `payload.basis`), `suggestion_accepted`, `suggestion_dismissed` y `offer_withheld` |
| El "¿Por qué?" de las ofertas | cada vez que abrió el "¿Por qué?" de una oferta: la hora, el momento, de qué sale y el concepto | `offer_why_open` (migración 053) |
| Recorrido por verticales | la primera vertical que tocó y cada una nueva, con la hora y el camino según el origen del evento: un acceso de la Home, Mochi (con el momento de la oferta), el buscador u otro. Los botones "Ver …" y "Abrir …" de una oferta de Mochi (y el "Ver en …" de una búsqueda sin resultado) dejan `vertical_open` con el origen de la oferta, `agent-<momento>`, y salen como "Mochi (momento)". Los eventos anteriores al 06-11-2026 no lo traían: quien llegó por ellos sale como "otro (vertical, …)" y, si vio una oferta de Mochi de esa vertical en los 30 minutos anteriores, la nombra ("antes, oferta de Mochi…") sin afirmar que llegó por ella. El observador anota igual el botón que tocó | `vertical_open`, `view_store`, `view_item`, `cart_add` y `app_orders` |
| Verticales | las abiertas desde un acceso o un botón de Mochi, los servicios abiertos y las verticales con pedido (sin los cancelados) | `vertical_open`, `service_opened` y `app_orders` |
| Mochi a la vista | si lo ocultó y lo trajo de vuelta, cuándo y desde dónde | `agent_visibility` |
| Pedidos | hora, vertical, total, líneas (cuántas de una oferta), modo, estado y si lo pidió la persona o Mochi ("Pedir por mí") | `app_orders` y `app_order_lines` |

No trae, y lo anota el observador: el texto exacto del "¿Por qué?" de cada oferta (los eventos guardan de qué sale, no la frase: puede traer lo que la persona escribió) y lo que la persona dijo. Una oferta mostrada antes de la migración 053 sale con "—" en "De qué sale".

## 7. Qué se puede concluir con 5 personas y qué no

Con 5 personas la prueba **describe**: qué entendieron, dónde se trabaron y qué hicieron en una sesión guiada. Sirve para encontrar los problemas de uso y de comprensión que más se repiten y decidir qué cambiar antes de una prueba más grande.

Se puede decir, por ejemplo:

- "3 de 5 abrieron una vertical distinta de la primera; 2 por una oferta de Mochi." Siempre como "n de 5", nunca en porcentaje: con 5 personas, una sola mueve 20 puntos.
- "4 de 5 dijeron un motivo parecido al del '¿Por qué?' antes de leerlo." Con la frase de cada una en el reporte.
- "Nadie encontró cómo traer de vuelta a Mochi sin ayuda." Es un problema a arreglar, aunque lo tenga una sola persona.

No se puede decir:

- **Nada de retención.** La retención M+1 pide ver si la persona vuelve a pedir el mes siguiente, con muchas personas y pedidos de verdad. Aquí hay una sesión y pedidos de mentira.
- **Nada de efecto.** No hay grupo de control, las tareas piden buscar, decidir sobre una oferta y pedir (lo hacen porque se les pide), y la persona sabe que la miran. "Abrió otra vertical" en la tarea 3 no muestra que Mochi lleve a probar otra vertical fuera de la prueba.
- **Comparaciones con la tabla de Rappi** ni con las cifras simuladas del motor: son otra población y otra pregunta. Las cifras de esta prueba nunca se juntan con las de `synthetic`.
- **Que a "las personas" les gusta o no Mochi.** Cinco personas elegidas por conveniencia no representan a quienes usan Rappi.

### Criterios, fijados antes de la primera sesión

Qué resultado lleva a qué cambio. Se fijan antes de la primera sesión y no se mueven después de ver los resultados: si el equipo quiere otro umbral, lo cambia aquí antes de empezar. Cada señal sale de la [hoja del observador](prueba-hoja-observador.md) o del resumen; el umbral se cuenta en personas, "n de 5", salvo en "¿Se nota la oferta?", que cuenta entre quienes tuvieron la oferta en la Home.

| Pregunta | Señal | Umbral | Cambio que dispara |
|---|---|---|---|
| ¿Se entiende el "¿Por qué?"? | En la tarea 4, lo que creía antes de leer no coincide con el texto, o dice que no lo entiende; o marca 1 o 2 en la afirmación 1 | 3 de 5 | Reescribir la plantilla del texto del "¿Por qué?" de ese momento |
| ¿Se nota la oferta? | Entre quienes tuvieron la oferta en la Home (una oferta de momento "carrito" en "Ofertas de Mochi" del resumen): en la tarea 3 no la vio o se fue sola ("se fue sola" en el resumen). A quien la Home no se la mostró no se cuenta: va a "Problemas encontrados" | 2 de quienes la tuvieron en la Home | Revisar dónde y cuánto rato se muestra el globo con oferta en la Home |
| ¿Se entiende qué pasa al aceptarla? | En la tarea 4 se sorprende de lo que pasó al tocar el "+" de un producto o "Ver …", o dice que no sabía que el "+" lo agregaba al carro | 2 de 5 | Cambiar cómo se ve o se rotula el "+" de los productos del globo |
| ¿Se puede rechazar sin problema? | No encuentra "Ahora no" o "Después", o pide ayuda para decir que no | 2 de 5 | Hacer más visible el botón de rechazar |
| ¿Mochi estorba? | Marca 4 o 5 en la afirmación 3, o lo cuenta en la pregunta abierta 2 | 2 de 5 | Revisar cuántas veces y cuándo habla Mochi en la Home |
| ¿Se puede ocultar y traer de vuelta? | En la tarea 5 no lo trae de vuelta sin ayuda | 1 de 5 | Mover o rotular "Mostrar a Mochi" |
| ¿Se entiende la corrección del tipeo? | En la tarea 1 no ve "Mostrando resultados para…", o marca 1 o 2 en la afirmación 5 | 2 de 5 | Revisar el aviso de la corrección en los resultados |
| ¿Lleva a mirar otra vertical? | No abre otra vertical por un acceso de la Home ni por una oferta de Mochi (recorrido del resumen) | 4 de 5 | Revisar, antes de una prueba más grande, si la oferta de vertical por probar aparece y se entiende; no se concluye nada de efecto ni de retención |

Medir si Mochi lleva a combinar verticales, y si eso retiene, pide una prueba con tráfico real y un grupo de control al azar (`ofertas_control`, hoy apagado), con Rappi ([capa-de-datos.md](capa-de-datos.md#impresiones-experimentos-y-vistas-derivadas)). El [plan de piloto](plan-piloto.md) dice de qué tamaño: para detectar +2 puntos de retención M+1 hacen falta unas 54 mil personas con 10 % de control, o unas 20 mil con 50/50. En dlab-mvp.com se enciende después de esta prueba, nunca durante: `OFFERS_CONTROL_PCT=10` en `~/rappi-tunel/tunel.env` (ver `deploy/macos/env.example`) y reiniciar la API (`launchctl kickstart -k gui/$(id -u)/cl.rappidlab.api`). Quien ya tenía variante la conserva; la pestaña Experimentos del panel muestra las dos con la fuente del prototipo.
