import { useState } from 'react'
import { AGENT_NAME } from '../../agent/name'

const MAX_PEOPLE = 40 // lo que entiende la API (agent/understand.py: MAX_PEOPLE)

/**
 * Las sugerencias para seguir una respuesta de Mochi (`conversation`, el estado que devolvió la API): «Más barato» (si
 * no está ya ordenada así), «Otra opción» y, con una ocasión o una cantidad de personas, «Para N personas» (dos más).
 * Ninguna bajo una respuesta de salud ni sin productos: ahí Mochi no propone nada por su cuenta.
 */
export function followUpChips(message) {
  const conversation = message?.conversation
  if (!conversation || message.health || !message.products?.length) return []
  const chips = []
  if (conversation.order !== 'barato') chips.push({ label: 'Más barato', message: 'más barato' })
  chips.push({ label: 'Otra opción', message: 'otra opción' })
  const people = (conversation.people ?? 2) + 2
  if ((conversation.people || conversation.occasion) && people <= MAX_PEOPLE)
    chips.push({ label: `Para ${people} personas`, message: `para ${people} personas` })
  return chips
}

function SendIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M4 12h14M13 6l6 6-6 6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/**
 * Debajo de la respuesta de Mochi: sus sugerencias para seguir y un campo que siempre le habla a Mochi (el buscador de
 * arriba busca lo que no parece pregunta, y «sin carne» no lo parece). Lo que se manda va con el pedido anterior.
 */
export default function FollowUp({ message, onSend, disabled = false }) {
  const [text, setText] = useState('')
  const chips = followUpChips(message)
  const submit = (event) => {
    event.preventDefault()
    const clean = text.trim()
    if (!clean || disabled) return
    setText('')
    onSend(clean)
  }
  return (
    <div className="agent-follow">
      {chips.length > 0 && (
        <div className="assistant-chips agent-follow-chips">
          {chips.map((chip, i) => (
            <button
              key={chip.label}
              type="button"
              className="assistant-chip agent-follow-chip"
              disabled={disabled}
              style={{ animationDelay: `${120 + i * 55}ms` }}
              onClick={() => onSend(chip.message)}
            >
              {chip.label}
            </button>
          ))}
        </div>
      )}
      <form className="agent-follow-form" onSubmit={submit}>
        <input
          type="text"
          aria-label={`Sigue la conversación con ${AGENT_NAME}`}
          placeholder={`Sigue con ${AGENT_NAME}: «sin carne», «para 10»…`}
          value={text}
          maxLength={500}
          enterKeyHint="send"
          disabled={disabled}
          onChange={(event) => setText(event.target.value)}
        />
        <button type="submit" className="agent-follow-send tap" aria-label="Enviar" disabled={disabled || !text.trim()}>
          <SendIcon />
        </button>
      </form>
    </div>
  )
}
