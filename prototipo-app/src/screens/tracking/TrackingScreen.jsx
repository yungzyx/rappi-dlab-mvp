import { useEffect, useState } from 'react'
import { AGENT_NAME } from '../../agent/name'
import BackButton from '../../components/BackButton'
import HScroll from '../../components/HScroll'
import { ProductCard } from '../../components/ProductCard'
import { ReorderButton } from '../../components/reorder/Reorder'
import Sheet from '../../components/Sheet'
import { useToast } from '../../components/Toast'
import { StarIcon } from '../../components/Icons'
import { HeadsetIcon } from '../../components/LineIcons'
import { offer } from '../../api/agent'
import { noteShown } from '../../api/suggestions'
import { userId } from '../../api/user'
import OfferWhy from '../../components/assistant/OfferWhy'
import { useAssistant } from '../../state/AssistantContext'
import { formatPrice, useCart } from '../../state/CartContext'
import { useDemo } from '../../state/DemoContext'
import { useEvents } from '../../state/EventsContext'
import { isHushed, isQuiet } from '../../state/agentQuiet'
import { useOrders } from '../../state/OrdersContext'
import { useProfile } from '../../state/ProfileContext'
import { today } from '../../utils/today'
import { TIPS } from '../checkout/pricing'
import TrackingMap from './TrackingMap'
import {
  deliveryCode,
  flowFor,
  isDelivered,
  isRiding,
  minutesLeft,
  rideProgress,
  secondsSince,
  stepAt,
} from './progress'
import './tracking.css'

const TICK_MS = 500
const STARS = [1, 2, 3, 4, 5]
// 3 estrellas o menos es una calificación mala (rappi-ia: events/store.py, LOW_RATING): pregunta qué pasó y, en el
// prototipo final, pausa la recompra y el «volver» de lo de ese pedido.
export const LOW_RATING = 3
// «¿Qué problema tuvo el pedido?»: los códigos que acepta rappi-ia (events/store.py: RATING_REASONS).
export const RATING_REASONS = [
  { id: 'tarde', label: 'Llegó tarde' },
  { id: 'faltante', label: 'Faltó un producto' },
  { id: 'mal_estado', label: 'Un producto llegó en mal estado' },
  { id: 'equivocado', label: 'Me llegó otro pedido' },
  { id: 'repartidor', label: 'Problema con el repartidor' },
  { id: 'otro', label: 'Otro problema' },
]

/**
 * Seguimiento del pedido (funcionalidad agregada): los pasos de su vertical avanzan solos y el agente recorre el mapa.
 * En camino muestra el código de entrega; entregado, la calificación, la propina y «Pídelo de nuevo». En el prototipo
 * final, mientras llega, el OnTop de Turbo.
 */
