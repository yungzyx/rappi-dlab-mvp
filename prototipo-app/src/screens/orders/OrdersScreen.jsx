import { useEffect, useState } from 'react'
import { AGENT_NAME } from '../../agent/name'
import BackButton from '../../components/BackButton'
import { ChevronRight } from '../../components/Icons'
import Img from '../../components/Img'
import { ReorderButton } from '../../components/reorder/Reorder'
import { formatPrice } from '../../state/CartContext'
import { useOrders } from '../../state/OrdersContext'
import HelpOrder from '../tracking/HelpOrder'
import { orderTotal } from '../tracking/liveChanges'
import { deliveredAt, statusOf } from '../tracking/progress'
import { relativeDay } from './dates'
import './orders.css'

const TICK_MS = 1000

/**
 * El estado de un pedido en la lista: el paso en que va (los de su vertical, "· atrasado" si se atrasó), "Programado ·
 * hoy 15:00–16:00", "Cancelado", "Por calificar" si ya se entregó y falta su calificación, o "Entregado".
 */
export function orderStatus(order, now) {
  const status = statusOf(order, now)
  if (status.kind !== 'delivered') return { label: status.short, done: status.done, kind: status.kind }
  return { label: order.rating ? 'Entregado' : 'Por calificar', done: true, kind: status.kind }
}

/**
 * Pedidos hechos en la demo (funcionalidad agregada), uno por tienda: una compra en dos tiendas son dos filas. Cada
 * fila abre su seguimiento, en curso, programado, cancelado o entregado; uno entregado trae "Pídelo de nuevo" y "Ayuda
 * con este pedido".
 */
export default function OrdersScreen({ back, push, reset }) {
  const { orders } = useOrders()
  const [now, setNow] = useState(() => Date.now())

  // El estado avanza solo, como el seguimiento.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), TICK_MS)
    return () => clearInterval(timer)
  }, [])

  return (
    <div className="screen orders">
      <header className="orders-header">
        <BackButton className="round-button" onClick={back} />
        <h1>Mis pedidos</h1>
      </header>

      {orders.length === 0 ? (
        <div className="orders-empty">
          <p>Todavía no tienes pedidos</p>
          <small>Lo que pidas aparece aquí con su seguimiento.</small>
          <button type="button" className="orders-empty-button tap" onClick={reset}>
            Ir al inicio
          </button>
        </div>
      ) : (
        <ul className="orders-list">
          {orders.map((order, position) => {
            const status = orderStatus(order, now)
            return (
              <li key={order.id} className="orders-item">
                <button
                  type="button"
                  className="orders-row tap"
                  onClick={() => push('tracking', { orderId: order.id })}
                >
                  <Img src={order.items[0]?.img} />
                  <span className="orders-row-text">
                    <strong>{order.stores.join(', ') || 'Tu pedido'}</strong>
                    <span>
                      {relativeDay(order.placedAt, now)} · {formatPrice(orderTotal(order))}
                      {/* Lo pidió Mochi solo, con permiso ("Pedir por mí": api/autonomy.js). */}
                      {order.byAgent && ` · Lo pidió ${AGENT_NAME} por ti`}
                    </span>
                    <span
                      className={
                        status.kind === 'cancelled'
                          ? 'orders-status is-cancelled'
                          : status.done
                            ? 'orders-status is-done'
                            : 'orders-status'
                      }
                    >
                      {status.label}
                    </span>
                  </span>
                  <ChevronRight size={18} />
                </button>
                {status.kind === 'delivered' && (
                  <div className="orders-actions">
                    <ReorderButton order={order} surface="orders" position={position} className="orders-reorder" />
                    <HelpOrder order={order} deliveredAt={deliveredAt(order)} now={now} className="orders-help tap" />
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
