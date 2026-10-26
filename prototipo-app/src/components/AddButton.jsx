import { useAddToCart } from '../hooks/useAddToCart'
import { pressable } from './pressable'
import './add-button.css'

/**
 * Botón verde "+" de los productos. Con unidades en el carrito se abre como contador "− 2 +". `beforeAdd(product)`
 * (opcional): una promesa que dice si se puede agregar la primera unidad (la fila de una tienda revisa si está agotado).
 */
export default function AddButton({ product, className = '', beforeAdd }) {
  const { add, remove, qtyOf } = useAddToCart()
  const qty = qtyOf(product)
  const addFirst = (item) => (beforeAdd ? beforeAdd(item).then((ok) => ok && add(item)) : add(item))

  const stop = (handler) => (e) => {
    e.stopPropagation()
    handler(product)
  }

  if (qty === 0) {
    return (
      <span className={`add-button ${className}`} aria-label={`Agregar ${product.name}`} {...pressable(stop(addFirst))}>
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
