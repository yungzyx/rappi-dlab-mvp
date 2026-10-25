import { useId, useState } from 'react'
import './offer-why.css'

/**
 * «¿Por qué?» de una oferta del agente: un botón que despliega la razón que trae la API (`reason.text`). Sin texto no
 * pinta nada: una oferta sin razón se muestra como antes. `onToggle(abierto)` avisa a quien lo aloja cuando se abre o
 * se cierra (el globo de la Home no se va solo mientras se lee).
 */
export default function OfferWhy({ reason, onToggle }) {
  const [open, setOpen] = useState(false)
  const id = useId()
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
