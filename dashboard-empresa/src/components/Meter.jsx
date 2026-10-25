/** Barra en línea para comparar filas de una tabla. Decorativa: el número va siempre al lado. */
export function Meter({ value, max, tone = 'data' }) {
  const pct = max > 0 && value > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <span className={`meter meter--${tone}`} aria-hidden="true">
      <span style={{ '--w': `${pct}%` }} />
    </span>
  )
}
