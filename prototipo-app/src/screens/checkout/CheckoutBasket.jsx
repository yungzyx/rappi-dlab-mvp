import BasketMinimum from '../../components/BasketMinimum'
import ProductRow from '../../components/ProductRow'
import { lineKey, formatPrice } from '../../state/CartContext'
import { DEFAULT_SUBSTITUTION, SUBSTITUTIONS, SUBSTITUTION_VERTICALS } from '../tracking/liveChanges'
import { needsPrescription } from './restrictions'

/**
 * Una canasta del checkout: una tienda, que es un pedido. Sus productos, su compra mínima, su envío (con Pro, gratis
 * sobre el mínimo de Pro), si es de Farmacia el aviso de receta y, en el Súper y Turbo, qué hacer si un producto se
 * agota (por línea: `substitutionOf` y `onSubstitution`). `basket` viene con sus montos (pricing.js).
 */
export default function CheckoutBasket({
  basket,
  isPro,
  pickup,
  prescription,
  onPrescription,
  substitutionOf,
  onSubstitution,
}) {
  const asks = SUBSTITUTION_VERTICALS.has(basket.vertical) && onSubstitution
  return (
    <section className="checkout-basket" aria-label={`Pedido de ${basket.store || 'la tienda'}`}>
      <h3 className="checkout-basket-store">{basket.store || 'Tienda'}</h3>
      <BasketMinimum basket={basket} />
      <ul className="checkout-items">
        {basket.lines.map(({ product }) => (
          <ProductRow key={lineKey(product)} product={product} />
        ))}
      </ul>
      {asks && (
        <div className="checkout-substitutions">
          <p>
            <strong>Si un producto se agota</strong>
            <small>Tu shopper sigue lo que elijas para cada uno.</small>
          </p>
          {basket.lines.map(({ product }) => (
            <label key={lineKey(product)} className="checkout-substitution">
              <span>{product.name}</span>
              <select
                aria-label={`Si se agota ${product.name}`}
                value={substitutionOf(product) ?? DEFAULT_SUBSTITUTION}
                onChange={(e) => onSubstitution(product, e.target.value)}
              >
                {SUBSTITUTIONS.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
      )}
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

/** El envío de la canasta y de dónde sale: del catálogo, o un supuesto por vertical ("de ejemplo"). */
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
