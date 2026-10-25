import { useSyncExternalStore } from 'react'

const QUERY = '(prefers-reduced-motion: reduce)'

// Sin `matchMedia` (jsdom, algunos entornos) se asume movimiento normal.
const media = () => (typeof window === 'undefined' ? null : (window.matchMedia?.(QUERY) ?? null))

function subscribe(onChange) {
  const query = media()
  query?.addEventListener?.('change', onChange)
  return () => query?.removeEventListener?.('change', onChange)
}

/** `true` si la persona pidió reducir el movimiento; se actualiza si lo cambia con la app abierta. */
export function useReducedMotion() {
  return useSyncExternalStore(
    subscribe,
    () => Boolean(media()?.matches),
    () => false,
  )
}
