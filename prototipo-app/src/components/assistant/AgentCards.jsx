import { useState } from 'react'
import { useCartPricing } from '../../screens/checkout/useCartPricing'
import { flowFor, isDelivered, minutesLeft, stepAt } from '../../screens/tracking/progress'
import { formatPrice, lineKey, parsePrice, useCart } from '../../state/CartContext'
import { useOrders } from '../../state/OrdersContext'

// El tiempo del checkout (CheckoutScreen): de ejemplo, como el envío, la tarifa y la propina de pricing.js.
const ETA = 'Llega en 25–35 min'
const SHOWN_LINES = 4

/**
 * El resumen del pedido antes de pagar, con el carro de ahora: productos, envío, tarifa, propina, total y tiempo,
 * calculados como en el checkout (`useCartPricing`: por tienda, con Pro y la propina de siempre; sin cupón ni créditos,
 * que se eligen en el pago). Solo se revisa: el pedido se hace en el checkout, nunca desde aquí.
 */
export function OrderSummaryCard() {
  const cart = useCart()
  if (!cart.count) return <p className="agent-card-note">Tu carro está vacío: agrega algo y te armo el resumen.</p>
  return <OrderSummary items={cart.items} />
}

function OrderSummary({ items }) {
  const { totals: price, priced } = useCartPricing(items)
  const short = price.short[0]
  const more = items.length - SHOWN_LINES
  return (
    <section className="agent-summary" aria-label="Resumen del pedido">
      <ul className="agent-summary-lines">
        {items.slice(0, SHOWN_LINES).map(({ product, qty }) => (
          <li key={lineKey(product)}>
            <span>
              {qty} × {product.name}
            </span>
            <b>{formatPrice(parsePrice(product.price) * qty)}</b>
          </li>
        ))}
        {more > 0 && <li className="agent-summary-more">y {more} más</li>}
      </ul>
      <dl className="agent-summary-rows">
        <Row label="Productos" value={formatPrice(price.subtotal)} />
        <Row
          label={priced.length > 1 ? `Envío (${priced.length} pedidos)` : 'Envío'}
          value={price.delivery === 0 ? 'Gratis con Pro' : formatPrice(price.delivery)}
        />
        <Row label="Tarifa de servicio" value={formatPrice(price.service)} />
        <Row label="Propina" value={formatPrice(price.tip)} />
        <Row label="Total" value={formatPrice(price.total)} total />
      </dl>
      <p className="agent-summary-eta">{ETA}</p>
      {short && (
        <p className="agent-summary-note">
          Te faltan {formatPrice(short.missing)} para hacer el pedido en {short.store || 'la tienda'}.
        </p>
      )}
      <p className="agent-summary-note">
        Lo que el catálogo no trae del envío y la tarifa, la propina y el tiempo son de ejemplo; los créditos y cupones
        se eligen en el pago. Nada se pide hasta que lo confirmes ahí.
      </p>
    </section>
  )
}

function Row({ label, value, total = false }) {
  return (
    <div className={total ? 'is-total' : undefined}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}

/** El último pedido de la demo: su estado y cuánto falta (la misma línea de tiempo del seguimiento), y su seguimiento. */
export function LastOrderCard({ onTrack }) {
  const order = useOrders()?.orders[0]
  const [now] = useState(() => Date.now()) // la hora en que Mochi respondió (como el seguimiento al abrirse)
  if (!order) return <p className="agent-card-note">Todavía no tienes pedidos en esta demo.</p>
  const seconds = (now - order.placedAt) / 1000
  const flow = flowFor(order) // los pasos de su vertical, como en el seguimiento
  const minutes = isDelivered(seconds) ? 0 : minutesLeft(seconds, flow)
  const units = order.items.reduce((sum, item) => sum + (item.qty ?? 1), 0)
  return (
    <section className="agent-summary agent-order" aria-label="Tu último pedido">
      <p className="agent-order-title">
        <strong>Tu último pedido</strong>
        {order.stores.length > 0 && <small>{order.stores.join(', ')}</small>}
      </p>
      <p className="agent-order-status">
        {flow.steps[stepAt(seconds, flow)].label}
        {minutes > 0 && ` · llega en ${minutes} min`}
      </p>
      <p className="agent-summary-note">
        {units} {units === 1 ? 'producto' : 'productos'} · {formatPrice(order.total)}
      </p>
      <button type="button" className="agent-msg-action tap" onClick={() => onTrack(order.id)}>
        Ver seguimiento →
      </button>
    </section>
  )
}
