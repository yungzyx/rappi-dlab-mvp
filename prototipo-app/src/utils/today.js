const pad = (n) => String(n).padStart(2, '0')

/** Fecha local AAAA-MM-DD (no UTC: a las 23:30 en Chile sigue siendo ese día). */
export function today(now = new Date()) {
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}
