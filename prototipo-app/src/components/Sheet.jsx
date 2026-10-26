import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useDialog } from '../hooks/useDialog'
import './sheet.css'

const CLOSE_MS = 260

/**
 * Hoja inferior dentro del teléfono (dirección, carrito). Se cierra tocando el fondo. `overPhone`: la hoja se dibuja
 * directo en el teléfono y no dentro de quien la abre (el buscador con Mochi tiene su propia capa, y la barra «Pedido en
 * curso» o la del carro quedaban encima de sus hojas).
 */
export default function Sheet({ open, onClose, title, children, overPhone = false }) {
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

  const layer = (
    <div className={open ? 'sheet-layer is-open' : 'sheet-layer'}>
      <button type="button" className="sheet-backdrop" aria-label="Cerrar" onClick={onClose} />
      <section ref={sheetRef} className="sheet" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
        <span className="sheet-grabber" />
        {title && <h2 className="sheet-title">{title}</h2>}
        {children}
      </section>
    </div>
  )
  const phone = overPhone ? document.querySelector('.phone') : null
  return phone ? createPortal(layer, phone) : layer
}
