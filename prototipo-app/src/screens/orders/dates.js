const MONTHS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

const startOfDay = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()

/** Día de un pedido en relación a hoy: «Hoy», «Ayer» o «12 oct». */
export function relativeDay(timestamp, now = Date.now()) {
  const date = new Date(timestamp)
  const days = Math.round((startOfDay(new Date(now)) - startOfDay(date)) / 86_400_000)
  if (days === 0) return 'Hoy'
  if (days === 1) return 'Ayer'
  return `${date.getDate()} ${MONTHS[date.getMonth()]}`
}
