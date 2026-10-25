import BasketMinimum from '../../components/BasketMinimum'
import ProductRow from '../../components/ProductRow'
import { lineKey, formatPrice } from '../../state/CartContext'
import { needsPrescription } from './restrictions'

/**
 * Una canasta del checkout: una tienda, que es un pedido. Sus productos, su compra mínima, su envío (con Pro, gratis
 * sobre el mínimo de Pro) y, si es de Farmacia, el aviso de receta. `basket` viene con sus montos (pricing.js).
 */
export default function CheckoutBasket({ basket, isPro, pickup, prescription, onPrescription }) {
  return (
    <section className="checkout-basket" aria-label={`Pedido de ${basket.store || 'la tienda'}`}>
      <h3 className="checkout-basket-store">{basket.store || 'Tienda'}</h3>
      <BasketMinimum basket={basket} />
      <ul className="checkout-items">
        {basket.lines.map(({ product }) => (
          <ProductRow key={lineKey(product)} product={product} />
        ))}
      </ul>
      {!pickup && <DeliveryLine basket={basket} isPro={isPro} />}
      {needsPrescription(basket) && (
        <label className="checkout-prescription">
          <input type="checkbox" checked={prescription} onChange={(e) => onPrescription(e.target.checked)} />
          <span>
            <strong>Tengo la receta médica</strong>
            <small>
              Algunos productos de Farmacia necesitan receta. En Rappi se adjunta antes de pagar; en esta demo solo
              confirmas que la tienes (no se sube nada).
            </small>
          </span>
        </label>
      )}
    </section>
  )
}

/** El envío de la canasta y de dónde sale: del catálogo, o un supuesto por vertical («de ejemplo»). */
function DeliveryLine({ basket, isPro }) {
  const example = basket.terms.delivery.basis === 'supuesto' ? ' · envío de ejemplo' : ''
  if (isPro && basket.delivery === 0)
    return (
      <p className="checkout-delivery is-free">
        Envío gratis con Pro <s>{formatPrice(basket.fullDelivery)}</s>
        <span className="checkout-basis">{example}</span>
      </p>
    )
  return (
    <p className="checkout-delivery">
      Envío {formatPrice(basket.delivery)}
      <span className="checkout-basis">{example}</span>
      {isPro && basket.proMissing > 0 && (
        <span className="checkout-pro-missing">
          Te faltan {formatPrice(basket.proMissing)} para envío gratis con Pro
        </span>
      )}
    </p>
  )
}
