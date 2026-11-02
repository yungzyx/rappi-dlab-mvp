import { useEffect, useRef, useState } from 'react'
import { appCheck, autoOrderBody, demoOrder, turnOffAutonomy } from '../../api/autonomy'
import { storeTerms } from '../../api/catalog'
import { sendOrder } from '../../api/client'
import { cartEventFields, trackOrder } from '../../api/orders'
import { useAddress } from '../../state/AddressContext'
import { useCart } from '../../state/CartContext'
import { sessionId, useEvents } from '../../state/EventsContext'
import { useOrders } from '../../state/OrdersContext'
import { usePro } from '../../state/pro'
import { UNDO_MS } from '../../screens/checkout/undo'
import { useToast } from '../Toast'

const AUTO_OFF = 'Listo: vuelvo a revisar antes de pedir.'
const AUTO_OFF_FAILED = 'No pude apagarlo ahora. Intenta de nuevo.'
const AUTO_NOT_SENT = 'no pude enviarlo ahora'
const AUTO_SENT = (store) => `Listo, pedí lo de siempre en ${store}: está en Mis pedidos.`
const AUTO_UNDONE_ON_CLOSE = (store) => `No pedí lo de siempre en ${store}: cerraste antes de que saliera.`

let nextKey = 1

/**
 * "Pedir por mí": el estado de cada "lo de siempre" que Mochi pide solo (clave → { state, reason, orderId }) y su
 * ventana de "Deshacer pedido" (clave → temporizador). La ventana la lleva el panel, que siempre está montado: sigue
 * aunque la respuesta cambie. `messages` y `shownAnswer` son los de la conversación (`useAgentConversation`).
 */
export function useAutoOrders({ messages, shownAnswer }) {
  const cart = useCart()
  const orders = useOrders()
  const address = useAddress()
  const events = useEvents()
  const toast = useToast()
  const isPro = usePro()
  const [status, setStatus] = useState({})
  const timers = useRef(new Map())
  useEffect(() => () => timers.current.forEach(clearTimeout), [])

  const setAuto = (key, next) => setStatus((prev) => ({ ...prev, [key]: next }))

  /**
   * "Pide lo de siempre": con "Pedir por mí", antes de abrir la ventana se suma lo que la API no sabe (el envío y la
   * tarifa, de ejemplo si el catálogo no los trae, como en el checkout) y se compara con el tope y la compra mínima; si
   * no cumple, se revisa antes y Mochi dice por qué. Cada uno lleva su clave (`key`) para su estado y su ventana.
   */
  const check = async (message) => {
    const order = { ...message.autoOrder, key: `auto-${nextKey++}` }
    if (order.mode !== 'pedir') return { ...message, autoOrder: order }
    const terms = await storeTerms([order.store.id]).catch(() => new Map())
    const { total, reason } = appCheck(order, terms.get(order.store.id) ?? null, { isPro })
    if (!reason) return { ...message, autoOrder: { ...order, total } }
    return {
      ...message,
      text: `Te armé lo de siempre en ${order.store.name}. Esta vez lo revisas tú: ${reason}.`,
      autoOrder: { ...order, total, mode: 'revisar', code: 'app', reason },
    }
  }

  /**
   * Cerrada la ventana: el pedido va a la API marcado `autopedido`, que vuelve a revisar cada límite. Si lo toma, queda
   * en los pedidos de la demo con su seguimiento; si no (un 409 con el motivo, o sin conexión), se revisa antes.
   */
  const commit = async (order) => {
    setAuto(order.key, { state: 'sending' })
    const cartId = `c-auto-${Date.now().toString(36)}`
    const body = autoOrderBody(order, { sessionId: sessionId(), cartId, pro: isPro })
    try {
      // Antes salen los eventos en cola (como en el checkout); todo el camino cuenta como pedido en vuelo para "Olvidar".
      await trackOrder(
        Promise.resolve(events.flush?.())
          .then(() => events.settled?.())
          .then(() => sendOrder(body)),
      )
      const orderId = orders?.place(demoOrder(order, { cartId, total: order.total, address: address?.selected.line }))
      setAuto(order.key, { state: 'sent', orderId })
      if (shownAnswer.current?.autoOrder?.key !== order.key) toast?.(AUTO_SENT(order.store.name))
    } catch (error) {
      setAuto(order.key, { state: 'review', reason: error?.detail?.motivo ?? AUTO_NOT_SENT })
    }
  }

  /** Abre la ventana de "Deshacer pedido" (una vez por pedido): al cerrarse, sale el pedido (`commit`). */
  const arm = (order) => {
    if (order.mode !== 'pedir' || timers.current.has(order.key)) return
    setAuto(order.key, { state: 'waiting' })
    timers.current.set(
      order.key,
      setTimeout(() => commit(order), UNDO_MS),
    )
  }

  /** Deshacer: el pedido no sale (nunca llegó a la API). */
  const undo = (order) => {
    clearTimeout(timers.current.get(order.key))
    setAuto(order.key, { state: 'undone' })
  }

  const undoAll = () => {
    for (const [key, timer] of timers.current) {
      clearTimeout(timer)
      setStatus((prev) => (prev[key]?.state === 'waiting' ? { ...prev, [key]: { state: 'undone' } } : prev))
    }
  }

  /**
   * Lo que Mochi iba a pedir solo y todavía está en su ventana: con el buscador cerrado ya no se ve su "Deshacer
   * pedido", así que no sale (nada se pide sin que la ventana esté a la vista) y un toast lo dice.
   */
  const undoWaitingOnClose = () => {
    const waiting = messages.filter((m) => m.autoOrder && status[m.autoOrder.key]?.state === 'waiting')
    if (!waiting.length) return
    undoAll()
    toast?.(AUTO_UNDONE_ON_CLOSE(waiting.at(-1).autoOrder.store.name))
  }

  /** "Revisar y pagar": lo de siempre al carro (con lo que ya tenía); quien llama lleva al checkout. */
  const review = (order) => {
    for (const { product, qty } of order.lines) {
      for (let n = 0; n < qty; n += 1) cart.add(product)
      events.track('cart_add', cartEventFields(product, cart.id, { qty }))
    }
  }

  /** "Apagar 'Pedir por mí'" en un toque: también deshace lo que esté en su ventana. */
  const turnOff = () => {
    undoAll()
    turnOffAutonomy().then(
      () => toast?.(AUTO_OFF),
      () => toast?.(AUTO_OFF_FAILED),
    )
  }

  return { status, check, arm, undo, undoAll, undoWaitingOnClose, review, turnOff }
}
