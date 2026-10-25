import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import { noteRecommendationClick } from '../api/attribution'
import { cartEventFields } from '../api/orders'
import { useEvents } from './EventsContext'

// Sin proveedor (tests sueltos de una tarjeta) tocar un producto no hace nada.
const ProductSheetContext = createContext({ open: () => {}, close: () => {}, current: null })

/**
 * Producto abierto en la hoja inferior. `open(product, { onOpenStore })`: la hoja ofrece «Ver tienda» si viene y el
 * producto sabe su tienda (`storeId`). Abrir un producto que vino de una recomendación (Mochi, «Para ti») es su
 * `recommendation_click`, con su lugar.
 */
export function ProductSheetProvider({ children }) {
  const [current, setCurrent] = useState(null)
  const [isOpen, setIsOpen] = useState(false)
  const { track } = useEvents()

  const open = useCallback(
    (product, { onOpenStore } = {}) => {
      noteRecommendationClick(track, product, cartEventFields(product))
      setCurrent({ product, onOpenStore })
      setIsOpen(true)
    },
    [track],
  )
  // Al cerrar, el producto se conserva hasta que termine la animación de salida de la hoja.
  const close = useCallback(() => setIsOpen(false), [])

  const value = useMemo(() => ({ current, isOpen, open, close }), [current, isOpen, open, close])
  return <ProductSheetContext.Provider value={value}>{children}</ProductSheetContext.Provider>
}

export const useProductSheet = () => useContext(ProductSheetContext)
