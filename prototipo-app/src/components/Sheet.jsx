import { useEffect, useRef, useState } from 'react'
import { useDialog } from '../hooks/useDialog'
import './sheet.css'

const CLOSE_MS = 260

/** Hoja inferior dentro del teléfono (dirección, carrito). Se cierra tocando el fondo. */
export default function Sheet({ open, onClose, title, children }) {
  const [mounted, setMounted] = useState(open)
  const sheetRef = useRef(null)
  useDialog(sheetRef, open && mounted, onClose)
  // Montar al abrir se decide durante el render; desmontar espera a que termine la animación de salida.
  if (open && !mounted) setMounted(true)

  useEffect(() => {
    if (open) return undefined
    const timer = setTimeout(() => setMounted(false), CLOSE_MS)
    return () => clearTimeout(timer)
  }, [open])

  if (!mounted) return null

  return (
    <div className={open ? 'sheet-layer is-open' : 'sheet-layer'}>
      <button type="button" className="sheet-backdrop" aria-label="Cerrar" onClick={onClose} />
      <section ref={sheetRef} className="sheet" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
        <span className="sheet-grabber" />
        {title && <h2 className="sheet-title">{title}</h2>}
        {children}
      </section>
    </div>
  )
}
