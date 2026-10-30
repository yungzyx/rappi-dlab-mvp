import { formatPrice } from '../state/CartContext'
import './threshold-bar.css'

/**
 * Barra "Agrega $X para…" hacia un monto del carro (`goal`, en pesos) con lo que ya suma (`total`). La usan el Turbo
 * (la tarifa de servicio) y la tienda con una promo que publica su mínimo ("Envío gratis sobre $15.000"). `title` es lo
 * que se gana; `pending` y `done`, las frases de antes y después de llegar (`pending` recibe el monto que falta ya con
 * formato). `icon`, una imagen decorativa opcional; `note`, una línea más (p. ej. que el umbral es el publicado).
 */
export default function ThresholdBar({ goal, total, title, pending, done, icon, note, className = '' }) {
  const remaining = Math.max(goal - total, 0)
  const progress = goal > 0 ? Math.min(total / goal, 1) : 1
  return (
    <div className={`threshold-bar ${className}`.trim()}>
      {icon && <img src={icon} alt="" loading="lazy" />}
      <div>
        <p className="threshold-bar-title">{title}</p>
        <p className="threshold-bar-sub">{remaining > 0 ? pending(<strong>{formatPrice(remaining)}</strong>) : done}</p>
        {note && <p className="threshold-bar-note">{note}</p>}
      </div>
      <div className="threshold-bar-track">
        <span className="threshold-bar-fill" style={{ width: `${progress * 100}%` }} />
        <span className={progress >= 1 ? 'threshold-bar-check is-done' : 'threshold-bar-check'} />
      </div>
    </div>
  )
}
