import { useState } from 'react'
import { cartEventFields } from '../api/orders'
import { formatPrice, lineKey, parsePrice, useCart } from '../state/CartContext'
import { useEvents } from '../state/EventsContext'
import AddButton from './AddButton'
import Img from './Img'
import Sheet from './Sheet'
import './cart.css'

/** Barra flotante «Ver carro» (aparece con productos) y la hoja con el detalle del carro. */
export default function CartBar({ raised, push }) {
  const cart = useCart()
  const events = useEvents()
  const [open, setOpen] = useState(false)

  if (cart.count === 0 && !open) return null

  // Vaciar también se registra (una salida por línea, con sus unidades): si no, el panel lo contaría como abandono.
  const emptyCart = () => {
    cart.items.forEach(({ product, qty }) => events.track('cart_remove', cartEventFields(product, cart.id, { qty })))
    cart.clear()
  }

  const checkout = () => {
    setOpen(false)
    push('checkout')
  }

  return (
    <>
      {cart.count > 0 && (
        <button
          type="button"
          className={raised ? 'cart-bar is-raised tap' : 'cart-bar tap'}
          onClick={() => setOpen(true)}
        >
          <span className="cart-bar-count">{cart.count}</span>
          Ver carro
          <span className="cart-bar-total">{formatPrice(cart.total)}</span>
        </button>
      )}

      <Sheet open={open} onClose={() => setOpen(false)} title="Tu carro">
        {cart.items.length === 0 ? (
          <p className="cart-empty">Tu carro está vacío.</p>
        ) : (
          <>
            <ul className="cart-lines">
              {cart.items.map(({ product, qty }) => (
                <li key={lineKey(product)} className="cart-line">
                  <Img src={product.img} />
                  <span className="cart-line-text">
                    <strong>{product.name}</strong>
                    <span>{product.store}</span>
                    <span className="cart-line-price">{formatPrice(parsePrice(product.price) * qty)}</span>
                  </span>
                  <span className="cart-line-stepper">
                    <AddButton product={product} />
                  </span>
                </li>
              ))}
            </ul>
            <div className="cart-summary">
              <span>Subtotal</span>
              <strong>{formatPrice(cart.total)}</strong>
            </div>
            <button type="button" className="cart-checkout tap" onClick={checkout}>
              Ir a pagar
            </button>
            <button type="button" className="cart-clear" onClick={emptyCart}>
              Vaciar carro
            </button>
          </>
        )}
      </Sheet>
    </>
  )
}
