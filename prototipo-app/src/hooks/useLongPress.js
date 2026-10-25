import { useEffect, useRef } from 'react'

const MOVE_TOLERANCE_PX = 10 // más que esto es scroll, no mantener presionado

/**
 * Mantener presionado (`ms` quieto) llama a `onLongPress`. Moverse cancela: en el celular, el dedo que se mueve está
 * haciendo scroll. `fired()` dice si el último toque fue largo, para que el clic que sigue al soltar no haga lo de
 * siempre.
 */
export function useLongPress(onLongPress, { ms = 500 } = {}) {
  const timer = useRef(null)
  const start = useRef(null)
  const fired = useRef(false)
  const cancel = () => {
    clearTimeout(timer.current)
    start.current = null
  }
  useEffect(() => () => clearTimeout(timer.current), [])

  const handlers = {
    onPointerDown: (event) => {
      cancel()
      fired.current = false
      start.current = { x: event.clientX, y: event.clientY }
      timer.current = setTimeout(() => {
        fired.current = true
        onLongPress()
      }, ms)
    },
    onPointerMove: (event) => {
      if (!start.current) return
      if (Math.hypot(event.clientX - start.current.x, event.clientY - start.current.y) > MOVE_TOLERANCE_PX) cancel()
    },
    onPointerUp: cancel,
    onPointerLeave: cancel,
    onPointerCancel: cancel,
    // Mientras se mantiene, el menú del sistema (copiar imagen…) no aparece.
    onContextMenu: (event) => {
      if (fired.current || start.current) event.preventDefault()
    },
  }
  return { handlers, fired: () => fired.current }
}
