import { useEffect, useState, useSyncExternalStore } from 'react'

const STORAGE_KEY = 'panel-empresa:tema'
const DARK_QUERY = '(prefers-color-scheme: dark)'

function storedTheme() {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return value === 'light' || value === 'dark' ? value : null
  } catch {
    return null // almacenamiento bloqueado: se sigue al sistema
  }
}

function subscribeSystem(listener) {
  const query = window.matchMedia?.(DARK_QUERY)
  query?.addEventListener('change', listener)
  return () => query?.removeEventListener('change', listener)
}

const systemPrefersDark = () => window.matchMedia?.(DARK_QUERY).matches ?? false

/** Tema efectivo ('light' | 'dark') y un toggle que fija la preferencia del usuario sobre la del sistema. */
export function useTheme() {
  const [chosen, setChosen] = useState(storedTheme)
  const prefersDark = useSyncExternalStore(subscribeSystem, systemPrefersDark)
  const theme = chosen ?? (prefersDark ? 'dark' : 'light')

  useEffect(() => {
    if (chosen) document.documentElement.dataset.theme = chosen
    else delete document.documentElement.dataset.theme
  }, [chosen])

  const toggle = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // Sin almacenamiento el tema dura solo esta visita.
    }
    setChosen(next)
  }

  return { theme, toggle }
}
