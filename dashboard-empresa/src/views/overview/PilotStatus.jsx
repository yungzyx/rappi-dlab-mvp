import { Icon } from '../../components/Icon.jsx'
import { Meter } from '../../components/Meter.jsx'
import { formatNumber, formatPct } from '../../lib/format.js'
import { useAnalytics } from '../../lib/useAnalytics.js'
import { CONTROL, hasHypotheses, offersExperiment, TREATMENT } from '../experiments/hypotheses.js'
import { pilotProgress } from './pilot.js'

/** "120 de 871 en control": el grupo que va más atrás contra lo que pide el plan. */
function behind({ have, need }) {
  const group = have[CONTROL] / need[CONTROL] <= have[TREATMENT] / need[TREATMENT] ? CONTROL : TREATMENT
  return `${formatNumber(have[group])} de ${formatNumber(need[group])} en ${group}`
}

/** El plazo que tiene que pasar para que una persona asignada cuente en la hipótesis. */
const wait = (row, experiment) =>
  row.id === 'H1' ? 'el mes siguiente completo' : `${formatNumber(experiment.rest_a_turbo.dias)} días`

/**
 * Cuánto falta, como piso: las semanas de asignación y después el plazo; o, si ya están asignadas tantas personas como
 * pide el mínimo, solo el plazo (no todas cuentan para la hipótesis: por eso sigue siendo un piso).
 */
function pending(row, experiment) {
  if (row.weeks === 0) {
    return `Ya hay asignadas tantas personas como pide el mínimo: cuentan cuando pasa su plazo (${wait(row, experiment)}).`
  }
  const weeks = `${formatNumber(row.weeks)} ${row.weeks === 1 ? 'semana más' : 'semanas más'}`
  return `Al ritmo de asignación de hoy, al menos ${weeks} de asignación, y después ${wait(row, experiment)}.`
}

/**
 * Estado del piloto, junto al enlace a las tres hipótesis: cuánto lleva cada una del mínimo de personas que pide el plan
 * para poder concluir y, si la API trae el ritmo de asignación, cuántas semanas faltan como piso (`pilot.js`). Con el
 * grupo de control apagado, lo dice: no hay qué medir todavía.
 */
export function PilotStatus({ source }) {
  const experiment = offersExperiment(useAnalytics('experimentos', source))
  if (!experiment || !hasHypotheses(experiment)) return null
  const { on, rows } = pilotProgress(experiment)
  if (!on) {
    return (
      <p className="pilot-off">
        <Icon name="info" />
        <span>
          <strong>Estado del piloto:</strong> el grupo de control está apagado, todavía no hay qué medir.
        </span>
      </p>
    )
  }
  return (
    <dl className="pilot" aria-label="Estado del piloto: avance hacia el mínimo de personas de cada hipótesis">
      {rows.map((row) => (
        <div key={row.id}>
          <dt>
            <span className="pilot-id">{row.id}</span> {row.title}
          </dt>
          {row.share === null ? (
            <dd className="pilot-note">Todavía sin mínimo: falta el dato del grupo de control.</dd>
          ) : (
            <dd>
              <Meter value={row.share * 100} max={100} tone="brand" />
              <span className="pilot-note num">
                {row.done ? 'Llegó al mínimo para concluir' : `${formatPct(row.share * 100, 0)} del mínimo`}
                {!row.done && ` · ${behind(row)}`}
              </span>
              {row.weeks !== null && <span className="pilot-note">{pending(row, experiment)}</span>}
            </dd>
          )}
        </div>
      ))}
    </dl>
  )
}
