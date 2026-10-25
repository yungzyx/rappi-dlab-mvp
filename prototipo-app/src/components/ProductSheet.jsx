import { useState } from 'react'
import { useAddToCart } from '../hooks/useAddToCart'
import { formatPrice, lineKey, parsePrice, useCart } from '../state/CartContext'
import { useProductSheet } from '../state/ProductSheetContext'
import { StoreLogo } from './ProductCard'
import Sheet from './Sheet'
import Img from './Img'
import './product-sheet.css'

/** Hoja inferior de un producto (foto, descripción, cantidad, nota para la tienda). Se monta una vez en App. */
export default function ProductSheet() {
  const { current, isOpen, close } = useProductSheet()

  return (
    <Sheet open={isOpen} onClose={close} title={current?.product.name}>
      {current && (
        // La clave reinicia cantidad y nota al abrir otro producto.
        <ProductDetail key={lineKey(current.product)} product={current.product} onOpenStore={current.onOpenStore} />
      )}
    </Sheet>
  )
}

function ProductDetail({ product, onOpenStore }) {
  const cart = useCart()
  const { add, remove } = useAddToCart()
  const { close } = useProductSheet()
  const inCart = cart.qtyOf(product)
  const [qty, setQty] = useState(inCart || 1)
  const [note, setNote] = useState(() => cart.noteOf(product))
  const total = formatPrice(qty * parsePrice(product.price))

  const confirm = () => {
    // Cada unidad pasa por «agregar» o «quitar» como con el botón "+": mismos eventos y mismo aviso del agente.
    for (let i = inCart; i < qty; i += 1) add(product)
    for (let i = inCart; i > qty; i -= 1) remove(product)
    cart.setNote(product, note.trim())
    close()
  }

  const openStore = () => {
    close()
    onOpenStore()
  }

  return (
    <div className="product-sheet">
      <div className="product-sheet-media">
        <Img src={product.img} eager />
        {product.ageRestricted && (
          <span className="product-sheet-age" aria-label="Solo mayores de 18">
            +18
          </span>
        )}
      </div>
      {product.size && <p className="product-sheet-size">{product.size}</p>}
      {product.description && <p className="product-sheet-description">{product.description}</p>}

      {product.store &&
        // «Ver tienda» abre la tienda por su id: sin `storeId` no hay a cuál ir y solo se muestra el nombre.
        (onOpenStore && product.storeId ? (
          <button type="button" className="product-sheet-store tap" onClick={openStore}>
            <StoreLogo item={product} />
            <span>{product.store}</span>
            <small>Ver tienda ›</small>
          </button>
        ) : (
          <p className="product-sheet-store">
            <StoreLogo item={product} />
            <span>{product.store}</span>
          </p>
        ))}

      <p className="product-sheet-prices">
        <b>{product.price}</b>
        {product.before && <s>{product.before}</s>}
        {product.discount && <span className="product-sheet-pct">{product.discount}</span>}
      </p>

      <div className="product-sheet-qty" role="group" aria-label="Cantidad">
        <button
          type="button"
          aria-label={`Quitar uno de ${product.name}`}
          disabled={qty <= 1}
          onClick={() => setQty(qty - 1)}
        >
          −
        </button>
        <strong aria-live="polite">{qty}</strong>
        <button type="button" aria-label={`Agregar uno de ${product.name}`} onClick={() => setQty(qty + 1)}>
          +
        </button>
      </div>

      <label className="product-sheet-note">
        <span>Notas para la tienda</span>
        <textarea
          rows={2}
          placeholder="Opcional: sin cebolla, bien maduro…"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </label>

      <button type="button" className="product-sheet-confirm tap" onClick={confirm}>
        {inCart > 0 ? 'Actualizar' : 'Agregar'} {qty} · {total}
      </button>
    </div>
  )
}
