// Estado del piloto: cuánto lleva cada hipótesis del mínimo de personas (o de respuestas, en la H3) que pide el plan de
// piloto para poder concluir y, con su ritmo, cuánto falta. Sale del experimento `ofertas_control` de
// /analytics/experimentos (los mínimos y los ritmos, `ritmo` y `ritmo_encuesta`, los calcula la API).
import { CONTROL, hypothesesMode, TREATMENT } from '../experiments/hypotheses.js'

const GROUPS = [TREATMENT, CONTROL]

const peopleOf = (rows, key) =>
  Object.fromEntries(GROUPS.map((group) => [group, 0]).concat(rows.map((row) => [row.variante, row[key] ?? 0])))

/** El mínimo por grupo: la API lo da por grupo ({tratamiento, control}) o igual para los dos (un número). */
const needOf = (minimum) => (typeof minimum === 'number' ? { [TREATMENT]: minimum, [CONTROL]: minimum } : minimum)

/**
 * Las semanas de asignación que faltan, como piso: las personas que a cada grupo le falta asignar (el mínimo menos las
 * ya asignadas, `assigned`) divididas por las que le entran por semana (`pace`); manda el que más tarda. Cuenta contra
 * las asignadas y no contra las que ya cumplieron su plazo (`have`): una persona asignada que todavía no madura va a
 * contar sin que entre nadie más. 0 si ya están asignadas tantas como pide el mínimo (falta solo que pase su plazo);
 * null sin mínimo, sin ritmo o si a un grupo al que le falta no le entra nadie. Es un piso porque no toda persona
 * asignada cuenta para la hipótesis (la H2 mira solo a quien pide en Restaurantes).
 */
function weeksLeft(assigned, need, pace) {
  if (!need || !pace) return null
  const each = GROUPS.map((group) => {
    const missing = need[group] - assigned[group]
    if (missing <= 0) return 0
    return pace[group] > 0 ? missing / pace[group] : Infinity
  })
  const slowest = Math.max(...each)
  return Number.isFinite(slowest) ? Math.ceil(slowest) : null
}

function progress(id, title, rows, key, minimum, pace, assigned) {
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
    weeks: done ? null : weeksLeft(assigned, need, pace),
  }
}

/**
 * { on, assigning, rows }: `on` es falso si un grupo no tiene personas (no hay qué medir); `assigning`, si entran
 * personas nuevas a los grupos (el control encendido, `control_pct` > 0). Con el control apagado y grupos de antes,
 * se sigue midiendo a quienes ya tienen grupo, sin ritmo de asignación: las semanas de la H1 y la H2 quedan en null
 * (o en 0, si ya están asignadas las que pide el mínimo).
 * `rows`: H1, H2 y H3, cada una con cuántas personas (respuestas, en la H3) lleva cada grupo (`have`), cuántas pide el
 * plan (`need`, o null si todavía no se puede calcular), la parte cubierta por el grupo que va más atrás (`share`, 0 a
 * 1), si llegó y, si no, las semanas que faltan como piso (`weeks`: 0 si ya están asignadas las que hacen falta y solo
 * queda esperar su plazo; null si no se puede estimar). En la H1 y la H2 son semanas de asignación; en la H3, de
 * respuestas, que cuentan apenas llegan (sin plazo que esperar).
 */
export function pilotProgress(experiment) {
  const on = hypothesesMode(experiment) === 'grupos'
  const assigning = experiment.control_pct > 0
  const { retencion, rest_a_turbo: turbo, encuesta } = experiment
  // Personas asignadas por semana a cada grupo (una foto grabada antes del 25-11 no lo trae) y las ya asignadas. Con el
  // control apagado no entra nadie: ritmo 0.
  const pace = assigning ? (experiment.ritmo?.por_semana ?? null) : { [TREATMENT]: 0, [CONTROL]: 0 }
  const assigned = peopleOf(experiment.variantes, 'personas')
  // Respuestas a la p1 por semana a cada grupo (una foto grabada antes del 25-11 no lo trae).
  const surveyPace = experiment.ritmo_encuesta?.por_semana ?? null
  const answered = peopleOf(encuesta?.variantes ?? [], 'respondidas')
  return {
    on,
    assigning,
    rows: [
      progress('H1', 'Retención M+1', retencion?.variantes, 'personas', retencion?.minimo, pace, assigned),
      progress('H2', 'Restaurantes → Turbo', turbo?.variantes, 'personas', turbo?.minimo, pace, assigned),
      // La H3 avanza con respuestas, no con asignaciones: su ritmo es el de las respuestas.
      progress(
        'H3',
        '"¿Encontraste lo que buscabas?"',
        encuesta?.variantes,
        'respondidas',
        encuesta?.minimo,
        surveyPace,
        answered,
      ),
    ],
  }
}
