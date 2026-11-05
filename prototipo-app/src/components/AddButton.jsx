import { useLayoutEffect, useRef } from 'react'
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
  const root = useRef(null) // "Agregar X" con el botón cerrado
  const plus = useRef(null) // "Agregar uno de X" con el contador
  const shownQty = useRef(qty)
  const keepFocus = useRef(false)

  // Al abrirse o cerrarse, el control con el foco desaparece (o deja de ser un botón): el foco pasa al que queda en su
  // lugar, "+" al abrir y "Agregar X" al cerrar. Solo si el foco estaba aquí (se anota al tocarlo o con una tecla).
  useLayoutEffect(() => {
    const opened = shownQty.current === 0 && qty > 0
    const closed = shownQty.current > 0 && qty === 0
    shownQty.current = qty
    const here =
      keepFocus.current && (root.current?.contains(document.activeElement) || document.activeElement === document.body)
    keepFocus.current = false
    if (!here) return
    if (opened) plus.current?.focus()
    else if (closed) root.current?.focus()
  }, [qty])

  const noteFocus = (e) => {
    if (e.key && e.key !== 'Enter' && e.key !== ' ') return // un Tab no lo activa
    keepFocus.current = e.currentTarget.contains(document.activeElement)
  }

  const stop = (handler) => (e) => {
    e.stopPropagation()
    handler(product)
  }

  if (qty === 0) {
    return (
      <span
        ref={root}
        onClickCapture={noteFocus}
        onKeyDownCapture={noteFocus}
        className={`add-button ${className}`}
        aria-label={`Agregar ${product.name}`}
        {...pressable(stop(addFirst))}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 4v16M4 12h16" stroke="#fff" strokeWidth="3.4" strokeLinecap="round" />
        </svg>
      </span>
    )
  }

  return (
    <span
      ref={root}
      onClickCapture={noteFocus}
      onKeyDownCapture={noteFocus}
      className={`add-button is-open ${className}`}
    >
      <span aria-label={`Quitar uno de ${product.name}`} {...pressable(stop(remove))}>
        −
      </span>
      <strong aria-live="polite">{qty}</strong>
      <span ref={plus} aria-label={`Agregar uno de ${product.name}`} {...pressable(stop(add))}>
        +
      </span>
    </span>
  )
}
