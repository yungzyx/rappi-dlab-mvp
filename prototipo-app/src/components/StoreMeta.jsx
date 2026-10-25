import { BoltIcon, ClockIcon, CrownIcon, ScooterIcon, SpeedBoltIcon } from './Icons'
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

/** Línea "⚡ 12 min • FREE SHIPPING • 1.4 km" de tarjetas y página de tienda. Lo que falta (p. ej. el tiempo) no se muestra. */
export function StoreMeta({ store, className = '' }) {
  const iconKind = store.etaIcon ?? (store.turbo ? 'turbo' : 'bolt')
  const meta = joinWithDots([
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
