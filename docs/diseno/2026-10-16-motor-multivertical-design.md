# Motor multivertical y Home dinámica: diseño

Fecha: 16-10-2026. Diseño vigente del motor, construido en seis etapas entre el 16 y el 17-10-2026. Lo que cambió después (la escalera fina, el rendimiento decreciente, «¿Volvemos a…?») está en [capa-de-datos.md](../capa-de-datos.md#motor-multivertical) y en [decisiones.md](../decisiones.md).

## 1. Para qué

Una conversación con el equipo de Rappi cambió el foco del proyecto hacia la Home y las recomendaciones entre verticales:

1. **Home dinámica.** Restaurantes y Turbo son los dos bloques grandes y no se mueven. Debajo, el motor aprende de la persona y ordena los accesos chicos: si pide más en Farmacia, Farmacia pasa al primer lugar. Lealtad y Beneficios Pro (entonces Loyalty y Benefits Pro) quedan siempre al final.
2. **Recomendaciones conectadas entre verticales.** Según una tabla de Rappi, quien usa Restaurantes + Turbo + Retail en el mismo mes vuelve en un 93 % al mes siguiente. El motor conecta todas las verticales en la base, aprende la tendencia (lo más pedido) y el comportamiento de cada persona, y predice qué vertical sumarle y qué le toca pedir de nuevo.
3. **Menos superficie.** El pasaporte Rappi y el juego de verticales, que se habían probado antes, salen del proyecto para dejar el foco en lo anterior.

La base de datos y los mecanismos de recomendación son la innovación central del proyecto.

## 2. Decisiones de partida (16-10-2026)

| Tema | Decisión |
|---|---|
| Base real | Las migraciones nuevas se aplican a `rappi` con un `pg_dump -Fc` manual antes de cada una. |
| Tabla de Rappi | Sus cifras pueden ir en el repositorio, rotuladas «dato compartido por Rappi». |
| Datos simulados | Se recalibran para parecerse a la mezcla de la tabla; siguen rotulados como simulados y nunca como evidencia. |

## 3. Dato de partida: «Chile · verticals used together»

Tabla compartida por el equipo de Rappi (cohortes de enero a junio de 2026, juntas). Una fila es el conjunto de verticales que una persona usó en el mes base (M0). La agrupación es gruesa, la misma de México («MX crosswalk»).

| Combinación en M0 | Usuarios | % usuarios | % pedidos | Pedidos/usuario | Retención M+1 | GMV/usuario |
|---|---|---|---|---|---|---|
| Rest | 739k | 62,6 % | 39,8 % | 1,9 | 47 % | $42 |
| Turbo | 80k | 6,8 % | 3,9 % | 1,7 | 50 % | $35 |
| Rest + Turbo | 78k | 6,6 % | 12,2 % | 5,5 | 82 % | $123 |
| Retail | 66k | 5,6 % | 2,5 % | 1,4 | 41 % | $34 |
| Rest + Retail | 64k | 5,4 % | 8,4 % | 4,7 | 76 % | $116 |
| Rest + Turbo + Retail | 56k | 4,7 % | 16,4 % | 10,5 | 93 % | $257 |
| Turbo + Retail | 20k | 1,7 % | 2,6 % | 4,6 | 80 % | $108 |
| Favor | 18k | 1,5 % | 1,0 % | 2,0 | 44 % | $11 |
| Todo Chile | 1,18M | 100 % | 100 % | 3,0 | 55 % | $68 |

**Lectura honesta.** La tabla es una correlación: quien ya pide mucho usa más verticales y además vuelve más. No prueba que sumar un vertical cause retención; eso solo lo mide un experimento A/B con grupo de control. El motor la usa como **punto de partida** (qué combinación conviene buscar), no como promesa de efecto.

**Agrupación gruesa del proyecto** (supuesto propio, en `combos.toml`): `rest` = restaurantes; `turbo` = turbo; `retail` = supermercado, conveniencia (Express), farmacia, licores, mall (Rappi Mall) y chocolatería. La tabla no tiene filas de Súper ni de Farmacia, y la suma de las filas mostradas (≈95 %) solo cierra si «Retail» agrupa todo el comercio que no es restaurante ni Turbo. Favor (RappiFavor) es un servicio sin catálogo y queda fuera del motor.

## 4. Etapas

Cada etapa dejó el MVP funcionando, con sus tests y el CI en verde.

| Etapa | Entrega |
|---|---|
| 1 | Salida del pasaporte y del juego, y este diseño. |
| 2 | La capa del motor en la base, los datos simulados recalibrados y la evaluación. |
| 3 | La Home ordenada por el motor y el evento de tocar un acceso. |
| 4 | Ofertas que buscan la combinación que retiene, recompra, «lo más pedido» y el panel. |
| 5 | QA sobre la base real, ciclo de mejora y ajustes. |
| 6 | Revisión del repositorio de punta a punta. |

### Etapa 1: salida del pasaporte y del juego

- **Se va todo el juego:** `rappi_ia/game/`, las rutas `/game/*`, el comando `rappi-ia knowledge`, `GAME_MIN_ITEMS`, «¿Sabías que…?» en `/agent/ask`, la métrica `game` del panel, las pantallas, el contexto y la lógica del juego en la app, el pasaporte de la Home, «Juega mientras llega tu pedido» y las revisiones del juego y del dato en `mvp-check`.
- **Migración 035** (`035_sin_juego.sql`): borra `game_state`, `knowledge_card_concepts` y `knowledge_cards`; borra los eventos `game_round_finished` y `game_card_discovered` (no hay en la base real) y deja el `CHECK` de `app_events.type` sin esos tipos. Las migraciones 028 y 029 no se editan: ya están aplicadas.
- **`vertical_por_probar` deja de depender de los sellos.** El servidor deduce las verticales que la persona ya probó de sus pedidos (`mode = 'propuesta'`) y la app ya no manda `stamped`. La razón pasa a «Porque aún no pides en {vertical}». En la etapa 4 este momento pasa a buscar la combinación que falta.
- **Se conserva lo compartido:** `today()` sale de `src/game/progress.js` a un módulo propio de la app; `ConnectionNotice`, las guardias de ofertas y el grafo (`knowledge_edges`) no son del juego.

### Etapa 2: el motor multivertical en la base

Código nuevo en `rappi-ia/src/rappi_ia/motor/`; reglas en `motor/combos.toml`; tablas en `public` y vistas estables en `capa` (con comentarios en español), igual que la capa de datos. Una migración (`036_motor.sql`).

**Fuente de población.** Los patrones de población (transiciones, combinaciones, compras cruzadas, tendencias) se aprenden de una sola fuente, `MOTOR_POBLACION` (por defecto `synthetic`; con datos reales sería otra fuente). Lo personal (afinidad, recompra) sale siempre de los datos de la propia persona. Cada recomendación declara en su `reason.basis` qué fuente usó. Esto cambia una decisión anterior («el agente no usa lo aprendido de los simulados»): sin datos reales, el motor no tiene otra población de la que aprender, y lo deja dicho en cada oferta.

**Tablas** (las de población llevan `run_id` de `layer_runs`, que suma la capa `motor`; las dos personales, `user_vertical_affinity` y `replenishment`, no tienen `run_id`: se refrescan por persona, también después de cada pedido):

| Tabla | Qué guarda | Cómo se calcula |
|---|---|---|
| `user_vertical_affinity` | Gusto de cada persona por cada vertical: puntaje, pedidos, señales, último uso | Σ peso × 0,5^(días/30) en 180 días. Pesos: pedido 5, `cart_add` 1,5, `vertical_open` 1, `view_store` 1, búsqueda en el vertical 0,5, `view_item` 0,3. Pedidos solo `mode = 'propuesta'` |
| `vertical_transitions` | P(próximo pedido en V \| último en U), por fuente | Pedidos consecutivos de la misma persona (un carro repartido en dos verticales no es transición), suavizado de Laplace (α = 1) |
| `combo_stats` | La tabla de Rappi reproducida con los datos propios, por fuente: usuarios, % usuarios, % pedidos, pedidos/usuario, retención M+1, gasto/usuario | Meses calendario; M0 = mes con pedidos; retención = algún pedido en M+1 |
| `combo_steps` | P(combinación en M+1 \| combinación en M0) por fuente | Pares de meses consecutivos de la misma persona |
| `cross_sell_rules` | Compra cruzada aprendida: concepto A en vertical X → concepto B en vertical Y ≠ X | Personas que piden B en Y dentro de 14 días después de A en X. Confianza P(B\|A), lift > 1,2, ≥ 10 personas con ambos. Sin líneas que vienen de una sugerencia del lado de B, sin conceptos sensibles |
| `trends` | Lo más pedido y lo que sube: por vertical, concepto y producto, en las últimas 4 semanas contra las 4 anteriores | Pedidos y personas distintas; `growth` = (ahora − antes) / max(antes, 5) |
| `replenishment` | Recompra por persona y concepto: pedidos, intervalo mediano, regularidad, fecha esperada | Conceptos pedidos en ≥ 3 pedidos distintos, coeficiente de variación de los intervalos ≤ 0,6 |

**Predicción del próximo vertical** (`motor/predict.py`): puntaje = a × afinidad normalizada + b × transición desde el último vertical + c × popularidad reciente. Los pesos (a, b, c) se eligen solos por búsqueda en grilla sobre una ventana de validación y quedan guardados con la corrida. **Farmacia y Licores solo suben por señales de la propia persona**: para ellos b = c = 0. El motor nunca los empuja con datos de otros.

**Combinación objetivo** (`motor/combos.py`): para la combinación actual de la persona (últimos 30 días), el siguiente paso es el grupo que más sube la retención esperada. Esa retención es la de la tabla de Rappi, mezclada con la aprendida cuando hay ≥ 30 personas en esa combinación; la aprendida pesa n/(n+100). Escalera esperada: Rest → Rest + Turbo → Rest + Turbo + Retail.

**Datos simulados recalibrados** (`events/synth.py`): cada persona simulada recibe un **arquetipo de combinación** sorteado con las proporciones de la tabla (sin Favor, renormalizado; un 5 % «otras» mezcla libre). El arquetipo dice en qué grupos pide; la persona (los 21 perfiles de hoy) dice qué conceptos. Si su perfil no tiene conceptos de un grupo del arquetipo, usa los del súper para Turbo, o los de un perfil vecino. La cadencia sale de pedidos/usuario de su combinación, y el abandono mensual de la retención M+1 de su combinación del mes. Aceptar una sugerencia que suma un grupo mueve a la persona de combinación: **supuesto explícito** de que la correlación de la tabla fuera efecto, rotulado en el código, en los documentos y en el panel.

Al implementarlo (16-10) se dejaron fuera el 5 % «otras» y el «perfil vecino»: quedan los 7 arquetipos de la tabla renormalizados y, para un grupo sin verticales en el perfil, `GENERIC_INTERESTS` (Turbo copia antes lo ofrecible del súper y Express de la persona).

**Evaluación** (dentro de `rappi-ia motor`; `--sin-evaluar` la salta): separación por fecha en tres tramos (entrenar, validar y probar, 28 días cada uno de los dos últimos). Métricas: próximo vertical (acierto@1, acierto@3, MRR, nDCG@8) contra el orden fijo de hoy, la popularidad, solo afinidad y solo transiciones; compra cruzada (precisión@3 contra lo más pedido del vertical, con su cobertura); recompra (`compraron`: la parte que volvió a comprar el concepto en la prueba; `error_mediano_dias`, solo sobre esas; `acierto_7_dias`, error de hasta 7 días sobre todas las predicciones que vencen). Los pesos del próximo vertical se eligen solos en validación y no se guardan pesos nuevos si no hay a quién validar. Informe por fuente en `rappi-ia/data/eval/motor-{fuente}.md` y resumen con fecha en `docs/resultados/`. El generador de datos simulados crea 3.000 personas por defecto (`DEFAULT_USERS`), con altas repartidas en todo el período para que la ventana de prueba tenga gente. **Sobre datos simulados la evaluación prueba la mecánica, no el efecto.**

**Comandos:** `rappi-ia motor [--source] [--sin-evaluar]` (calcula todo, evalúa y guarda la corrida; no hay un `motor-eval` aparte). `make layers` y `post-refresh` corren `motor` después de `synth` y `segments`. Un pedido (`POST /orders`) recalcula la afinidad y la recompra de esa persona en segundo plano, como los segmentos.

**Evento nuevo:** `vertical_open` (tocar un acceso de la Home), en `EVENT_TYPES` y en el `CHECK` (migración 036).

### Etapa 3: Home dinámica

- `GET /profile/{user_id}/verticales` devuelve `{"fixed": ["restaurantes", "turbo"], "order": [{"id", "score", "reason"}], "personalized": bool}` con los 6 verticales de los accesos chicos (supermercado, farmacia, mall, licores, conveniencia, chocolatería) en el orden de la predicción; exige el token de la persona, como `/profile/{id}`.
- La app (modo Prototipo final) pinta los accesos en ese orden: primero los 6 verticales, después RappiTravel y RappiFavor, y al final **Lealtad y Beneficios Pro, siempre**. Sin historial o si la API falla, el orden de hoy. «Rappi hoy» no cambia.
- Tocar un acceso manda `vertical_open` con su vertical (los servicios mandan el suyo en `payload.servicio`); en «Rappi hoy» no enseña, como el resto.
- Una línea bajo la fila dice por qué, solo cuando el orden es personal («Ordenadas según lo que más pides»).

### Etapa 4: recomendaciones conectadas

- **`vertical_por_probar` busca la combinación que falta.** Elige el grupo de la combinación objetivo y, dentro, el vertical con mejor predicción (nunca Farmacia ni Licores). Los productos salen de las compras cruzadas desde los conceptos de la persona; si no hay, de lo más pedido del vertical, y si no, de las ofertas como hoy. La razón habla de la persona («Porque pides sushi: en Turbo llega despensa asiática en minutos»), nunca de cifras de retención.
- **Momento nuevo `recompra`:** «¿Repetimos?» cuando un concepto de la persona está por tocar según su propio ritmo; mismos guardias.
- **Complementos (`carrito`, `checkout`, `proximo_pedido`, `/agent/ask`):** las compras cruzadas aprendidas entran como candidatas junto a las curadas; ante dos candidatos parecidos, gana el del vertical que completa la combinación.
- **«Para ti»** suma «Lo más pedido en {vertical}» desde `trends`.
- **Panel:** en «Entre verticales», «Combinaciones de verticales» muestra la tabla de Rappi (dato compartido) junto a la reproducida con datos simulados, y «Motor» muestra la evaluación; «Uso del MVP» cuenta los toques de accesos y el momento `recompra`.

### Etapa 5: QA y mejora continua

- Revisar el motor sobre la base real (casos sensibles, Farmacia, Licores, bebé, rendimiento de las consultas nuevas) y en `mvp-check`.
- Ciclo propio: medir con `rappi-ia motor`, encontrar el punto más débil, ajustar y volver a medir, hasta que las mejoras dejen de ser claras. Cada ajuste queda con su cifra antes y después.
- La mejora sigue sola: la tarea semanal recalcula el motor y vuelve a elegir los pesos.

### Etapa 6: pulido final

README, índice de documentos, convenciones, decisiones, diagramas, código muerto y coherencia de nombres, de principio a fin.

## 5. Reglas que no cambian

- Guardias de ofertas: nunca alcohol, Licores, Farmacia, bebé, salud ni conceptos sensibles por iniciativa propia.
- Datos de personas: solo `synthetic` o `prototype`; nunca se mezclan en una cifra; lo simulado nunca se presenta como evidencia.
- «Rappi hoy» (`mode = 'actual'`) no enseña al motor.
- «Olvidar» borra también lo que el motor sabe de la persona (afinidad y recompra caen con sus eventos y pedidos, por `ON DELETE CASCADE`).
- Código en inglés; todo lo que ve una persona, en español.
