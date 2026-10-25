import { useRef } from 'react'
import { useDragScroll } from '../hooks/useDragScroll'

/** Fila con scroll horizontal que también se puede arrastrar con el mouse. */
export default function HScroll({ className = '', children, ...rest }) {
  const ref = useRef(null)
  useDragScroll(ref)
  return (
    <div ref={ref} className={`hscroll ${className}`} {...rest}>
      {children}
    </div>
  )
}
