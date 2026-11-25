# Elementos nuevos del panel de negocio: diseño

Fecha: 25-11-2026. El panel gana cinco elementos pensados para decidir, no para describir. Tres usan lo que la API ya entrega y quedan funcionando; dos son un diseño con filas de ejemplo, y este documento dice qué ruta le falta a cada uno. El frente está en `dashboard-empresa/`; el backend de las rutas nuevas se programa después.

## 1. Por qué estos y no los de antes

El 22-10-2026 el panel se redujo a lo que responde a una decisión de la gerencia o de RappiAds ([decisión](../decisiones.md#datos-simulados-y-panel)). La API sigue entregando lo que salió entonces (cohortes, embudo por vertical, ritmo, afinidad, retención por estrato, accesos de la Home y salud del catálogo), pero volver a mostrarlo tal cual sería deshacer esa decisión: describe, o repite el supuesto del simulador.

Los elementos nuevos siguen la misma regla. Cada uno responde a una pregunta de quien decide:

| Elemento | Pregunta | Estado |
|---|---|---|
| Qué cambió | ¿Qué miro primero esta semana? | Funciona, sin backend nuevo |
| Estado del piloto | ¿Cuánto falta para poder concluir? | Funciona; la fecha estimada pide backend (§3) |
| CSV y período | ¿Cómo me llevo estas cifras? | Funciona, sin backend |
| Audiencias | ¿A quién le ofrezco qué? | Diseño con filas de ejemplo (§4) |
| Ficha por vertical | ¿En qué vertical pongo el esfuerzo? | Diseño con filas de ejemplo (§5) |

Un sexto queda anotado y sin diseñar en el frente: lo que Mochi no ofreció por las guardias (§6).

## 2. Lo que no es evidencia sigue rotulado

Un bloque diseñado sin datos no puede parecer una medición. Por eso:

- sus filas son cifras redondas a propósito y viven en el componente (`EXAMPLE_AUDIENCES`, `EXAMPLE_VERTICALS`), no en `src/fixtures/` ni en la API;
- arriba lleva un aviso ámbar y punteado ("Diseño, aún sin datos", `components/DesignNotice.jsx`) que dice que las filas son de ejemplo y qué ruta falta;
- su sección lleva el rótulo "Diseño · filas de ejemplo" y su panel no ofrece bajar el CSV;
- no cambian con la fuente (Simulados o Prototipo): no salen de ninguna.

Cuando exista la ruta, el componente deja de traer filas, las lee con `useAnalytics`, y el aviso y el rótulo de diseño se quitan: pasa a llevar el rótulo de su fuente, como cualquier otro bloque.

## 3. Estado del piloto: lo que falta

Hoy (`views/overview/pilot.js`) el panel lee de `/analytics/experimentos` las personas de cada grupo y el mínimo que pide el plan de piloto para H1, H2 y H3, y muestra la parte cubierta por el grupo que va más atrás.

Falta responder "¿cuándo?". Para eso la API tiene que decir a qué ritmo entran personas a cada grupo. Propuesta, dentro del experimento `ofertas_control` de la misma respuesta:

```json
"ritmo": {
  "semanas": [
    { "semana": "2026-11-02", "tratamiento": 210, "control": 24 }
  ],
  "por_semana": { "tratamiento": 198.5, "control": 22.0 }
}
```

- `semanas`: personas asignadas por semana (lunes), solo semanas completas.
- `por_semana`: el promedio de las últimas 4 semanas completas, o `null` con menos de 2.

Con eso el frente calcula las semanas que faltan (`(mínimo − personas) / por_semana`, del grupo que va más atrás) y las muestra como un rango, no como una fecha exacta. Para H1 hay que sumar el mes de espera de la retención M+1; para H3, el ritmo es de respuestas, no de asignaciones, así que necesita su propia serie (`encuesta.ritmo`, con la misma forma).

## 4. Audiencias: `/analytics/audiencias`

Una audiencia es un grupo de personas que cumple una regla. Sirve para decidir a quién se le ofrece qué, en RappiAds o en una campaña propia, y para medirlo después contra un grupo de control.

Los segmentos ya existen en la capa de datos (`capa.user_segments`, `capa.segment_sizes`, [capa-de-datos.md](../capa-de-datos.md)); la ruta los junta con lo que ya calculan otras (`at-risk`, `volver`, `pro`).

```json
{
  "source": "synthetic",
  "data": {
    "as_of": "2026-11-13",
    "audiencias": [
      {
        "id": "solo-restaurantes-con-habito",
        "nombre": "Solo Restaurantes, con hábito",
        "regla": "Pide solo en Restaurantes y lleva 2 o más pedidos en 30 días",
        "personas": 0,
        "aceptan_avisos": 0,
        "ofrecer": { "momento": "vertical_por_probar", "vertical": "turbo", "texto": "Turbo, su vertical por probar" },
        "cambio_4_semanas_pct": null
      }
    ]
  }
}
```

Reglas que tiene que cumplir el backend:

- **Población declarada.** Como todo el panel, `source` es `synthetic` o `prototype` y nunca se mezclan.
- **Nada sensible.** Ninguna audiencia se define por un concepto o un segmento sensible (`capa.segment_defs.sensitive`), ni por Farmacia o Licores.
- **Lo que se ofrece pasa por las guardias.** `ofrecer` sale de lo que el motor ya propone (`motor/predict.py:target_step`, `offers/winback.py`) y pasa por `offers/guards.py`.
- **Mínimo de personas.** Una audiencia con menos de 20 personas no se entrega (como "Pro y sin Pro").
- **Consentimiento.** `aceptan_avisos` cuenta a quienes aceptaron avisos: fuera de la app solo se les escribe a ellas.
- **"Rappi hoy" no enseña.** Las reglas leen solo pedidos y eventos de la propuesta.

La lista de ids seudónimos de una audiencia va en una segunda ruta, `/analytics/audiencias/{id}` (hasta 100, como `at-risk`), que el panel mostraría a pedido. Es una tabla de personas: si guarda algo nuevo, hay que sumarla a `PERSON_TABLES` (`rappi_ia/delivery.py`).

Audiencias iniciales (las cinco del diseño): solo Restaurantes con hábito; en riesgo con un concepto que pedía seguido; probó Turbo una vez; Pro que no combina; ya combina 3 o más (a esta no se le ofrece nada: no molestar).

## 5. Ficha por vertical: `/analytics/verticales`

Las verticales lado a lado, una fila cada una. Las cifras ya existen repartidas (`funnel` por vertical, `unmet.por_vertical`, `combos`); la ruta las junta con la misma definición que usa el Resumen.

```json
{
  "source": "synthetic",
  "data": {
    "as_of": "2026-11-13",
    "verticales": [
      {
        "vertical": "restaurantes",
        "personas_30d": 0,
        "pedidos_30d": 0,
        "abandono_carrito_pct": null,
        "sin_resultado_pct": null,
        "combinan_pct": null,
        "cambio": { "personas_pct": null, "pedidos_pct": null, "abandono_puntos": null, "sin_resultado_puntos": null }
      }
    ]
  }
}
```

- `combinan_pct`: de quienes pidieron en la vertical en 60 días, cuántos pidieron además en otra.
- `cambio`: contra las 4 semanas anteriores; las tasas, en puntos.
- Una tasa con menos de 10 casos en su denominador va en `null` (la regla del panel).
- Los pedidos cancelados no cuentan (migración 051), y "Rappi hoy" tampoco.
- Farmacia y Licores aparecen como vertical (son cifras agregadas), pero nunca con un concepto.

## 6. Lo que Mochi no ofreció (sin diseñar)

Cuántas veces las guardias frenaron una oferta (alcohol, +18, Farmacia, bebé, salud), por motivo. Sirve para mostrar que Mochi es seguro para la marca. Hoy esos bloqueos no se cuentan: `offers/guards.py` filtra y no deja evento. Haría falta un contador agregado por motivo y momento (sin persona ni producto), y una ruta `/analytics/guardias`. Queda fuera de este cambio.

## 7. Lo que ya funciona, en detalle

- **Qué cambió** (`views/overview/changes.js`): junta la serie semanal, lo que buscan y no encuentran (`opportunities`) y lo que sube (`trends`). Umbrales: 5 % en un conteo, 1 punto en una tasa, 20 % de crecimiento en una demanda. Orden: lo que empeora, lo que mejora y la demanda que crece, que va sin juicio. No calcula ninguna cifra nueva.
- **CSV** (`lib/csv.js`): exporta la tabla del panel tal como se ve, leyendo el DOM. Por eso funciona igual en el panel de un solo HTML, y nunca exporta algo distinto de lo que está en pantalla.
- **Período** (`views/overview/Pulse.jsx`): recorta la línea a las últimas 4, 12 o 26 semanas. La tabla sigue completa.
