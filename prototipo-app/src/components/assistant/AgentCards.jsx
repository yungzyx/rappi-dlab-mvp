import { useEffect, useState } from 'react'
import { useCartPricing } from '../../screens/checkout/useCartPricing'
import { UNDO_MS } from '../../screens/checkout/undo'
import { orderTotal } from '../../screens/tracking/liveChanges'
import { etaMinutes, secondsSince, statusOf } from '../../screens/tracking/progress'
import { formatPrice, lineKey, parsePrice, useCart } from '../../state/CartContext'
import { useOrders } from '../../state/OrdersContext'
import { activeOrder } from '../ActiveOrderBar'

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

/**
 * "Pide lo de siempre en…" (api/autonomy.js): lo de siempre en esa tienda con el precio de hoy, calculado como en el
 * checkout pero sin propina (se elige al recibirlo). Con "Pedir por mí" (`status` de useAutoOrders): ya enviado con la
 * ventana de "Deshacer pedido" (`waiting`; el pedido sale al cerrarse), enviándose, hecho o deshecho. Sin permiso, o si
 * algo no cumple sus límites, se revisa antes (`review`, con el motivo) y lleva al checkout de siempre. `onShown` abre la
 * ventana cuando la tarjeta ya se ve (`revealed`: terminó de escribirse el texto de arriba).
 */
