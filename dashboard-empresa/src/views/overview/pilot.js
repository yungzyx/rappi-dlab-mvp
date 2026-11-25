// Estado del piloto: cuánto lleva cada hipótesis del mínimo de personas que pide el plan de piloto para poder
// concluir y, con el ritmo de asignación, cuánto falta. Sale del experimento `ofertas_control` de
// /analytics/experimentos (los mínimos y el ritmo los calcula la API).
import { CONTROL, hypothesesMode, TREATMENT } from '../experiments/hypotheses.js'

const GROUPS = [TREATMENT, CONTROL]

const peopleOf = (rows, key) =>
  Object.fromEntries(GROUPS.map((group) => [group, 0]).concat(rows.map((row) => [row.variante, row[key] ?? 0])))

/** El mínimo por grupo: la API lo da por grupo ({tratamiento, control}) o igual para los dos (un número). */
const needOf = (minimum) => (typeof minimum === 'number' ? { [TREATMENT]: minimum, [CONTROL]: minimum } : minimum)

/**
 * Las semanas que faltan, como piso: lo que le falta a cada grupo dividido por las personas que le entran por semana
 * (`pace`), y manda el que más tarda. null sin mínimo, sin ritmo o si a un grupo que no llegó no le entra nadie. Es un
 * piso porque no toda persona asignada cuenta para la hipótesis (la H2 mira solo a quien pide en Restaurantes).
 */
function weeksLeft(have, need, pace) {
  if (!need || !pace) return null
  const each = GROUPS.map((group) => {
    const missing = need[group] - have[group]
    if (missing <= 0) return 0
    return pace[group] > 0 ? missing / pace[group] : Infinity
  })
  const slowest = Math.max(...each)
  return Number.isFinite(slowest) ? Math.ceil(slowest) : null
}

function progress(id, title, rows, key, minimum, pace) {
  const have = peopleOf(rows ?? [], key)
  const need = minimum === null || minimum === undefined ? null : needOf(minimum)
  // El grupo que va más atrás manda: los dos tienen que llegar.
  const share = need ? Math.min(...GROUPS.map((group) => (need[group] > 0 ? have[group] / need[group] : 1))) : null
  const done = share !== null && share >= 1
  return {
    id,
    title,
    have,
    need,
    share: share === null ? null : Math.min(1, share),
    done,
    weeks: done ? null : weeksLeft(have, need, pace),
  }
}

/**
 * { on, rows }: `on` es falso si el grupo de control está apagado o un grupo no tiene personas (no hay qué medir).
 * `rows`: H1, H2 y H3, cada una con cuántas personas lleva cada grupo (`have`), cuántas pide el plan (`need`, o null
 * si todavía no se puede calcular), la parte cubierta por el grupo que va más atrás (`share`, 0 a 1), si llegó y, si
 * no, las semanas que faltan como piso al ritmo de asignación (`weeks`, o null si no se puede estimar).
 */
export function pilotProgress(experiment) {
  const on = experiment.control_pct > 0 && hypothesesMode(experiment) === 'grupos'
  const { retencion, rest_a_turbo: turbo, encuesta } = experiment
  // Personas asignadas por semana a cada grupo (una foto grabada antes del 25-11 no lo trae).
  const pace = experiment.ritmo?.por_semana ?? null
  return {
    on,
    rows: [
      progress('H1', 'Retención M+1', retencion?.variantes, 'personas', retencion?.minimo, pace),
      progress('H2', 'Restaurantes → Turbo', turbo?.variantes, 'personas', turbo?.minimo, pace),
      // La H3 avanza con respuestas, no con asignaciones: sin ritmo propio, no se estima.
      progress('H3', '"¿Encontraste lo que buscabas?"', encuesta?.variantes, 'respondidas', encuesta?.minimo, null),
    ],
  }
}
