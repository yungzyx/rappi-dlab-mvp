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
- **Sin grabación:** no se graba pantalla ni voz. El observador anota lo que la persona dice.

Antes de empezar, el moderador lee esto y espera un sí:

> Estamos probando un prototipo del programa dLab, desarrollado junto con Rappi Chile; no es la app oficial. Queremos ver si se entiende, no evaluarte a ti: si algo no funciona, es culpa del prototipo. Los pedidos son de mentira, nadie te cobra ni te llega nada. No necesitas dar tu nombre ni ningún dato tuyo; por favor no los escribas en la app. Guardamos lo que haces en la app con un número al azar, sin tu nombre, y lo borramos al terminar, después de anotar un resumen. No grabamos ni la pantalla ni tu voz. Puedes parar cuando quieras. ¿Te parece bien?

Si dice que no, no hay sesión. Si para en medio, se borran sus datos igual (sección 6).

## 3. Antes de la primera sesión

- **Equipo:** un teléfono del equipo con el navegador (o un notebook con la vista de teléfono), en dlab-mvp.com. La puerta de acceso (usuario y clave) la escribe el moderador, nunca la persona.
- **Modo:** si el sitio se construyó sin `VITE_DEMO` (lo normal, ver [despliegue.md](despliegue.md)), siempre abre en el prototipo con Mochi ("Propuesta") y no tiene el interruptor de la demo. Si se construyó con `VITE_DEMO=1`, tiene el interruptor (tecla D y la fila de Cuenta) y el navegador recuerda el último modo: antes de cada sesión, dejarlo en "Prototipo final ✨", no en "Rappi hoy".
- **Grupo de control apagado:** quien opera dlab-mvp.com confirma que `OFFERS_CONTROL_PCT` está en 0 (lo de siempre). Si no, a una persona le pueden retener las ofertas de Mochi y la tarea 3 no se puede hacer; el resumen lo diría en "Experimentos: … ofertas_control = control".
- **Comandos:** `rappi-ia resumen-prueba` y `rappi-ia olvidar` corren en el equipo que sirve la demo, con el `.env` que apunta a su base (en el Mac de [deploy/macos](../deploy/macos/README.md), desde `rappi-ia/` de esa copia y con su `.venv`).
- **Roles:** un moderador (lee las consignas, no ayuda) y un observador (anota). Pedirle a la persona que piense en voz alta.
- **Una corrida en seco** con alguien del equipo, en una pestaña privada como las de verdad (sección 6). Al terminarla, con los mismos dos pasos del final de la sección 6: `resumen-prueba --desde <hora en que empezó la corrida>` da su id (anotarlo) y `olvidar` con ese id la borra. Así no queda en el servidor aunque las sesiones de verdad sean otro día.

## 4. Guion: 6 tareas (unos 25 minutos)

Se lee cada consigna tal cual. Si la persona se traba más de 2 minutos, el moderador pregunta "¿qué buscarías?" y, si sigue, da la pista y lo anota como "con ayuda". El observador anota por tarea: si la completó (sola, con ayuda o no), el tiempo aproximado y lo que dijo.

| # | Consigna | Qué mirar | Qué deja el resumen |
|---|---|---|---|
| 1 | "Busca unos Doritos. Escríbelo rápido, como te salga; si te sale bien, escribe 'doritoz'." | Si ve el aviso "Mostrando resultados para…" y si le parece bien que corrija. Otro error que el buscador corrige: "mantequlla" ([reporte del 24-10](resultados/busqueda-2026-10-24.md)) | La búsqueda con `corregida a "doritos"`, o "sin resultado" si no la corrigió |
| 2 | "Ahora pídele a Mochi algo para la once." | Si entiende que el buscador también es Mochi, qué espera que pase y si las tarjetas y los chips le sirven | Lo escrito, como pedido a Mochi ("Mochi") y, si también buscó, en el buscador, con cuántos resultados |
| 3 | "Agrega algo al carro y vuelve al inicio. Si Mochi te propone algo, decide si lo agregas o no, y cuéntanos por qué." | Si nota la oferta, si la acepta o la descarta y su motivo, dicho con sus palabras. Si Mochi no ofrece nada en la Home, sirve la sugerencia del checkout (tarea 6) | La oferta mostrada, con su momento, concepto, vertical y si se aceptó. El "Ahora no" del globo no deja evento: lo anota el observador |
| 4 | "Antes de tocar nada: ¿por qué crees que Mochi te propuso eso? Ahora toca '¿Por qué?'." | Lo que la persona cree antes de leer, y si el texto coincide o le sorprende. El observador copia el texto del "¿Por qué?" | Que lo abrió (`offer_why_open`), de qué oferta y de qué sale; el texto no se guarda |
| 5 | "Imagina que Mochi te molesta: escóndelo. Ahora tráelo de vuelta." | Si encuentra el menú de Mochi ("Ocultar"), y "Mostrar a Mochi" en Cuenta para traerlo | "Ocultó a Mochi: sí", con la hora y desde dónde (`menu-mochi`, `cuenta`) |
| 6 | "Haz un pedido de algo que pedirías de verdad, de la tienda que quieras, hasta ver por dónde viene." | Dónde duda en el checkout, si mira la sugerencia de Mochi antes de pagar, si llega al seguimiento | El pedido (vertical, total, líneas que salieron de una oferta, estado) y su vertical en "Con pedido" |

