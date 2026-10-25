import { useEffect, useRef, useState } from 'react'

// Sin ResizeObserver (tests en jsdom) se dibuja con un ancho fijo.
const FALLBACK_WIDTH = 600

/** Ancho en px del elemento (para dibujar SVG nítido, con texto a su tamaño real). */
export function useElementWidth() {
  const ref = useRef(null)
  const [width, setWidth] = useState(() => (typeof ResizeObserver === 'undefined' ? FALLBACK_WIDTH : 0))

  useEffect(() => {
    const element = ref.current
    if (!element || typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  return [ref, width]
}
