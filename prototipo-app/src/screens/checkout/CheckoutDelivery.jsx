import { formatPrice } from '../../state/CartContext'
import { slotLabel } from '../tracking/progress'
import { DELIVERY_TYPES } from './pricing'

const MAX_SLOTS = 12

/**
 * Cuándo llega: «Ahora» con su tipo de entrega (Básica, Sin prisa o Prioritaria, montos de ejemplo) o «Programar» en
 * una franja de una hora de hoy o mañana. Con una tienda cerrada según lo publicado solo se puede programar. `when` es
 * 'now' o el inicio de la franja (ms).
 */
export default function CheckoutDelivery({ type, onType, when, onWhen, slots, closed, baskets }) {
  const scheduled = when !== 'now'
  return (
    <>
      <h2 className="checkout-title">Entrega</h2>
      {closed && (
        <p className="checkout-closed" role="status">
          La tienda está cerrada pero puedes programar tu pedido.
        </p>
      )}
      <div className="checkout-when" role="radiogroup" aria-label="Cuándo">
        <button
          type="button"
          role="radio"
          aria-checked={!scheduled && !closed}
          disabled={closed}
          className={!scheduled && !closed ? 'checkout-chip is-on' : 'checkout-chip'}
          onClick={() => onWhen('now')}
        >
          Ahora
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={scheduled}
          disabled={slots.length === 0}
          className={scheduled ? 'checkout-chip is-on' : 'checkout-chip'}
          onClick={() => !scheduled && slots[0] && onWhen(slots[0].from)}
        >
          Programar
        </button>
      </div>

      {scheduled ? (
        <div className="checkout-slots" role="radiogroup" aria-label="Franja de entrega">
          {slots.slice(0, MAX_SLOTS).map((slot) => (
            <button
              key={slot.from}
              type="button"
              role="radio"
              aria-checked={when === slot.from}
              className={when === slot.from ? 'checkout-slot is-on' : 'checkout-slot'}
              onClick={() => onWhen(slot.from)}
            >
              {slotLabel(slot.from)}
            </button>
          ))}
        </div>
      ) : (
        <div className="checkout-types" role="radiogroup" aria-label="Tipo de entrega">
          {DELIVERY_TYPES.map((option) => (
            <button
              key={option.id}
              type="button"
              role="radio"
              aria-checked={type === option.id}
              className={type === option.id ? 'checkout-type is-on' : 'checkout-type'}
              onClick={() => onType(option.id)}
            >
              <strong>{option.label}</strong>
              <small>{option.eta}</small>
              <small>{feeText(option.fee, baskets)}</small>
            </button>
          ))}
        </div>
      )}
      {closed && slots.length === 0 && (
        <p className="checkout-blocked-note">No hay franjas para programar hoy ni mañana en esta tienda.</p>
      )}
      <p className="checkout-basis-note">
        {scheduled
          ? 'Franjas de una hora para hoy y mañana: en una tienda sin horario publicado, la ventana de entrega es de ejemplo.'
          : 'Los montos y tiempos de cada tipo de entrega son de ejemplo, no tarifas de Rappi.'}
      </p>
    </>
  )
}

/** «+$990 por pedido», «−$500 por pedido» o «Sin costo extra». */
function feeText(fee, baskets) {
  if (fee === 0) return 'Sin costo extra'
  const per = baskets > 1 ? ' por pedido' : ''
  return `${fee > 0 ? '+' : '−'}${formatPrice(Math.abs(fee))}${per}`
}
