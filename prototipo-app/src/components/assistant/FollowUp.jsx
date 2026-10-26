const MAX_PEOPLE = 40 // lo que entiende la API (agent/understand.py: MAX_PEOPLE)
// Lo que ya dice que no lleva carne: «Sin carne» no se ofrece de nuevo.
const MEATLESS = /\b(?:sin carne|vegetarian[oa]s?|vegan[oa]s?|veggies?)\b/

/**
 * Los refinamientos de una respuesta de Mochi (`conversation`, el estado que devolvió la API), como chips de un toque:
 * «Más barato» (si no está ya ordenada así), «Otra opción», «Sin carne» en lo de restaurantes (si no lo dice ya) y, con
 * una ocasión o una cantidad de personas, «Para N personas» (dos más). Cada uno manda a la API la frase que su
 * seguimiento ya entiende (`agent/understand.py: _follow_up`) con el turno anterior: la persona no escribe nada.
 * Ninguno bajo una respuesta de salud ni sin productos: ahí Mochi no propone nada por su cuenta.
 */
export function followUpChips(message) {
  const conversation = message?.conversation
  if (!conversation || message.health || !message.products?.length) return []
  const chips = []
  if (conversation.order !== 'barato') chips.push({ label: 'Más barato', message: 'más barato' })
  chips.push({ label: 'Otra opción', message: 'otra opción' })
  if (conversation.vertical === 'restaurantes' && !MEATLESS.test(conversation.query ?? ''))
    chips.push({ label: 'Sin carne', message: 'sin carne' })
  const people = (conversation.people ?? 2) + 2
  if ((conversation.people || conversation.occasion) && people <= MAX_PEOPLE)
    chips.push({ label: `Para ${people} personas`, message: `para ${people} personas` })
  return chips
}

/** Debajo de los productos de la respuesta: sus refinamientos, sin un campo para escribirle a Mochi. */
export default function FollowUp({ message, onRefine, disabled = false }) {
  const chips = followUpChips(message)
  if (!chips.length) return null
  return (
    <div className="assistant-chips agent-follow-chips" role="group" aria-label="Refinar">
      {chips.map((chip, i) => (
        <button
          key={chip.label}
          type="button"
          className="assistant-chip agent-follow-chip"
          disabled={disabled}
          style={{ animationDelay: `${120 + i * 55}ms` }}
          onClick={() => onRefine(chip)}
        >
          {chip.label}
        </button>
      ))}
    </div>
  )
}
