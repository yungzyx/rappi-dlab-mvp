import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

// "final" = el prototipo final: el agente de cuerpo entero vive en la Home y el buscador es el del agente.
// "actual" = «Rappi hoy», solo de la demo: una réplica de la app como es hoy, para comparar en una presentación. Solo se
// puede elegir en desarrollo o en un build con VITE_DEMO=1 (interruptor, tecla D y la fila de Cuenta); en cualquier otro
// build la app es siempre el prototipo final, aunque el navegador tenga guardado «Rappi hoy».
const STORAGE_KEY = 'rappi-proto-demo-mode'
const MODES = ['final', 'actual']
export const MODE_LABELS = { final: 'Prototipo final ✨', actual: 'Rappi hoy' }
const isDemoBuild = () => import.meta.env.DEV || import.meta.env.VITE_DEMO === '1'

// Cualquier otro valor guardado entra al prototipo final.
function load() {
  if (!isDemoBuild()) return 'final'
  try {
    return localStorage.getItem(STORAGE_KEY) === 'actual' ? 'actual' : 'final'
  } catch {
    return 'final'
  }
}

function persist(mode) {
  try {
    localStorage.setItem(STORAGE_KEY, mode)
  } catch {
    // Sin almacenamiento: el modo dura hasta recargar.
  }
}

export const nextMode = (mode) => MODES[(MODES.indexOf(mode) + 1) % MODES.length]

const DemoContext = createContext(null)

export function DemoProvider({ children }) {
  const [mode, setModeState] = useState(load)

  const setMode = useCallback((next) => {
    persist(next)
    setModeState(next)
  }, [])

  const toggle = useCallback(() => {
    setModeState((prev) => {
      persist(nextMode(prev))
      return nextMode(prev)
    })
  }, [])

  // Tecla D para cambiar de modo en vivo durante una presentación (salvo mientras se escribe). Solo en desarrollo o en
  // un build con VITE_DEMO=1: en el sitio desplegado, apretar «d» sobre un botón no debe cambiar la app de modo.
  useEffect(() => {
    if (!isDemoBuild()) return undefined
    const onKey = (event) => {
      // Chrome dispara keydown sin `key` al autocompletar un campo.
      if (event.key?.toLowerCase() !== 'd' || event.metaKey || event.ctrlKey || event.altKey) return
      if (event.target.closest?.('input, textarea, [contenteditable="true"]')) return
      toggle()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [toggle])

  const value = useMemo(() => ({ mode, isFinal: mode === 'final', setMode, toggle }), [mode, setMode, toggle])

  return <DemoContext.Provider value={value}>{children}</DemoContext.Provider>
}

export const useDemo = () => useContext(DemoContext)
