import { useEffect, useState, useSyncExternalStore } from 'react'

const STORAGE_KEY = 'panel-empresa:tema'
const DARK_QUERY = '(prefers-color-scheme: dark)'

// ?tema=claro u ?tema=oscuro en la dirección (p. ej. el QR de una presentación) fija el tema como el botón.
const URL_THEMES = { claro: 'light', oscuro: 'dark' }

export function storedTheme() {
  const fromUrl = URL_THEMES[new URLSearchParams(window.location.search).get('tema')] ?? null
  try {
    if (fromUrl) localStorage.setItem(STORAGE_KEY, fromUrl)
    const value = localStorage.getItem(STORAGE_KEY)
    return value === 'light' || value === 'dark' ? value : null
  } catch {
    return fromUrl // almacenamiento bloqueado: el de la dirección o, sin él, el del sistema
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
