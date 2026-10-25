// Formatos es-CL: 1.234 · $1.290 · 28,6% · 26-09-2026. `null` o `undefined` se muestran como "—".
// useGrouping 'always': el español agrupa por defecto solo desde 5 cifras (1234 en vez de 1.234).
const EMPTY = '—'
const MINUS = '−'
const MONTHS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

const numberFormats = new Map()

function numberFormat(decimals) {
  if (!numberFormats.has(decimals)) {
    numberFormats.set(
      decimals,
      new Intl.NumberFormat('es-CL', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
        useGrouping: 'always',
      }),
    )
  }
  return numberFormats.get(decimals)
}

const isMissing = (value) => value === null || value === undefined || Number.isNaN(value)

/** 1234 → "1.234"; con decimales: formatNumber(2.99, 2) → "2,99". */
export function formatNumber(value, decimals = 0) {
  if (isMissing(value)) return EMPTY
  return numberFormat(decimals).format(value).replace('-', MINUS)
}

/** Porcentaje ya multiplicado por 100: 28.6 → "28,6%". */
export function formatPct(value, decimals = 1) {
  if (isMissing(value)) return EMPTY
  return `${formatNumber(value, decimals)}%`
}

/** Cambio con signo: 43 → "+43%", −4 → "−4%". */
export function formatSignedPct(value, decimals = 0) {
  if (isMissing(value)) return EMPTY
  const sign = value > 0 ? '+' : ''
  return `${sign}${formatNumber(value, decimals)}%`
}

/** Diferencia en puntos porcentuales, con la palabra («pp» no lo lee cualquiera): 10.9 → "+10,9 puntos". */
export function formatPoints(value, decimals = 1) {
  if (isMissing(value)) return EMPTY
  const sign = value > 0 ? '+' : ''
  return `${sign}${formatNumber(value, decimals)} puntos`
}

/** Toma la fecha de un ISO ("2026-09-26" o "2026-09-26T23:58:56-03:00") sin pasar por la zona horaria del navegador. */
function dateParts(iso) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '')
  if (!match) return null
  return { year: match[1], month: Number(match[2]), day: Number(match[3]) }
}

/** "2026-09-26" → "26-09-2026". */
export function formatDate(iso) {
  const parts = dateParts(iso)
  if (!parts) return EMPTY
  return `${String(parts.day).padStart(2, '0')}-${String(parts.month).padStart(2, '0')}-${parts.year}`
}

/** "2026-05-11" → "11 may". */
export function formatShortDate(iso) {
  const parts = dateParts(iso)
  if (!parts) return EMPTY
  return `${parts.day} ${MONTHS[parts.month - 1]}`
}
