import { Async } from '../../components/Async.jsx'
import { Delta } from '../../components/Delta.jsx'
import { Icon } from '../../components/Icon.jsx'
import { ProvenanceBadge } from '../../components/ProvenanceBadge.jsx'
import { SourceNote } from '../../components/SourceNote.jsx'
import { formatPoints } from '../../lib/format.js'

// Cómo se llama la acción según de dónde salen los datos: solo la del dato de Rappi es una sugerencia; con datos
// simulados es un ejemplo de la mecánica y con los del prototipo, algo para revisar (ninguno de los dos es evidencia).
const ACTION_LABELS = {
  rappi: 'Acción sugerida',
  synthetic: 'Ejemplo de acción (datos simulados)',
  prototype: 'Para revisar en el MVP',
}

/**
 * Lo que dice una decisión (`decisions.js`): a la izquierda la cifra (si la hay) y su cambio; a la derecha el contexto y
 * la acción, rotulada según su fuente. Sin cifra, el texto ocupa todo el ancho.
 */
export function DecisionBody({ decision, source }) {
  if (!decision) return <p className="decision-context decision-empty">Sin datos suficientes en esta fuente.</p>
  const { figure, unit, context, delta, action } = decision
  return (
    <>
      {(figure || delta) && (
        <div className="decision-metric">
          {figure && (
            <p className="decision-figure">
              <strong>{figure}</strong>
              <span>{unit}</span>
            </p>
          )}
          {delta && <Delta value={delta.value} format={formatPoints} goodWhen={delta.goodWhen} suffix={delta.suffix} />}
        </div>
      )}
      <div className="decision-detail">
        <p className="decision-context">{context}</p>
        {action && (
          <p className="decision-action">
            <span>{ACTION_LABELS[source]}</span>
            {action}
          </p>
        )}
      </div>
    </>
  )
}

/**
 * Una pregunta de negocio del Resumen, como fila de una lista: la pregunta con su procedencia (y el rótulo del
 * prototipo, si lo es), la cifra y lo que la explica, y el enlace al detalle. Pregunta, procedencia y enlace se ven
 * mientras cargan los datos; el cuerpo (`children`) lee la API dentro de su propio <Async>, así un bloque caído no tumba
 * a los otros.
 */
export function DecisionCard({ id, question, badge, linkLabel, onOpen, children }) {
  return (
    <article className="decision" aria-labelledby={id}>
      <header className="decision-head">
        <h3 id={id}>{question}</h3>
        <div className="decision-provenance">
          <ProvenanceBadge kind={badge} />
          <SourceNote source={badge} />
        </div>
      </header>
      <div className="decision-body">
        <Async>{children}</Async>
      </div>
      <button type="button" className="text-button decision-link" onClick={onOpen}>
        {linkLabel}
        <Icon name="arrowRight" />
      </button>
    </article>
  )
}
