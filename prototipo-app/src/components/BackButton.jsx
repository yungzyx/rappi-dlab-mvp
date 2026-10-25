import { ChevronLeft } from './Icons'
import './back-button.css'

/**
 * Botón «Volver» de todas las pantallas. Cada una conserva su aspecto con `className` (fondo, tamaño, posición);
 * el área táctil se extiende a 40 × 40 como mínimo sin cambiar lo visible. `icon={false}` para zonas sin dibujo
 * (p. ej. sobre una captura que ya trae la flecha).
 */
export default function BackButton({ onClick, className = '', size = 20, icon = true }) {
  return (
    <button type="button" className={`back-button ${className} tap`} aria-label="Volver" onClick={onClick}>
      {icon && <ChevronLeft size={size} />}
    </button>
  )
}
