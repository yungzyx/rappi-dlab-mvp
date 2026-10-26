import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { DELAY, DEMO_DELAY_EVENT, delayCompensation } from '../screens/tracking/delay'
import { flowFor, isAhead, isDelivered, secondsSince } from '../screens/tracking/progress'
import { addCredits, markCoupon } from './credits'
import { loadStored, saveStored } from './storage'

// Pedidos hechos en la demo, uno por tienda (como en la API: un carro con dos tiendas son dos pedidos, con el mismo
// `cartId`). Se guardan en el navegador para que el seguimiento sobreviva a una recarga. Cada línea guarda su producto
// (`product`, con su tienda y su vertical) para «Pídelo de nuevo», y el pedido su carro (`cartId`) y su tienda
// (`storeId`), que es como la API encuentra el pedido que se califica o se cancela.
const STORAGE_KEY = 'rappi-proto-orders'
const MAX_ORDERS = 10

// Lo que usan las pantallas de un pedido guardado: un valor de otra forma (a mano, o de una versión vieja) se descarta.
const isOrder = (order) =>
  order &&
  typeof order === 'object' &&
  typeof order.id === 'string' &&
  Number.isFinite(order.placedAt) &&
  Array.isArray(order.stores) &&
  Array.isArray(order.items) &&
  order.items.every((item) => item && typeof item === 'object') &&
  Number.isFinite(order.total)

/**
 * Al cargar, la pausa de «Cancelar pedido» se suelta: la hoja ya no está abierta (una recarga no la cierra) y el pedido
 * quedaba detenido para siempre. La de un producto agotado (`heldBy: 'cambio'`) sigue: el pedido espera a la persona.
 */
export const releaseStaleHolds = (orders, now = Date.now()) =>
  orders.map((order) =>
    order.heldAt && order.heldBy === 'cancelar'
      ? { ...order, heldAt: undefined, heldBy: undefined, pausedMs: (order.pausedMs ?? 0) + now - order.heldAt }
      : order,
  )

/** El pedido que el «Panel de la demo» atrasa: el más reciente que va en curso (ni programado, ni entregado). */
const delayable = (orders, now) =>
  orders.find(
    (order) => !order.cancelled && !order.delay && !isAhead(order, now) && !isDelivered(secondsSince(order, now)),
  )

const OrdersContext = createContext(null)

