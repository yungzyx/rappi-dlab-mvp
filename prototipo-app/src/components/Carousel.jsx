import { Children, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { childScrollLeft, nearestChildIndex, useDragScroll } from '../hooks/useDragScroll'
import { useReducedMotion } from '../hooks/useReducedMotion'
import './carousel.css'

export function Dots({ count, active, className = '' }) {
  return (
    <div className={`dots ${className}`} aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <span key={i} className={i === active ? 'dot is-active' : 'dot'} />
      ))}
    </div>
  )
}

/**
 * Carrusel con scroll-snap. Avanza solo cada `autoplayMs` (0 = nunca) y avisa el
 * índice visible con `onIndexChange` para que la pantalla dibuje los puntos donde quiera.
 * No avanza con "reducir movimiento" ni mientras tiene el foco o el puntero encima (WCAG 2.2.2): un banner
 * enfocado con Tab no se va de la vista.
 */
export default function Carousel({ children, initialIndex = 0, autoplayMs = 0, onIndexChange, className = '' }) {
  const ref = useRef(null)
  const [index, setIndex] = useState(initialIndex)
  const count = Children.count(children)
  const reduced = useReducedMotion()
  const [focused, setFocused] = useState(false)
  const [hovered, setHovered] = useState(false)
  useDragScroll(ref)

  useLayoutEffect(() => {
    const el = ref.current
    el.scrollLeft = childScrollLeft(el, initialIndex)
  }, [initialIndex])

  useEffect(() => {
    onIndexChange?.(index)
  }, [index, onIndexChange])

  useEffect(() => {
    if (!autoplayMs || count < 2 || reduced || focused || hovered) return undefined
    const timer = setTimeout(() => {
      const el = ref.current
      el.scrollTo({ left: childScrollLeft(el, (index + 1) % count), behavior: 'smooth' })
    }, autoplayMs)
    return () => clearTimeout(timer)
  }, [autoplayMs, count, index, reduced, focused, hovered])

  const handleScroll = () => setIndex(nearestChildIndex(ref.current))

  return (
    <div
      ref={ref}
      className={`hscroll carousel ${className}`}
      onScroll={handleScroll}
      onFocus={() => setFocused(true)}
      // Solo cuando el foco sale del carrusel, no al pasar de un banner a otro.
      onBlur={(e) => !e.currentTarget.contains(e.relatedTarget) && setFocused(false)}
      onPointerEnter={() => setHovered(true)}
      onPointerLeave={() => setHovered(false)}
    >
      {children}
    </div>
  )
}
