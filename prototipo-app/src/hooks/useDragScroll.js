import { useEffect } from 'react'

const DRAG_THRESHOLD_PX = 5
const SNAP_RESTORE_FALLBACK_MS = 600

/** Índice del hijo cuyo borde izquierdo (menos scroll-padding) queda más cerca del scroll actual. */
export function nearestChildIndex(el) {
  const pad = parseFloat(getComputedStyle(el).scrollPaddingLeft) || 0
  let best = 0
  let bestDist = Infinity
  Array.from(el.children).forEach((child, i) => {
    const dist = Math.abs(child.offsetLeft - pad - el.scrollLeft)
    if (dist < bestDist) {
      best = i
      bestDist = dist
    }
  })
  return best
}

export function childScrollLeft(el, index) {
  const child = el.children[index]
  if (!child) return 0
  const pad = parseFloat(getComputedStyle(el).scrollPaddingLeft) || 0
  const max = el.scrollWidth - el.clientWidth
  return Math.min(Math.max(child.offsetLeft - pad, 0), max)
}

/**
 * Permite arrastrar con el mouse las filas horizontales, como un swipe en el teléfono.
 * El touch y el trackpad ya hacen scroll nativo; esto es para demos en notebook.
 */
export function useDragScroll(ref) {
  useEffect(() => {
    const el = ref.current
    if (!el) return undefined
    const hasSnap = getComputedStyle(el).scrollSnapType !== 'none'
    let startX = 0
    let startLeft = 0
    let dragging = false
    let moved = false

    const restoreSnap = () => {
      el.style.scrollSnapType = ''
    }

    const onDown = (e) => {
      if (e.pointerType !== 'mouse' || e.button !== 0) return
      dragging = true
      moved = false
      startX = e.clientX
      startLeft = el.scrollLeft
    }

    const onMove = (e) => {
      if (!dragging) return
      const dx = e.clientX - startX
      if (!moved && Math.abs(dx) < DRAG_THRESHOLD_PX) return
      if (!moved) {
        moved = true
        el.style.scrollSnapType = 'none'
      }
      el.scrollLeft = startLeft - dx
    }

    const onUp = () => {
      if (!dragging) return
      dragging = false
      if (!moved || !hasSnap) {
        restoreSnap()
        return
      }
      el.scrollTo({ left: childScrollLeft(el, nearestChildIndex(el)), behavior: 'smooth' })
      el.addEventListener('scrollend', restoreSnap, { once: true })
      setTimeout(restoreSnap, SNAP_RESTORE_FALLBACK_MS)
    }

    // Un arrastre no debe contar como click en la tarjeta donde se soltó.
    const onClickCapture = (e) => {
      if (!moved) return
      e.stopPropagation()
      e.preventDefault()
      moved = false
    }

    el.addEventListener('pointerdown', onDown)
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    el.addEventListener('click', onClickCapture, true)
    return () => {
      el.removeEventListener('pointerdown', onDown)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      el.removeEventListener('click', onClickCapture, true)
    }
  }, [ref])
}
