import { useProductSheet } from '../state/ProductSheetContext'
import AddButton from './AddButton'
import Img from './Img'
import './product-card.css' // la marca +18 (.product-age) es la de ProductCard
import './product-row.css'

/**
 * Producto en formato lista (página de tienda y resultados del buscador). Tocarlo abre su hoja; el "+" va aparte.
 * Con `onOpenStore`, la hoja ofrece «Ver tienda».
 */
export default function ProductRow({ product, showStore = false, showDescription = false, onOpenStore }) {
  const sheet = useProductSheet()
  return (
    <li className="product-row">
      <button type="button" className="product-row-main" onClick={() => sheet.open(product, { onOpenStore })}>
        <span className="product-row-text">
          <strong>{product.name}</strong>
          {showStore && <span className="product-row-store">{product.store}</span>}
          {showDescription && product.description && (
            <span className="product-row-description">{product.description}</span>
          )}
          <span className="product-row-prices">
            <b>{product.price}</b>
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
      <AddButton product={product} className="add-button--row" />
    </li>
  )
}
