import { Children, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { childScrollLeft, nearestChildIndex, useDragScroll } from '../hooks/useDragScroll'
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
 */
export default function Carousel({ children, initialIndex = 0, autoplayMs = 0, onIndexChange, className = '' }) {
  const ref = useRef(null)
  const [index, setIndex] = useState(initialIndex)
  const count = Children.count(children)
  useDragScroll(ref)

  useLayoutEffect(() => {
    const el = ref.current
    el.scrollLeft = childScrollLeft(el, initialIndex)
  }, [initialIndex])

  useEffect(() => {
    onIndexChange?.(index)
  }, [index, onIndexChange])

  useEffect(() => {
    if (!autoplayMs || count < 2) return undefined
    const timer = setTimeout(() => {
      const el = ref.current
      el.scrollTo({ left: childScrollLeft(el, (index + 1) % count), behavior: 'smooth' })
    }, autoplayMs)
    return () => clearTimeout(timer)
  }, [autoplayMs, count, index])

  const handleScroll = () => setIndex(nearestChildIndex(ref.current))

  return (
    <div ref={ref} className={`hscroll carousel ${className}`} onScroll={handleScroll}>
      {children}
    </div>
  )
}
