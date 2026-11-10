import { useSyncExternalStore } from 'react'

/** Si la media query calza ahora (y se actualiza al cambiar). Sin matchMedia (tests en jsdom), `false`. */
export function useMediaQuery(query) {
  return useSyncExternalStore(
    (onChange) => {
      const list = window.matchMedia?.(query)
      list?.addEventListener('change', onChange)
      return () => list?.removeEventListener('change', onChange)
    },
    () => window.matchMedia?.(query).matches ?? false,
    () => false,
  )
}
