# Datos simulados con la mezcla de la tabla de Rappi (17-10-2026)

> **Simulado: no es evidencia.** Las personas, sus pedidos y su retención los genera `events/synth.py` con supuestos propios; aquí solo se mide qué tan parecida queda su **forma** a la tabla de combinaciones que compartió Rappi (`motor/combos.toml`, una correlación, no un efecto). Ninguna cifra de este documento dice algo sobre personas reales.

**Dónde y cuándo:** el 17-10-2026, sobre `rappi_staging` (una copia del catálogo real; la base `rappi` no se tocó), 3.000 personas simuladas por semilla, 26 semanas hasta el 17-10-2026. La mezcla se mide como el motor (`combo_months` y `combo_stats`, nivel grueso): parte de las **personas-mes** con pedidos en cada combinación y retención M+1 (pide algo el mes siguiente), sobre los meses con el siguiente completo. La tabla de Rappi va sin Favor y renormalizada a 100, porque Favor no tiene catálogo. Las cifras por semilla salen de `rappi-ia/scripts/calibrar_simulados.py` (corre el generador en memoria con el catálogo de la copia, sin escribir); la semilla 7 se corrió además con `rappi-ia synth` + `segments` + `motor` sobre la copia y da lo mismo.

Decisión del 16-10-2026: recalibrar los datos simulados a la mezcla de la tabla de Rappi ([decisiones](../decisiones.md#datos-simulados-y-panel)).

## Qué se cambió en el generador

1. **Las altas se sortean con un factor por arquetipo** (`ARCHETYPE_CALIBRATION`). La tabla cuenta personas-mes y el generador sorteaba altas con esa misma mezcla; pero quien combina grupos vive más meses, pasa algunos meses en un solo grupo y las sugerencias aceptadas llevan a quien solo pide en Restaurantes a combinar. Los factores salen de un ajuste (NNLS): cada persona se simula sola, así que se mide cuántos meses de cada combinación deja un alta de cada arquetipo y se buscan los pesos de alta cuya mezcla es la de la tabla. Las metas se siguen leyendo de `combos.toml`; el código solo guarda la corrección.
2. **Cada sesión sortea primero el grupo**, parejo entre los del arquetipo, y después el vertical. Antes, el grupo con más conceptos en el perfil se llevaba casi todas las sesiones.
3. **El ritmo da los pedidos por persona de la tabla.** La tabla cuenta los pedidos entre quienes pidieron ese mes (la media de un Poisson sin el cero), así que se despeja λ de λ / (1 − e^−λ) y el ritmo considera la parte de sesiones que no terminan en pedido según la persona (antes, una constante de 1,3 sesiones por pedido; la medida era 1,7).
4. **La supervivencia mensual es la retención de la tabla dividida por la probabilidad de pedir en un mes** con el ritmo del arquetipo (1 − e^−λ), con tope 0,99. Antes era la retención tal cual, y como quien sigue activa puede saltarse un mes, la M+1 medida quedaba 0,05 a 0,1 bajo la de Rappi en todas las filas.

Lo demás queda igual: semilla y determinismo, 3.000 personas por defecto (el generador tarda lo mismo, unos segundos), las guardias del agente simulado (sin alcohol, bebé, salud, sensibles, Farmacia ni Licores), los conceptos sensibles fuera de compra cruzada, tendencias y recompra, y `synthetic` separado de `prototype`.

### Factores ajustados

Orden exacta (desde `rappi-ia/`, semilla de las altas `FIT_SEED = 101`; `--hasta` es obligatoria al ajustar):

```
.venv/bin/python scripts/calibrar_simulados.py --base rappi_staging --ajustar --altas 12000 --hasta 2026-10-17
```

Catálogo: el de `rappi_staging` en la noche del 17-10-2026, **mientras otro proceso reetiquetaba sus conceptos**, así que no se puede reconstruir tal cual. La misma orden, repetida más tarde esa noche, dio factores algo distintos (rest 1,16 · turbo 0,86 · rest+turbo 0,66 · retail 1,15 · rest+retail 0,15 · rest+turbo+retail 0,67 · turbo+retail 0,13). Con los factores guardados y ese catálogo posterior, cada fila siguió a menos de 1,2 puntos de la tabla en las cinco semillas (distancia 1,7 a 3,9): la tolerancia se cumple con los dos catálogos. Las cifras de abajo son del primero.

| Arquetipo | Personas-mes por alta | Rappi sin Favor % (dato compartido por Rappi) | Alta ajustada % | Factor |
|---|---:|---:|---:|---:|
| rest | 1,35 | 67,0 | 77,2 | 1,15 |
| turbo | 1,40 | 7,3 | 6,3 | 0,87 |
| rest+turbo | 2,13 | 7,1 | 4,7 | 0,67 |
| retail | 1,14 | 6,0 | 6,9 | 1,14 |
| rest+retail | 1,86 | 5,8 | 1,1 | 0,20 |
| rest+turbo+retail | 2,60 | 5,0 | 3,4 | 0,68 |
| turbo+retail | 1,94 | 1,8 | 0,3 | 0,19 |

Pocas altas «rest+retail» y «turbo+retail»: esas filas se llenan sobre todo con personas de otros arquetipos (de «rest» que aceptan una sugerencia del súper o Express; de «rest+turbo+retail» o «turbo» en un mes en que no usaron un grupo).

## Tolerancia

Se fijó antes de medir el resultado:

- **Mezcla:** cada combinación a ±3 puntos de su parte en la tabla sin Favor, en cada semilla; Restaurantes la mayor y turbo+retail la menor.
- **Retención:** rest+turbo+retail la más alta; cada combinación de dos o más grupos sobre cada una de un solo grupo; el orden de Rappi se conserva en los pares que Rappi separa por 0,05 o más.

## Antes y después: parte de personas-mes (%)

Promedio de las semillas 7, 11, 23, 31 y 47, con el rango entre semillas.

| Combinación | Rappi % (dato compartido por Rappi) | Rappi sin Favor % | Antes (simulado) | Después (simulado) |
|---|---:|---:|---:|---:|
| rest | 62,6 | 67,0 | 57,4 (56,4 a 58,5) | **66,9** (65,2 a 68,5) |
| turbo | 6,8 | 7,3 | 9,4 (8,8 a 10,1) | **7,2** (6,1 a 8,6) |
| rest+turbo | 6,6 | 7,1 | 7,3 (6,8 a 8,0) | **6,5** (6,2 a 7,3) |
| retail | 5,6 | 6,0 | 8,7 (8,2 a 9,0) | **6,0** (5,6 a 6,4) |
| rest+retail | 5,4 | 5,8 | 7,9 (7,4 a 8,5) | **6,1** (5,7 a 7,0) |
| rest+turbo+retail | 4,7 | 5,0 | 5,7 (5,4 a 6,2) | **5,3** (4,8 a 5,9) |
| turbo+retail | 1,7 | 1,8 | 3,7 (3,2 a 4,0) | **2,0** (1,6 a 2,3) |
| **Distancia** (suma de diferencias, semillas 7 · 11 · 23 · 31 · 47) | | | 21,7 · 17,7 · 18,1 · 20,7 · 19,4 | **2,9 · 5,5 · 3,7 · 4,3 · 2,5** |
| **Mayor diferencia de una fila** | | | 8,5 a 10,6 | **0,8 a 1,8** |

«Antes» es el generador de `main` del 17-10 medido hoy con el mismo catálogo; por eso la distancia de la semilla 7 (21,7) no es la de 18,2 del 16-10 ([motor-2026-10-16.md](motor-2026-10-16.md#mejora-continua-etapa-5-datos-simulados)): entre medio cambiaron los complementos curados y las etiquetas del catálogo de la copia.

**Cumple:** cada fila queda a menos de 2 puntos en las cinco semillas (la tolerancia era 3), Restaurantes es la mayor y turbo+retail la menor en todas. Las cinco filas del medio (5 a 7 %) están a menos de 1,3 puntos entre sí en la tabla y se ordenan distinto según la semilla: ese orden no se puede pedir con 3.000 personas.

## Antes y después: retención M+1

Retención de todas las semillas juntas (meses con el siguiente completo); entre paréntesis, el rango entre semillas.

| Combinación | Rappi (dato compartido por Rappi) | Antes (simulado) | Después (simulado) |
|---|---:|---:|---:|
| rest+turbo+retail | 0,93 | 0,906 (0,870 a 0,926) | **0,901** (0,868 a 0,922) |
| rest+turbo | 0,82 | 0,723 (0,675 a 0,753) | **0,779** (0,767 a 0,792) |
| turbo+retail | 0,80 | 0,741 (0,687 a 0,831) | **0,737** (0,667 a 0,800) |
| rest+retail | 0,76 | 0,682 (0,649 a 0,713) | **0,741** (0,692 a 0,771) |
| turbo | 0,50 | 0,413 (0,389 a 0,451) | **0,446** (0,405 a 0,478) |
| rest | 0,47 | 0,383 (0,365 a 0,397) | **0,460** (0,452 a 0,468) |
| retail | 0,41 | 0,356 (0,339 a 0,372) | **0,421** (0,314 a 0,487) |

**Cumple:** rest+turbo+retail es la más alta en las cinco semillas y cada combinación de dos o más grupos retiene más que cada una de un solo grupo en todas. El orden de Rappi se conserva en todos los pares que Rappi separa por 0,05 o más. Los dos pares más juntos en la tabla se dan vuelta en el total: turbo+retail y rest+retail (0,80 y 0,76 en Rappi; 0,737 y 0,741) y turbo y rest (0,50 y 0,47; 0,446 y 0,460). Están dentro del ruido: turbo+retail tiene 45 a 66 meses por semilla. En el total, cada fila queda a 0,063 o menos de la de Rappi, bajo ella en 6 de las 7 (retail, 0,011 sobre; antes, hasta 0,097 bajo); todavía un poco bajo, por el riesgo extra de quien no encuentra lo que busca o abandona carros (`CHURN_*`).

**Lo que no se calibró:** los pedidos por persona de las combinaciones de varios grupos quedan bajo la tabla (rest+turbo 3,9 contra 5,5; rest+turbo+retail 8,4 contra 10,5 en la semilla 7), porque los meses de alta y de salida son parciales.

## El motor con la población nueva (semilla 7, `rappi-ia motor --source synthetic`)

Tramos: entrenar hasta el 2026-08-21, validar hasta el 2026-09-18 y probar hasta el 2026-10-16 (28 días cada uno de los dos últimos). Cambia la población con que se mide, no el motor: las diferencias no son mejoras ni empeoramientos del motor.

| Bloque | Cifra (prueba) | Antes | Después |
|---|---|---:|---:|
| Próxima vertical | personas evaluadas | 352 | 477 |
| Próxima vertical | nDCG@8 combinado · solo afinidad · popularidad · orden fijo | 0,960 · 0,959 · 0,880 · 0,872 | 0,978 · 0,976 · 0,924 · 0,918 |
| Próxima vertical | acierto@1 combinado | 0,923 | 0,962 |
| Próxima vertical | pesos elegidos en validación (afinidad, transición, popularidad) | 1 · 0,1 · 0,1 | 1 · 0,1 · 0,3 |
| Compra cruzada | precisión@3 mezcla (λ) · lo más pedido · reglas (personas con regla) | 0,118 (4) · 0,123 · 0,028 (136) | 0,129 (0) · 0,129 · 0,030 (134) |
| Recompra | predicciones · acierto ±7 días · error mediano | 94 · 0,202 · 6,5 días | 110 · 0,191 · 6 días |
| Paso de la escalera | acierto@1 del paso · la vertical que más se suma (personas) | 0,634 · 0,634 (71) | 0,620 · 0,479 (71) |

**Cómo leerlo, con honestidad:**

- Todo se sigue calculando. Hay más personas evaluadas porque la retención simulada subió y quedan más activas en la ventana de prueba.
- La próxima vertical es más fácil de adivinar para todos los métodos, incluido el orden fijo, porque hay más personas que solo piden en Restaurantes (66,9 % de los meses-persona contra 57,4 %).
- En la compra cruzada, λ volvió a 0: la mezcla es lo más pedido. Es lo mismo que pasaba con el generador de la etapa 5 en las semillas 7, 11 y 23.
- El paso de la escalera ahora gana a la línea base (0,620 contra 0,479), pero son 71 personas de una sola semilla y el paso se mide sobre una población que el generador hace retener según la misma tabla: no es evidencia de que el paso retenga.
- El paso para quien solo pide en Restaurantes sigue siendo Turbo (retención esperada con lo aprendido: Restaurantes + Turbo 0,792, Restaurantes + Supermercado 0,751).

### Tabla fina aprendida (las 10 más frecuentes, semilla 7)

| Combinación fina | Personas-mes | % | n | Retención M+1 |
|---|---:|---:|---:|---:|
| restaurantes | 2.907 | 66,4 | 1.939 | 0,452 |
| turbo | 343 | 7,8 | 226 | 0,478 |
| restaurantes+turbo | 273 | 6,2 | 189 | 0,778 |
| supermercado | 155 | 3,5 | 98 | 0,541 |
| restaurantes+conveniencia | 137 | 3,1 | 91 | 0,802 |
| restaurantes+supermercado | 87 | 2,0 | 65 | 0,738 |
| restaurantes+turbo+supermercado | 79 | 1,8 | 47 | 0,915 |
| restaurantes+turbo+conveniencia | 63 | 1,4 | 39 | 0,872 |
| turbo+conveniencia | 45 | 1,0 | 30 | 0,633 |
| restaurantes+turbo+supermercado+conveniencia | 42 | 1,0 | 31 | 0,871 |

La retención fina aprendida sigue siendo circular (el generador simula con la misma retención esperada) y con pocas personas por fila: Restaurantes + Turbo + Súper + Express (0,871, n 31) queda bajo Restaurantes + Turbo + Súper (0,915, n 47), lo contrario del rendimiento decreciente que supone el generador. Con el tope de supervivencia, quien pide poco y llega por una sugerencia a una combinación que retiene mucho no alcanza a mostrar el supuesto; con 30 a 50 meses por fila tampoco se distingue del ruido.

## La prueba que lo cuida

`tests/integration/test_synth_combos.py::test_the_mix_and_the_retention_track_the_rappi_table` corre el generador con 1.800 personas (semilla 3) sobre el catálogo inventado de la demo. Cuida la **retención** (la de Restaurantes a 0,1 de la de Rappi, rest+turbo+retail la más alta, cada combinación de varios grupos sobre cada una de un solo grupo) y las **regresiones gruesas de la mezcla** (cada fila a 4 puntos, Restaurantes la mayor), no la calibración fina. Con el catálogo de prueba, chico y con muchas búsquedas sin resultado, la peor fila del generador nuevo queda a 3,7 puntos (Restaurantes) y la del anterior a 3,3: la mezcla no los distingue ahí, y no se puede ajustar más la tolerancia. La retención sí: con el generador anterior la de Restaurantes da 0,315 y la prueba falla. La calibración fina se revisa con el catálogo real y `scripts/calibrar_simulados.py`.
