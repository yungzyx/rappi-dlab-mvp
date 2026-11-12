import { useState } from 'react'
import { AGENT_NAME } from '../../agent/name'
import { offer } from '../../api/agent'
import { storeKeyOf } from '../../api/orders'
import { noteOfferShown, wasRefused } from '../../api/suggestions'
import { userId } from '../../api/user'
import Mascot from '../../components/assistant/Mascot'
import OfferWhy from '../../components/assistant/OfferWhy'
import { useAddToCart } from '../../hooks/useAddToCart'
import { VERTICAL_NAMES } from '../../data/verticals'
import { useCart } from '../../state/CartContext'
import { useDemo } from '../../state/DemoContext'
import { useAgentHidden } from '../../state/agentHidden'
import { useEvents } from '../../state/EventsContext'
import { useProfile } from '../../state/ProfileContext'

/**
 * "¿Me falta algo?" en el checkout (prototipo final): solo si la persona lo pide, se consulta la oferta `checkout` de
 * El agente con lo que lleva el carro. Si hay oferta, sugiere UNA cosa (con su razón, "Agregar" y "Deshacer"); si no (204),
 * dice que el carro está completo; si la API no contesta, no dice nada. Nada aparece por su cuenta. Lo que la persona
 * ya rechazó en la sesión no se vuelve a proponer (dice que no tiene otra idea: el carro no está "completo"), y si el
 * producto es de una tienda que no está en el carro, avisa que va en otro pedido, con su propio envío. Lo agregado
 * aquí no lo comenta Mochi en la Home.
 */
export default function CheckoutSuggestion() {
  const demo = useDemo()
  const cart = useCart()
  const profile = useProfile()
  const events = useEvents()
  const { add, remove } = useAddToCart()
  const [asking, setAsking] = useState(false)
  const [picked, setPicked] = useState(null) // la oferta pedida: { text, product }; queda fija aunque cambie el carro
  // Sin nada que agregar: la API no tiene nada (204, "completo") o solo tenía lo que la persona ya rechazó ("sin idea").
  const [complete, setComplete] = useState(null)
  const [added, setAdded] = useState(null)
  const hidden = useAgentHidden()

  // Con Mochi oculto no hay a quién pedirle.
  if (!demo?.isFinal || hidden) return null
  if (complete)
    return (
      <p className="checkout-ask" role="status">
        <Mascot size={28} badge />
        {complete === 'completo' ? 'Tu carro está completo' : 'Por ahora no tengo otra idea para tu carro'}
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
        const made = await offer('checkout', { cart: lines }, { userId: userId(), surface: 'checkout' })
        if (!made?.products.length) return setComplete('completo')
        const product = made.products.find((candidate) => !wasRefused(made, candidate))
        if (!product) return setComplete('sin idea')
        noteOfferShown(events.track, made, { generation: profile.resets, products: [product] })
        // Si es de otra tienda, sale en un pedido aparte (basketsOf): se dice al mostrarlo, con el carro de ese momento.
        const otherStore = !cart.items.some((line) => storeKeyOf(line.product) === storeKeyOf(product))
        setPicked({ text: made.text, product, reason: made.reason, origin: `agent-${made.moment}`, otherStore })
      } catch {
        // Sin respuesta, el agente no dice nada: el botón sigue ahí para volver a pedir.
      } finally {
        setAsking(false)
      }
    }
    return (
      <button type="button" className="checkout-ask tap" disabled={asking} onClick={ask}>
        <Mascot size={28} badge />
        ¿Me falta algo? Pídele a {AGENT_NAME}
      </button>
    )
  }

  const { text, product, reason, origin, otherStore } = picked
  return (
    <section className="checkout-suggestion" aria-label={`Sugerencia de ${AGENT_NAME}`}>
      <Mascot size={40} badge mood="wave" />
      <div className="checkout-suggestion-body">
        <p className="checkout-suggestion-reason">{text}</p>
        <OfferWhy reason={reason} origin={origin} />
        <p className="checkout-suggestion-product">
          {product.name} · {product.price} · {VERTICAL_NAMES[product.vertical] ?? product.vertical}
          {product.ageRestricted && (
            <span className="checkout-suggestion-age" aria-label="Solo mayores de 18">
              +18
            </span>
          )}
        </p>
        {otherStore && (
          <p className="checkout-suggestion-store checkout-basis">
            Es de otra tienda: va en otro pedido, con su propio envío.
          </p>
        )}
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
              add(product, { comment: false })
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
