import { useEffect, useState } from 'react'
import { AGENT_NAME } from '../../agent/name'
import BackButton from '../../components/BackButton'
import Sheet from '../../components/Sheet'
import { useToast } from '../../components/Toast'
import { StarIcon } from '../../components/Icons'
import { HeadsetIcon } from '../../components/LineIcons'
import { offer } from '../../api/agent'
import { noteShown } from '../../api/suggestions'
import { userId } from '../../api/user'
import OfferWhy from '../../components/assistant/OfferWhy'
import { useAssistant } from '../../state/AssistantContext'
import { formatPrice } from '../../state/CartContext'
import { useDemo } from '../../state/DemoContext'
import { useEvents } from '../../state/EventsContext'
import { isHushed, isQuiet } from '../../state/agentQuiet'
import { useOrders } from '../../state/OrdersContext'
import { useProfile } from '../../state/ProfileContext'
import { today } from '../../utils/today'
import TrackingMap from './TrackingMap'
import { STEPS, minutesLeft, rideProgress, stepAt } from './progress'
import './tracking.css'

const TICK_MS = 500
const STARS = [1, 2, 3, 4, 5]

/** Seguimiento del pedido (funcionalidad agregada): pasos que avanzan solos y el agente recorriendo el mapa. */
export default function TrackingScreen({ back, reset, params }) {
  const orders = useOrders()
  const demo = useDemo()
  const order = orders.find(params.orderId)
  const [now, setNow] = useState(() => Date.now())

  const seconds = order ? (now - order.placedAt) / 1000 : 0
  const step = stepAt(seconds)
  const delivered = step === STEPS.length - 1

  // El reloj avanza hasta la entrega: después ya no hay nada que mover.
  useEffect(() => {
    if (delivered) return undefined
    const timer = setInterval(() => setNow(Date.now()), TICK_MS)
    return () => clearInterval(timer)
  }, [delivered])

  if (!order) {
    return (
      <div className="screen tracking">
        <p className="tracking-missing">No encontramos este pedido.</p>
        <button type="button" className="tracking-home-button tap" onClick={back}>
          Volver
        </button>
      </div>
    )
  }

  return (
    <div className="screen tracking">
      <div className="tracking-map-wrap">
        {/* La pose que sigue la etapa y «¡Ya casi!» son del prototipo final; «Rappi hoy» queda como antes. */}
        <TrackingMap progress={rideProgress(seconds)} delivered={delivered} step={demo.isFinal ? step : undefined} />
        <BackButton className="tracking-back" onClick={back} />
      </div>

      <section className="tracking-sheet">
        <p className="tracking-eta-label">{delivered ? '¡Disfruta tu pedido!' : 'Llegada estimada'}</p>
        <h1 className="tracking-eta">{delivered ? 'Entregado 🎉' : `${minutesLeft(seconds)} min`}</h1>

        <ol className="tracking-steps">
          {STEPS.map((item, i) => (
            <li key={item.id} className={i < step || delivered ? 'is-done' : i === step ? 'is-current' : undefined}>
              <span className="tracking-dot" />
              {item.label}
            </li>
          ))}
        </ol>

        {delivered ? <Delivered order={order} /> : <Courier />}

        <OrderSummary order={order} />

        {delivered && (
          <button type="button" className="tracking-home-button tap" onClick={reset}>
            Volver al inicio
          </button>
        )}
      </section>
    </div>
  )
}

// Conversación fija con el Rappitendero (el prototipo no tiene chat en vivo).
const COURIER_CHAT = [
  { from: 'courier', text: 'Hola, ya tengo tu pedido y voy en camino 🛵' },
  { from: 'user', text: 'Gracias. Si no contesto el timbre, llámame.' },
  { from: 'courier', text: 'Perfecto, llego en unos minutos.' },
]

