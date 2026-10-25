import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { loadStored, saveStored } from './storage'

const STORAGE_KEY = 'rappi-proto-address'

// Dos direcciones de ejemplo, inventadas, para poder cambiar de dirección.
const ADDRESSES = [
  { id: 'home', label: 'Casa', line: 'Los Aromos 123' },
  { id: 'work', label: 'Trabajo', line: 'Av. Apoquindo 3000' },
]

const AddressContext = createContext(null)

export function AddressProvider({ children }) {
  const [selectedId, setSelectedId] = useState(() =>
    loadStored(STORAGE_KEY, (id) => ADDRESSES.some((address) => address.id === id), ADDRESSES[0].id),
  )
  const [sheetOpen, setSheetOpen] = useState(false)

  useEffect(() => {
    saveStored(STORAGE_KEY, selectedId)
  }, [selectedId])

  const value = useMemo(
    () => ({
      addresses: ADDRESSES,
      selected: ADDRESSES.find((address) => address.id === selectedId),
      select: setSelectedId,
      sheetOpen,
      openSheet: () => setSheetOpen(true),
      closeSheet: () => setSheetOpen(false),
    }),
    [selectedId, sheetOpen],
  )

  return <AddressContext.Provider value={value}>{children}</AddressContext.Provider>
}

export const useAddress = () => useContext(AddressContext)