Después de la tarea 6, una pregunta abierta antes del cuestionario: "¿Hay algo que te haya llamado la atención?".

## 5. Preguntas al final

Cinco afirmaciones de 1 a 5 (1 = muy en desacuerdo, 5 = muy de acuerdo). El moderador las lee y anota el número; no las explica.

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

1. **Pestaña privada nueva.** En el teléfono, cerrar todas las pestañas privadas (en Chrome comparten lo guardado mientras quede una abierta) y abrir una nueva en dlab-mvp.com; la puerta de acceso la escribe el moderador. Anotar la hora (HH:MM) en la hoja de P*n*.
2. **Consentimiento, tareas y cuestionario** (secciones 2, 4 y 5). Que la persona no toque "Borrar mis datos" ni "Olvidar" de Mochi en medio: borran lo hecho hasta ahí. Si pide que se borre en ese momento, "Borrar mis datos" (Cuenta) lo hace en el servidor, y esa persona queda sin resumen.
3. **Cerrar la pestaña privada.**

Al terminar las sesiones del día, en el equipo que sirve la demo (sección 3):

1. **Los resúmenes**, desde la hora del primer participante:

   ```bash
   cd rappi-ia
   .venv/bin/python -m rappi_ia resumen-prueba --desde 2026-11-03T15:00 --salida ~/prueba-usuarios/2026-11-03
   ```

   Escribe un Markdown por persona del prototipo creada desde esa hora (`proto-….md`), con la hora en que se creó al comienzo. La de P*n* es la que coincide con la hora de su hoja y con lo que hizo; si sale alguna de más, alguien más entró a la demo en ese rato. Renombrar el archivo a `P1.md` y anotar su id en la hoja de P1.
2. **Borrar**, con los ids que salieron de los resúmenes (los de P1 a P5; la corrida en seco ya se borró al terminarla, sección 3):

   ```bash
   .venv/bin/python -m rappi_ia olvidar proto-… proto-…
   ```

   Dice cuántos eventos, pedidos y sesiones tiene cada una y pide confirmación ("s"). Borra lo mismo que "Borrar mis datos" de la app (DELETE /profile): la persona entera, con sus eventos, búsquedas, pedidos, sesiones y preferencias, y su afinidad y su recompra del motor, en cascada. Solo acepta personas del prototipo: si un id es de una simulada o no existe, no borra a ninguna. Con esto se cumple lo dicho en el consentimiento: se borra al terminar, después de anotar el resumen.

Los resúmenes y las hojas se quedan fuera de git (`~/prueba-usuarios/`, no en el repositorio). Al reporte en `docs/resultados/` solo van las cifras por participante, las respuestas y citas cortas sin nada que identifique a nadie.

### Qué trae el resumen y qué no