export default function TrackingScreen({ back, reset, push, params }) {
  const orders = useOrders()
  const demo = useDemo()
  const order = orders.find(params.orderId)
  const [now, setNow] = useState(() => Date.now())

  const seconds = secondsSince(order, now)
  const flow = flowFor(order)
  const step = stepAt(seconds, flow)
  const delivered = isDelivered(seconds)
  const riding = isRiding(seconds)
  const arrived = riding && minutesLeft(seconds, flow) === 0

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

  const eta = delivered ? 'Entregado 🎉' : arrived ? 'Llegó tu Rappi' : `${minutesLeft(seconds, flow)} min`
  return (
    <div className="screen tracking">
      <div className="tracking-map-wrap">
        {/* La pose (tímido antes del viaje) y «¡Ya casi!» son del prototipo final; «Rappi hoy» queda como antes. */}
        <TrackingMap
          progress={rideProgress(seconds)}
          delivered={delivered}
          step={demo.isFinal ? (riding || delivered ? 2 : 1) : undefined}
        />
        <BackButton className="tracking-back" onClick={back} />
      </div>

      <section className="tracking-sheet">
        <p className="tracking-eta-label">{delivered ? '¡Disfruta tu pedido!' : 'Llegada estimada'}</p>
        <h1 className="tracking-eta">{eta}</h1>
        {flow.promise && !delivered && <p className="tracking-promise">{flow.promise}</p>}

        <ol className="tracking-steps">
          {flow.steps.map((item, i) => (
            <li key={item.id} className={i < step || delivered ? 'is-done' : i === step ? 'is-current' : undefined}>
              <span className="tracking-dot" />
              {item.label}
            </li>
          ))}
        </ol>

        {riding && !order.pickup && <DeliveryCode orderId={order.id} />}
        {!delivered && riding && <Courier />}
        {!delivered && demo.isFinal && <OnTop order={order} flow={flow} now={now} push={push} />}
        {delivered && <Delivered order={order} push={push} />}

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

/** El código que la persona le dice a su Rappi al recibir (el «handshake» de la app de Rappi). */
function DeliveryCode({ orderId }) {
  return (
    <div className="tracking-code" role="note" aria-label="Código de entrega">
      <span>Código de entrega</span>
      <strong>{deliveryCode(orderId)}</strong>
      <small>Dáselo a tu Rappi solo cuando tengas el pedido en tus manos.</small>
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
          Tu Rappi · <StarIcon filled size={12} /> 4,9
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

/** Las líneas de un pedido como las pide la API (las que tienen id del catálogo). */
const entitiesOf = (order) =>
  order.items
    .filter((item) => item.entityId != null)
    .map((item) => ({ entity_type: item.entityType, entity_id: item.entityId }))

/** «HH:MM» de una hora (ms), en la hora del teléfono. */
export const clock = (ts) => new Date(ts).toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit' })

/** ¿El agente puede ofrecer algo ahora? En silencio (por hoy o porque lo ignoraron) no ofrece ni se le pide. */
const agentMaySpeak = () => !isQuiet(today()) && !isHushed()

/**
 * El OnTop de Turbo (prototipo final, mientras el pedido va en curso y no es de Turbo): «Turbo: suma esto antes de
 * HH:MM», con productos que elige el motor (`cross_picks`) y pasan las guardias (la oferta `ontop` de la API). El plazo
 * y el envío sin costo extra son supuestos: se rotulan «de ejemplo». Lo que se agrega va al carro como un pedido de
 * Turbo aparte.
 */
function OnTop({ order, flow, now, push }) {
  const events = useEvents()
  const profile = useProfile()
  const cart = useCart()
  const [made, setMade] = useState(null)
  const vertical =
    flow.id === 'restaurants' ? 'restaurants' : order.items.map((item) => item.vertical).find((v) => v && v !== 'turbo')

  useEffect(() => {
    const items = entitiesOf(order)
    if (flow.id === 'turbo' || !vertical || !items.length || !agentMaySpeak()) return undefined
    let current = true
    offer('ontop', { vertical, items }, { userId: userId(), surface: 'tracking' }).then(
      (reply) => {
        if (!current || !reply?.products.length) return
        noteShown(events.track, reply.products, {
          origin: `agent-${reply.moment}`,
          concept: reply.reason?.concept,
          generation: profile.resets,
        })
        setMade(reply)
      },
      () => {},
    )
    return () => {
      current = false
    }
    // Una vez por pedido en curso.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [order.id])

  if (!made) return null
  const deadline = order.placedAt + (made.windowMin ?? 15) * 60_000
  if (now > deadline) return null
  return (
    <section className="tracking-ontop" aria-label="Turbo: suma a tu pedido">
      <h2>Turbo: suma esto antes de las {clock(deadline)}</h2>
      <p>{made.text}</p>
      <OfferWhy reason={made.reason} />
      <HScroll className="tracking-ontop-items">
        {made.products.map((product) => (
          <div key={product.id} className="tracking-ontop-item">
            <ProductCard product={product} impression />
          </div>
        ))}
      </HScroll>
      <small className="tracking-ontop-note">Plazo y envío de ejemplo: no son condiciones de Rappi.</small>
      {cart.count > 0 && (
        <button type="button" className="tracking-ontop-cart tap" onClick={() => push('checkout')}>
          Ver carro · {formatPrice(cart.total)}
        </button>
      )}
    </section>
  )
}

function Delivered({ order, push }) {
  const demo = useDemo()
  const assistant = useAssistant()
  const events = useEvents()
  const profile = useProfile()
  // El próximo pedido que arma el agente (oferta `proximo_pedido` de la API); sin oferta, sin tarjeta.
  const [next, setNext] = useState(null)
  const items = entitiesOf(order)
  // Una calificación mala en el prototipo final: el agente no ofrece nada más en este pedido.
  const bad = demo.isFinal && order.rating && order.rating.stars <= LOW_RATING

  useEffect(() => {
    if (!demo.isFinal || bad || !items.length || !agentMaySpeak()) return undefined
    let current = true
    offer('proximo_pedido', { items }, { userId: userId(), surface: 'tracking' }).then(
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

  return (
    <>
      <Rating order={order} />
      {!order.pickup && <TipAfter order={order} />}
      <div className="tracking-reorder">
        <ReorderButton order={order} surface="tracking" onDone={() => push?.('checkout')} />
      </div>
      {demo.isFinal && next && !bad && (
        <>
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
          <OfferWhy reason={next.reason} />
        </>
      )}
    </>
  )
}

/**
 * «¿Cómo estuvo tu pedido?»: las estrellas y, con 3 o menos, «¿Qué problema tuvo el pedido?» con sus opciones. Queda en
 * el pedido y como evento `order_rated` (estrellas y motivos; el pedido es su carro, `cart_id`).
 */
function Rating({ order }) {
  const toast = useToast()
  const orders = useOrders()
  const events = useEvents()
  const [draft, setDraft] = useState(0)
  const [reasons, setReasons] = useState([])
  const saved = order.rating

  const send = (stars, chosen) => {
    orders.rate(order.id, { stars, reasons: chosen })
    // Sin carro (un pedido guardado antes) la API no sabría qué pedido es: queda solo en el teléfono.
    // Sale al tiro (no espera el lote de 5 s): al volver a la Home, la recompra ya debe saber de una calificación mala.
    if (order.cartId) {
      events.track('order_rated', { surface: 'tracking', cart_id: order.cartId, payload: { stars, reasons: chosen } })
      events.flush()
    }
    toast('¡Gracias por tu calificación!')
  }

  const choose = (value) => {
    setDraft(value)
    setReasons([])
    if (value > LOW_RATING) send(value, [])
  }

  const stars = saved?.stars ?? draft
  const asking = !saved && draft > 0 && draft <= LOW_RATING
  return (
    <div className="tracking-rate">
      <p>{saved ? 'Tu calificación' : '¿Cómo estuvo tu pedido?'}</p>
      <div className="tracking-stars" role="radiogroup" aria-label="Calificación">
        {STARS.map((value) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={stars === value}
            aria-label={`${value} estrellas`}
            className={value <= stars ? 'is-on' : undefined}
            disabled={Boolean(saved)}
            onClick={() => choose(value)}
          >
            <StarIcon filled size={30} />
          </button>
        ))}
      </div>
      {asking && (
        <div className="tracking-reasons">
          <p>¿Qué problema tuvo el pedido?</p>
          <div className="tracking-reason-chips">
            {RATING_REASONS.map((reason) => {
              const on = reasons.includes(reason.id)
              return (
                <button
                  key={reason.id}
                  type="button"
                  aria-pressed={on}
                  className={on ? 'tracking-reason is-on tap' : 'tracking-reason tap'}
                  onClick={() => setReasons(on ? reasons.filter((r) => r !== reason.id) : [...reasons, reason.id])}
                >
                  {reason.label}
                </button>
              )
            })}
          </div>
          <button type="button" className="tracking-reason-send tap" onClick={() => send(draft, reasons)}>
            Enviar calificación
          </button>
        </div>
      )}
    </div>
  )
}

/** Propina después de entregar: el 100% es para el Rappi. En la demo no se cobra. */
function TipAfter({ order }) {
  const orders = useOrders()
  const toast = useToast()
  const chosen = order.tipAfter ?? 0
  return (
    <div className="tracking-tip">
      <p>
        <strong>Agrega una propina</strong> · El 100% es para tu Rappi
      </p>
      <div className="tracking-tip-chips" role="radiogroup" aria-label="Propina">
        {TIPS.filter((amount) => amount > 0).map((amount) => (
          <button
            key={amount}
            type="button"
            role="radio"
            aria-checked={chosen === amount}
            className={chosen === amount ? 'tracking-tip-chip is-on tap' : 'tracking-tip-chip tap'}
            onClick={() => {
              orders.tipAfter(order.id, amount)
              toast('Tu Rappi recibe el 100% de la propina')
            }}
          >
            {formatPrice(amount)}
          </button>
        ))}
      </div>
      <small>Demo: no se cobra.</small>
    </div>
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
