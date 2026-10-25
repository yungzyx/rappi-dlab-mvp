import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { loadStored, saveStored } from './storage'

// El carro sobrevive a una recarga (líneas, id y notas), como los pedidos.
const STORAGE_KEY = 'rappi-proto-cart'

const newCartId = () => `c-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`

const CartContext = createContext(null)

/** "$10.990" → 10990 (precios chilenos con punto de miles). */
export function parsePrice(text) {
  return Number(String(text).replace(/[^\d]/g, '')) || 0
}

export function formatPrice(value) {
  return `$${value.toLocaleString('es-CL')}`
}

/**
 * Clave de una línea: la oferta. Un producto del catálogo de la API ("cat-<id>") se vende en varias tiendas con el mismo
 * id: cada tienda va en su propia línea. La tienda es su `storeId`; la vertical no cuenta, porque depende de la pantalla
 * (Lider Big llega como `grocery` desde una oferta y como `express` desde su página) y partiría el mismo producto en dos
 * líneas y dos pedidos. Sin `storeId` (productos locales), la oferta es producto + vertical + nombre de la tienda.
 */
export const lineKey = (product) =>
  product.storeId != null
    ? `${product.id}|${product.storeId}`
    : `${product.id}|${product.vertical ?? ''}|${product.store ?? ''}`

const isLine = (line) =>
  line && typeof line === 'object' && line.product?.id != null && Number.isInteger(line.qty) && line.qty > 0
const isStoredCart = (value) =>
  value &&
  typeof value === 'object' &&
  typeof value.id === 'string' &&
  value.lines &&
  typeof value.lines === 'object' &&
  Object.values(value.lines).every(isLine)

// Un carro guardado con las claves de antes (id|vertical|tienda) vuelve a la clave de hoy, y las líneas que ahora son la
// misma oferta se suman: así agregar el producto otra vez no abre una línea nueva.
const rekeyed = (lines) =>
  Object.values(lines).reduce((byKey, line) => {
    const key = lineKey(line.product)
    const same = byKey[key]
    byKey[key] = same
      ? {
          ...same,
          qty: same.qty + line.qty,
          fromSuggestion: Boolean(same.fromSuggestion || line.fromSuggestion),
          note: same.note ?? line.note,
        }
      : line
    return byKey
  }, {})

const loadCart = () => {
  const stored = loadStored(STORAGE_KEY, isStoredCart, null)
  return stored ? { id: stored.id, lines: rekeyed(stored.lines) } : { id: newCartId(), lines: {} }
}

/** Carrito del prototipo: ofertas con su cantidad. Se guarda en el navegador para sobrevivir a una recarga. */
export function CartProvider({ children }) {
  const [initial] = useState(loadCart)
  const [lines, setLines] = useState(initial.lines)
  const [cartId, setCartId] = useState(initial.id)

  useEffect(() => {
    saveStored(STORAGE_KEY, { id: cartId, lines })
  }, [cartId, lines])

  // `delta` sobre el estado vigente: dos toques rápidos suman 2 aunque el render aún no se actualice.
  const change = useCallback((product, delta) => {
    const key = lineKey(product)
    setLines((prev) => {
      const qty = (prev[key]?.qty ?? 0) + delta
      const { [key]: _removed, ...rest } = prev
      // Si alguna unidad vino de una sugerencia, la línea lo recuerda (no la pisa un "+" desde otra tarjeta).
      const fromSuggestion = Boolean(prev[key]?.fromSuggestion || product.fromSuggestion)
      const note = prev[key]?.note
      return qty > 0 ? { ...rest, [key]: { product, qty, fromSuggestion, note } } : rest
    })
  }, [])

  // Nota para la tienda (hoja de producto): vive en la línea y se va con ella.
  const setNote = useCallback((product, note) => {
    const key = lineKey(product)
    setLines((prev) => (prev[key] ? { ...prev, [key]: { ...prev[key], note: note || undefined } } : prev))
  }, [])

  const value = useMemo(() => {
    const items = Object.values(lines)
    const count = items.reduce((sum, line) => sum + line.qty, 0)
    const total = items.reduce((sum, line) => sum + line.qty * parsePrice(line.product.price), 0)
    return {
      id: cartId,
      items,
      count,
      total,
      qtyOf: (product) => lines[lineKey(product)]?.qty ?? 0,
      noteOf: (product) => lines[lineKey(product)]?.note ?? '',
      add: (product) => change(product, 1),
      remove: (product) => change(product, -1),
      setNote,
      // Tras un pedido, el carro siguiente es otro (el abandono se mide por carro).
      clear: () => {
        setLines({})
        setCartId(newCartId())
      },
    }
  }, [lines, change, setNote, cartId])

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>
}

export const useCart = () => useContext(CartContext)
