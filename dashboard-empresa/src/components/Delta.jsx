import { Icon } from './Icon.jsx'

/**
 * Cambio con dirección y juicio: el color sale de dirección × si subir es bueno (rojo solo si empeora).
 * `goodWhen`: 'up' | 'down' | null (null = neutro, sin juicio).
 */
export function Delta({ value, format, goodWhen = 'up', suffix }) {
  if (value === null || value === undefined) return null
  const direction = value > 0 ? 'up' : value < 0 ? 'down' : null
  let tone = 'muted'
  if (direction && goodWhen) tone = direction === goodWhen ? 'good' : 'bad'
  return (
    <span className={`status status--${tone} delta`}>
      {direction && <Icon name={direction} />}
      <span className="num">{format(value)}</span>
      {suffix && <span className="delta-suffix">{suffix}</span>}
    </span>
  )
}
