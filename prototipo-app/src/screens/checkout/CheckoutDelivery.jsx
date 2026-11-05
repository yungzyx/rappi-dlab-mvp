import { useRovingGroup } from '../../hooks/useRovingGroup'
import { formatPrice } from '../../state/CartContext'
import { slotLabel } from '../tracking/progress'
import { DELIVERY_TYPES } from './pricing'

const MAX_SLOTS_PER_DAY = 12
const DAY_LABELS = { hoy: 'Hoy', manana: 'Mañana' }

/**
 * Cuándo llega (o cuándo se retira): "Ahora", con su tipo de entrega en un envío (Básica, Sin prisa o Prioritaria,
 * montos de ejemplo), o "Programar" en una franja de una hora de hoy o mañana, agrupadas por día. Con una tienda
 * cerrada según lo publicado solo se puede programar. `when` es 'now' o el inicio de la franja (ms); `published`: si
 * todas las tiendas publicaron su horario (las franjas caben en él; si no, la ventana es de ejemplo).
 */
export default function CheckoutDelivery({
  type,
  onType,
  when,
  onWhen,
  slots,
  closed,
  baskets,
  pickup = false,
  published = false,
}) {
  const scheduled = when !== 'now'
  const days = ['hoy', 'manana']
    .map((day) => ({ day, slots: slots.filter((slot) => slot.day === day).slice(0, MAX_SLOTS_PER_DAY) }))
    .filter((group) => group.slots.length)
  const chooseWhen = [() => onWhen('now'), () => !scheduled && slots[0] && onWhen(slots[0].from)]
  const whenGroup = useRovingGroup(
    2,
    scheduled ? 1 : closed ? -1 : 0,
    (i) => chooseWhen[i](),
    (i) => (i === 0 ? closed : slots.length === 0),
  )
  const types = useRovingGroup(
    DELIVERY_TYPES.length,
    DELIVERY_TYPES.findIndex((option) => option.id === type),
    (i) => onType(DELIVERY_TYPES[i].id),
  )
  return (
    <>
      <h2 className="checkout-title">{pickup ? 'Retiro' : 'Entrega'}</h2>
      {closed && (
        <p className="checkout-closed" role="status">
          La tienda está cerrada pero puedes programar tu pedido.
        </p>
      )}
      <div className="checkout-when" role="radiogroup" aria-label="Cuándo" onKeyDown={whenGroup.onKeyDown}>
        <button
          type="button"
          role="radio"
          aria-checked={!scheduled && !closed}
          disabled={closed}
          className={!scheduled && !closed ? 'checkout-chip is-on' : 'checkout-chip'}
          onClick={chooseWhen[0]}
          {...whenGroup.itemProps(0)}
        >
          Ahora
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={scheduled}
          disabled={slots.length === 0}
          className={scheduled ? 'checkout-chip is-on' : 'checkout-chip'}
          onClick={chooseWhen[1]}
          {...whenGroup.itemProps(1)}
        >
          Programar
        </button>
      </div>

      {scheduled ? (
        days.map((group) => (
          <div key={group.day} className="checkout-slot-day">
            <p className="checkout-slot-day-label">{DAY_LABELS[group.day]}</p>
            <SlotGroup
              slots={group.slots}
              when={when}
              onWhen={onWhen}
              label={`Franja de ${pickup ? 'retiro' : 'entrega'}, ${DAY_LABELS[group.day].toLowerCase()}`}
            />
          </div>
        ))
      ) : pickup ? null : (
        <div className="checkout-types" role="radiogroup" aria-label="Tipo de entrega" onKeyDown={types.onKeyDown}>
          {DELIVERY_TYPES.map((option, i) => (
            <button
              key={option.id}
              type="button"
              role="radio"
              aria-checked={type === option.id}
              className={type === option.id ? 'checkout-type is-on' : 'checkout-type'}
              onClick={() => onType(option.id)}
              {...types.itemProps(i)}
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
          ? published
            ? 'Franjas de una hora para hoy y mañana, dentro del horario que publicó la tienda.'
            : 'Franjas de una hora para hoy y mañana: sin horario publicado, la ventana (de 10:00 a 22:00) es de ejemplo.'
          : pickup
            ? 'El tiempo para retirar es de ejemplo.'
            : 'Los montos y tiempos de cada tipo de entrega son de ejemplo, no tarifas de Rappi.'}
      </p>
    </>
  )
}

/** Las franjas de un día: un grupo que se recorre con las flechas. */
function SlotGroup({ slots, when, onWhen, label }) {
  const roving = useRovingGroup(
    slots.length,
    slots.findIndex((slot) => slot.from === when),
    (i) => onWhen(slots[i].from),
  )
  return (
    <div className="checkout-slots" role="radiogroup" aria-label={label} onKeyDown={roving.onKeyDown}>
      {slots.map((slot, i) => (
        <button
          key={slot.from}
          type="button"
          role="radio"
          aria-checked={when === slot.from}
          className={when === slot.from ? 'checkout-slot is-on' : 'checkout-slot'}
          onClick={() => onWhen(slot.from)}
          {...roving.itemProps(i)}
        >
          {slotLabel(slot.from)}
        </button>
      ))}
    </div>
  )
}

/** "+$990 por pedido", "−$500 por pedido" o "Sin costo extra". */
function feeText(fee, baskets) {
  if (fee === 0) return 'Sin costo extra'
  const per = baskets > 1 ? ' por pedido' : ''
  return `${fee > 0 ? '+' : '−'}${formatPrice(Math.abs(fee))}${per}`
}
