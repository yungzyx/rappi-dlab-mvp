# Plan de piloto: medir si las ofertas de Mochi retienen

La propuesta para medir con Rappi el efecto de las ofertas de Mochi: qué se mide, en quiénes, con qué reparto, cuánto dura, cómo se analiza y cuántas personas hacen falta. rappi-dlab fue desarrollado junto con Rappi Chile; es un prototipo, no un producto oficial.

La tabla de combinaciones de Rappi muestra que quien combina verticales retiene más, pero es una correlación ([contexto-y-problema.md](contexto-y-problema.md)). Para saber si Mochi causa algo hace falta un grupo de control al azar: el experimento `ofertas_control`, que ya está en el MVP y viene apagado ([capa-de-datos.md](capa-de-datos.md#impresiones-experimentos-y-vistas-derivadas)).

## Qué se mide

- **Métrica primaria: la retención M+1 de quien usa una sola vertical.** Es la parte de las personas que recibieron su variante en el mes M y tienen algún pedido confirmado en el mes M+1. Es la misma definición de la tabla de Rappi.
- **Secundarias:**
  - la parte que **suma una vertical nueva en 28 días**, es decir, que pide en una vertical en la que no había pedido antes de recibir su variante;
  - la **aceptación de las ofertas por momento** (carro, checkout, vertical por probar, recompra, etc.), que el panel ya muestra en la pestaña "Mochi y búsquedas".

## En quiénes, con qué reparto y cuánto dura

- **Población:** personas que en el mes anterior pidieron en una sola vertical. Quien ya combina verticales tiene otra retención base y queda fuera. Cada persona recibe su variante una sola vez, con el sorteo estable de su id (`rappi_ia/events/experiments.py`).
- **Reparto:** `OFFERS_CONTROL_PCT` es la parte de las personas que queda en control: a ellas no se les muestran las ofertas que Mochi propone solo, y cada oferta retenida queda registrada como `offer_withheld`. Con **10** (10 % en control y 90 % con ofertas) son menos las personas sin ofertas, pero el total crece. Con **50** (50/50) la prueba es la más chica.
- **Duración:** un mes de asignación (M) y su mes siguiente completo (M+1), o sea unos dos meses. Si en un mes no se llega al tamaño de la tabla, se asigna un segundo mes y la prueba dura unos tres.

## Análisis declarado antes de empezar

- Prueba de dos proporciones (aproximación normal), α = 0,05 a dos colas, potencia 0,8.
- **Por intención de tratar:** cuenta a todas las personas asignadas, hayan visto una oferta o no. Si solo una parte llega a un momento con oferta, el efecto se diluye y hace falta más gente que en la tabla.
- **Cuándo se lee:** una sola vez, cuando termina el M+1 de la última cohorte asignada. Mirar a medio camino y parar cuando aparece algo aumenta los falsos positivos.
- Las métricas secundarias se informan con su intervalo de 95 %, como exploratorias.

## Qué haría falta para medirlo

La tabla parte de una base de 47 % de retención M+1, la de la fila "solo Restaurantes" de la tabla de Rappi (Chile, cohortes de enero a junio de 2026). **Es un supuesto:** la población del piloto puede tener otra base. El efecto mínimo es cuánto sube la retención del grupo con ofertas sobre la del grupo de control.

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

- La pestaña Experimentos del panel (`/analytics/experimentos`) muestra, para cada variante de `ofertas_control`, la retención M+1 y la parte que suma una vertical nueva en 28 días. Cuenta solo la cohorte que ya tiene su mes siguiente completo y agrega la diferencia con su intervalo de 95 % y el n de cada grupo. Mientras un grupo esté bajo el mínimo para +5 puntos (calculado con el reparto real de quienes tienen variante), la lectura queda en "no es concluyente". El panel calcula sobre todas las personas con variante: el filtro de la población lo hace el piloto cuando decide a quién asignar.
- En dlab-mvp.com, el grupo de control solo sirve para comprobar que la mecánica funciona: que asigna, retiene las ofertas, registra `offer_withheld` y el panel lo lee. No sirve para sacar conclusiones. Las personas del prototipo con eventos por semana, desde el 21-09-2026, fueron 6, 3, 36, 2, 5, 5 y 1, muy lejos incluso de las 1.569 por grupo que pide +5 puntos con 50/50. No se enciende durante la prueba con usuarios ([prueba-usuarios.md](prueba-usuarios.md#7-qué-se-puede-concluir-con-5-personas-y-qué-no)).
