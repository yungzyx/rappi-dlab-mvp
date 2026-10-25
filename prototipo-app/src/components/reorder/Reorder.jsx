import { useEffect, useId, useState } from 'react'
import { envelope } from '../../api/attribution'
import { cartEventFields } from '../../api/orders'
import { REORDER_ORIGIN, availability, canReorder, reorderLines, reorderPlan } from '../../api/reorder'
import { formatPrice, lineKey, parsePrice, useCart } from '../../state/CartContext'
import { useEvents } from '../../state/EventsContext'
import { useOrders } from '../../state/OrdersContext'
import { isDelivered, secondsSince } from '../../screens/tracking/progress'
import HScroll from '../HScroll'
import Img from '../Img'
import { ProductCard } from '../ProductCard'
import Sheet from '../Sheet'
import { useToast } from '../Toast'
import './reorder.css'

// Fuera del proveedor de pedidos (tests de pantallas sueltas) no hay pedidos.
const NO_ORDERS = []
const units = (lines) => lines.reduce((sum, { qty }) => sum + qty, 0)

/**
 * «Pídelo de nuevo» de un pedido (Mis pedidos, el pedido entregado, la Home de «Rappi hoy»): revisa qué sigue a la venta
 * hoy en la misma tienda y lo muestra en una hoja, con lo que ya no está marcado «No disponible». Si el carro ya tiene
 * productos, pregunta si mantenerlos. Agregar registra `reorder` (con su lugar: `surface`, «pidelo-de-nuevo» y la
 * posición del pedido en su lista) y un `cart_add` por línea. `onDone` se llama después de agregar (el seguimiento no
 * muestra la barra del carro: ahí lleva al checkout).
 */
export function ReorderButton({ order, surface, position = 0, className = '', onDone }) {
  const cart = useCart()
  const events = useEvents()
  const toast = useToast()
  const [plan, setPlan] = useState(null)
  const [open, setOpen] = useState(false)
  const [checking, setChecking] = useState(false)
  if (!canReorder(order)) return null

  const check = async () => {
    setChecking(true)
    try {
      const lines = reorderLines(order)
      setPlan(reorderPlan(lines, await availability(lines), { surface }))
      setOpen(true)
    } catch {
      toast('No pudimos revisar qué sigue disponible. Intenta de nuevo.')
    } finally {
      setChecking(false)
    }
  }

  const confirm = (keep) => {
    const hadItems = cart.count > 0
    if (hadItems && !keep) {
      // Vaciar el carro de antes con sus salidas (una por línea, con sus unidades), sin cambiar de carro.
      for (const { product, qty } of cart.items) {
        events.track('cart_remove', cartEventFields(product, cart.id, { qty }))
        for (let n = 0; n < qty; n += 1) cart.remove(product)
      }
    }
    for (const { product, qty } of plan.available) {
      for (let n = 0; n < qty; n += 1) cart.add(product)
      events.track('cart_add', cartEventFields(product, cart.id, { qty }))
    }
    events.track('reorder', {
      ...envelope({ surface, origin: REORDER_ORIGIN, position }),
      cart_id: cart.id,
      value: plan.available.reduce((sum, { product, qty }) => sum + parsePrice(product.price) * qty, 0) || undefined,
      payload: {
        available: plan.available.length,
        unavailable: plan.unavailable.length,
        ...(hadItems ? { kept: keep } : {}),
      },
    })
    setOpen(false)
    toast(`Agregamos ${units(plan.available)} ${units(plan.available) === 1 ? 'producto' : 'productos'} a tu carro`)
    onDone?.()
  }

  const total = plan?.available.reduce((sum, { product, qty }) => sum + parsePrice(product.price) * qty, 0) ?? 0
  return (
    <>
      <button type="button" className={`reorder-button tap ${className}`} disabled={checking} onClick={check}>
        {checking ? 'Revisando…' : 'Pídelo de nuevo'}
      </button>
      <Sheet open={open} onClose={() => setOpen(false)} title="Pídelo de nuevo">
        {plan && (
          <>
            <ul className="reorder-lines">
              {[...plan.available, ...plan.unavailable].map(({ product, qty }) => {
                const missing = plan.unavailable.some((line) => line.product === product)
                return (
                  <li key={lineKey(product)} className={missing ? 'reorder-line is-missing' : 'reorder-line'}>
                    <Img src={product.img} />
                    <span className="reorder-line-text">
                      <strong>
                        {qty} × {product.name}
                      </strong>
                      <span>{product.store}</span>
                    </span>
                    {missing ? (
                      <span className="reorder-missing">No disponible</span>
                    ) : (
                      <b>{formatPrice(parsePrice(product.price) * qty)}</b>
                    )}
                  </li>
                )
              })}
            </ul>
            {plan.available.length === 0 ? (
              <p className="reorder-note">Ninguno de estos productos está a la venta hoy en esa tienda.</p>
            ) : (
              <>
                <p className="reorder-note">Con el precio de hoy en la misma tienda.</p>
                {cart.count > 0 ? (
                  <div className="reorder-keep">
                    <p>Tu carro ya tiene productos. ¿Los mantienes?</p>
                    <button type="button" className="reorder-confirm tap" onClick={() => confirm(true)}>
                      Mantener y agregar · {formatPrice(total)}
                    </button>
                    <button type="button" className="reorder-secondary tap" onClick={() => confirm(false)}>
                      Vaciar el carro y agregar
                    </button>
                  </div>
                ) : (
                  <button type="button" className="reorder-confirm tap" onClick={() => confirm(true)}>
                    Agregar al carro · {formatPrice(total)}
                  </button>
                )}
              </>
            )}
          </>
        )}
      </Sheet>
    </>
  )
}

