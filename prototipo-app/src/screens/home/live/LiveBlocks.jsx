import OfferWhy from '../../../components/assistant/OfferWhy'
import HScroll from '../../../components/HScroll'
import { ProductCard } from '../../../components/ProductCard'
import { useRovingGroup } from '../../../hooks/useRovingGroup'
import { storeOfProduct } from '../../../api/catalog'
import { basketsOf, storeCount } from '../../../api/orders'
import { pricedBasket } from '../../checkout/pricing'
import { formatPrice, parsePrice } from '../../../state/CartContext'
import { VERTICAL_NAMES } from '../../../data/verticals'

/** Abre la tienda de un producto o plato que el agente ofreció (por su id; sin él, con el nombre y el logo que trae). */
export function openItem(product, push) {
  return push('store', {
    store:
      product.storeId != null
        ? storeOfProduct(product)
        : { name: product.store, img: product.storeLogo ?? product.img, logo: true },
    item: product,
  })
}

/** Lo que dice Mochi al agregar un kit: un pedido es de una tienda, así que uno de varias tiendas no "llega todo junto". */
export function kitAddedText(kit) {
  const stores = storeCount(kit)
  return stores > 1
    ? `¡Listo! Está en tu carro: llega en ${stores} pedidos, uno por tienda 🛵`
    : '¡Listo! Está en tu carro 🛵 Velo abajo.'
}

/**
 * Las tiendas del kit que no llegan a su compra mínima: `[{ store, missing, example }]`. La que marca la API
 * (`belowMin`, con el mínimo del catálogo) y, si el catálogo no sabe el mínimo de una tienda, el supuesto del carro
 * (`pricedBasket`, rotulado de ejemplo). El kit no suma productos para llegar: lo dice.
 */
export function kitShortStores(kit, stores = []) {
  return basketsOf(kit.map((product) => ({ product, qty: 1 }))).flatMap((basket) => {
    const known = stores.find((entry) => entry.storeId != null && entry.storeId === basket.storeId)
    if (known?.minOrder != null)
      return known.belowMin ? [{ store: basket.store, missing: known.missing, example: false }] : []
    const { missing } = pricedBasket(basket, null)
    return missing > 0 ? [{ store: basket.store, missing, example: true }] : []
  })
}

/** "En X te faltan $Y para la compra mínima (de ejemplo).", una tienda tras otra. */
const shortText = (short) =>
  short
    .map(
      ({ store, missing, example }) =>
        `En ${store} te faltan ${formatPrice(missing)} para la compra mínima${example ? ' (de ejemplo)' : ''}.`,
    )
    .join(' ')

/** "¿Qué plan tienes hoy?": las ocasiones salen de la API y el agente arma, también con la API, un kit de varias verticales. */
export function PlanBlock({
  plans,
  plan,
  kit,
  kitReason,
  kitStores = [],
  added,
  onPick,
  onOpen,
  onAddKit,
  onCheckout,
}) {
  const total = (kit ?? []).reduce((sum, product) => sum + parsePrice(product.price), 0)
  const verticals = [...new Set((kit ?? []).map((product) => VERTICAL_NAMES[product.vertical] ?? product.vertical))]
  const stores = storeCount(kit ?? [])
  const short = kitShortStores(kit ?? [], kitStores)
  const chips = useRovingGroup(
    plans.length,
    plans.findIndex((option) => option.id === plan),
    (i) => onPick(plans[i].id),
  )
  return (
    <section className="live-card live-card--plan">
      <h2 className="live-plan-title">¿Qué plan tienes hoy?</h2>
      <div className="live-plan-chips" role="radiogroup" aria-label="Plan de hoy" onKeyDown={chips.onKeyDown}>
        {plans.map((option, i) => (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={plan === option.id}
            className={plan === option.id ? 'live-plan-chip is-active tap' : 'live-plan-chip tap'}
            onClick={() => onPick(option.id)}
            {...chips.itemProps(i)}
          >
            <span aria-hidden="true">{option.emoji}</span>
            {option.name}
            {option.reason && <small className="live-plan-chip-tag">Para ti</small>}
          </button>
        ))}
      </div>
      {kit?.length ? (
        <div key={plan} className="live-kit">
          <p className="live-kit-meta">
            Tu kit en {verticals.length} {verticals.length === 1 ? 'vertical' : 'verticales'}: {verticals.join(', ')}
            {stores > 1 && ` · ${stores} tiendas, un pedido por tienda`}
          </p>
          {short.length > 0 && <p className="live-kit-min">{shortText(short)}</p>}
          <OfferWhy reason={kitReason} origin="agent-plan" />
          <HScroll className="live-items">
            {kit.map((product, i) => (
              <div key={product.id} className="live-item" style={{ '--i': i }}>
                <ProductCard product={product} onOpenStore={() => onOpen(product)} impression />
              </div>
            ))}
          </HScroll>
          {added ? (
            <button type="button" className="live-kit-add is-added tap" onClick={onCheckout}>
              ✓ En tu carro · Ir a pagar
            </button>
          ) : (
            <button type="button" className="live-kit-add tap" onClick={onAddKit}>
              Agregar el kit · {formatPrice(total)}
            </button>
          )}
        </div>
      ) : (
        <p className="live-plan-empty">Elige uno y te armo todo de una, de las tiendas que hagan falta.</p>
      )}
    </section>
  )
}
