import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import { loadStored, saveStored } from './storage'

// Pedidos hechos en la demo. Se guardan en el navegador para que el seguimiento sobreviva a una recarga. Cada línea guarda
// su producto (`product`, con su tienda y su vertical) para «Pídelo de nuevo», y el pedido su carro (`cartId`), que es
// como la API encuentra el pedido que se califica.
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

const OrdersContext = createContext(null)

export function OrdersProvider({ children }) {
  const [orders, setOrders] = useState(() =>
    loadStored(STORAGE_KEY, (value) => Array.isArray(value) && value.every(isOrder), []),
  )

  /** Crea el pedido y devuelve su id. `placedAt` marca el inicio del seguimiento. */
  const place = useCallback((order) => {
    const created = { ...order, id: `order-${Date.now()}`, placedAt: Date.now() }
    setOrders((prev) => {
      const next = [created, ...prev].slice(0, MAX_ORDERS)
      saveStored(STORAGE_KEY, next)
      return next
    })
    return created.id
  }, [])

  // Lo que se le suma a un pedido ya hecho (la calificación, la propina después de entregar) queda en el mismo pedido.
  const update = useCallback((id, change) => {
    setOrders((prev) => {
      const next = prev.map((order) => (order.id === id ? { ...order, ...change } : order))
      saveStored(STORAGE_KEY, next)
      return next
    })
  }, [])

  const value = useMemo(
    () => ({
      orders,
      place,
      find: (id) => orders.find((order) => order.id === id),
      /** La calificación del pedido entregado: `{ stars, reasons }`. */
      rate: (id, rating) => update(id, { rating }),
      /** La propina que se suma después de entregar (en la demo no se cobra). */
      tipAfter: (id, amount) => update(id, { tipAfter: amount }),
    }),
    [orders, place, update],
  )

  return <OrdersContext.Provider value={value}>{children}</OrdersContext.Provider>
}

export const useOrders = () => useContext(OrdersContext)