/** Lo que la persona ya compró en una tienda (sus pedidos de la demo, del más nuevo al más viejo), una vez cada uno. */
export function boughtAt(orders, storeId) {
  const seen = new Map()
  for (const order of orders)
    for (const line of reorderLines(order))
      if (String(line.product.storeId) === String(storeId) && !seen.has(lineKey(line.product)))
        seen.set(lineKey(line.product), { product: line.product, qty: 1 })
  return [...seen.values()]
}

const MAX_CAROUSEL = 10

/**
 * El carrusel «Pídelo de nuevo» de una tienda: lo que la persona ya compró ahí y sigue a la venta, con el precio de hoy.
 * Cada producto lleva su lugar (la tienda, «pidelo-de-nuevo» y su posición): agregarlo es un `cart_add` de ese bloque.
 * Sin compras ahí (o si nada sigue a la venta, o la API no contesta) no se muestra.
 */
export function ReorderCarousel({ storeId, onOpenStore }) {
  const orders = useOrders()?.orders ?? NO_ORDERS
  const lines = storeId == null ? [] : boughtAt(orders, storeId).slice(0, MAX_CAROUSEL)
  const key = lines.map(({ product }) => lineKey(product)).join(',')
  const [products, setProducts] = useState([])

  useEffect(() => {
    if (!key) return undefined
    let current = true
    availability(lines).then(
      (replies) =>
        current && setProducts(reorderPlan(lines, replies, { surface: 'store' }).available.map((l) => l.product)),
      () => {},
    )
    return () => {
      current = false
    }
    // Las líneas cambian solo con la clave (lo que compró ahí).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  if (!key || products.length === 0) return null
  return (
    <section className="reorder-carousel" aria-label="Pídelo de nuevo">
      <h2 className="section-title store-title">Pídelo de nuevo</h2>
      <p className="reorder-carousel-note">Lo que ya pediste aquí, con el precio de hoy.</p>
      <HScroll className="reorder-items">
        {products.map((product) => (
          <div key={lineKey(product)} className="reorder-item">
            <ProductCard product={product} onOpenStore={onOpenStore} />
          </div>
        ))}
      </HScroll>
    </section>
  )
}

const HOME_ORDERS = 3
const HOME_TICK_MS = 2000

/**
 * «Pídelo de nuevo» en la Home de «Rappi hoy» (en el prototipo final la Home tiene «¿Repetimos?»): los últimos pedidos
 * entregados que se pueden volver a pedir, cada uno con su botón. Sin ninguno, no se ve. La Home queda montada bajo el
 * seguimiento: mientras haya un pedido en curso, revisa cada 2 s si ya se entregó.
 */
export function ReorderHomeRow() {
  const orders = useOrders()?.orders ?? NO_ORDERS
  const titleId = useId()
  const [now, setNow] = useState(() => Date.now())
  const pending = orders.some((order) => !isDelivered(secondsSince(order, now)))
  useEffect(() => {
    if (!pending) return undefined
    const timer = setInterval(() => setNow(Date.now()), HOME_TICK_MS)
    return () => clearInterval(timer)
  }, [pending])
  const done = orders
    .filter((order) => isDelivered(secondsSince(order, now)) && canReorder(order))
    .slice(0, HOME_ORDERS)
  if (done.length === 0) return null
  return (
    <section className="reorder-home" aria-labelledby={titleId}>
      <h2 id={titleId} className="section-title home-list-title">
        Pídelo de nuevo
      </h2>
      <HScroll className="home-cards home-cards--list">
        {done.map((order, position) => (
          <div key={order.id} className="reorder-home-card">
            <Img src={order.items[0]?.img} />
            <strong>{order.stores.join(', ') || 'Tu pedido'}</strong>
            <span>
              {units(order.items)} {units(order.items) === 1 ? 'producto' : 'productos'} · {formatPrice(order.total)}
            </span>
            <ReorderButton order={order} surface="home" position={position} />
          </div>
        ))}
      </HScroll>
    </section>
  )
}
