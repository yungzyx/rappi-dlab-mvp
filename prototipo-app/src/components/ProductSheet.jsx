import { useState } from 'react'
import { productStores } from '../api/catalog'
import { useApi } from '../api/useApi'
import { useAddToCart } from '../hooks/useAddToCart'
import { formatPrice, lineKey, parsePrice, useCart } from '../state/CartContext'
import { useProductSheet } from '../state/ProductSheetContext'
import { StoreLogo } from './ProductCard'
import Sheet from './Sheet'
import Img from './Img'
import './product-sheet.css'

/**
 * Hoja inferior de un producto (foto, descripción, cantidad, nota para la tienda). Se monta una vez en App. Un producto
 * del catálogo dice además en cuántas tiendas está (con precio, tiempo y envío: elegir otra la abre con esa tienda), si
 * quedan pocas unidades en la suya y, si ahí está agotado, ofrece productos similares de esa misma tienda.
 */
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

/** El producto en otra tienda de la comparación (su precio, su tienda y su lugar en la ficha). */
const inStore = (product, offer) => ({
  ...product,
  store: offer.store,
  storeId: offer.storeId,
  price: offer.price,
  before: offer.before,
  discount: undefined,
  vertical: offer.vertical,
  backendVertical: offer.backendVertical,
  placement: offer.placement,
})

function ProductDetail({ product, onOpenStore }) {
  const cart = useCart()
  const { add, remove } = useAddToCart()
  const { close, open } = useProductSheet()
  const comparable = product.entityType === 'catalog_item' && Boolean(product.entityId)
  const offers = useApi(
    () => (comparable ? productStores(product.entityId, product.storeId).catch(() => null) : null),
    [comparable, product.entityId, product.storeId],
  )
  const here = offers.data?.here
  const soldOut = here?.available === false
  const inCart = cart.qtyOf(product)
  const [qty, setQty] = useState(inCart || 1)
  const [note, setNote] = useState(() => cart.noteOf(product))
  const total = formatPrice(qty * parsePrice(product.price))

  const confirm = () => {
    // Cada unidad pasa por "agregar" o "quitar" como con el botón "+": mismos eventos y mismo aviso del agente.
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
        // "Ver tienda" abre la tienda por su id: sin `storeId` no hay a cuál ir y solo se muestra el nombre.
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
        {here?.lowStock && <span className="product-sheet-stock">Pocas unidades</span>}
      </p>

      {soldOut && <SoldOut similar={offers.data.similar} onOpen={(similar) => open(similar, { onOpenStore })} />}
      {offers.data?.count > 1 && (
        <StoreCompare
          count={offers.data.count}
          offers={offers.data.stores}
          current={product.storeId}
          onChoose={(offer) => open(inStore(product, offer))}
        />
      )}

      {!soldOut && (
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
      )}

      <label className="product-sheet-note">
        <span>Notas para la tienda</span>
        <textarea
          rows={2}
          placeholder="Opcional: sin cebolla, bien maduro…"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </label>

      <button type="button" className="product-sheet-confirm tap" onClick={confirm} disabled={soldOut}>
        {soldOut ? 'Agotado en esta tienda' : `${inCart > 0 ? 'Actualizar' : 'Agregar'} ${qty} · ${total}`}
      </button>
    </div>
  )
}

/**
 * "Disponible en N tiendas": cada tienda con su precio, tiempo y envío publicados, y las marcas "Mejor precio" y "Más
 * rápido" (si hay de dónde elegir). Tocar otra abre el producto con esa tienda.
 */
function StoreCompare({ count, offers, current, onChoose }) {
  const available = offers.filter((offer) => offer.available)
  return (
    <section className="product-compare" aria-label="Comparar tiendas">
      <h3>Disponible en {count} tiendas</h3>
      <ul>
        {available.map((offer) => {
          const here = offer.storeId === current
          return (
            <li key={offer.storeId}>
              <button
                type="button"
                className={here ? 'product-compare-row is-here' : 'product-compare-row tap'}
                aria-current={here ? 'true' : undefined}
                disabled={here}
                onClick={() => onChoose(offer)}
              >
                <img src={offer.logo} alt="" loading="lazy" />
                <span className="product-compare-store">
                  <strong>{offer.store}</strong>
                  <small>{[offer.eta, offer.fee && `Envío ${offer.fee}`].filter(Boolean).join(' · ')}</small>
                  <span className="product-compare-tags">
                    {here && <em>Esta tienda</em>}
                    {offer.bestPrice && <em className="is-price">Mejor precio</em>}
                    {offer.fastest && <em className="is-fast">Más rápido</em>}
                    {offer.lowStock && <em>Pocas unidades</em>}
                  </span>
                </span>
                <b>{offer.price}</b>
              </button>
            </li>
          )
        })}
      </ul>
      <p className="product-compare-note">
        Precio, tiempo y envío publicados por cada tienda en Rappi el día de la descarga.
      </p>
    </section>
  )
}

/** Agotado en esta tienda: los productos del mismo tipo que la tienda sí tiene (tocar uno lo abre). */
function SoldOut({ similar, onOpen }) {
  return (
    <section className="product-soldout" role="status">
      <p>
        <strong>Agotado en esta tienda</strong>
        {similar.length > 0 ? 'Mira estos productos similares:' : 'Por ahora no tiene uno parecido.'}
      </p>
      {similar.length > 0 && (
        <ul aria-label="Productos similares">
          {similar.map((item) => (
            <li key={item.id}>
              <button type="button" className="product-similar tap" onClick={() => onOpen(item)}>
                <Img src={item.img} />
                <span>{item.name}</span>
                <b>{item.price}</b>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
