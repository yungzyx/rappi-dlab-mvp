import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { DELAY, DEMO_DELAY_EVENT, delayCompensation } from '../screens/tracking/delay'
import { flowFor, isAhead, isDelivered, secondsSince } from '../screens/tracking/progress'
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

/** El pedido que el «Panel de la demo» atrasa: el más reciente que va en curso (ni programado, ni entregado). */
const delayable = (orders, now) =>
  orders.find(
    (order) => !order.cancelled && !order.delay && !isAhead(order, now) && !isDelivered(secondsSince(order, now)),
  )

const OrdersContext = createContext(null)

export function OrdersProvider({ children }) {
  const [orders, setOrders] = useState(() =>
    loadStored(STORAGE_KEY, (value) => Array.isArray(value) && value.every(isOrder), []),
  )

  const save = useCallback((change) => {
    setOrders((prev) => {
      const next = change(prev)
      saveStored(STORAGE_KEY, next)
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
  const update = useCallback(
    (id, change) =>
      save((prev) =>
        prev.map((order) =>
          order.id === id ? { ...order, ...(typeof change === 'function' ? change(order) : change) } : order,
        ),
      ),
    [save],
  )

  // El reloj de un pedido se detiene mientras la persona decide algo que el pedido espera, y sigue donde quedó.
  const hold = useCallback((id) => update(id, (order) => (order.heldAt ? {} : { heldAt: Date.now() })), [update])
  const release = useCallback(
    (id) =>
      update(id, (order) =>
        order.heldAt ? { heldAt: undefined, pausedMs: (order.pausedMs ?? 0) + Date.now() - order.heldAt } : {},
      ),
    [update],
  )

  // «Atrasar el pedido en curso» del «Panel de la demo» (solo en «Prototipo MVP.html»): en otros builds nadie lo manda.
  useEffect(() => {
    const onDelay = () => {
      const now = Date.now()
      save((prev) => {
        const target = delayable(prev, now)
        if (!target) return prev
        const delay = {
          ...DELAY,
          from: secondsSince(target, now),
          at: now,
          credits: delayCompensation(flowFor(target), target),
        }
        return prev.map((order) => (order.id === target.id ? { ...order, delay } : order))
      })
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
      /** Cancelar: `{ reason, stage, fee }` (el costo es de ejemplo). Suelta el reloj. */
      cancel: (id, cancelled) =>
        update(id, (order) => ({
          cancelled: { ...cancelled, at: Date.now() },
          heldAt: undefined,
          pausedMs: (order.pausedMs ?? 0) + (order.heldAt ? Date.now() - order.heldAt : 0),
        })),
      /** «Aún tiene solución»: cambiar la dirección o el medio de pago en vez de cancelar. */
      change: (id, change) => update(id, change),
      hold,
      release,
      /** El cambio en vivo ya resuelto (`liveChanges.js: resolveChange`). */
      resolveLiveChange: (id, liveChange) => update(id, { liveChange }),
      /** Una solicitud de «Ayuda con este pedido» (de demostración: no mueve dinero). */
      addHelp: (id, request) =>
        update(id, (order) => ({ help: [...(order.help ?? []), { ...request, at: Date.now() }] })),
    }),
    [orders, placeMany, update, hold, release],
  )

  return <OrdersContext.Provider value={value}>{children}</OrdersContext.Provider>
}

export const useOrders = () => useContext(OrdersContext)