function Courier() {
  const [chatOpen, setChatOpen] = useState(false)
  return (
    <div className="tracking-courier">
      <span className="tracking-avatar">CR</span>
      <span className="tracking-courier-text">
        <strong>Carlos R.</strong>
        <small>
          Tu Rappitendero · <StarIcon filled size={12} /> 4,9
        </small>
      </span>
      <button type="button" className="tracking-contact tap" aria-label="Contactar" onClick={() => setChatOpen(true)}>
        <HeadsetIcon size={20} />
      </button>
      <Sheet open={chatOpen} onClose={() => setChatOpen(false)} title="Chat con Carlos R.">
        <ul className="tracking-chat">
          {COURIER_CHAT.map((line, i) => (
            <li key={i} className={line.from === 'user' ? 'tracking-chat-line is-user' : 'tracking-chat-line'}>
              {line.text}
            </li>
          ))}
        </ul>
        <p className="tracking-chat-note">Carlos R. está conduciendo: responde cuando pueda.</p>
      </Sheet>
    </div>
  )
}

function Delivered({ order }) {
  const toast = useToast()
  const demo = useDemo()
  const assistant = useAssistant()
  const events = useEvents()
  const profile = useProfile()
  const [rating, setRating] = useState(0)
  // El próximo pedido que arma el agente (oferta `proximo_pedido` de la API); sin oferta, sin tarjeta.
  const [next, setNext] = useState(null)
  const items = order.items
    .filter((item) => item.entityId != null)
    .map((item) => ({ entity_type: item.entityType, entity_id: item.entityId }))

  useEffect(() => {
    // En silencio (por hoy o porque lo ignoraron) el agente no ofrece nada, así que tampoco se le pide.
    if (!demo.isFinal || !items.length || isQuiet(today()) || isHushed()) return undefined
    let current = true
    offer('proximo_pedido', { items }, { userId: userId() }).then(
      (made) => {
        if (!current || !made) return
        noteShown(events.track, made.products, {
          origin: `agent-${made.moment}`,
          concept: made.reason?.concept,
          generation: profile.resets,
        })
        setNext({
          context: { items },
          label: made.actions.find((action) => action.query)?.query ?? 'algo más',
          reason: made.reason,
        })
      },
      () => {},
    )
    return () => {
      current = false
    }
    // Una vez por pedido entregado.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [order.id, demo.isFinal])

  const rate = (value) => {
    setRating(value)
    toast('¡Gracias por tu calificación!')
  }

  return (
    <>
      <div className="tracking-rate">
        <p>¿Cómo estuvo tu pedido?</p>
        <div className="tracking-stars" role="radiogroup" aria-label="Calificación">
          {STARS.map((value) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={rating === value}
              aria-label={`${value} estrellas`}
              className={value <= rating ? 'is-on' : undefined}
              onClick={() => rate(value)}
            >
              <StarIcon filled size={30} />
            </button>
          ))}
        </div>
      </div>
      {demo.isFinal && next && (
        <button
          type="button"
          className="tracking-next tap"
          onClick={() =>
            assistant.open({
              query: `¿Y ahora ${next.label}?`,
              offer: { moment: 'proximo_pedido', context: next.context },
            })
          }
        >
          <span>✨ ¿Y ahora {next.label}?</span>
          <small>{AGENT_NAME} te arma el próximo pedido</small>
        </button>
      )}
      {demo.isFinal && next && <OfferWhy reason={next.reason} />}
    </>
  )
}

function OrderSummary({ order }) {
  return (
    <details className="tracking-summary">
      <summary>Detalle del pedido · {formatPrice(order.total)}</summary>
      <ul>
        {order.items.map((item, i) => (
          <li key={`${i}-${item.name}`}>
            <span>
              {item.qty} × {item.name}
            </span>
            <b>{item.price}</b>
          </li>
        ))}
      </ul>
      <p>{order.pickup ? 'Retiro en tienda' : `Entrega en ${order.address}`}</p>
    </details>
  )
}