export function OrdersProvider({ children }) {
  const [orders, setOrders] = useState(() =>
    releaseStaleHolds(loadStored(STORAGE_KEY, (value) => Array.isArray(value) && value.every(isOrder), [])),
  )

  const current = useRef(orders)
  useEffect(() => {
    current.current = orders
  })

  const save = useCallback((change) => {
    setOrders((prev) => {
      const next = change(prev)
      if (next !== prev) saveStored(STORAGE_KEY, next)
      return next
    })
  }, [])

  /**
   * Crea los pedidos de una compra (uno por tienda) y devuelve sus ids en el mismo orden. `placedAt` marca el inicio
   * del seguimiento (o, programado, `scheduledFor`).
   */
  const placeMany = useCallback(
    (list) => {
      const now = Date.now()
      const created = list.map((order, i) => ({ ...order, id: `order-${now}${i ? `-${i}` : ''}`, placedAt: now }))
      save((prev) => [...created, ...prev].slice(0, MAX_ORDERS))
      return created.map((order) => order.id)
    },
    [save],
  )

  // Lo que se le suma a un pedido ya hecho (la calificación, la propina, una cancelación…) queda en el mismo pedido.
  // Un cambio vacío (soltar un pedido que no estaba detenido) no guarda nada ni vuelve a pintar.
  const update = useCallback(
    (id, change) =>
      save((prev) => {
        let changed = false
        const next = prev.map((order) => {
          if (order.id !== id) return order
          const patch = typeof change === 'function' ? change(order) : change
          if (!Object.keys(patch).length) return order
          changed = true
          return { ...order, ...patch }
        })
        return changed ? next : prev
      }),
    [save],
  )

  // El reloj de un pedido se detiene mientras la persona decide algo que el pedido espera, y sigue donde quedó. `by`
  // dice quién lo detuvo ('cancelar' o 'cambio'): cada uno suelta solo su pausa (cerrar «Cancelar pedido» no suelta la
  // de un producto agotado que sigue sin respuesta).
  const hold = useCallback(
    (id, by) => update(id, (order) => (order.heldAt ? {} : { heldAt: Date.now(), heldBy: by })),
    [update],
  )
  const release = useCallback(
    (id, by) =>
      update(id, (order) =>
        order.heldAt && (!by || !order.heldBy || order.heldBy === by)
          ? { heldAt: undefined, heldBy: undefined, pausedMs: (order.pausedMs ?? 0) + Date.now() - order.heldAt }
          : {},
      ),
    [update],
  )

  // «Atrasar el pedido en curso» del «Panel de la demo» (solo en «Prototipo MVP.html»): en otros builds nadie lo manda.
  useEffect(() => {
    const onDelay = () => {
      const now = Date.now()
      const target = delayable(current.current, now)
      if (!target) return
      const delay = {
        ...DELAY,
        from: secondsSince(target, now),
        at: now,
        credits: delayCompensation(flowFor(target), target),
      }
      save((prev) => prev.map((order) => (order.id === target.id && !order.delay ? { ...order, delay } : order)))
      // La garantía de Turbo de ejemplo se paga en el saldo de créditos de la demo.
      addCredits(delay.credits)
    }
    window.addEventListener(DEMO_DELAY_EVENT, onDelay)
    return () => window.removeEventListener(DEMO_DELAY_EVENT, onDelay)
  }, [save])

  const value = useMemo(
    () => ({
      orders,
      placeMany,
      /** Un pedido (de una tienda). Devuelve su id. */
      place: (order) => placeMany([order])[0],
      find: (id) => orders.find((order) => order.id === id),
      /** Los pedidos de la misma compra (el mismo carro), en el orden en que se hicieron. */
      siblingsOf: (order) =>
        order?.cartId ? orders.filter((other) => other.cartId === order.cartId) : order ? [order] : [],
      /** La calificación del pedido entregado: `{ stars, reasons }`. */
      rate: (id, rating) => update(id, { rating }),
      /** La propina que se suma después de entregar (en la demo no se cobra). */
      tipAfter: (id, amount) => update(id, { tipAfter: amount }),
      /**
       * Cancelar: `{ reason, stage, fee }` (el costo es de ejemplo). Suelta el reloj, y los créditos y el cupón que usó
       * el pedido vuelven al saldo de la demo.
       */
      cancel: (id, cancelled) => {
        const order = orders.find((o) => o.id === id)
        if (!order || order.cancelled) return
        update(id, (prev) => ({
          cancelled: { ...cancelled, at: Date.now() },
          heldAt: undefined,
          heldBy: undefined,
          pausedMs: (prev.pausedMs ?? 0) + (prev.heldAt ? Date.now() - prev.heldAt : 0),
        }))
        addCredits(order.credits ?? 0)
        if (order.coupon) markCoupon(order.coupon.code, false)
      },
      /** «Aún tiene solución»: cambiar la dirección o el medio de pago en vez de cancelar. */
      change: (id, change) => update(id, change),
      hold,
      release,
      /** El cambio en vivo ya resuelto (`liveChanges.js: resolveChange`). */
      resolveLiveChange: (id, liveChange) => update(id, { liveChange }),
      /**
       * Una solicitud de «Ayuda con este pedido» (de demostración: no mueve dinero real). Un reembolso en créditos se
       * suma al saldo de créditos de ejemplo.
       */
      addHelp: (id, request) => {
        update(id, (order) => ({ help: [...(order.help ?? []), { ...request, at: Date.now() }] }))
        if (request.method === 'creditos') addCredits(request.amount)
      },
    }),
    [orders, placeMany, update, hold, release],
  )

  return <OrdersContext.Provider value={value}>{children}</OrdersContext.Provider>
}

export const useOrders = () => useContext(OrdersContext)
