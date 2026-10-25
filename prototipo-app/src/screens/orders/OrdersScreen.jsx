import { useEffect, useState } from 'react'
import BackButton from '../../components/BackButton'
import { ChevronRight } from '../../components/Icons'
import Img from '../../components/Img'
import { formatPrice } from '../../state/CartContext'
import { useOrders } from '../../state/OrdersContext'
import { STEPS, stepAt } from '../tracking/progress'
import { relativeDay } from './dates'
import './orders.css'

const TICK_MS = 1000

/** Pedidos hechos en la demo (funcionalidad agregada). Cada fila abre su seguimiento, en curso o entregado. */
export default function OrdersScreen({ back, push, reset }) {
  const { orders } = useOrders()
  const [now, setNow] = useState(() => Date.now())

  // El estado «En camino» / «Entregado» avanza solo, como el seguimiento.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), TICK_MS)
    return () => clearInterval(timer)
  }, [])

  const isDelivered = (order) => stepAt((now - order.placedAt) / 1000) === STEPS.length - 1

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
          {orders.map((order) => {
            const delivered = isDelivered(order)
            return (
              <li key={order.id}>
                <button
                  type="button"
                  className="orders-row tap"
                  onClick={() => push('tracking', { orderId: order.id })}
                >
                  <Img src={order.items[0]?.img} />
                  <span className="orders-row-text">
                    <strong>{order.stores.join(', ') || 'Tu pedido'}</strong>
                    <span>
                      {relativeDay(order.placedAt, now)} · {formatPrice(order.total)}
                    </span>
                    <span className={delivered ? 'orders-status is-done' : 'orders-status'}>
                      {delivered ? 'Entregado' : 'En camino'}
                    </span>
                  </span>
                  <ChevronRight size={18} />
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
