import { BoltIcon, ClockIcon, CrownIcon, ScooterIcon, SpeedBoltIcon } from './Icons'
import { hoursLabel, isClosed, promoLabel } from './storeHours'
import './store-meta.css'

const ETA_ICONS = {
  turbo: (size) => <SpeedBoltIcon size={size} className="featured-bolt" />,
  bolt: (size) => <BoltIcon size={size} className="featured-bolt featured-bolt--plain" />,
  clock: (size) => <ClockIcon size={size} />,
  none: () => null,
}

export function EtaIcon({ kind, size = 16 }) {
  return (ETA_ICONS[kind] ?? ETA_ICONS.none)(size)
}

/** Separa los datos de la línea de metadatos con un punto gris, como en la app. */
function joinWithDots(parts) {
  return parts.filter(Boolean).flatMap((part, i) =>
    i === 0
      ? [part]
      : [
          <span key={`sep-${i}`} className="meta-sep">
            •
          </span>,
          part,
        ],
  )
}

/**
 * Línea "⚡ 12 min • FREE SHIPPING • 1.4 km" de tarjetas y página de tienda. Lo que falta (p. ej. el tiempo) no se muestra.
 * Una tienda cerrada según lo publicado en la descarga lo dice primero («Cerrado · Abre a las 11:00»).
 */
export function StoreMeta({ store, className = '' }) {
  const iconKind = store.etaIcon ?? (store.turbo ? 'turbo' : 'bolt')
  const meta = joinWithDots([
    isClosed(store.hours) && (
      <span key="closed" className="store-closed">
        {hoursLabel(store.hours)}
      </span>
    ),
    store.eta && (
      <span key="eta" className="featured-eta">
        <EtaIcon kind={iconKind} />
        {store.eta}
      </span>
    ),
    store.deliveryLabel && (
      <span key="pill" className="free-delivery">
        <CrownIcon size={13} />
        {store.deliveryLabel}
      </span>
    ),
    store.fee && (
      <span key="fee" className="featured-eta">
        <ScooterIcon size={16} />
        {store.fee}
      </span>
    ),
    store.distance && <span key="dist">{store.distance}</span>,
  ])

  return <span className={`featured-meta ${className}`}>{meta}</span>
}

/** La promo de la tarjeta (la que publicó la tienda, o «Con promociones» en un restaurante con platos rebajados). */
export function PromoTag({ store, className = '' }) {
  const label = promoLabel(store)
  return label ? <span className={`store-promo ${className}`.trim()}>{label}</span> : null
}
