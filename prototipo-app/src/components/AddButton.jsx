import { useAddToCart } from '../hooks/useAddToCart'
import { pressable } from './pressable'
import './add-button.css'

/** Botón verde "+" de los productos. Con unidades en el carrito se abre como contador "− 2 +". */
export default function AddButton({ product, className = '' }) {
  const { add, remove, qtyOf } = useAddToCart()
  const qty = qtyOf(product)

  const stop = (handler) => (e) => {
    e.stopPropagation()
    handler(product)
  }

  if (qty === 0) {
    return (
      <span className={`add-button ${className}`} aria-label={`Agregar ${product.name}`} {...pressable(stop(add))}>
        <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 4v16M4 12h16" stroke="#fff" strokeWidth="3.4" strokeLinecap="round" />
        </svg>
      </span>
    )
  }

  return (
    <span className={`add-button is-open ${className}`}>
      <span aria-label={`Quitar uno de ${product.name}`} {...pressable(stop(remove))}>
        −
      </span>
      <strong aria-live="polite">{qty}</strong>
      <span aria-label={`Agregar uno de ${product.name}`} {...pressable(stop(add))}>
        +
      </span>
    </span>
  )
}
