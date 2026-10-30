import { useState } from 'react'
import { soldOutHere } from '../api/catalog'
import { productItem } from '../api/impressions'
import { useImpressions } from '../hooks/useImpressions'
import { useProductSheet } from '../state/ProductSheetContext'
import AddButton from './AddButton'
import Img from './Img'
import './product-card.css' // la marca +18 (.product-age) es la de ProductCard
import './product-row.css'

/**
 * Producto en formato lista (página de tienda y resultados del buscador). Tocarlo abre su hoja; el "+" va aparte.
 * Con `onOpenStore`, la hoja ofrece "Ver tienda". Con `impression`, la fila cuenta como vista en su lista cuando aparece
 * en pantalla (api/impressions.js). Con `checkStock` (los pasillos de una tienda), antes de agregar revisa si está
 * agotado ahí: agotado no se agrega, la fila dice "Agotado" y tocarla abre la ficha con los similares.
 */
export default function ProductRow({
  product,
  showStore = false,
  showDescription = false,
  onOpenStore,
  impression = false,
  checkStock = false,
}) {
  const sheet = useProductSheet()
  const watch = useImpressions()
  const [checkedOut, setCheckedOut] = useState(false)
  const soldOut = product.soldOut || checkedOut
  const beforeAdd = checkStock
    ? (item) =>
        soldOutHere(item).then((out) => {
          if (out) setCheckedOut(true)
          return !out
        })
    : undefined
  return (
    <li className="product-row" ref={impression ? watch(product, productItem(product)) : undefined}>
      <button type="button" className="product-row-main" onClick={() => sheet.open(product, { onOpenStore })}>
        <span className="product-row-text">
          <strong>{product.name}</strong>
          {showStore && <span className="product-row-store">{product.store}</span>}
          {showDescription && product.description && (
            <span className="product-row-description">{product.description}</span>
          )}
          <span className="product-row-prices">
            {soldOut ? <b className="product-row-soldout">Agotado</b> : <b>{product.price}</b>}
            {product.before && <s>{product.before}</s>}
            {product.discount && <span className="product-row-pct">{product.discount}</span>}
          </span>
        </span>
        <span className="product-row-media">
          <Img src={product.img} />
          {product.ageRestricted && (
            <span className="product-age" aria-label="Solo mayores de 18">
              +18
            </span>
          )}
        </span>
      </button>
      {!soldOut && <AddButton product={product} className="add-button--row" beforeAdd={beforeAdd} />}
    </li>
  )
}
