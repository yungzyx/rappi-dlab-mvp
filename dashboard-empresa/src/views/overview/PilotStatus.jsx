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
 * pide el mínimo, solo el plazo. En la H2 no todas cuentan (solo quien pide en Restaurantes) y el texto lo dice.
 */
function pending(row, experiment) {
  if (row.weeks === 0) {
    // En la H2 no toda persona asignada cuenta (solo quien pide en Restaurantes): puede faltar asignar a más.
    const caveat =
      row.id === 'H2' ? ' De ellas cuentan solo quienes piden en Restaurantes: pueden hacer falta más.' : ''
    return `Ya hay asignadas tantas personas como pide el mínimo: falta que pase su plazo (${wait(row, experiment)}).${caveat}`
  }
  const weeks = `${formatNumber(row.weeks)} ${row.weeks === 1 ? 'semana más' : 'semanas más'}`
  // La H3 cuenta respuestas, que valen apenas llegan: no hay plazo que esperar.
  if (row.id === 'H3') return `Al ritmo de respuestas de hoy, al menos ${weeks}.`
  return `Al ritmo de asignación de hoy, al menos ${weeks} de asignación, y después ${wait(row, experiment)}.`
}

/** Una línea en lugar del avance: por qué no hay qué mostrar. */
function PilotNote({ children }) {
  return (
    <p className="pilot-off">
      <Icon name="info" />
      <span>
        <strong>Estado del piloto:</strong> {children}
      </span>
    </p>
  )
}

/**
 * Estado del piloto, junto al enlace a las tres hipótesis: cuánto lleva cada una del mínimo de personas que pide el plan
 * para poder concluir y, si la API trae su ritmo (de asignación o de respuestas), cuántas semanas faltan como piso
 * (`pilot.js`). Con los simulados no hay piloto: sus grupos y sus diferencias los pone el generador (lo mismo que dicen
 * las hipótesis, "Simulado: sin veredicto"). Sin personas en un grupo, lo dice: no hay qué medir todavía. Con el control
 * apagado y grupos de antes, el avance de esos grupos, con una línea que dice que no entra nadie.
 */
export function PilotStatus({ source }) {
  const experiment = offersExperiment(useAnalytics('experimentos', source))
  if (!experiment || !hasHypotheses(experiment)) return null
  if (source === 'synthetic') {
    return <PilotNote>los grupos simulados no son un piloto: su avance se ve con el uso del MVP (Prototipo).</PilotNote>
  }
  const { on, assigning, rows } = pilotProgress(experiment)
  if (!on) {
    return (
      <PilotNote>
        {assigning
          ? 'un grupo todavía no tiene personas, todavía no hay qué medir.'
          : 'el grupo de control está apagado, todavía no hay qué medir.'}
      </PilotNote>
    )
  }
  return (
    <>
      {!assigning && (
        <PilotNote>
          no entran personas nuevas, el grupo de control está apagado. El avance es el de quienes ya tienen grupo.
        </PilotNote>
      )}
      <PilotProgress rows={rows} experiment={experiment} />
    </>
  )
}

function PilotProgress({ rows, experiment }) {
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
                {row.done ? 'Llegó al mínimo para concluir' : `${formatPct(Math.floor(row.share * 100), 0)} del mínimo`}
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
