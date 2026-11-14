# Simulados con grupo de control (14-11-2026)

> **Datos simulados: prueban la mecánica, no el efecto.** Ninguna cifra de esta página es evidencia de uso real. La diferencia entre los grupos simulados la ponen supuestos del generador, no Mochi.

## Qué cambió y por qué

Hasta ahora el generador (`rappi-ia/src/rappi_ia/events/synth.py`) ponía a todas sus personas con Mochi y no simulaba el grupo de control (decisión del 25-10-2026). Con los simulados, el panel de Experimentos no podía mostrar "Las tres hipótesis" ni "Adopción y apagado" por grupo, y la H3 y el apagado quedaban en "—".

Desde el 14-11-2026 cada persona simulada tiene variante en `ofertas_control` con el sorteo estable de la API y su propio porcentaje (`SYNTH_CONTROL_PCT` = 50 %; `OFFERS_CONTROL_PCT` sigue en 0). El control es "Mochi apagado", la pregunta in-app sale en los dos grupos y una parte chica del tratamiento oculta o silencia a Mochi. Los supuestos y sus valores están en [capa-de-datos.md](../capa-de-datos.md#datos-simulados-y-datos-reales).

## La mezcla de combinaciones se volvió a calibrar

Sin sugerencias, el control combina menos verticales. Con los factores de calibración de antes, la mezcla de personas-mes se corría hacia "solo Restaurantes": 69,6 a 71,8 % contra 67,0 % en la tabla (semillas 7, 11 y 23), y "rest+retail" bajaba a 3,6 a 4,1 % contra 5,8 %. Se ajustaron de nuevo los factores con `scripts/calibrar_simulados.py --base rappi_staging --ajustar --altas 12000 --hasta 2026-11-14`, con el control incluido. Con el generador anterior, la misma orden da los factores del 17-10 (1,16 · 0,87 · 0,65 · 1,13 · 0,16 · 0,67 · 0,12): el cambio viene del control, no del catálogo.

| Arquetipo | Factor antes | Factor ahora |
|---|---:|---:|
| rest | 1,15 | 1,10 |
| turbo | 0,87 | 0,71 |
| rest+turbo | 0,67 | 0,95 |
| retail | 1,14 | 0,78 |
| rest+retail | 0,20 | 0,89 |
| rest+turbo+retail | 0,68 | 0,78 |
| turbo+retail | 0,19 | 0,54 |

Con los factores nuevos (3.000 personas hasta el 14-11, semillas 7, 11, 23, 31 y 47) la mayor distancia de una fila a la tabla es 0,6, 2,7, 1,3, 0,7 y 1,3 puntos (con el generador anterior, 0,6, 1,2 y 0,8 en las tres primeras). La que pasa de 2 puntos es "rest" en la semilla 11 (64,3 % contra 67,0 %). La retención M+1 de cada fila con 100 meses o más sigue a menos de 0,1 de la de Rappi.

## El motor antes y después

El motor aprende de `MOTOR_POBLACION` (por defecto `synthetic`), así que se midió antes y después en una copia aparte de `rappi_staging`: 3.000 personas, 26 semanas hasta el 14-11-2026, tres semillas. "Antes" es el generador de main y "después" el de este cambio, con el control y la calibración nueva.

| Qué | Antes (semillas 7 · 11 · 23) | Después (semillas 7 · 11 · 23) |
|---|---|---|
| Pedidos simulados | 9.304 · 9.431 · 9.998 | 9.790 · 10.457 · 9.284 |
| Próxima vertical, nDCG@8 combinado | 0,980 · 0,973 · 0,974 | 0,972 · 0,972 · 0,971 |
| Próxima vertical, nDCG@8 orden fijo | 0,918 · 0,907 · 0,918 | 0,916 · 0,914 · 0,927 |
| Compra cruzada, λ elegido | 0 · 0 · 0 | 0 · 1 · 0 |
| Compra cruzada, precisión@3 de la mezcla | 0,124 · 0,107 · 0,110 | 0,101 · 0,121 · 0,133 |
| Recompra, acierto ±7 días (predicciones) | 0,22 (100) · 0,14 (119) · 0,19 (123) | 0,18 (123) · 0,21 (112) · 0,18 (122) |
| Paso de la escalera, acierto@1 (personas) | 0,58 (76) · 0,51 (83) · 0,51 (75) | 0,56 (63) · 0,49 (65) · 0,49 (73) |
| La vertical que más se suma, acierto@1 | 0,58 · 0,48 · 0,40 | 0,56 · 0,29 · 0,41 |

Cómo leerlo:

- **El motor no cambia de forma relevante.** El nDCG combinado baja 0,004 en promedio y sigue unos 0,05 sobre el orden fijo; compra cruzada, recompra y escalera se mueven dentro de lo que se mueven entre semillas.
- **λ = 1 en la semilla 11** no es un cambio del motor: ya había salido el 04-11 con el generador anterior, y elegirlo depende de pocos aciertos en validación.
- **La escalera se mide con menos personas** (63 a 73 contra 75 a 83): en el control nadie suma una vertical por una sugerencia aceptada.
- Sin la calibración nueva (control al 50 % con los factores de antes), la escalera bajaba a 54 a 59 personas y la mezcla quedaba corrida; por eso se recalibró en vez de achicar el control (con menos del 10 % en control, la H3 y la adopción por grupo casi no tendrían respuestas).

## El panel con la fuente "Simulados"

Con los dos grupos con personas, "Las tres hipótesis" y "Adopción y apagado" muestran la tabla por grupo con "Simulado: sin veredicto", sin intervalo y con un aviso de que la diferencia entre los grupos la ponen supuestos del generador. El control queda en 0 en usar, ocultar y silenciar a Mochi por diseño. Las cifras de `rappi_staging` regenerado están en [capa-de-datos.md](../capa-de-datos.md#datos-simulados-y-datos-reales) solo como supuestos: lo que se ve en el panel es lo que se puso en el generador.
