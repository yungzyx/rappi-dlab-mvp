import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import { loadStored, saveStored } from './storage'

// Pedidos hechos en la demo. Se guardan en el navegador para que el seguimiento sobreviva a una recarga.
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

  const value = useMemo(
    () => ({ orders, place, find: (id) => orders.find((order) => order.id === id) }),
    [orders, place],
  )

  return <OrdersContext.Provider value={value}>{children}</OrdersContext.Provider>
}

export const useOrders = () => useContext(OrdersContext)
