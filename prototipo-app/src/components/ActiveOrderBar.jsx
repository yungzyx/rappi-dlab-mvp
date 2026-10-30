import { useEffect, useRef, useState } from 'react'
import { useCart } from '../state/CartContext'
import { useOrders } from '../state/OrdersContext'
import { etaMinutes, isDelivered, secondsSince, statusOf } from '../screens/tracking/progress'
import { ChevronRight } from './Icons'
import { useFloatingInset } from './floatingInset'
import './active-order-bar.css'

const TICK_MS = 1000
// Fuera del proveedor de pedidos (tests de pantallas sueltas) no hay pedidos.
const NO_ORDERS = []

/** ¿Sigue en curso? Ni entregado ni cancelado (uno programado cuenta: espera su franja). */
const inCourse = (order, now) => !order.cancelled && !isDelivered(secondsSince(order, now))

/** El pedido en curso más reciente (el último que todavía no se entrega ni se canceló), o null. */
export function activeOrder(orders, now) {
  return orders.find((order) => inCourse(order, now)) ?? null
}

/**
 * Barra "Pedido en curso" fuera del seguimiento (la de la app de Rappi y su Live Activity): el paso en que va el pedido
 * y cuánto falta (o su franja, si está programado). Con varios en curso (una compra en dos tiendas), cuántos son. Tocarla abre su seguimiento. Sobre la barra del carro si hay productos; a la izquierda de Mochi. Un
 * pedido recién hecho (todavía sin tic del reloj) cuenta como en curso: aún no pasa su hora.
 */
export default function ActiveOrderBar({ push, raised }) {
  const orders = useOrders()?.orders ?? NO_ORDERS
  const withCart = useCart().count > 0
  const [now, setNow] = useState(() => Date.now())
  const order = activeOrder(orders, now)
  const id = order?.id
  const bar = useRef(null)
  useFloatingInset(() => bar.current)

  // Avanza mientras haya un pedido en curso; sin él no hay reloj.
  useEffect(() => {
    if (!id) return undefined
    const timer = setInterval(() => setNow(Date.now()), TICK_MS)
    return () => clearInterval(timer)
  }, [id])

  if (!order) return null
  const status = statusOf(order, now)
  const minutes = status.kind === 'active' ? etaMinutes(order, secondsSince(order, now)) : 0
  const count = orders.filter((other) => inCourse(other, now)).length
  const classes = ['active-order-bar', 'tap', raised && 'is-raised', withCart && 'with-cart'].filter(Boolean)
  return (
    <button
      ref={bar}
      type="button"
      className={classes.join(' ')}
      onClick={() => push('tracking', { orderId: order.id })}
    >
      <span className="active-order-dot" aria-hidden="true" />
      <span className="active-order-text">
        <strong>{count > 1 ? `${count} pedidos en curso` : 'Pedido en curso'}</strong>
        <span>
          {/* Un producto agotado detiene el pedido hasta que la persona elige: la barra lo dice, no un reloj quieto. */}
          {order.heldBy === 'cambio'
            ? 'Tus productos te necesitan'
            : `${status.short}${minutes > 0 ? ` · ${minutes} min` : ''}`}
        </span>
      </span>
      <ChevronRight size={16} />
    </button>
  )
}