export function AutoOrderCard({ order, status, revealed, onShown, onUndo, onReview, onTurnOff, onTrack }) {
  const { totals: price } = useCartPricing(order.lines, { tip: 0 })
  useEffect(() => {
    if (revealed) onShown?.(order)
    // Solo cuando se ve: la ventana la lleva el panel, que sigue aunque la tarjeta se desmonte.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revealed])
  const state = status?.state ?? (order.mode === 'pedir' ? 'waiting' : 'review')
  const units = order.lines.reduce((sum, line) => sum + line.qty, 0)
  return (
    <section className="agent-summary agent-auto" aria-label="Lo de siempre">
      <p className="agent-order-title">
        <strong>Lo de siempre</strong>
        <small>{order.store.name}</small>
      </p>
      <ul className="agent-summary-lines">
        {order.lines.slice(0, SHOWN_LINES).map(({ product, qty }) => (
          <li key={lineKey(product)}>
            <span>
              {qty} × {product.name}
            </span>
            <b>{formatPrice(parsePrice(product.price) * qty)}</b>
          </li>
        ))}
        {order.lines.length > SHOWN_LINES && (
          <li className="agent-summary-more">y {order.lines.length - SHOWN_LINES} más</li>
        )}
      </ul>
      <dl className="agent-summary-rows">
        <Row label={`Productos (${units})`} value={formatPrice(price.subtotal)} />
        <Row label="Envío" value={price.delivery === 0 ? 'Gratis con Pro' : formatPrice(price.delivery)} />
        <Row label="Tarifa de servicio" value={formatPrice(price.service)} />
        <Row label="Total" value={formatPrice(price.total)} total />
      </dl>
      {state === 'waiting' && (
        <div className="agent-auto-window" role="status">
          <p>
            <strong>Pedido enviado.</strong> ¿Quieres modificar algo? Tienes unos segundos para deshacerlo.
          </p>
          <span className="agent-auto-bar" style={{ animationDuration: `${UNDO_MS}ms` }} />
          <button type="button" className="agent-msg-action is-strong tap" onClick={() => onUndo(order)}>
            Deshacer pedido
          </button>
        </div>
      )}
      {state === 'sending' && (
        <p className="agent-auto-window" role="status">
          Enviando tu pedido…
        </p>
      )}
      {state === 'sent' && (
        <div className="agent-auto-window" role="status">
          <p>
            <strong>Listo, lo pedí por ti</strong> con tu permiso
            {order.cap != null ? `, dentro de tu tope de ${formatPrice(order.cap)}` : ''}.
          </p>
          <button type="button" className="agent-msg-action tap" onClick={() => onTrack(status.orderId)}>
            Ver seguimiento →
          </button>
        </div>
      )}
      {state === 'undone' && (
        <div className="agent-auto-window" role="status">
          <p>Deshiciste el pedido: no se pidió nada.</p>
          <button type="button" className="agent-msg-action tap" onClick={() => onReview(order)}>
            Revisar y pagar →
          </button>
        </div>
      )}
      {state === 'review' && (
        <div className="agent-auto-window">
          {status?.reason && <p>Esta vez lo revisas tú: {status.reason}.</p>}
          <button type="button" className="agent-msg-action tap" onClick={() => onReview(order)}>
            Revisar y pagar →
          </button>
        </div>
      )}
      <p className="agent-summary-note">
        Tu último pedido en esta tienda, con el precio de hoy. Lo que el catálogo no trae del envío y la tarifa es de
        ejemplo; la propina la eliges al recibirlo.
        {order.mode === 'pedir' || status
          ? ' Solo pido lo de siempre, nunca alcohol, +18, farmacia, bebé ni salud.'
          : ''}
      </p>
      {/* Apagarlo en un toque; "Cómo pido por ti" (el ajuste) va en las acciones de la respuesta. */}
      {order.mode === 'pedir' && state !== 'review' && (
        <button type="button" className="agent-auto-off" onClick={onTurnOff}>
          Apagar "Pedir por mí"
        </button>
      )}
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

/** El pedido que muestra "Mi último pedido": el más reciente en curso (no uno cancelado después) o, sin uno, el último. */
export const shownOrder = (orders, now = Date.now()) => activeOrder(orders, now) ?? orders[0] ?? null

/**
 * "¿Dónde está mi pedido?": los pedidos de la última compra (uno por tienda), cada uno con su estado y cuánto falta (la
 * misma línea de tiempo del seguimiento: programado, atrasado o cancelado incluidos) y su seguimiento, donde se cancela
 * o se pide ayuda. Es una tarjeta con botones, no una conversación.
 */
export function LastOrderCard({ onTrack }) {
  const ordersState = useOrders()
  const [now] = useState(() => Date.now()) // la hora en que Mochi respondió (como el seguimiento al abrirse)
  const last = shownOrder(ordersState?.orders ?? [], now)
  if (!last) return <p className="agent-card-note">Todavía no tienes pedidos en esta demo.</p>
  const purchase = ordersState.siblingsOf ? ordersState.siblingsOf(last) : [last]
  return (
    <section className="agent-summary agent-order" aria-label="Tu último pedido">
      <p className="agent-order-title">
        <strong>{purchase.length > 1 ? `Tu última compra: ${purchase.length} pedidos` : 'Tu último pedido'}</strong>
        {purchase.length === 1 && last.stores.length > 0 && <small>{last.stores.join(', ')}</small>}
      </p>
      {purchase.map((order) => (
        <OrderLine key={order.id} order={order} now={now} named={purchase.length > 1} onTrack={onTrack} />
      ))}
    </section>
  )
}

function OrderLine({ order, now, named, onTrack }) {
  const status = statusOf(order, now)
  const minutes = status.kind === 'active' ? etaMinutes(order, secondsSince(order, now)) : 0
  const units = order.items.reduce((sum, item) => sum + (item.qty ?? 1), 0)
  return (
    <>
      {named && <p className="agent-order-store">{order.stores.join(', ') || 'Tienda'}</p>}
      <p className="agent-order-status">
        {status.label}
        {order.delay && status.kind === 'active' && ' · viene atrasado'}
        {minutes > 0 && ` · llega en ${minutes} min`}
      </p>
      <p className="agent-summary-note">
        {units} {units === 1 ? 'producto' : 'productos'} · {formatPrice(orderTotal(order))}
      </p>
      <button type="button" className="agent-msg-action tap" onClick={() => onTrack(order.id)}>
        Ver seguimiento →
      </button>
    </>
  )
}
