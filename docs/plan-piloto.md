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
- **Reparto:** `OFFERS_CONTROL_PCT` es la parte de las personas que queda en control. Hoy, a ellas no se les muestran las ofertas que la app pide a Mochi sin que la persona las pida (`HOLDOUT_MOMENTS`): el comentario del carro y la recompra, "¿Volvemos a…?" y la vertical por probar ("Muéstrame algo nuevo", en el menú que abre tocar a Mochi en la Home), la de una búsqueda sin resultado y el próximo pedido y el OnTop del seguimiento. Cada una queda registrada como `offer_withheld`, una vez por sesión, y en tratamiento la misma oferta, que la API sí entrega, queda como `offer_eligible`, con la misma regla. Sí ven lo que piden: un plan, un perfil de gusto, "¿Me falta algo?" del checkout y lo que piden en el buscador ("Repite lo de siempre", "¿Con qué acompaño…?", "¿Qué puedo probar?"). También ven "Para ti", la sugerencia cruzada de las respuestas de Mochi y el orden de la Home, que el control hoy no retiene: si el piloto los retiene es una decisión pendiente, y cambia lo que mide. Con **10** (10 % en control y 90 % con ofertas) son menos las personas sin ofertas, pero el total crece. Con **50** (50/50) la prueba es la más chica.
- **Duración:** un mes de asignación (M) y su mes siguiente completo (M+1), o sea unos dos meses. Si en un mes no se llega al tamaño de la tabla, se asigna un segundo mes y la prueba dura unos tres.

## Análisis declarado antes de empezar

- Prueba de dos proporciones (aproximación normal), α = 0,05 a dos colas, potencia 0,8.
- **Por intención de tratar:** cuenta a todas las personas asignadas, hayan visto una oferta o no. Si solo una parte llega a un momento con oferta, el efecto se diluye y hace falta más gente que en la tabla. La conversión: efecto total ≈ parte expuesta × efecto entre expuestos. Si la mitad de las personas llega a una oferta, +4 puntos entre ellas son unos +2 en total, la fila de +2 puntos de la tabla; y como el tamaño crece con 1/δ², exponer a la mitad pide unas cuatro veces más personas. La parte expuesta se mide en el piloto, no se supone: las personas de la misma cohorte de la retención M+1 con una oferta retenible entre su asignación y el inicio de M+1, contadas igual en los dos grupos con lo que anota la API (`offer_withheld` en control, `offer_eligible` en tratamiento; lo que piden en el buscador lo ven los dos grupos y no expone a nadie). Como cuenta a las personas con al menos una, la que las expone es la primera, y hasta ella los dos grupos vivieron lo mismo: la parte expuesta debería salir parecida en los dos, y si no, algo falla. Con ella se pasa del efecto por intención de tratar al efecto entre expuestos: la diferencia dividida por la parte expuesta, suponiendo que en quien no tuvo una oferta el efecto es cero.
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

- La pestaña Experimentos del panel (`/analytics/experimentos`) muestra, para cada variante de `ofertas_control`, la retención M+1 y la parte que suma una vertical nueva en 28 días. Cuenta solo la cohorte que ya tiene su mes siguiente completo y agrega la diferencia y el n de cada grupo. Mientras un grupo esté bajo el mínimo para +5 puntos (calculado con el reparto real de quienes tienen variante), la lectura queda en "no es concluyente" y la diferencia va sin intervalo: con pocas personas, un grupo en 0 % o 100 % encoge el de 95 % y parecería un efecto. Con cada grupo en su mínimo, la diferencia lleva su intervalo de 95 %. El panel calcula sobre todas las personas con variante: el filtro de la población lo hace el piloto cuando decide a quién asignar. Junto a la retención, por grupo, va la parte expuesta de esa misma cohorte ("Expuestas antes de M+1", la de "Por intención de tratar"). La tabla de las ofertas muestra además las personas con oferta desde la asignación, sin tope (incluye el mes M+1): sirve para ver la mecánica, no para la conversión. Las dos se cuentan igual en los dos grupos, con lo que anota la API cada vez que tiene una oferta retenible (`offer_withheld` en control y `offer_eligible` en tratamiento, una vez por sesión, origen, concepto y vertical), la haya alcanzado a mostrar la app o no. Las ofertas mostradas (`suggestion_shown`) y aceptadas siguen siendo las que anota la app en tratamiento.
- En dlab-mvp.com, el grupo de control solo sirve para comprobar que la mecánica funciona: que asigna, retiene las ofertas, registra `offer_withheld` y el panel lo lee. No sirve para sacar conclusiones. Las personas del prototipo con eventos por semana, desde el 21-09-2026, fueron 6, 3, 36, 2, 5, 5 y 1, muy lejos incluso de las 1.569 por grupo que pide +5 puntos con 50/50. No se enciende durante la prueba con usuarios ([prueba-usuarios.md](prueba-usuarios.md#7-qué-se-puede-concluir-con-5-personas-y-qué-no)).
- **Lo rechazado ya no sesga la cuenta** (resuelto el 11-11-2026; antes era un límite conocido). La app no vuelve a mostrar en la sesión una oferta del carro ni de "¿Me falta algo?" cuyo concepto la persona ya rechazó (`wasRefused` en `prototipo-app/src/api/suggestions.js`), y lo sigue haciendo. Antes, en tratamiento esa oferta se pedía y no se mostraba (no quedaba `suggestion_shown`) y en control la misma quedaba como `offer_withheld`. Ahora la exposición se mide con hechos del servidor que no dependen de lo que la app muestre o filtre: la API anota `offer_withheld` en control y `offer_eligible` en tratamiento al responder, antes de que la app decida mostrarla. El filtro no pasa a la API: los rechazos que cuentan solo los anota la app en la Home, sobre ofertas que fuera del buscador solo ve tratamiento, así que en la API actuaría solo en un grupo. Con esto el control queda listo para encenderse; para la prueba con usuarios sigue apagado.
- **La exposición pareja cuenta desde la migración 056.** Antes no existía `offer_eligible`: si el control hubiera estado encendido antes, las personas de tratamiento de entonces saldrían sin oferta. El piloto se asigna después de aplicar la 056.
