import { useId, useState } from 'react'
import { basisKinds } from '../../api/suggestions'
import { useEvents } from '../../state/EventsContext'
import './offer-why.css'

/**
 * "¿Por qué?" de una oferta del agente: un botón que despliega la razón que trae la API (`reason.text`). Sin texto no
 * pinta nada: una oferta sin razón se muestra como antes. `onToggle(abierto)` avisa a quien lo aloja cuando se abre o
 * se cierra (el globo de la Home no se va solo mientras se lee). Con `origin` (el de la oferta, `agent-<momento>`),
 * cada vez que se abre queda un `offer_why_open` con el concepto de la razón y los tipos de su `basis`, como la
 * mostrada (`noteShown`): así la prueba con usuarios sabe si se leyó. Sin `origin` (el porqué de los accesos de la
 * Home, que no es una oferta), no se anota.
 */
export default function OfferWhy({ reason, origin, onToggle }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const events = useEvents()
  if (!reason?.text) return null
  return (
    <div className="offer-why">
      <button
        type="button"
        className="offer-why-toggle tap"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => {
          setOpen(!open)
          onToggle?.(!open)
          if (!open && origin) {
            const basis = basisKinds(reason)
            events.track('offer_why_open', {
              origin,
              ...(reason.concept ? { concept_id: reason.concept } : {}),
              ...(basis ? { payload: { basis } } : {}),
            })
          }
        }}
      >
        ¿Por qué?
      </button>
      {open && (
        <span id={id} className="offer-why-text">
          {reason.text}
        </span>
      )}
    </div>
  )
}