| Sección | Qué cuenta | De dónde sale |
|---|---|---|
| Experimentos | `modo_app` y, si estaba encendido, `ofertas_control` | `experiment_assignments` |
| Sesiones | cada sesión (30 minutos sin actividad la cierran) con su inicio, duración, modo y eventos; el total cuenta una vez las que se superponen | `app_sessions` y la hora de sus eventos |
| Búsquedas | lo escrito en el buscador (`search`) y lo que se le pidió a Mochi (`ask`), con resultados; marca "sin resultado", "corregida a…" y "buscó tal cual" | `app_events` |
| Ofertas de Mochi | cada oferta mostrada (origen `agent-<momento>` o el "Para ti" de su tarjeta) con su momento, de qué sale su "¿Por qué?" (sus pedidos, lo que buscó, su perfil…), concepto y vertical, y si se aceptó (se agregó algo al carro), se rechazó (con el botón de su momento, como "Después" de "¿Volvemos a…?") o quedó sin respuesta registrada | `suggestion_shown` (con `payload.basis`), `suggestion_accepted`, `suggestion_dismissed` y `offer_withheld` |
| El "¿Por qué?" de las ofertas | cada vez que abrió el "¿Por qué?" de una oferta: la hora, el momento, de qué sale y el concepto | `offer_why_open` (migración 053) |
| Recorrido por verticales | la primera vertical que tocó y cada una nueva, con la hora y el camino según el origen del evento: un acceso de la Home, Mochi (con el momento de la oferta), el buscador u otro. Los botones "Ver …" de una oferta de Mochi no dejan origen: quien llega por ellos sale como "otro (vertical, …)", y si vio una oferta de Mochi de esa vertical en los 30 minutos anteriores, la nombra ("antes, oferta de Mochi…") sin afirmar que llegó por ella; el observador anota el botón que tocó | `vertical_open`, `view_store`, `view_item`, `cart_add` y `app_orders` |
| Verticales | las abiertas desde un acceso o un botón de Mochi, los servicios abiertos y las verticales con pedido (sin los cancelados) | `vertical_open`, `service_opened` y `app_orders` |
| Mochi a la vista | si lo ocultó y lo trajo de vuelta, cuándo y desde dónde | `agent_visibility` |
| Pedidos | hora, vertical, total, líneas (cuántas de una oferta), modo, estado y si lo pidió la persona o Mochi ("Pedir por mí") | `app_orders` y `app_order_lines` |

No trae, y lo anota el observador: el texto exacto del "¿Por qué?" de cada oferta (los eventos guardan de qué sale, no la frase: puede traer lo que la persona escribió), el "Ahora no" del globo de la Home y lo que la persona dijo. Una oferta mostrada antes de la migración 053 sale con "—" en "De qué sale".

## 7. Qué se puede concluir con 5 personas y qué no

Con 5 personas la prueba **describe**: qué entendieron, dónde se trabaron y qué hicieron en una sesión guiada. Sirve para encontrar los problemas de uso y de comprensión que más se repiten y decidir qué cambiar antes de una prueba más grande.

Se puede decir, por ejemplo:

- "3 de 5 abrieron una vertical distinta de la primera; 2 por una oferta de Mochi." Siempre como "n de 5", nunca en porcentaje: con 5 personas, una sola mueve 20 puntos.
- "4 de 5 dijeron un motivo parecido al del '¿Por qué?' antes de leerlo." Con la frase de cada una en el reporte.
- "Nadie encontró cómo traer de vuelta a Mochi sin ayuda." Es un problema a arreglar, aunque lo tenga una sola persona.

No se puede decir:

- **Nada de retención.** La retención M+1 pide ver si la persona vuelve a pedir el mes siguiente, con muchas personas y pedidos de verdad. Aquí hay una sesión y pedidos de mentira.
- **Nada de efecto.** No hay grupo de control, las tareas piden buscar, aceptar una oferta y pedir (lo hacen porque se les pide), y la persona sabe que la miran. "Abrió otra vertical" en la tarea 3 no muestra que Mochi lleve a probar otra vertical fuera de la prueba.
- **Comparaciones con la tabla de Rappi** ni con las cifras simuladas del motor: son otra población y otra pregunta. Las cifras de esta prueba nunca se juntan con las de `synthetic`.
- **Que a "las personas" les gusta o no Mochi.** Cinco personas elegidas por conveniencia no representan a quienes usan Rappi.

Medir si Mochi lleva a combinar verticales, y si eso retiene, pide una prueba con tráfico real y un grupo de control al azar (`ofertas_control`, hoy apagado), con Rappi ([capa-de-datos.md](capa-de-datos.md#impresiones-experimentos-y-vistas-derivadas)). En dlab-mvp.com se enciende después de esta prueba, nunca durante: `OFFERS_CONTROL_PCT=10` en `~/rappi-tunel/tunel.env` (ver `deploy/macos/env.example`) y reiniciar la API (`launchctl kickstart -k gui/$(id -u)/cl.rappidlab.api`). Quien ya tenía variante la conserva; la pestaña Experimentos del panel muestra las dos con la fuente del prototipo.
