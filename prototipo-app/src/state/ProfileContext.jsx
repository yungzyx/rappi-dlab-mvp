import { createContext, useContext, useMemo, useState } from 'react'

// El perfil de la persona lo construye el servidor con sus eventos (`/profile`). Aquí solo queda la «generación»:
// un contador que sube con «Olvidar», para que lo mostrado y aceptado antes de olvidar cuente como sugerencia nueva
// (`firstShowing`) y lo pedido antes a la API ya no valga.
const ProfileContext = createContext(null)

export function ProfileProvider({ children }) {
  const [resets, setResets] = useState(0)
  const value = useMemo(() => ({ resets, reset: () => setResets((n) => n + 1) }), [resets])
  return <ProfileContext.Provider value={value}>{children}</ProfileContext.Provider>
}

export const useProfile = () => useContext(ProfileContext)
