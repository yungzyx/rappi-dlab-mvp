# Plan de piloto: medir si las ofertas de Mochi retienen

La propuesta para medir con Rappi el efecto de las ofertas de Mochi: qué se mide, en quiénes, con qué reparto, cuánto dura, cómo se analiza y cuántas personas hacen falta. rappi-dlab fue desarrollado junto con Rappi Chile; es un prototipo, no un producto oficial.

La tabla de combinaciones de Rappi muestra que quien combina verticales retiene más, pero es una correlación ([contexto-y-problema.md](contexto-y-problema.md)). Para saber si Mochi causa algo hace falta un grupo de control al azar: el experimento `ofertas_control`, que ya está en el MVP y viene apagado ([capa-de-datos.md](capa-de-datos.md#impresiones-experimentos-y-vistas-derivadas)).

## Qué se mide

- **Métrica primaria: la retención M+1 de quien usa una sola vertical.** Es la parte de las personas que recibieron su variante en el mes M y tienen algún pedido confirmado en el mes M+1, como la calcula el panel (`_offers_retention` en `rappi_ia/analytics/queries.py`). Se parece a la de la tabla de Rappi, pero queda un mes más lejos del mes que define a la persona (ver "Población").
- **Secundarias:**
  - la parte que **suma una vertical nueva en 28 días**, es decir, que pide en una vertical en la que no había pedido antes de recibir su variante;
  - la **aceptación de las ofertas por momento** (carro, checkout, vertical por probar, recompra, etc.), que el panel ya muestra en la pestaña "Mochi y búsquedas".

## En quiénes, con qué reparto y cuánto dura

- **Población:** personas que en el mes anterior a su asignación (M−1) pidieron en una sola vertical. Quien ya combina verticales tiene otra retención base y queda fuera. Cada persona recibe su variante una sola vez, con el sorteo estable de su id (`rappi_ia/events/experiments.py`).
- **Desfase con la tabla de Rappi:** la tabla mide algún pedido en M0+1 de quien pidió solo en una vertical en M0, un mes después del mes que define a la persona. El piloto define a la persona en M−1, la asigna durante M y mide M+1: dos meses después. Se deja así porque el panel toma el mes de asignación como M y mide el mes siguiente, y porque definir a la persona con sus pedidos del mismo mes en que ya ve ofertas mezclaría la población con el efecto. Por eso el 47 % de la tabla (a un mes) no es la base de esta métrica: la base hay que pedírsela a Rappi con esta definición (algún pedido en M0+2 de quien pidió solo en una vertical en M0).
- **Reparto:** `OFFERS_CONTROL_PCT` es la parte de las personas que queda en control. Hoy, a ellas no se les muestran las ofertas que la app pide a Mochi sin que la persona las pida (`HOLDOUT_MOMENTS`): el comentario del carro y la recompra, "¿Volvemos a…?" y la vertical por probar ("Muéstrame algo nuevo", en el menú que abre tocar a Mochi en la Home), la de una búsqueda sin resultado y el próximo pedido y el OnTop del seguimiento. Cada una queda registrada como `offer_withheld`, una vez por sesión. Sí ven lo que piden: un plan, un perfil de gusto, "¿Me falta algo?" del checkout y lo que piden en el buscador ("Repite lo de siempre", "¿Con qué acompaño…?", "¿Qué puedo probar?"). También ven "Para ti", la sugerencia cruzada de las respuestas de Mochi y el orden de la Home, que el control hoy no retiene: si el piloto los retiene es una decisión pendiente, y cambia lo que mide. Con **10** (10 % en control y 90 % con ofertas) son menos las personas sin ofertas, pero el total crece. Con **50** (50/50) la prueba es la más chica.
- **Duración:** un mes de asignación (M) y su mes siguiente completo (M+1), o sea unos dos meses. Si en un mes no se llega al tamaño de la tabla, se asigna un segundo mes y la prueba dura unos tres.

## Análisis declarado antes de empezar

- Prueba de dos proporciones (aproximación normal), α = 0,05 a dos colas, potencia 0,8.
- **Por intención de tratar:** cuenta a todas las personas asignadas, hayan visto una oferta o no. Si solo una parte llega a un momento con oferta, el efecto se diluye y hace falta más gente que en la tabla. La conversión: efecto total ≈ parte expuesta × efecto entre expuestos. Si la mitad de las personas llega a una oferta, +4 puntos entre ellas son unos +2 en total, la fila de +2 puntos de la tabla; y como el tamaño crece con 1/δ², exponer a la mitad pide unas cuatro veces más personas. La parte expuesta se mide en el piloto, no se supone: las personas con una oferta retenible, mostrada fuera del buscador en tratamiento o retenida en control (lo que piden en el buscador lo ven los dos grupos y no expone a nadie). Falta para el piloto: medirla igual en los dos grupos, con el mismo evento del servidor, y dentro de la misma cohorte antes de M+1; hasta entonces no sirve para el efecto entre expuestos (lo que muestra hoy el panel, en "Qué hace hoy el MVP").
- **Cuándo se lee:** una sola vez, cuando termina el M+1 de la última cohorte asignada. Mirar a medio camino y parar cuando aparece algo aumenta los falsos positivos.
- Las métricas secundarias se informan con su intervalo de 95 %, como exploratorias.

## Qué haría falta para medirlo

La tabla parte de una base de 47 % de retención M+1, la de la fila "solo Restaurantes" de la tabla de Rappi (Chile, cohortes de enero a junio de 2026). **Es un supuesto:** la población del piloto puede tener otra base, y esa fila mide a un mes, no a dos (ver "Desfase con la tabla de Rappi"). El efecto mínimo es cuánto sube la retención del grupo con ofertas sobre la del grupo de control.

| Efecto mínimo | Con 10 % en control: en control | en tratamiento | total | Con 50/50: por grupo | total |
|---|---:|---:|---:|---:|---:|
| +1 punto (47 → 48 %) | 21.754 | 195.780 | 217.534 | 39.146 | 78.292 |
| +2 puntos (47 → 49 %) | 5.444 | 48.988 | 54.432 | 9.795 | 19.590 |
| +5 puntos (47 → 52 %) | 871 | 7.836 | 8.707 | 1.569 | 3.138 |

Con k la parte en control, p₀ = 0,47 la base, p₁ = p₀ + δ y p̄ = k·p₀ + (1 − k)·p₁, el total N es:

N = [z₀,₉₇₅ · √(p̄(1 − p̄)(1/k + 1/(1 − k))) + z₀,₈ · √(p₀(1 − p₀)/k + p₁(1 − p₁)/(1 − k))]² / δ²

donde z₀,₉₇₅ = 1,960 y z₀,₈ = 0,842. Cada grupo se redondea hacia arriba (⌈k·N⌉ y ⌈(1 − k)·N⌉), así que el total puede quedar una persona sobre ⌈N⌉. El cálculo está en `rappi-ia/src/rappi_ia/analytics/power.py` y lo prueban los tests de `tests/unit/test_power.py`.

La fila "solo Restaurantes" de la tabla de Rappi reúne 739 mil personas, así que para Rappi el tamaño no es el límite. El efecto mínimo que vale la pena medir se decide con Rappi; la tabla muestra las tres opciones.

## Qué hace hoy el MVP

- La pestaña Experimentos del panel (`/analytics/experimentos`) muestra, para cada variante de `ofertas_control`, la retención M+1 y la parte que suma una vertical nueva en 28 días. Cuenta solo la cohorte que ya tiene su mes siguiente completo y agrega la diferencia y el n de cada grupo. Mientras un grupo esté bajo el mínimo para +5 puntos (calculado con el reparto real de quienes tienen variante), la lectura queda en "no es concluyente" y la diferencia va sin intervalo: con pocas personas, un grupo en 0 % o 100 % encoge el de 95 % y parecería un efecto. Con cada grupo en su mínimo, la diferencia lleva su intervalo de 95 %. El panel calcula sobre todas las personas con variante: el filtro de la población lo hace el piloto cuando decide a quién asignar. Por grupo muestra también las personas expuestas y su parte del grupo: la exposición acumulada desde la asignación, sin tope (incluye el mes M+1 y las ofertas que trae el propio pedido, como el próximo pedido o el OnTop). En control cuenta las ofertas que la API retuvo (`offer_withheld`, anotada cada vez que tiene una oferta retenible, aunque la app no hubiera podido mostrarla) y en tratamiento las que la app mostró (`suggestion_shown`), así que los dos grupos no son comparables uno a uno.
- En dlab-mvp.com, el grupo de control solo sirve para comprobar que la mecánica funciona: que asigna, retiene las ofertas, registra `offer_withheld` y el panel lo lee. No sirve para sacar conclusiones. Las personas del prototipo con eventos por semana, desde el 21-09-2026, fueron 6, 3, 36, 2, 5, 5 y 1, muy lejos incluso de las 1.569 por grupo que pide +5 puntos con 50/50. No se enciende durante la prueba con usuarios ([prueba-usuarios.md](prueba-usuarios.md#7-qué-se-puede-concluir-con-5-personas-y-qué-no)).
- **Límite conocido: lo rechazado se filtra en la app.** Desde el 11-11-2026, la app no vuelve a mostrar en la sesión una oferta del carro ni de "¿Me falta algo?" cuyo concepto la persona ya rechazó (`wasRefused` en `prototipo-app/src/api/suggestions.js`). La API no lo sabe: en tratamiento esa oferta se pide y no se muestra (no queda `suggestion_shown`), mientras que en control la misma oferta queda como `offer_withheld`. Los dos grupos no se cuentan igual. Antes de encender el control (`OFFERS_CONTROL_PCT` mayor que 0), ese filtro tiene que pasar a la API, para que decida igual en los dos grupos. Para la prueba con usuarios el control está apagado.
