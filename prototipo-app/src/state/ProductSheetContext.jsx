import { createContext, useCallback, useContext, useMemo, useState } from 'react'

// Sin proveedor (tests sueltos de una tarjeta) tocar un producto no hace nada.
const ProductSheetContext = createContext({ open: () => {}, close: () => {}, current: null })

/** Producto abierto en la hoja inferior. `open(product, { onOpenStore })`: la hoja ofrece «Ver tienda» si viene y el producto sabe su tienda (`storeId`). */
export function ProductSheetProvider({ children }) {
  const [current, setCurrent] = useState(null)
  const [isOpen, setIsOpen] = useState(false)

  const open = useCallback((product, { onOpenStore } = {}) => {
    setCurrent({ product, onOpenStore })
    setIsOpen(true)
  }, [])
  // Al cerrar, el producto se conserva hasta que termine la animación de salida de la hoja.
  const close = useCallback(() => setIsOpen(false), [])

  const value = useMemo(() => ({ current, isOpen, open, close }), [current, isOpen, open, close])
  return <ProductSheetContext.Provider value={value}>{children}</ProductSheetContext.Provider>
}

export const useProductSheet = () => useContext(ProductSheetContext)
