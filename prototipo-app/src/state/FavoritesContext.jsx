import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { loadStored, saveStored } from './storage'

const STORAGE_KEY = 'rappi-proto-favorites'
const isStoredStores = (value) =>
  Array.isArray(value) && value.every((store) => store && typeof store === 'object' && typeof store.name === 'string')

// Un favorito sin id numérico es de una tienda local, de cuando las tiendas no salían de la base: ya no existe, y su
// enlace llevaría a «Esta tienda no está en el catálogo».
const inCatalog = (store) => Number.isInteger(store.id)

// Sin el menú real (`sections`): la pestaña solo necesita nombre y foto, y el catálogo completa el resto al abrirla.
const light = (stores) => stores.map(({ sections: _sections, ...store }) => store)

/** ¿Es la misma tienda? Por `id` cuando las dos lo traen (dos sucursales pueden llamarse igual); si no, por nombre. */
const sameStore = (a, b) => (a.id != null && b.id != null ? String(a.id) === String(b.id) : a.name === b.name)

const FavoritesContext = createContext(null)

/** Tiendas que el usuario marca con ♥ en la página de tienda; se suman a "Favorite stores" y se guardan en el navegador. */
export function FavoritesProvider({ children }) {
  const [stores, setStores] = useState(() => loadStored(STORAGE_KEY, isStoredStores, []).filter(inCatalog))

  useEffect(() => {
    saveStored(STORAGE_KEY, light(stores))
  }, [stores])

  const value = useMemo(
    () => ({
      stores,
      isFavorite: (store) => stores.some((saved) => sameStore(saved, store)),
      toggle: (store) =>
        setStores((prev) =>
          prev.some((saved) => sameStore(saved, store))
            ? prev.filter((saved) => !sameStore(saved, store))
            : [store, ...prev],
        ),
    }),
    [stores],
  )

  return <FavoritesContext.Provider value={value}>{children}</FavoritesContext.Provider>
}

export const useFavorites = () => useContext(FavoritesContext)
