import { useState } from 'react'
import { AGENT_NAME } from '../../agent/name'
import { offer } from '../../api/agent'
import { noteShown } from '../../api/suggestions'
import { userId } from '../../api/user'
import Mascot from '../../components/assistant/Mascot'
import OfferWhy from '../../components/assistant/OfferWhy'
import { useAddToCart } from '../../hooks/useAddToCart'
import { VERTICAL_NAMES } from '../../data/verticals'
import { useCart } from '../../state/CartContext'
import { useDemo } from '../../state/DemoContext'
import { useEvents } from '../../state/EventsContext'
import { useProfile } from '../../state/ProfileContext'

/**
 * «¿Me falta algo?» en el checkout (prototipo final): solo si la persona lo pide, se consulta la oferta `checkout` de
 * El agente con lo que lleva el carro. Si hay oferta, sugiere UNA cosa (con su razón, «Agregar» y «Deshacer»); si no (204),
 * dice que el carro está completo; si la API no contesta, no dice nada. Nada aparece por su cuenta.
 */
export default function CheckoutSuggestion() {
  const demo = useDemo()
  const cart = useCart()
  const profile = useProfile()
  const events = useEvents()
  const { add, remove } = useAddToCart()
  const [asking, setAsking] = useState(false)
  const [picked, setPicked] = useState(null) // la oferta pedida: { text, product }; queda fija aunque cambie el carro
  const [complete, setComplete] = useState(false) // la API no tiene nada que agregar
  const [added, setAdded] = useState(null)

  if (!demo?.isFinal) return null
  if (complete)
    return (
      <p className="checkout-ask" role="status">
        <Mascot size={28} badge />
        Tu carrito está completo
      </p>
    )

  if (!picked) {
    const lines = cart.items
      .filter(({ product }) => product.entityId != null)
      .map(({ product }) => ({ entity_type: product.entityType, entity_id: product.entityId }))
    if (!lines.length) return null
    const ask = async () => {
      setAsking(true)
      try {
        const made = await offer('checkout', { cart: lines }, { userId: userId() })
        if (!made?.products.length) return setComplete(true)
        const [product] = made.products
        noteShown(events.track, [product], {
          origin: `agent-${made.moment}`,
          concept: made.reason?.concept,
          generation: profile.resets,
        })
        setPicked({ text: made.text, product, reason: made.reason })
      } catch {
        // Sin respuesta, el agente no dice nada: el botón sigue ahí para volver a pedir.
      } finally {
        setAsking(false)
      }
    }
    return (
      <button type="button" className="checkout-ask tap" disabled={asking} onClick={ask}>
        <Mascot size={28} badge />
        ¿Me falta algo? Pregúntale a {AGENT_NAME}
      </button>
    )
  }

  const { text, product, reason } = picked
  return (
    <section className="checkout-suggestion" aria-label={`Sugerencia de ${AGENT_NAME}`}>
      <Mascot size={40} badge mood="wave" />
      <div className="checkout-suggestion-body">
        <p className="checkout-suggestion-reason">{text}</p>
        <OfferWhy reason={reason} />
        <p className="checkout-suggestion-product">
          {product.name} · {product.price} · {VERTICAL_NAMES[product.vertical] ?? product.vertical}
          {product.ageRestricted && (
            <span className="checkout-suggestion-age" aria-label="Solo mayores de 18">
              +18
            </span>
          )}
        </p>
        {added ? (
          <button
            type="button"
            className="checkout-suggestion-action tap"
            onClick={() => {
              remove(added)
              setAdded(null)
            }}
          >
            Deshacer
          </button>
        ) : (
          <button
            type="button"
            className="checkout-suggestion-action is-primary tap"
            onClick={() => {
              add(product)
              setAdded(product)
            }}
          >
            Agregar
          </button>
        )}
      </div>
    </section>
  )
}
