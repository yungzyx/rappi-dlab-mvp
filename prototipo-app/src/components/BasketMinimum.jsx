import { formatPrice } from '../state/CartContext'

/**
 * La compra mínima de una canasta (una tienda) con su barra: «Te faltan $X para hacer el pedido» mientras no llega, y
 * «¡Sin mínimo!» si la tienda no tiene. Un mínimo que no trae el catálogo es un supuesto: se rotula «de ejemplo».
 * `basket` es una canasta con sus montos (screens/checkout/pricing.js: pricedBasket).
 */
export default function BasketMinimum({ basket }) {
  const { value, basis } = basket.terms.minOrder
  const example = basis === 'supuesto' && <span className="basket-min-basis"> · mínimo de ejemplo</span>
  if (value === 0) return <p className="basket-min is-none">¡Sin mínimo de compra!{example}</p>
  const filled = Math.min(basket.subtotal, value)
  return (
    <div className={basket.missing > 0 ? 'basket-min is-short' : 'basket-min'}>
      <span
        className="basket-min-bar"
        role="progressbar"
        aria-label={`Compra mínima ${formatPrice(value)}`}
        aria-valuemin={0}
        aria-valuemax={value}
        aria-valuenow={filled}
      >
        <span style={{ width: `${Math.round((filled / value) * 100)}%` }} />
      </span>
      <p>
        {basket.missing > 0
          ? `Te faltan ${formatPrice(basket.missing)} para hacer el pedido`
          : `Compra mínima de ${formatPrice(value)} lista`}
        {example}
      </p>
    </div>
  )
}
