import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { loadStored, saveStored } from './storage'

const STORAGE_KEY = 'rappi-proto-loyalty'

const LoyaltyContext = createContext(null)

/** Programa de puntos vinculado (uno a la vez, como explica la pantalla Loyalty); se recuerda entre recargas. */
export function LoyaltyProvider({ children }) {
  const [activeId, setActiveId] = useState(() =>
    loadStored(STORAGE_KEY, (id) => id === null || typeof id === 'string', null),
  )

  useEffect(() => {
    saveStored(STORAGE_KEY, activeId)
  }, [activeId])
  const value = useMemo(() => ({ activeId, link: setActiveId, unlink: () => setActiveId(null) }), [activeId])
  return <LoyaltyContext.Provider value={value}>{children}</LoyaltyContext.Provider>
}

export const useLoyalty = () => useContext(LoyaltyContext)
