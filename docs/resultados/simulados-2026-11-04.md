# Datos simulados al día (04-11-2026)

> **Datos simulados: prueban la mecánica, no el efecto.** Ninguna cifra de esta página es evidencia de uso real.

## Qué cambió y por qué

Los datos simulados de la base eran del 17-10-2026, anteriores al sobre de eventos (migración 043): sus búsquedas no traían `request_id` ni impresiones. Con la fuente "Simulados", el panel dejaba vacíos el abandono de búsqueda (#60), el CTR por posición y el embudo por sesión.

Se volvieron a generar el 04-11-2026 (`rappi-ia synth`: 3.000 personas, 26 semanas hasta el 03-11, semilla 7) en una copia de la base (`rappi_staging`) con el catálogo real, y después los segmentos simulados, el motor y la purga, en el orden de `make post-refresh`. El generador es el mismo del 17-10 más una cosa: el 8 % de las búsquedas con resultados viene después de la misma búsqueda mal escrita en la misma vertical, sin toque, 20 a 90 segundos antes (`REFORMULATE`, supuesto propio). Sale de un sorteo aparte, así que la conducta calibrada no cambia: las personas activas (1.334) y los pedidos de 30 días (1.995) son los mismos del 17-10, con la fecha corrida.

## El panel con la fuente "Simulados"

| Qué | Cifra |
|---|---|
| Abandono de búsqueda | 11,7 % (1.207 de 10.275 búsquedas); 8.387 con toque y 681 rescatadas al reformular |
| CTR por posición (resultados de búsqueda) | 0,431 en el primer lugar, 0,353 en el segundo y 0,271 en el tercero: es el sesgo de posición puesto en el generador (`POSITION_DECAY`), no una medida |
| Embudo por sesión | 16.256 sesiones; 54,6 % de las que buscan llegan a pedir |
| Búsquedas sin resultado | 21,3 % (antes 22,3 %: las reformulaciones suman búsquedas con resultados) |

## El motor (tramo de prueba, `rappi-ia motor`)

Tramos por fecha: entrenar hasta el 08-09, validar hasta el 06-10 y probar hasta el 03-11 (28 días cada uno de los dos últimos).

| Qué | 17-10-2026 | 04-11-2026 |
|---|---|---|
| Próxima vertical, nDCG@8 | combinado 0,978 · orden fijo 0,918 (477 personas) | combinado 0,980 · solo afinidad 0,978 · popularidad 0,924 · orden fijo 0,918 (505 personas) |
| Compra cruzada, precisión@3 | mezcla 0,129 · lo más pedido 0,129, con λ = 0 | mezcla 0,129 · lo más pedido 0,129, con λ = 1; las reglas solas, 0,118 en 17 personas |
| Recompra, acierto ±7 días | 0,191 (110 predicciones) | 0,214 (103 predicciones), error mediano 6,5 días |
| Paso de la escalera fina, acierto@1 | paso 0,620 · la vertical que más se suma 0,479 (71 personas) | paso 0,540 · la vertical que más se suma 0,595 (74 personas); 55 de 74 reciben la misma vertical y la diferencia la deciden 14 personas (5 contra 9, McNemar p = 0,42) |

Cómo leerlo:

- **Las cifras se mueven con la fecha de corte**, no porque el motor cambiara: los tramos caen sobre otros días de la misma población. Con una sola semilla y menos de 100 personas en la escalera, la diferencia entre el 17-10 y el 04-11 es ruido.
- **λ = 1 no cambia el acierto, pero sí la variante de la oferta.** En validación ganó por 2 aciertos de 1.509 y, en la prueba, la mezcla y lo más pedido aciertan lo mismo (0,129): las reglas aprendidas llegan a 17 de 505 personas. Con λ > 0, quien tiene una regla podía ver "Para tu pedido de …". Desde el 05-11 un λ mayor tiene que ganar al menos 5 aciertos ([decisiones](../decisiones.md#datos-simulados-y-panel)): con estos mismos simulados `make motor` deja λ = 0, el acierto en la prueba no cambia y esa variante no aparece.
- **El paso de la escalera pierde contra la línea base** en esta corrida (el 17-10 ganaba). El paso busca la vertical que más retiene según la tabla de Rappi, no adivinar la que la persona sumaría sola; con 74 personas, ni la ventaja de antes ni la desventaja de ahora son evidencia: 55 de 74 reciben la misma vertical de los dos y la diferencia la deciden 14 personas (5 contra 9, McNemar p = 0,42). Desde el 05-11 el informe del motor da esos pares y su p.

Reporte completo de la corrida: `rappi-ia/data/eval/motor-synthetic.md` (fuera de git), generado por `make motor`.
