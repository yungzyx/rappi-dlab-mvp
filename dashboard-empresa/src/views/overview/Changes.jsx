import { EmptyState } from '../../components/States.jsx'
import { Icon } from '../../components/Icon.jsx'
import { useAnalyticsMany } from '../../lib/useAnalytics.js'
import { notableChanges } from './changes.js'
import { COMPARE_WEEKS } from './weekly.js'

// El juicio también en texto: el color no llega al lector de pantalla ni a quien no distingue rojo de verde.
const JUDGMENT = { bad: ' (empeora)', good: ' (mejora)', muted: '' }

/**
 * "Qué cambió": hasta 4 cambios para mirar primero, de más a menos urgente (`changes.js`). Cada uno con su cifra, cuánto
 * se movió y, si su detalle está en otra vista, un botón que lleva ahí.
 */
export function Changes({ source, onNavigate }) {
  const [weekly, kpis, trends, opportunities] = useAnalyticsMany(['weekly', 'kpis', 'trends', 'opportunities'], source)
  const items = notableChanges({ weekly, asOf: kpis.as_of, trends, opportunities })
  if (!items.length) {
    return (
      <EmptyState title="Nada que destacar" inline>
        Ningún indicador se movió lo suficiente frente a hace {COMPARE_WEEKS} semanas.
      </EmptyState>
    )
  }
  return (
    <ul className="changes">
      {items.map((item) => (
        <li key={item.key} className={`change change--${item.tone}`}>
          <span className="change-mark" aria-hidden="true">
            <Icon name={item.direction} />
          </span>
          <div className="change-text">
            <p className="change-title">{item.title}</p>
            <p className="change-figure num">{item.figure}</p>
            <p className="change-detail">
              <strong className="change-delta num">{item.change}</strong> {item.detail}
              <span className="visually-hidden">{JUDGMENT[item.tone]}</span>
            </p>
          </div>
          {item.target && (
            <button
              type="button"
              className="text-button change-link"
              aria-label={`Ver el detalle: ${item.title}`}
              onClick={() => onNavigate(...item.target)}
            >
              Ver
              <Icon name="arrowRight" />
            </button>
          )}
        </li>
      ))}
    </ul>
  )
}
