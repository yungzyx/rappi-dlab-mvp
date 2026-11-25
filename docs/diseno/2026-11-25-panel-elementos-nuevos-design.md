# Elementos nuevos del panel de negocio: diseño

Fecha: 25-11-2026. El panel gana cinco elementos pensados para decidir, no para describir. Los cinco funcionan con datos de la API: tres con lo que ya entregaba y dos con rutas nuevas (`/analytics/verticales` y `/analytics/audiencias`, con la lista de cada audiencia en `/analytics/audiencias/{id}`), más el ritmo de asignación y el de respuestas del piloto en `/analytics/experimentos`. El frente está en `dashboard-empresa/` y el backend en `rappi-ia/src/rappi_ia/analytics/queries.py`.

> Cómo se hizo: primero el frente, con audiencias y ficha por vertical como diseño con filas de ejemplo rotuladas ([#173](https://github.com/yungzyx/rappi-dlab-mvp/pull/173)); después las rutas, y el panel dejó las filas de ejemplo.

## 1. Por qué estos y no los de antes

El 22-10-2026 el panel se redujo a lo que responde a una decisión de la gerencia o de RappiAds ([decisión](../decisiones.md#datos-simulados-y-panel)). La API sigue entregando lo que salió entonces (cohortes, embudo por vertical, ritmo, afinidad, retención por estrato, accesos de la Home y salud del catálogo), pero volver a mostrarlo tal cual sería deshacer esa decisión: describe, o repite el supuesto del simulador.

Los elementos nuevos siguen la misma regla. Cada uno responde a una pregunta de quien decide:

| Elemento | Pregunta | De dónde sale |
|---|---|---|
| Qué cambió | ¿Qué miro primero esta semana? | `weekly`, `opportunities` y `trends`, ordenados en el frente |
| Estado del piloto | ¿Cuánto falta para poder concluir? | `experimentos` (mínimos, `ritmo` y `ritmo_encuesta`) |
| CSV y período | ¿Cómo me llevo estas cifras? | El frente: exporta la tabla que se ve |
| Audiencias | ¿A quién le ofrezco qué? | `/analytics/audiencias` y `/analytics/audiencias/{id}` |
| Ficha por vertical | ¿En qué vertical pongo el esfuerzo? | `/analytics/verticales` |

## 2. Estado del piloto y su ritmo

El panel (`views/overview/pilot.js`) lee de `/analytics/experimentos` las personas de cada grupo y el mínimo que pide el plan de piloto para H1, H2 y H3, y muestra la parte cubierta por el grupo que va más atrás.

Para responder "¿cuándo?", el experimento `ofertas_control` trae `ritmo` (`_assignment_pace`):

```json
"ritmo": {
  "semanas": [{ "semana": "2026-11-02", "tratamiento": 210, "control": 24 }],
  "por_semana": { "tratamiento": 198.5, "control": 22.0 },
  "semanas_promedio": 4
}
```

- `semanas`: personas asignadas por semana (lunes), solo semanas completas al corte de la fuente; una semana sin nadie va en 0.
- `por_semana`: el promedio de las últimas 4 semanas completas, o `null` con menos de 2.

El frente divide las personas que a cada grupo le falta asignar por su ritmo y muestra lo que tarda el más lento, como piso ("al menos 16 semanas más de asignación, y después el mes siguiente completo"). Cuenta contra las personas ya asignadas, no contra las que ya cumplieron su plazo: una persona asignada que todavía no madura va a contar sin que entre nadie más. Si ya hay asignadas tantas como pide el mínimo, dice que solo falta su plazo (el mes siguiente completo en la H1, 28 días en la H2). Es un piso porque no toda persona asignada cuenta para cada hipótesis: la H2 mira solo a quien pide en Restaurantes. Si a un grupo al que le falta no le entra nadie, no se estima.

La H3 avanza con respuestas a la pregunta de la app, no con asignaciones, así que tiene su propia serie, `ritmo_encuesta` (`_survey_pace`), con la misma forma que `ritmo`: las respuestas a la P1 por semana y grupo, con la variante que la persona ya tenía al responder (las mismas que cuenta `encuesta`). El frente divide las respuestas que le faltan a cada grupo para llegar a 100 por su ritmo y muestra lo que tarda el más lento, también como piso ("al menos 8 semanas más"). Una respuesta cuenta apenas llega: no hay plazo que esperar después. La tarjeta H3 de Experimentos dice lo mismo bajo su tabla.

## 3. Ficha por vertical: `/analytics/verticales`

Las verticales lado a lado, una fila cada una, de más a menos personas (`queries.verticals`). Usa las definiciones del Resumen (`kpis`), por vertical:

```json
{
  "verticales": [
    {
      "vertical": "restaurantes",
      "personas_30d": 756,
      "pedidos_30d": 1271,
      "cambio_personas_pct": -4,
      "cambio_pedidos_pct": -6,
      "abandono_carrito_pct": 28.1,
      "sin_resultado_pct": 27.1,
      "combinan_pct": 22.3
    }
  ],
  "bajo_el_minimo": 3,
  "minimo_personas": 20,
  "dias": 30,
  "dias_combinacion": 60,
  "minimo_casos": 10
}
```

- `personas_30d` y `pedidos_30d`: personas con pedido confirmado y pedidos de los últimos 30 días; `cambio_*`, contra los 30 anteriores (`null` si antes no hubo).
- `abandono_carrito_pct`: de los carros que tuvieron algo de esa vertical, con actividad en 30 días. El abandono es del carro entero, como en el indicador general.
- `sin_resultado_pct`: búsquedas y preguntas sin resultado en esa vertical, sin conceptos sensibles.
- `combinan_pct`: de quienes pidieron en la vertical en 60 días, cuántos pidieron además en otra.
- Una tasa con menos de 10 casos en su denominador va en `null` (la regla del panel).
- **Privacidad:** una vertical con menos de 20 personas en 60 días no sale. Con pocas personas, Farmacia o Licores dirían demasiado; `bajo_el_minimo` dice cuántas quedaron fuera.
- La fecha de corte es la de la fuente (la del encabezado del panel, `kpis.as_of`).
- Los pedidos cancelados no cuentan (migración 051). Como en `kpis`, cuentan los dos modos de la app: es una cifra de negocio, no algo que el motor aprenda.

## 4. Audiencias: `/analytics/audiencias`

Una audiencia es un grupo de personas que cumple una regla (`queries.audiences`, con las reglas en `AUDIENCES`). Sirve para decidir a quién se le ofrece qué, en RappiAds o en una campaña propia, y para medirlo después contra un grupo de control.

```json
{
  "audiencias": [
    {
      "id": "solo-restaurantes-con-habito",
      "nombre": "Solo Restaurantes, con hábito",
      "regla": "Pidió solo en Restaurantes en 60 días y lleva 2 o más compras en 30",
      "ofrecer": "Turbo, su vertical por probar",
      "personas": 178,
      "aceptan_avisos": 68,
      "personas_antes": 160,
      "cambio_personas_pct": 11
    }
  ],
  "bajo_el_minimo": 0,
  "minimo_personas": 20,
  "dias_cambio": 28
}
```

Las cinco reglas:

| Audiencia | Regla | Qué ofrecer |
|---|---|---|
| Solo Restaurantes, con hábito | Solo Restaurantes en 60 días y 2 o más compras en 30 | Turbo, su vertical por probar |
| En riesgo, con algo que pedía | El doble de su ritmo sin pedir (mínimo 21 días) y algo que Mochi puede volver a ofrecer | "¿Volvemos a…?" con ese concepto |
| Probó Turbo una vez | Un solo pedido en Turbo en 60 días y alguno en Restaurantes | Repetir en Turbo lo que pidió |
| Pro que no combina | Pro y una sola vertical en 60 días (que no sea Farmacia ni Licores) | Una segunda vertical con su beneficio Pro |
| Ya combina 3 o más | 3 o más verticales en 60 días | Nada nuevo: no molestar |

Reglas que cumple el backend:

- **Población declarada.** `source` es `synthetic` o `prototype` y nunca se mezclan.
- **Nada sensible.** Ninguna regla usa un concepto sensible ni se define por Farmacia o Licores. El concepto de "en riesgo" tiene que pasar las guardias de ofertas (`guards.is_offerable`: sin alcohol, +18, bebé ni salud) y haberse pedido fuera de las verticales bloqueadas: quien solo pidió cerveza, o solo en Farmacia, no entra.
- **Lo que se ofrece es fijo por audiencia** y nunca es de una vertical bloqueada por las guardias (`offers/guards.py`; un test lo revisa). El paso "con Turbo" es el de la tabla de Rappi para quien solo pide en Restaurantes.
- **Mínimo de personas.** Una audiencia con menos de 20 personas no sale (como "Pro y sin Pro"); `bajo_el_minimo` dice cuántas.
- **Consentimiento.** `aceptan_avisos` cuenta a quienes aceptaron avisos: fuera de la app solo se les escribe a ellas.
- Una persona puede estar en más de una audiencia.

**Cambio de tamaño.** `personas_antes` son las personas que cumplían la misma regla 28 días antes del corte (`dias_cambio`), con lo pedido hasta entonces y el corte movido a esa fecha (ritmo, días sin pedir, verticales de los 60 días). Ser Pro y aceptar avisos son de hoy: no tienen historia. `cambio_personas_pct` es el cambio en %. Si entonces no llegaba a 20 personas, los dos van en `null`: su tamaño diría demasiado de pocas personas. El panel lo muestra sin color de juicio (que crezca "En riesgo" no es bueno; que crezca "Ya combina 3 o más", sí) y, en `null`, dice "Hace 4 semanas no llegaba a 20".

**La lista: `/analytics/audiencias/{id}`.** Para llevar una audiencia a una campaña:

```json
{
  "id": "solo-restaurantes-con-habito",
  "nombre": "Solo Restaurantes, con hábito",
  "personas": [{ "usuario": "u-0a1b2c3d", "acepta_avisos": true }]
}
```

- `usuario` es el id seudónimo de la lista de riesgo (`at-risk`: `u-` y las 8 primeras letras del md5 del id), para poder cruzarlas sin entregar el id real. Ordenadas por él.
- Las mismas reglas que el tamaño: misma población (`source`), nada sensible, y 404 si la audiencia no existe o no llega a 20 personas (una audiencia que no se muestra tampoco se entrega).
- En el panel, cada fila de la tabla tiene "CSV" (baja `Usuario;Acepta avisos`) y "Copiar" (el mismo CSV al portapapeles); la lista se pide a la API al tocar, sin caché ni datos guardados. El CSV de la tabla no lleva esos botones (`data-no-csv`).
- En el panel de un solo HTML no hay lista: la foto no graba listas de personas, porque el archivo se comparte suelto. La tabla no ofrece los botones y lo dice al pie.

## 5. Lo que Mochi no ofreció (sin hacer)

Cuántas veces las guardias frenaron una oferta (alcohol, +18, Farmacia, bebé, salud), por motivo. Sirve para mostrar que Mochi es seguro para la marca. Hoy esos bloqueos no se cuentan: `offers/guards.py` filtra y no deja evento. Haría falta un contador agregado por motivo y momento (sin persona ni producto) y una ruta `/analytics/guardias`.

## 6. Lo que sale del frente, en detalle

- **Qué cambió** (`views/overview/changes.js`): junta la serie semanal, lo que buscan y no encuentran (`opportunities`) y lo que sube (`trends`). Umbrales: 5 % en un conteo, 1 punto en una tasa, 20 % de crecimiento en una demanda. Orden: lo que empeora, lo que mejora y la demanda que crece, que va sin juicio. No calcula ninguna cifra nueva.
- **CSV** (`lib/csv.js`): exporta las tablas del panel tal como se ven, leyendo el DOM. Por eso funciona igual en el panel de un solo HTML, y nunca exporta algo distinto de lo que está en pantalla.
- **Período** (`views/overview/Pulse.jsx`): recorta la línea a las últimas 4, 12 o 26 semanas. La tabla sigue completa.

## 7. Datos guardados

- Los ejemplos `verticales.*.json` y `audiencias.*.json` de `dashboard-empresa/src/fixtures/` los escribe `make contract` (están en `PANEL_METRICS` de `tests/integration/test_contract.py`).
- Sus respuestas para el modo sin conexión (`src/fixtures/sin-conexion/`) salen de una copia de la base, como las demás. Una foto grabada antes del 25-11 no trae `personas_antes` ni `ritmo_encuesta`: el panel muestra "—" en el cambio y no estima la H3.
- La lista de una audiencia (`/analytics/audiencias/{id}`) no se graba: ni en `sin-conexion/` ni en la foto del panel de un solo HTML.
