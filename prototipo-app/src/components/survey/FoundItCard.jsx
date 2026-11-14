import { useId } from 'react'
import { AGENT_NAME } from '../../agent/name'
import { P1_ANSWERS, P3_ANSWERS } from '../../state/survey'
import { useFoundItSurvey } from './useFoundItSurvey'
import './found-it.css'

export const P1_TEXT = '¿Encontraste lo que buscabas?'
export const P3_TEXT = `¿Confías en las sugerencias de ${AGENT_NAME}?`

/**
 * La tarjeta de la pregunta in-app: el texto, sus respuestas como chips de un toque (sin texto libre) y una × para
 * cerrarla sin responder. Neutra a propósito (sin la mascota ni sus colores): la p1 tiene que leerse igual con Mochi y
 * sin él. No es un diálogo: no toma el foco ni tapa la pantalla, y se puede seguir usando la app con ella abierta.
 */
export function FoundItCard({ question, thanks = false, raised = false, onAnswer, onClose }) {
  const titleId = useId()
  const classes = ['found-it']
  if (raised) classes.push('is-raised')
  if (thanks)
    return (
      <section className={[...classes, 'is-thanks'].join(' ')} role="status">
        <p className="found-it-thanks">¡Gracias! Tu respuesta nos ayuda a mejorar.</p>
      </section>
    )
  const p3 = question === 'p3'
  return (
    <section className={classes.join(' ')} aria-labelledby={titleId}>
      <div className="found-it-head">
        <h2 id={titleId} className="found-it-title">
          {p3 ? P3_TEXT : P1_TEXT}
        </h2>
        <button type="button" className="found-it-close tap" aria-label="Cerrar sin responder" onClick={onClose}>
          ×
        </button>
      </div>
      <div className={p3 ? 'found-it-chips is-scale' : 'found-it-chips'} role="group" aria-labelledby={titleId}>
        {p3
          ? P3_ANSWERS.map((value) => (
              <button
                key={value}
                type="button"
                className="found-it-chip tap"
                aria-label={value === 1 ? '1, nada' : value === 5 ? '5, mucho' : String(value)}
                onClick={() => onAnswer(value)}
              >
                {value}
              </button>
            ))
          : P1_ANSWERS.map((option) => (
              <button key={option.id} type="button" className="found-it-chip tap" onClick={() => onAnswer(option.id)}>
                {option.label}
              </button>
            ))}
      </div>
      {p3 && (
        <p className="found-it-scale" aria-hidden="true">
          <span>Nada</span>
          <span>Mucho</span>
        </p>
      )}
    </section>
  )
}

/** La pregunta in-app en la pantalla de arriba (`screen`, con `depth` pantallas en la pila); `raised` con barra inferior. */
export default function FoundItSurvey({ screen, depth, raised }) {
  const { card, visible, answer, close } = useFoundItSurvey({ screen, depth })
  if (!card || !visible) return null
  return <FoundItCard question={card.question} thanks={card.thanks} raised={raised} onAnswer={answer} onClose={close} />
}
