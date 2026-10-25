import { useEffect, useState } from 'react'
import { useCart } from '../state/CartContext'
import { useOrders } from '../state/OrdersContext'
import { flowFor, isDelivered, minutesLeft, secondsSince, stepAt } from '../screens/tracking/progress'
import { ChevronRight } from './Icons'
import './active-order-bar.css'

const TICK_MS = 1000
// Fuera del proveedor de pedidos (tests de pantallas sueltas) no hay pedidos.
const NO_ORDERS = []

/** El pedido en curso más reciente (el último que todavía no se entrega), o null. */
export function activeOrder(orders, now) {
  return orders.find((order) => !isDelivered(secondsSince(order, now))) ?? null
}

/**
 * Barra «Pedido en curso» fuera del seguimiento (la de la app de Rappi y su Live Activity): el paso en que va el pedido
 * y cuánto falta. Tocarla abre su seguimiento. Sobre la barra del carro si hay productos; a la izquierda de Mochi. Un
 * pedido recién hecho (todavía sin tic del reloj) cuenta como en curso: aún no pasa su hora.
 */
export default function ActiveOrderBar({ push, raised }) {
  const orders = useOrders()?.orders ?? NO_ORDERS
  const withCart = useCart().count > 0
  const [now, setNow] = useState(() => Date.now())
  const order = activeOrder(orders, now)
  const id = order?.id

  // Avanza mientras haya un pedido en curso; sin él no hay reloj.
  useEffect(() => {
    if (!id) return undefined
    const timer = setInterval(() => setNow(Date.now()), TICK_MS)
    return () => clearInterval(timer)
  }, [id])

  if (!order) return null
  const seconds = secondsSince(order, now)
  const flow = flowFor(order)
  const minutes = minutesLeft(seconds, flow)
  const classes = ['active-order-bar', 'tap', raised && 'is-raised', withCart && 'with-cart'].filter(Boolean)
  return (
    <button type="button" className={classes.join(' ')} onClick={() => push('tracking', { orderId: order.id })}>
      <span className="active-order-dot" aria-hidden="true" />
      <span className="active-order-text">
        <strong>Pedido en curso</strong>
        <span>
          {flow.steps[stepAt(seconds, flow)].short}
          {minutes > 0 ? ` · ${minutes} min` : ''}
        </span>
      </span>
      <ChevronRight size={16} />
    </button>
  )
}
