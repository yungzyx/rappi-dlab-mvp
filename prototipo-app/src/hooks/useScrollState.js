import { useEffect, useRef, useState } from 'react'

const INITIAL = { collapsed: false, showBackToTop: false, scrolled: false }

/**
 * Lo que las pantallas necesitan saber del scroll, en booleanos (encabezado compacto, "Back to top", si se movió
 * del tope): se lee una vez por cuadro (requestAnimationFrame) y solo re-renderiza cuando alguno cambia.
 * `collapseAt`: desde qué `scrollTop` el encabezado se compacta; `backToTopFrom`: desde cuál aparece el botón al subir.
 */
export function useScrollState({ collapseAt = 0, backToTopFrom = Infinity } = {}) {
  const lastTop = useRef(0)
  const frame = useRef(0)
  const [state, setState] = useState(INITIAL)
  useEffect(() => () => cancelAnimationFrame(frame.current), [])

  const onScroll = (e) => {
    const element = e.currentTarget
    if (frame.current) return
    frame.current = requestAnimationFrame(() => {
      frame.current = 0
      const top = element.scrollTop
      const goingUp = top < lastTop.current
      lastTop.current = top
      const next = { collapsed: top > collapseAt, showBackToTop: goingUp && top > backToTopFrom, scrolled: top > 0 }
      setState((prev) =>
        prev.collapsed === next.collapsed &&
        prev.showBackToTop === next.showBackToTop &&
        prev.scrolled === next.scrolled
          ? prev
          : next,
      )
    })
  }
  return [state, onScroll]
}
