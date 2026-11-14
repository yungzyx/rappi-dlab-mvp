# Especificación de las métricas del piloto

Cómo calcular cada métrica del piloto de Mochi sobre las tablas de Rappi: quién entra, qué ventana, qué evento cuenta, la fórmula, la prueba estadística y una consulta SQL de referencia. Es para el equipo de datos de Rappi y no supone conocer el MVP. rappi-dlab fue desarrollado junto con Rappi Chile; es un prototipo, no un producto oficial.

El piloto corre dentro de Rappi y lo calcula Rappi: el equipo del proyecto no tiene acceso a su base. Por eso esta especificación no depende del esquema del MVP. Las hipótesis, las metas, el reparto y los tamaños de muestra están en [plan-piloto.md](plan-piloto.md); aquí está cómo se cuenta cada cosa. Cada definición se revisó contra el código que la calcula en el MVP (`rappi-ia/src/rappi_ia/analytics/queries.py` y `analytics/power.py`). Si algo de aquí no calza con ese código, manda el código y este documento tiene un error.

## Índice

1. [Resumen en una página](#1-resumen-en-una-página)
2. [Orden de lectura](#2-orden-de-lectura)
3. [Lo común a todas las métricas](#3-lo-común-a-todas-las-métricas): esquema supuesto, población, asignación, pedido confirmado, hora y ventanas, corte de lectura
4. [Las fórmulas estadísticas](#4-las-fórmulas-estadísticas)
5. [H1, retención M+1](#5-h1-retención-m1)
6. [H2, Restaurantes → Turbo](#6-h2-restaurantes--turbo)
7. [H2, frecuencia](#7-h2-frecuencia)
8. [Suma una vertical nueva](#8-suma-una-vertical-nueva)
9. [H3, "¿Encontraste lo que buscabas?"](#9-h3-encontraste-lo-que-buscabas)
10. [Exposición (la parte expuesta)](#10-exposición-la-parte-expuesta)
11. [Adopción](#11-adopción)
12. [Apagado y silencio](#12-apagado-y-silencio)
13. [Resguardos: cancelaciones, reclamos y conversión al primer pedido](#13-resguardos-cancelaciones-reclamos-y-conversión-al-primer-pedido)
14. [Las consultas de referencia](#14-las-consultas-de-referencia)
15. [Errores típicos](#15-errores-típicos)
16. [Lista de verificación antes de encender el piloto](#16-lista-de-verificación-antes-de-encender-el-piloto)
17. [Qué decide cada resultado](#17-qué-decide-cada-resultado)
18. [Cómo se probaron estas consultas](#18-cómo-se-probaron-estas-consultas)

## 1. Resumen en una página

Todas comparan "Mochi activo" (tratamiento) con "Mochi apagado" (control), por intención de tratar: cuentan a todas las personas asignadas, hayan visto a Mochi o no.

| Métrica | Quién cuenta | Qué cuenta | Meta | Prueba | Cuándo se lee |
|---|---|---|---|---|---|
| **H1, retención M+1** (la primaria) | Asignadas en el mes M, con M+1 ya terminado | Algún pedido confirmado en el mes calendario M+1 | **+2 puntos** sobre el control | Dos proporciones a dos colas: IC de 95 % de la diferencia (Wald) | Una vez, al terminar el M+1 de la última cohorte, y solo si cada grupo llega al mínimo para +2 puntos |
| **H2, Restaurantes → Turbo** | Asignadas con sus 28 días cumplidos y un pedido confirmado de Restaurantes antes de que terminen | Un pedido confirmado de Turbo en los 28 días desde la asignación | **+10 % relativo** sobre el control | Dos proporciones a dos colas: IC de 95 % (Wald); también la diferencia relativa | Igual que la H1, con el mínimo para +10 % relativo sobre la tasa del control |
| **H2, frecuencia** | Asignadas con sus 30 días cumplidos; y la cohorte de la H1 | Pedidos confirmados por persona en los 30 días desde la asignación; y en M+1 | Sin meta | Diferencia de promedios, IC de 95 % (Welch) | Con la H2 (los 30 días) y con la H1 (M+1) |
| Suma una vertical nueva (secundaria) | La cohorte de la H1 | Un pedido confirmado en los 28 días desde la asignación, en una vertical sin pedidos confirmados antes | Sin meta, exploratoria | Dos proporciones, IC de 95 % | Con la H1 |
| **H3, "¿Encontraste lo que buscabas?"** | Respuestas a la P1 después de la asignación | % de "Sí" sobre las respondidas | **Sin umbral** | Dos proporciones a **una cola** (la alternativa: más "Sí" con Mochi), p e IC de 95 % | Desde 100 respuestas por grupo |
| Exposición | La cohorte de la H1 | Una oferta retenible entre la asignación y el inicio de M+1 | Debe salir parecida en los dos grupos | Descriptiva: revisa la mecánica y pasa del efecto total al efecto entre expuestos | Con la H1 |
| Adopción | Asignadas | Usó al asistente desde la asignación | Sin meta | Descriptiva (en control, 0 por diseño) | Después de las hipótesis |
| Apagado y silencio | Asignadas | Lo tiene oculto (su último cambio) / lo silenció alguna vez | Sin meta: indicador de alerta | Descriptiva | Después de las hipótesis |
| Resguardos | Asignadas con sus 30 días cumplidos | Pedidos cancelados y reclamos por persona; parte con algún pedido confirmado | Sin meta: Rappi fija antes cuánto empeoramiento tolera | Diferencia de promedios (Welch) o de proporciones, IC de 95 % | Con las hipótesis |

## 2. Orden de lectura

El que pidió Rappi ([plan-piloto.md](plan-piloto.md#orden-de-lectura)):

1. **Retención, frecuencia y venta cruzada**: la H1 (retención M+1) y la H2 (Restaurantes → Turbo y frecuencia). Junto a ellas, la exposición (para pasar al efecto entre expuestos) y los resguardos.
2. **"¿Encontraste lo que buscabas?"** (H3).
3. **Adopción y apagado**, al final. No son hipótesis: ocultar y silenciar son un indicador de alerta. Si suben, Mochi molesta aunque la retención no lo muestre todavía; no se usan para declarar un efecto.

"Suma una vertical nueva" y las demás secundarias van al final, como exploratorias.

## 3. Lo común a todas las métricas

### Esquema mínimo supuesto

Las consultas de la [sección 14](#14-las-consultas-de-referencia) suponen estas cinco tablas. Son genéricas y con nombres descriptivos: hay que adaptarlas a las tablas de Rappi (un `JOIN` o una vista por tabla suele bastar).

```sql
-- consulta: esquema
CREATE TABLE asignaciones (
  user_id     VARCHAR(64) PRIMARY KEY,           -- una fila por persona: la variante no cambia
  grupo       VARCHAR(16) NOT NULL,              -- 'tratamiento' (Mochi activo) o 'control' (Mochi apagado)
  asignado_en TIMESTAMP WITH TIME ZONE NOT NULL  -- cuándo entró al piloto
);

CREATE TABLE pedidos (
  pedido_id VARCHAR(64) PRIMARY KEY,
  user_id   VARCHAR(64) NOT NULL,
  vertical  VARCHAR(32) NOT NULL,                -- 'restaurantes', 'turbo', 'supermercados', ...
  estado    VARCHAR(16) NOT NULL,                -- 'confirmado' o 'cancelado': el estado de hoy
  creado_en TIMESTAMP WITH TIME ZONE NOT NULL    -- cuándo se hizo el pedido
);

CREATE TABLE respuestas_encuesta (
  respuesta_id  VARCHAR(64) PRIMARY KEY,
  user_id       VARCHAR(64) NOT NULL,
  pregunta      VARCHAR(8)  NOT NULL,            -- 'p1' o 'p3'
  respuesta     VARCHAR(16) NOT NULL,            -- p1: 'si', 'en_parte' o 'no'; p3: '1' a '5'
  respondida_en TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE eventos_asistente (
  evento_id VARCHAR(64) PRIMARY KEY,
  user_id   VARCHAR(64) NOT NULL,
  tipo      VARCHAR(32) NOT NULL,                -- ver la tabla de abajo
  momento   VARCHAR(32),                         -- solo en 'oferta_retenible'
  creado_en TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE reclamos (
  reclamo_id VARCHAR(64) PRIMARY KEY,
  user_id    VARCHAR(64) NOT NULL,
  pedido_id  VARCHAR(64),                        -- el pedido del reclamo, si lo hay
  creado_en  TIMESTAMP WITH TIME ZONE NOT NULL
);
```

Los tipos de `eventos_asistente` y de dónde salen en el MVP:

| `tipo` | Qué es | En el MVP |
|---|---|---|
| `abrio` | La persona tocó la mascota (abrió al asistente) | `agent_open`: entra con el PR que lo suma a la adopción, en curso (hoy tocar la mascota no deja evento propio) |
| `busco` | Buscó o preguntó en el buscador con Mochi | `ask` (o `chat`, el nombre antiguo), fuera de "Rappi hoy" |
| `acepto_oferta` | Aceptó una oferta de Mochi (agregó al carro lo que propuso) | `suggestion_accepted` con origen `agent-<momento>` (o los históricos `mochi-<momento>` y `chat`) |
| `oculto` | Ocultó a Mochi | `agent_visibility` con `visible: false`, sin `quiet` |
| `mostro` | Lo trajo de vuelta | `agent_visibility` con `visible: true`, sin `quiet` |
| `silencio` | "Silenciar por hoy" | `agent_visibility` con `quiet: true` |
| `oferta_retenible` | El servidor tuvo una oferta que la app pidió sola, en cualquiera de los dos grupos; `momento` dice cuál | `offer_withheld` (control) y `offer_eligible` (tratamiento), fuera del buscador con Mochi |

El estado `confirmado` o `cancelado` de `pedidos` es el estado del pedido **al momento de leer**, y `creado_en` es cuándo se hizo: un pedido cancelado no cuenta nunca, aunque se haya cancelado días después.

Las consultas usan SQL estándar: `WITH`, `CASE`, `EXISTS`, `VAR_SAMP`, literales `TIMESTAMP WITH TIME ZONE '…'`, `INTERVAL '28' DAY` y `VALUES` dentro de un `WITH`. Corren tal cual en PostgreSQL (así se probaron, [sección 18](#18-cómo-se-probaron-estas-consultas)); en un motor que no acepte `VALUES` en un `WITH`, se reemplaza por `SELECT … UNION ALL SELECT …`, y donde no exista `INTERVAL '28' DAY`, por la suma de días del motor.

### Población: quién entra

- **Personas que en el mes anterior a su asignación (M−1) pidieron en una sola vertical**: pedidos confirmados en exactamente una vertical en ese mes calendario (hora de Chile). Quien ya combina verticales tiene otra retención base y queda fuera ([plan-piloto.md](plan-piloto.md#en-quiénes-con-qué-reparto-y-cuánto-dura)). La consulta `elegibles` ([sección 14](#14-las-consultas-de-referencia)) arma la lista.
- La población se define **antes** de asignar y no cambia después. El MVP no filtra la población al medir: calcula sobre todas las personas con variante, porque el filtro lo hace el piloto cuando decide a quién asignar. Por eso `asignaciones` debe tener solo personas elegibles.
- Exclusiones: las cuentas que Rappi ya excluye de sus experimentos (de prueba, de empleados). Nada más: no se excluye a quien no abrió la app, no vio una oferta o canceló.
- **Desde cuándo:** desde que Rappi registre los eventos de la exposición en los dos grupos (en el MVP, desde la migración 056). Una persona asignada antes de eso no se puede contar en la parte expuesta.

### Asignación: al azar, estable, por intención de tratar

- **Al azar y estable por persona:** cada persona recibe su variante una sola vez y la conserva aunque cambie el porcentaje. En el MVP es un sorteo con el id de la persona (`rappi_ia/events/experiments.py`): el lugar de la persona es `int(sha256("ofertas_control:" + user_id)[0:8], big-endian) mod 100`, y cae en control si ese lugar es menor que `OFFERS_CONTROL_PCT`. Por ejemplo, `u-003` tiene el lugar 5 (control con 10 %) y `u-001`, el 71 (tratamiento). Rappi puede usar su propia herramienta de experimentos si cumple lo mismo: al azar, una vez, estable.
- **Reparto:** `OFFERS_CONTROL_PCT` es la parte que queda en control: 10 (10 % en control) o 50 (50/50), según [plan-piloto.md](plan-piloto.md#en-quiénes-con-qué-reparto-y-cuánto-dura). Se decide antes de empezar.
- **`asignado_en`** es cuándo la persona entra al piloto. En el MVP, su primera sesión con el piloto encendido (`POST /session` la asigna y le dice si ve a Mochi). Rappi tiene que usar el mismo momento en los dos grupos y guardar la hora exacta: todas las ventanas parten de ahí.
- **Intención de tratar:** se cuenta a todas las personas asignadas, en el grupo que les tocó, hayan visto a Mochi o no. Nunca se reemplaza a "asignadas" por "expuestas" o "las que usaron a Mochi" (ver [sección 15](#15-errores-típicos)).

### Qué es un pedido confirmado

Un pedido cuyo estado al leer es `confirmado`, es decir, que se hizo y no se canceló. Cuenta en el momento en que se hizo (`creado_en`), no en el de la entrega. En el MVP: `app_orders.status = 'confirmado'` (desde la migración 051 ninguna métrica cuenta un pedido cancelado). En Rappi corresponde a los pedidos que no terminaron cancelados ni fallidos; lo que Rappi considere "pedido válido" sirve si es igual para los dos grupos y se declara antes.

### Hora y ventanas

- **Meses en hora de Chile** (America/Santiago): el mes M es el mes calendario de `asignado_en` en hora de Chile. En las consultas, cada inicio de mes va como literal con la diferencia horaria de Chile en esa fecha (`-03:00` en horario de verano, `-04:00` en invierno).
- **Ventanas de días** (28 y 30) desde el instante de `asignado_en`, de 24 horas cada día, con el inicio incluido y el final excluido: `[asignado_en, asignado_en + 28 días)`.
- **Una ventana cumplida** es una cuyo final ya pasó al momento de leer. Quien todavía no la cumple no entra en esa métrica (no se cuenta como cero).

### El corte de lectura

`corte` es el momento en que se leen los datos. En el MVP es el último evento de la fuente; en el piloto, la hora en que Rappi corre las consultas, una sola vez, cuando termina el M+1 de la última cohorte ([plan-piloto.md](plan-piloto.md#análisis-declarado-antes-de-empezar)). Si M+1 es febrero, quien fue asignado el 30 o el 31 de enero cumple sus 30 días después del fin de febrero: para que la frecuencia de 30 días los incluya, el corte va en la mayor de dos fechas, el fin de M+1 y la última asignación más 30 días.

## 4. Las fórmulas estadísticas

Son las de `rappi-ia/src/rappi_ia/analytics/power.py`: aproximación normal, α = 0,05 a dos colas y potencia 0,8. z₀,₉₇₅ = 1,959964 y z₀,₈ = 0,841621.

**Proporción de un grupo:** p = x / n (personas que cumplen / personas que cuentan).

**Diferencia de dos proporciones y su intervalo de 95 %** (`difference_ci`, Wald con varianzas sin juntar):

d = p_t − p_c, IC = d ± 1,96 · √(p_t(1 − p_t)/n_t + p_c(1 − p_c)/n_c), recortado a [−1, 1].

La prueba a dos colas se lee con ese intervalo: hay diferencia al 5 % si el intervalo no incluye el 0. El MVP no calcula un p para la H1 ni para la H2: su veredicto es "sube con el tratamiento" si el intervalo queda entero sobre 0, "baja" si queda entero bajo 0 y "sin diferencia clara" si lo cruza.

**Diferencia relativa** (la de la meta de la H2): d / p_c.

**Diferencia de dos promedios y su intervalo de 95 %** (`mean_difference_ci`, Welch con la aproximación normal):

d = m_t − m_c, IC = d ± 1,96 · √(s²_t/n_t + s²_c/n_c),

con m el promedio por persona y s² la varianza de la muestra (dividida por n − 1). Si un grupo tiene una sola persona, su varianza se toma como 0.

**Prueba de dos proporciones a una cola** (`one_sided_p`, la de la H3; H0: iguales; la alternativa: mayor en tratamiento):

p̂ = (x_t + x_c)/(n_t + n_c), z = (p_t − p_c) / √(p̂(1 − p̂)(1/n_t + 1/n_c)), p = 1 − Φ(z).

Si p̂ es 0 o 1 (nadie o todos dijeron "Sí"), no hay diferencia que probar y p = 0,5. Se rechaza H0 si p < 0,05.

**Mínimo de muestra** (`sample_size`). Con k la parte en control, p₀ la tasa base, δ el efecto mínimo, p₁ = p₀ + δ y p̄ = k·p₀ + (1 − k)·p₁, el total es

N = [z₀,₉₇₅ · √(p̄(1 − p̄)(1/k + 1/(1 − k))) + z₀,₈ · √(p₀(1 − p₀)/k + p₁(1 − p₁)/(1 − k))]² / δ²

y cada grupo se redondea hacia arriba: control ⌈k·N⌉ y tratamiento ⌈(1 − k)·N⌉. Una diferencia es **concluyente** solo si cada grupo llega a su mínimo; antes, el MVP la muestra sin intervalo y dice "no es concluyente". k es la parte en control de todas las personas con variante (con un reparto de 10, cerca de 0,10).

| Métrica | p₀ (base) | δ (efecto mínimo) | Quién debe llegar al mínimo |
|---|---|---|---|
| H1 | La retención M+1 de la población del piloto. El MVP usa la fila "solo Restaurantes" de la tabla de combinaciones de Rappi, que es un supuesto y mide a un mes; en el piloto se usa la base de Rappi con la definición de la H1 ([plan-piloto.md](plan-piloto.md#en-quiénes-con-qué-reparto-y-cuánto-dura), "Desfase con la tabla de Rappi") | 0,02 (+2 puntos) | Las personas de la cohorte de la H1, por grupo |
| H2, Restaurantes → Turbo | La tasa del control observada, x_c / n_c | 0,10 · p₀ (+10 % relativo) | Los clientes de Restaurantes, por grupo. Sin mínimo (y no concluyente) si el control está en 0 % o si 1,1 · p₀ ≥ 1 |
| H3 | No hay: sin umbral no hay efecto mínimo con que calcular | — | 100 respuestas a la P1 por grupo, un supuesto propio (con 100, el IC de la diferencia no pasa de ±14 puntos y la aproximación normal vale) |

Los tamaños con distintas bases y repartos están en [plan-piloto.md](plan-piloto.md#qué-haría-falta-para-medirlo).

**Efecto entre expuestos.** El efecto por intención de tratar se diluye si solo una parte de las personas llega a una oferta. Efecto total ≈ parte expuesta × efecto entre expuestos, así que el efecto entre expuestos es la diferencia dividida por la parte expuesta, suponiendo efecto cero en quien no tuvo una oferta ([plan-piloto.md](plan-piloto.md#análisis-declarado-antes-de-empezar)). La parte expuesta se mide ([sección 10](#10-exposición-la-parte-expuesta)) y debe salir parecida en los dos grupos; el plan no dice de cuál grupo tomarla: conviene declarar antes que se usa la de la cohorte completa.

## 5. H1, retención M+1

- **Unidad y población:** la persona asignada. La cohorte es la de las personas asignadas en un mes M cuyo mes siguiente (M+1) ya terminó al leer. Si se asigna en dos meses, las dos cohortes se suman, cada persona con su propio M.
- **Ventana y evento:** el mes calendario M+1 completo, en hora de Chile, de su primer instante incluido al primero del mes siguiente excluido. Cuenta cualquier pedido confirmado; los cancelados no cuentan.
- **Fórmula:** retención M+1 = personas de la cohorte con al menos un pedido confirmado en M+1 / personas de la cohorte. Diferencia en puntos: tratamiento − control.
- **Prueba:** dos proporciones a dos colas, con su IC de 95 % (Wald). Concluyente cuando cada grupo llega al mínimo para +2 puntos ([sección 4](#4-las-fórmulas-estadísticas)). Se lee una vez, al terminar el M+1 de la última cohorte.
- **Meta:** +2 puntos sobre el control.
- **Consulta:** `cohorte_m1`, columnas `personas` y `retenidas`.
- **Datos que necesita:** `asignaciones` y `pedidos` (con el estado al leer).
- **Errores típicos:** tomar el mes M o M+1 en UTC (una asignación del 31 a las 22:00 de Chile cae en otro mes en UTC); leer antes de que termine M+1 (la cohorte se achica y la retención baja); comparar con la retención de la tabla de Rappi, que mide un mes antes (ver "Desfase con la tabla de Rappi" en [plan-piloto.md](plan-piloto.md#en-quiénes-con-qué-reparto-y-cuánto-dura)).

## 6. H2, Restaurantes → Turbo

- **Unidad y población:** la persona asignada que ya cumplió sus 28 días desde la asignación y tiene **un pedido confirmado de Restaurantes antes de que terminen esos 28 días** (puede ser anterior a la asignación). Son los "clientes de Restaurantes" de cada grupo.
- **Ventana y evento:** un pedido confirmado de Turbo en `[asignado_en, asignado_en + 28 días)`. Un pedido de Turbo anterior a la asignación no cuenta; tampoco uno cancelado.
- **Fórmula:** tasa = clientes de Restaurantes con un pedido de Turbo en la ventana / clientes de Restaurantes. Diferencia en puntos (tratamiento − control) y relativa (diferencia / tasa del control).
- **Prueba:** dos proporciones a dos colas, con su IC de 95 % (Wald). Concluyente cuando cada grupo tiene los clientes de Restaurantes que pide +10 % relativo con la tasa del control como base ([sección 4](#4-las-fórmulas-estadísticas)). Se lee con la H1.
- **Meta:** +10 % relativo sobre el control (la tasa del tratamiento, 1,1 veces la del control).
- **Consulta:** `desde_asignacion`, columnas `clientes_restaurantes` y `con_turbo`.
- **Datos que necesita:** `asignaciones` y `pedidos`, con la vertical de cada pedido.
- **Errores típicos:** contar como cliente de Restaurantes solo a quien pidió antes de la asignación, o solo dentro de la ventana (el MVP cuenta las dos); contar a quien todavía no cumple sus 28 días. En el piloto la población (una sola vertical en M−1) se define antes de asignar, pero un pedido de Restaurantes dentro de la ventana también hace cliente a la persona, y ese pedido puede venir del tratamiento: si los clientes de Restaurantes salen muy distintos entre los grupos, hay que mirarlo antes de leer la tasa.

## 7. H2, frecuencia

Dos medidas, sin meta propia:

- **Frecuencia de 30 días.** Unidad: la persona asignada que ya cumplió sus 30 días desde la asignación. Cuenta los pedidos confirmados en `[asignado_en, asignado_en + 30 días)`. Fórmula: promedio de pedidos por persona (suma de pedidos / personas, con las que no pidieron en 0). Consulta: `desde_asignacion`, columnas `personas_30d`, `pedidos_30d_promedio` y `pedidos_30d_varianza`.
- **Frecuencia en M+1.** Unidad: la cohorte de la H1. Cuenta los pedidos confirmados en el mes calendario M+1. Consulta: `cohorte_m1`, columnas `personas`, `pedidos_m1_promedio` y `pedidos_m1_varianza`.
- **Prueba:** diferencia de promedios con su IC de 95 % (Welch, [sección 4](#4-las-fórmulas-estadísticas)). El MVP muestra el intervalo de la de 30 días cuando Restaurantes → Turbo llega a su mínimo, y el de M+1 cuando la H1 llega al suyo; antes, solo la diferencia.
- **Errores típicos:** dividir por las personas que pidieron en vez de por todas las asignadas que cumplieron la ventana (sube la frecuencia y la sesga hacia quien ya pide); contar los cancelados; contar un carro de dos tiendas como un pedido (en el MVP son dos pedidos: lo que vale es contarlo igual en los dos grupos).

## 8. Suma una vertical nueva

Secundaria y exploratoria ([plan-piloto.md](plan-piloto.md#secundarias)).

- **Unidad y población:** la cohorte de la H1. Como M+1 termina al menos 28 días después de cualquier día de M, todas cumplieron sus 28 días.
- **Ventana y evento:** un pedido confirmado en `[asignado_en, asignado_en + 28 días)` en una vertical en la que la persona no tenía ningún pedido confirmado antes de su asignación (en toda su historia; un pedido anterior cancelado no cuenta como haber pedido ahí).
- **Fórmula:** personas que suman una vertical / personas de la cohorte.
- **Prueba:** dos proporciones, IC de 95 %, que el MVP muestra cuando la H1 llega a su mínimo.
- **Consulta:** `cohorte_m1`, columna `suman_vertical`.
- **Errores típicos:** mirar la historia solo de M−1 (una vertical que la persona usó hace un año no es nueva); contar una vertical nueva cancelada.

## 9. H3, "¿Encontraste lo que buscabas?"

- **La pregunta:** la P1, "¿Encontraste lo que buscabas?", con Sí, En parte y No, igual en los dos grupos, tras un recorrido de búsqueda ([diseno-ia.md](diseno-ia.md#la-pregunta-de-la-h3)). Topes: una por sesión y una por día por persona; nunca en el checkout, el pago ni el seguimiento. La P3 ("¿Confías en las sugerencias de Mochi?") solo la ve el tratamiento y no entra en la comparación.
- **Unidad y población:** la **respuesta**, no la persona. Cuentan las respuestas a la P1 de personas asignadas, dadas desde su asignación (las de antes no tienen grupo).
- **Fórmula:** % de "Sí" = respuestas "Sí" / respuestas a la P1. "En parte" y "No" cuentan en el denominador. Diferencia en puntos: tratamiento − control.
- **Prueba:** dos proporciones a **una cola** (H0: igual; la alternativa: más "Sí" con Mochi), con su p y su IC de 95 % ([sección 4](#4-las-fórmulas-estadísticas)). Sin umbral previo. Se lee desde 100 respuestas por grupo; antes, "no es concluyente".
- **Consulta:** `h3`, columnas `respondidas` y `si`.
- **Datos que necesita:** las respuestas, con su persona y su hora. Para la tasa de respuesta, también las veces que se mostró y que se cerró sin responder (en el MVP, `survey_shown` y `survey_dismissed`), que no cambian la H3.
- **Errores típicos:** que la pregunta salga distinto en los dos grupos (otro texto, otro momento, otra frecuencia: la comparación deja de valer); no respetar el tope diario (quien responde mucho pesa más); contar respuestas de antes de la asignación. La prueba trata cada respuesta como independiente, aunque una persona puede responder varios días: es una aproximación que el plan acepta.

## 10. Exposición (la parte expuesta)

- **Qué es:** la parte de la cohorte de la H1 que tuvo al menos una oferta retenible entre su asignación y el inicio de M+1. Una oferta retenible es una que la app pide sola, igual en los dos grupos, y que el servidor tiene para mostrar: la retiene en control y la entrega en tratamiento, y en los dos casos lo anota ([plan-piloto.md](plan-piloto.md#el-control-mochi-apagado)). Cuenta el hecho del servidor, no lo que la app alcanzó a mostrar.
- **Los momentos que cuentan** (`EXPOSURE_MOMENTS` en `events/experiments.py`): `carrito` (la oferta del carro), `sin_resultado` (búsqueda sin resultado), `proximo_pedido` (el próximo pedido, en el seguimiento), `recompra` ("¿Repetimos?"), `volver` ("¿Volvemos a…?") y `ontop` (el OnTop de Turbo). No cuentan "Muéstrame algo nuevo" (`vertical_por_probar`: se pide desde el menú de la mascota, que el control no tiene), los planes, el perfil de gusto, "¿Me falta algo?" ni lo que la persona pide en el buscador con Mochi: solo el tratamiento los puede pedir.
- **Unidad y fórmula:** persona. Parte expuesta = personas de la cohorte con al menos una oferta retenible en `[asignado_en, inicio de M+1)` / personas de la cohorte, por grupo.
- **Para qué sirve:** revisa la mecánica (debe salir parecida en los dos grupos: hasta la primera oferta los dos vivieron lo mismo; si no, algo falla) y pasa del efecto por intención de tratar al efecto entre expuestos ([sección 4](#4-las-fórmulas-estadísticas)).
- **Consulta:** `cohorte_m1`, columna `expuestas`.
- **Errores típicos:** contar en tratamiento las ofertas mostradas y en control las retenidas (dos hechos distintos: la app filtra lo que la persona ya rechazó, la Home puede estar tapada); contar ofertas por sesión en vez de personas; usar ofertas posteriores al inicio de M+1.

## 11. Adopción

- **Qué es:** usó al asistente: **lo abrió, buscó con él o aceptó una oferta suya**, desde su asignación. El toque a la mascota (abrirlo) entra en el MVP con el PR que suma el evento `agent_open`, en curso; hasta entonces el MVP cuenta buscar y aceptar.
- **Unidad y población:** todas las personas asignadas.
- **Ventana:** desde `asignado_en` hasta el corte.
- **Fórmula:** personas que usaron al asistente / personas asignadas, por grupo.
- **Prueba:** ninguna: es descriptiva. En control es 0 por diseño (no tiene a Mochi). Si sale mayor que 0, el control vio a Mochi y hay que arreglarlo antes de leer.
- **Consulta:** `adopcion`, columna `usaron`.
- **Errores típicos:** usar la adopción como denominador de las hipótesis ("la retención de quienes usaron a Mochi" compara gente que se eligió sola, no mide un efecto); contar sesiones o toques en vez de personas.

## 12. Apagado y silencio

- **Oculto:** la persona tiene a Mochi oculto si su último cambio desde la asignación (ocultar o traerlo de vuelta) fue ocultarlo. Silenciar y despertar no cuentan como ocultar ni como traerlo de vuelta.
- **Silenció:** "Silenciar por hoy" al menos una vez desde la asignación.
- **Unidad y población:** todas las personas asignadas; ventana desde `asignado_en` hasta el corte.
- **Fórmula:** personas con Mochi oculto / asignadas; personas que lo silenciaron / asignadas. En control son 0 por diseño.
- **Prueba:** ninguna: es un indicador de alerta, no una hipótesis. El plan no fija cuánto es demasiado: Rappi lo fija antes de empezar ([sección 16](#16-lista-de-verificación-antes-de-encender-el-piloto)).
- **Consulta:** `adopcion`, columnas `ocultos` y `silenciaron`.
- **Sin grupos:** con el control apagado, el panel del MVP muestra lo mismo para toda la población (`/analytics/presencia`): de las personas activas en 30 días (algún evento), cuántas lo tienen oculto (su último cambio, de cuando sea) y cuántas lo silenciaron en esos 30 días. Describe, no mide un efecto.
- **Errores típicos:** contar como oculta a quien lo ocultó y lo trajo de vuelta; contar los ocultos de antes de la asignación; sumar el silencio al ocultar.

## 13. Resguardos: cancelaciones, reclamos y conversión al primer pedido

El MVP no los mide por grupo; Rappi sí puede. Miran que Mochi no haga daño mientras busca subir la retención. No tienen meta: Rappi fija antes de empezar cuánto empeoramiento tolera. Usan la misma unidad y la misma ventana que la frecuencia de 30 días: personas asignadas que ya cumplieron sus 30 días, y lo que pasa en `[asignado_en, asignado_en + 30 días)`.

- **Cancelaciones:** pedidos cancelados por persona (promedio, con las que no cancelaron en 0); diferencia de promedios con su IC de 95 % (Welch). Como referencia, la tasa: pedidos cancelados / pedidos hechos en la ventana, por grupo (sin prueba: los pedidos de una misma persona no son independientes). Una cancelación cuenta por el día en que se hizo el pedido.
- **Reclamos:** reclamos por persona, por el día del reclamo (Rappi decide qué cuenta como reclamo: un ticket de ayuda de un pedido, por ejemplo, igual en los dos grupos); diferencia de promedios con su IC de 95 % (Welch).
- **Conversión al primer pedido:** la parte de las personas con al menos un pedido confirmado en los 30 días desde su asignación; dos proporciones, IC de 95 % (Wald). Mira que Mochi no frene la compra (una mascota que estorba, ofertas que distraen). Si Rappi tiene su propia conversión de sesión a pedido, puede sumarla, contada igual en los dos grupos.
- **Consulta:** `resguardos`.
- **Datos que necesita:** `pedidos` (con los cancelados) y `reclamos`.

## 14. Las consultas de referencia

Seis consultas sobre el esquema de la [sección 3](#esquema-mínimo-supuesto). Las fechas son de ejemplo: se cambian el corte y los meses. Devuelven conteos por grupo; las diferencias, intervalos y p salen de las fórmulas de la [sección 4](#4-las-fórmulas-estadísticas).

### `elegibles`: quién puede entrar al piloto del mes M

```sql
-- consulta: elegibles
-- Pidieron (pedidos confirmados) en una sola vertical en el mes anterior a M. Aquí M es enero de 2027.
WITH parametros (inicio_m_menos_1, inicio_m) AS (
  VALUES (TIMESTAMP WITH TIME ZONE '2026-12-01 00:00:00-03:00',
          TIMESTAMP WITH TIME ZONE '2027-01-01 00:00:00-03:00')
)
SELECT p.user_id, MIN(p.vertical) AS vertical
FROM pedidos p
CROSS JOIN parametros x
WHERE p.estado = 'confirmado'
  AND p.creado_en >= x.inicio_m_menos_1 AND p.creado_en < x.inicio_m
GROUP BY p.user_id
HAVING COUNT(DISTINCT p.vertical) = 1
ORDER BY p.user_id;
```

### `cohorte_m1`: H1, frecuencia en M+1, suma una vertical y exposición

```sql
-- consulta: cohorte_m1
WITH parametros (corte) AS (
  VALUES (TIMESTAMP WITH TIME ZONE '2027-04-02 12:00:00-03:00')
),
meses (inicio_m, inicio_m1, fin_m1) AS (   -- cada mes de asignación, con su M+1, en hora de Chile
  VALUES
    (TIMESTAMP WITH TIME ZONE '2027-01-01 00:00:00-03:00',
     TIMESTAMP WITH TIME ZONE '2027-02-01 00:00:00-03:00',
     TIMESTAMP WITH TIME ZONE '2027-03-01 00:00:00-03:00'),
    (TIMESTAMP WITH TIME ZONE '2027-02-01 00:00:00-03:00',
     TIMESTAMP WITH TIME ZONE '2027-03-01 00:00:00-03:00',
     TIMESTAMP WITH TIME ZONE '2027-04-01 00:00:00-03:00'),
    (TIMESTAMP WITH TIME ZONE '2027-03-01 00:00:00-03:00',
     TIMESTAMP WITH TIME ZONE '2027-04-01 00:00:00-03:00',
     TIMESTAMP WITH TIME ZONE '2027-05-01 00:00:00-04:00')
),
cohorte AS (  -- solo los meses con M+1 ya terminado al corte
  SELECT a.user_id, a.grupo, a.asignado_en, m.inicio_m1, m.fin_m1
  FROM asignaciones a
  JOIN meses m ON a.asignado_en >= m.inicio_m AND a.asignado_en < m.inicio_m1
  CROSS JOIN parametros x
  WHERE m.fin_m1 <= x.corte
),
por_persona AS (
  SELECT c.user_id, c.grupo,
         (SELECT COUNT(*) FROM pedidos o
           WHERE o.user_id = c.user_id AND o.estado = 'confirmado'
             AND o.creado_en >= c.inicio_m1 AND o.creado_en < c.fin_m1) AS pedidos_m1,
         CASE WHEN EXISTS (
           SELECT 1 FROM pedidos o
            WHERE o.user_id = c.user_id AND o.estado = 'confirmado'
              AND o.creado_en >= c.asignado_en AND o.creado_en < c.asignado_en + INTERVAL '28' DAY
              AND NOT EXISTS (
                SELECT 1 FROM pedidos b
                 WHERE b.user_id = c.user_id AND b.estado = 'confirmado'
                   AND b.vertical = o.vertical AND b.creado_en < c.asignado_en))
         THEN 1 ELSE 0 END AS suma_vertical,
         CASE WHEN EXISTS (
           SELECT 1 FROM eventos_asistente e
            WHERE e.user_id = c.user_id AND e.tipo = 'oferta_retenible'
              AND e.momento IN ('carrito', 'sin_resultado', 'proximo_pedido', 'recompra', 'volver', 'ontop')
              AND e.creado_en >= c.asignado_en AND e.creado_en < c.inicio_m1)
         THEN 1 ELSE 0 END AS expuesta
  FROM cohorte c
)
SELECT grupo,
       COUNT(*) AS personas,
       SUM(CASE WHEN pedidos_m1 > 0 THEN 1 ELSE 0 END) AS retenidas,
       SUM(suma_vertical) AS suman_vertical,
       SUM(expuesta) AS expuestas,
       AVG(CAST(pedidos_m1 AS DOUBLE PRECISION)) AS pedidos_m1_promedio,
       VAR_SAMP(CAST(pedidos_m1 AS DOUBLE PRECISION)) AS pedidos_m1_varianza
FROM por_persona
GROUP BY grupo
ORDER BY grupo;
```

`meses` tiene que listar todos los meses en que se asignó: una persona asignada en un mes que no está en la lista no entra en la cohorte.

### `desde_asignacion`: H2, Restaurantes → Turbo y frecuencia de 30 días

```sql
-- consulta: desde_asignacion
WITH parametros (corte) AS (
  VALUES (TIMESTAMP WITH TIME ZONE '2027-04-02 12:00:00-03:00')
),
por_persona AS (
  SELECT a.user_id, a.grupo,
         CASE WHEN a.asignado_en + INTERVAL '30' DAY <= x.corte THEN 1 ELSE 0 END AS cumplio_30,
         CASE WHEN a.asignado_en + INTERVAL '28' DAY <= x.corte THEN 1 ELSE 0 END AS cumplio_28,
         (SELECT COUNT(*) FROM pedidos o
           WHERE o.user_id = a.user_id AND o.estado = 'confirmado'
             AND o.creado_en >= a.asignado_en AND o.creado_en < a.asignado_en + INTERVAL '30' DAY) AS pedidos_30,
         CASE WHEN EXISTS (
           SELECT 1 FROM pedidos o
            WHERE o.user_id = a.user_id AND o.estado = 'confirmado' AND o.vertical = 'restaurantes'
              AND o.creado_en < a.asignado_en + INTERVAL '28' DAY)
         THEN 1 ELSE 0 END AS restaurantes,
         CASE WHEN EXISTS (
           SELECT 1 FROM pedidos o
            WHERE o.user_id = a.user_id AND o.estado = 'confirmado' AND o.vertical = 'turbo'
              AND o.creado_en >= a.asignado_en AND o.creado_en < a.asignado_en + INTERVAL '28' DAY)
         THEN 1 ELSE 0 END AS turbo
  FROM asignaciones a
  CROSS JOIN parametros x
)
SELECT grupo,
       SUM(cumplio_30) AS personas_30d,
       AVG(CASE WHEN cumplio_30 = 1 THEN CAST(pedidos_30 AS DOUBLE PRECISION) END) AS pedidos_30d_promedio,
       VAR_SAMP(CASE WHEN cumplio_30 = 1 THEN CAST(pedidos_30 AS DOUBLE PRECISION) END) AS pedidos_30d_varianza,
       SUM(cumplio_28 * restaurantes) AS clientes_restaurantes,
       SUM(cumplio_28 * restaurantes * turbo) AS con_turbo
FROM por_persona
GROUP BY grupo
ORDER BY grupo;
```

### `h3`: "¿Encontraste lo que buscabas?"

```sql
-- consulta: h3
WITH parametros (corte) AS (
  VALUES (TIMESTAMP WITH TIME ZONE '2027-04-02 12:00:00-03:00')
)
SELECT a.grupo,
       COUNT(*) AS respondidas,
       SUM(CASE WHEN r.respuesta = 'si' THEN 1 ELSE 0 END) AS si,
       SUM(CASE WHEN r.respuesta = 'en_parte' THEN 1 ELSE 0 END) AS en_parte,
       SUM(CASE WHEN r.respuesta = 'no' THEN 1 ELSE 0 END) AS respuesta_no,
       COUNT(DISTINCT r.user_id) AS personas
FROM respuestas_encuesta r
JOIN asignaciones a ON a.user_id = r.user_id AND a.asignado_en <= r.respondida_en
CROSS JOIN parametros x
WHERE r.pregunta = 'p1' AND r.respondida_en <= x.corte
GROUP BY a.grupo
ORDER BY a.grupo;
```

### `adopcion`: adopción, apagado y silencio

```sql
-- consulta: adopcion
WITH parametros (corte) AS (
  VALUES (TIMESTAMP WITH TIME ZONE '2027-04-02 12:00:00-03:00')
),
por_persona AS (
  SELECT a.user_id, a.grupo,
         CASE WHEN EXISTS (
           SELECT 1 FROM eventos_asistente e
            WHERE e.user_id = a.user_id AND e.tipo IN ('abrio', 'busco', 'acepto_oferta')
              AND e.creado_en >= a.asignado_en AND e.creado_en <= x.corte)
         THEN 1 ELSE 0 END AS uso,
         CASE WHEN EXISTS (  -- su último cambio desde la asignación fue ocultarlo
           SELECT 1 FROM eventos_asistente v
            WHERE v.user_id = a.user_id AND v.tipo = 'oculto'
              AND v.creado_en >= a.asignado_en AND v.creado_en <= x.corte
              AND NOT EXISTS (
                SELECT 1 FROM eventos_asistente w
                 WHERE w.user_id = v.user_id AND w.tipo IN ('oculto', 'mostro')
                   AND w.creado_en > v.creado_en AND w.creado_en <= x.corte))
         THEN 1 ELSE 0 END AS oculto,
         CASE WHEN EXISTS (
           SELECT 1 FROM eventos_asistente q
            WHERE q.user_id = a.user_id AND q.tipo = 'silencio'
              AND q.creado_en >= a.asignado_en AND q.creado_en <= x.corte)
         THEN 1 ELSE 0 END AS silencio
  FROM asignaciones a
  CROSS JOIN parametros x
)
SELECT grupo,
       COUNT(*) AS personas,
       SUM(uso) AS usaron,
       SUM(oculto) AS ocultos,
       SUM(silencio) AS silenciaron
FROM por_persona
GROUP BY grupo
ORDER BY grupo;
```

### `resguardos`: cancelaciones, reclamos y conversión al primer pedido

```sql
-- consulta: resguardos
WITH parametros (corte) AS (
  VALUES (TIMESTAMP WITH TIME ZONE '2027-04-02 12:00:00-03:00')
),
por_persona AS (  -- solo quien ya cumplió sus 30 días
  SELECT a.user_id, a.grupo,
         (SELECT COUNT(*) FROM pedidos o
           WHERE o.user_id = a.user_id
             AND o.creado_en >= a.asignado_en AND o.creado_en < a.asignado_en + INTERVAL '30' DAY) AS hechos,
         (SELECT COUNT(*) FROM pedidos o
           WHERE o.user_id = a.user_id AND o.estado = 'cancelado'
             AND o.creado_en >= a.asignado_en AND o.creado_en < a.asignado_en + INTERVAL '30' DAY) AS cancelados,
         (SELECT COUNT(*) FROM reclamos r
           WHERE r.user_id = a.user_id
             AND r.creado_en >= a.asignado_en AND r.creado_en < a.asignado_en + INTERVAL '30' DAY) AS reclamos,
         CASE WHEN EXISTS (
           SELECT 1 FROM pedidos o
            WHERE o.user_id = a.user_id AND o.estado = 'confirmado'
              AND o.creado_en >= a.asignado_en AND o.creado_en < a.asignado_en + INTERVAL '30' DAY)
         THEN 1 ELSE 0 END AS con_pedido
  FROM asignaciones a
  CROSS JOIN parametros x
  WHERE a.asignado_en + INTERVAL '30' DAY <= x.corte
)
SELECT grupo,
       COUNT(*) AS personas,
       SUM(hechos) AS pedidos_hechos,
       SUM(cancelados) AS pedidos_cancelados,
       AVG(CAST(cancelados AS DOUBLE PRECISION)) AS cancelados_promedio,
       VAR_SAMP(CAST(cancelados AS DOUBLE PRECISION)) AS cancelados_varianza,
       AVG(CAST(reclamos AS DOUBLE PRECISION)) AS reclamos_promedio,
       VAR_SAMP(CAST(reclamos AS DOUBLE PRECISION)) AS reclamos_varianza,
       SUM(con_pedido) AS con_pedido
FROM por_persona
GROUP BY grupo
ORDER BY grupo;
```

## 15. Errores típicos

- **Contar expuestas en vez de asignadas.** Todas las hipótesis se cuentan por intención de tratar, sobre todas las asignadas. Quedarse con quienes vieron una oferta o usaron a Mochi compara a quien se eligió sola con un control que no tuvo esa elección. La parte expuesta solo sirve para dividir la diferencia ya calculada ([sección 4](#4-las-fórmulas-estadísticas)).
- **Mezclar poblaciones.** Cada grupo tiene que salir de la misma población elegible (una sola vertical en M−1) y del mismo sorteo. No sumar personas que ya combinan verticales, cuentas de prueba, ni personas asignadas por otro camino. En el MVP, los datos simulados y los del prototipo nunca se mezclan (`source`); en Rappi, lo mismo con cualquier tráfico que no sea el del piloto.
- **Ventanas que se pisan o se mueven.** Cada ventana parte de `asignado_en`, no de la fecha de lectura ni de la primera oferta. La H1 usa el mes calendario M+1, la H2 y "suma una vertical" 28 días, la frecuencia y los resguardos 30 días: no intercambiarlas. Quien no cumplió la ventana no entra; no se cuenta como cero.
- **Doble conteo de sesiones.** Todas las métricas son por persona, salvo la H3 (por respuesta). Un evento repetido (la Home pide la misma oferta varias veces, la app reintenta un envío) no suma: los `EXISTS` cuentan a la persona una vez. En la H3, si la tabla de respuestas puede traer duplicados del mismo envío, se quitan antes (en el MVP, el id del evento del cliente lo impide).
- **Leer antes de tiempo.** Mirar a medio camino y parar cuando aparece algo aumenta los falsos positivos. Se lee una vez ([sección 3](#el-corte-de-lectura)). Durante el piloto solo se revisa la mecánica ([sección 17](#17-qué-decide-cada-resultado)).
- **El estado del pedido al leer.** Un pedido se cancela después de hecho: con el estado de hoy y no el del día del pedido, un pedido cancelado deja de contar. Hay que leer después de que se cierren las cancelaciones de los últimos días de la ventana.
- **La hora.** Los meses en hora de Chile; con UTC, las asignaciones de la noche del último día del mes caen en el mes siguiente.
- **Un control que no es "Mochi apagado".** Si el control ve la mascota, su buscador o alguna oferta de Mochi, la comparación mide otra cosa. La adopción del control debe ser 0.

## 16. Lista de verificación antes de encender el piloto

- [ ] **Hito 0 cumplido:** en la prueba con 5 personas, 3 de 5 o más entienden el "¿Por qué?" y a lo más 1 se molesta con Mochi ([prueba-usuarios.md](prueba-usuarios.md)). Hasta entonces el control sigue en 0.
- [ ] **Población congelada:** la lista de elegibles de cada mes (una sola vertical en M−1) se arma antes de asignar, con la consulta `elegibles` o su equivalente.
- [ ] **Asignación:** al azar, una vez, estable por persona; el reparto (`OFFERS_CONTROL_PCT`, 10 o 50) decidido y anotado; `asignado_en` se guarda con hora exacta y significa lo mismo en los dos grupos.
- [ ] **El control es "Mochi apagado" completo:** sin la mascota, sin sus ofertas y con el buscador de siempre; conserva "Para ti", el orden de la Home y la P1 ([plan-piloto.md](plan-piloto.md#el-control-mochi-apagado)).
- [ ] **Eventos en los dos grupos:** la oferta retenible del servidor (retenida en control, elegible en tratamiento, de los mismos momentos), las respuestas de la P1 y, en tratamiento, abrir, buscar, aceptar, ocultar, traer de vuelta y silenciar. Probado con cuentas de prueba de cada grupo antes de abrirlo a personas.
- [ ] **Pedido confirmado y reclamo definidos** igual para los dos grupos, con el estado al leer.
- [ ] **Bases y tamaños:** la retención de la población con la definición de la H1 (algún pedido en M0+2 de quien pidió en una sola vertical en M0) y la tasa de Restaurantes → Turbo en 28 días; con ellas, el mínimo por grupo ([sección 4](#4-las-fórmulas-estadísticas) y [plan-piloto.md](plan-piloto.md#qué-haría-falta-para-medirlo)). Si un mes no alcanza, se asigna un segundo mes.
- [ ] **Meses de asignación y fecha de lectura** fijados (el fin del M+1 de la última cohorte o, si es más tarde, la última asignación más 30 días).
- [ ] **Tolerancias fijadas por Rappi** (el plan no las fija): cuánto pueden empeorar los resguardos y cuánto pueden subir ocultar y silenciar antes de revisar o detener, y si eso se mira solo al final o también durante el piloto.
- [ ] **Análisis declarado:** este documento y [plan-piloto.md](plan-piloto.md), sin cambios después de encender. Las consultas corridas una vez en vacío, para ver que funcionan con las tablas de Rappi, sin leer resultados.

## 17. Qué decide cada resultado

Con los hitos y metas de [plan-piloto.md](plan-piloto.md) y [prueba-usuarios.md](prueba-usuarios.md); sin umbrales nuevos. Donde el plan no fija un número, lo dice.

| Cuándo | Resultado | Qué decide |
|---|---|---|
| Antes de encender | Hito 0 no se cumple | No encender: arreglar lo que dice la tabla de la prueba con usuarios y repetirla |
| Durante (solo la mecánica, sin mirar resultados) | El reparto real se aleja del declarado, la adopción del control no es 0 o faltan los eventos de un grupo | **Ajustar**: la mecánica falla; arreglarla antes de seguir asignando |
| Al leer | Un grupo bajo su mínimo | No es concluyente: no se decide. Si fue por tamaño, se asigna un segundo mes ([plan-piloto.md](plan-piloto.md#en-quiénes-con-qué-reparto-y-cuánto-dura)) |
| Al leer | La parte expuesta sale distinta entre los grupos | **Ajustar**: algo falla en cómo se cuenta la exposición; no dividir por ella hasta entenderlo |
| Al leer | H1 o H2 (Restaurantes → Turbo) con el IC entero sobre 0 y la diferencia en la meta o más (+2 puntos; tratamiento ≥ 1,1 × control), con los resguardos dentro de lo tolerado | **Seguir**: se cumple la meta |
| Al leer | IC entero sobre 0 pero la diferencia bajo la meta | Hay efecto, menor que la meta. Rappi decide si le basta (seguir) o qué cambiar (ajustar); el plan no fija un número intermedio |
| Al leer | Cada grupo en su mínimo y el IC cruza el 0 | No se ve un efecto del tamaño de la meta: **ajustar** y volver a probar. No prueba que no haya un efecto menor |
| Al leer | IC entero bajo 0 en la H1 o la H2 | **Detener**: con Mochi baja la retención o la venta cruzada |
| Al leer | H3: p de una cola < 0,05 | Más personas encuentran lo que buscan con Mochi. Sin umbral: acompaña a la H1 y la H2, no decide sola |
| Al leer o durante, según lo que fijó Rappi | Ocultar o silenciar suben en tratamiento | Alerta: Mochi molesta aunque la retención no lo muestre. **Ajustar** (cuándo y cuánto habla). El plan no fija cuánto es demasiado |
| Al leer o durante, según lo que fijó Rappi | Un resguardo empeora más de lo tolerado | **Ajustar** o **detener**, según la tolerancia que Rappi fijó antes de empezar |

## 18. Cómo se probaron estas consultas

El 14-11-2026, sobre una base temporal propia (`mochi_spec_tmp`, PostgreSQL 17, borrada al final), con las cinco tablas del esquema y filas inventadas con casos borde: asignaciones a medianoche del fin de mes en hora de Chile, pedidos justo en el borde de cada ventana, pedidos cancelados, pedidos de Turbo anteriores a la asignación, clientes de Restaurantes de antes y de dentro de la ventana, una cohorte con M+1 sin terminar, ofertas de "Muéstrame algo nuevo" (que no cuentan), respuestas anteriores a la asignación y de la P3, ocultar y traer de vuelta en los dos órdenes, y personas que no cumplieron sus 28 o 30 días. Cada consulta se copió tal cual de este documento y su resultado se comparó con un cálculo independiente en Python sobre las mismas filas: coincidieron todas las columnas de las seis consultas. Las fórmulas de la [sección 4](#4-las-fórmulas-estadísticas), escritas aparte, dan lo mismo que `power.py`, y reproducen las tablas de tamaños de [plan-piloto.md](plan-piloto.md#qué-haría-falta-para-medirlo).
