import { useEffect, useRef, useState } from 'react'
import BackButton from '../../components/BackButton'
import { health, sendOrder } from '../../api/client'
import { buildOrders, trackOrder } from '../../api/orders'
import { userId } from '../../api/user'
import ProductRow from '../../components/ProductRow'
import { useToast } from '../../components/Toast'
import { ChevronRight } from '../../components/Icons'
import { CardIcon, PinIcon } from '../../components/LineIcons'
import { useAddress } from '../../state/AddressContext'
import { sessionId, useEvents } from '../../state/EventsContext'
import { formatPrice, lineKey, useCart } from '../../state/CartContext'
import CheckoutSuggestion from './CheckoutSuggestion'
import { useOrders } from '../../state/OrdersContext'
import { useDemo } from '../../state/DemoContext'
import { DEFAULT_TIP, TIPS, priceBreakdown } from './pricing'
import './checkout.css'

const MODES = ['Envío', 'Retiro']

/** Checkout (funcionalidad agregada). El medio de pago es solo un texto de ejemplo: no se ingresan datos. */
export default function CheckoutScreen({ back, push }) {
  const cart = useCart()
  const address = useAddress()
  const orders = useOrders()
  const toast = useToast()
  const events = useEvents()
  const demo = useDemo()
  const [mode, setMode] = useState(MODES[0])
  const [tip, setTip] = useState(DEFAULT_TIP)
  const pickup = mode === 'Retiro'
  const price = priceBreakdown({ subtotal: cart.total, tip, pickup })
  const stores = [...new Set(cart.items.map(({ product }) => product.store).filter(Boolean))]

  // Abrir el checkout es iniciar el pago (quien vuelve atrás sin pagar es el abandono de esa etapa). Uno por carro
  // y vertical, porque el embudo del panel se mide por sesión y vertical; el ref evita contarlo dos veces en StrictMode.
  const started = useRef(new Set())
  const verticals = buildOrders(cart.items, {})
    .map((order) => order.vertical)
    .join(',')
  useEffect(() => {
    for (const vertical of verticals ? verticals.split(',') : []) {
      const key = `${cart.id}|${vertical}`
      if (started.current.has(key)) continue
      started.current.add(key)
      events.track('checkout_start', { cart_id: cart.id, vertical })
    }
  }, [cart.id, verticals, events])

  const placeOrder = () => {
    const pending = buildOrders(cart.items, {
      userId: userId(),
      sessionId: sessionId(),
      cartId: cart.id,
      mode: demo.isFinal ? 'propuesta' : 'actual',
    })
    // Registro para el panel (si la API está arriba). No bloquea el pedido de la demo. Antes salen los eventos en cola
    // (y se esperan los lotes en camino): el servidor les pone la hora al recibirlos, y checkout_start va primero.
    // Todo el camino cuenta como pedido en vuelo: «Olvidar» lo espera antes de borrar el perfil.
    trackOrder(
      events
        .flush()
        .then(() => events.settled())
        .then(() => health())
        .then((online) => online && Promise.all(pending.map((order) => sendOrder(order).catch(() => {})))),
    )
    const id = orders.place({
      stores,
      items: cart.items.map(({ product, qty }) => ({
        name: product.name,
        img: product.img,
        price: product.price,
        qty,
        // Con ellos el agente arma el próximo pedido al entregar (oferta `proximo_pedido`).
        entityType: product.entityType,
        entityId: product.entityId,
      })),
      total: price.total,
      pickup,
      address: address.selected.line,
    })
    cart.clear()
    // El seguimiento reemplaza al checkout en el historial: "volver" desde ahí no regresa a un carrito vacío.
    push('tracking', { orderId: id }, { swap: true })
  }

  if (cart.count === 0) {
    return (
      <div className="screen checkout">
        <CheckoutHeader back={back} />
        <p className="checkout-empty">Tu carro está vacío.</p>
        <button type="button" className="checkout-continue tap" onClick={back}>
          Seguir comprando
        </button>
      </div>
    )
  }

  return (
    <>
      <div className="screen checkout">
        <CheckoutHeader back={back} />

        <div className="checkout-modes" role="tablist">
          {MODES.map((option) => (
            <button
              key={option}
              type="button"
              role="tab"
              aria-selected={option === mode}
              className={option === mode ? 'checkout-mode is-active' : 'checkout-mode'}
              onClick={() => setMode(option)}
            >
              {option}
            </button>
          ))}
        </div>

        <button type="button" className="checkout-card tap" onClick={address.openSheet}>
          <PinIcon size={24} />
          <span>
            <strong>{pickup ? 'Retiro en tienda' : address.selected.label}</strong>
            <small>{pickup ? stores.join(', ') : address.selected.line}</small>
          </span>
          <ChevronRight size={18} />
        </button>
        <p className="checkout-eta">{pickup ? 'Listo en 15–20 min' : 'Llega en 25–35 min'}</p>

        <h2 className="checkout-title">Tu pedido</h2>
        <ul className="checkout-items">
          {cart.items.map(({ product }) => (
            <ProductRow key={lineKey(product)} product={product} showStore />
          ))}
        </ul>
        <CheckoutSuggestion />

        {!pickup && (
          <>
            <h2 className="checkout-title">Propina para tu Rappitendero</h2>
            <div className="checkout-tips">
              {TIPS.map((amount) => (
                <button
                  key={amount}
                  type="button"
                  className={amount === tip ? 'checkout-tip is-active' : 'checkout-tip'}
                  aria-pressed={amount === tip}
                  onClick={() => setTip(amount)}
                >
                  {amount === 0 ? 'Sin propina' : formatPrice(amount)}
                </button>
              ))}
            </div>
          </>
        )}

        <h2 className="checkout-title">Medio de pago</h2>
        <button type="button" className="checkout-card tap" onClick={() => toast('Medio de pago de ejemplo')}>
          <CardIcon size={24} />
          <span>
            <strong>Visa •••• 4242</strong>
            <small>Tarjeta de ejemplo</small>
          </span>
          <span className="checkout-change">Cambiar</span>
        </button>

        <dl className="checkout-summary">
          <SummaryRow label="Subtotal" value={formatPrice(price.subtotal)} />
          {!pickup && (
            <SummaryRow
              label="Envío"
              value={price.delivery === 0 ? 'Gratis con Pro' : formatPrice(price.delivery)}
              accent={price.delivery === 0}
            />
          )}
          <SummaryRow label="Tarifa de servicio" value={formatPrice(price.service)} />
          {!pickup && <SummaryRow label="Propina" value={formatPrice(price.tip)} />}
          <SummaryRow label="Total" value={formatPrice(price.total)} total />
        </dl>
      </div>

      {/* Fuera del contenedor con scroll para que quede fijo abajo */}
      <div className="checkout-footer">
        <button type="button" className="checkout-place tap" onClick={placeOrder}>
          Hacer pedido · {formatPrice(price.total)}
        </button>
      </div>
    </>
  )
}

function CheckoutHeader({ back }) {
  return (
    <header className="checkout-header">
      <BackButton className="round-button" onClick={back} />
      <h1>Tu pedido</h1>
    </header>
  )
}

function SummaryRow({ label, value, accent = false, total = false }) {
  return (
    <div className={total ? 'checkout-row is-total' : 'checkout-row'}>
      <dt>{label}</dt>
      <dd className={accent ? 'is-accent' : undefined}>{value}</dd>
    </div>
  )
}
