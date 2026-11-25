// Estado del piloto: cuánto lleva cada hipótesis del mínimo de personas que pide el plan de piloto para poder
// concluir. Sale del experimento `ofertas_control` de /analytics/experimentos (los mínimos los calcula la API).
import { CONTROL, hypothesesMode, TREATMENT } from '../experiments/hypotheses.js'

const GROUPS = [TREATMENT, CONTROL]

const peopleOf = (rows, key) =>
  Object.fromEntries(GROUPS.map((group) => [group, 0]).concat(rows.map((row) => [row.variante, row[key] ?? 0])))

/** El mínimo por grupo: la API lo da por grupo ({tratamiento, control}) o igual para los dos (un número). */
const needOf = (minimum) => (typeof minimum === 'number' ? { [TREATMENT]: minimum, [CONTROL]: minimum } : minimum)

function progress(id, title, rows, key, minimum) {
  const have = peopleOf(rows ?? [], key)
  const need = minimum === null || minimum === undefined ? null : needOf(minimum)
  // El grupo que va más atrás manda: los dos tienen que llegar.
  const share = need ? Math.min(...GROUPS.map((group) => (need[group] > 0 ? have[group] / need[group] : 1))) : null
  return {
    id,
    title,
    have,
    need,
    share: share === null ? null : Math.min(1, share),
    done: share !== null && share >= 1,
  }
}

/**
 * { on, rows }: `on` es falso si el grupo de control está apagado o un grupo no tiene personas (no hay qué medir).
 * `rows`: H1, H2 y H3, cada una con cuántas personas lleva cada grupo (`have`), cuántas pide el plan (`need`, o null
 * si todavía no se puede calcular), la parte cubierta por el grupo que va más atrás (`share`, 0 a 1) y si llegó.
 */
export function pilotProgress(experiment) {
  const on = experiment.control_pct > 0 && hypothesesMode(experiment) === 'grupos'
  const { retencion, rest_a_turbo: turbo, encuesta } = experiment
  return {
    on,
    rows: [
      progress('H1', 'Retención M+1', retencion?.variantes, 'personas', retencion?.minimo),
      progress('H2', 'Restaurantes → Turbo', turbo?.variantes, 'personas', turbo?.minimo),
      progress('H3', '"¿Encontraste lo que buscabas?"', encuesta?.variantes, 'respondidas', encuesta?.minimo),
    ],
  }
}
