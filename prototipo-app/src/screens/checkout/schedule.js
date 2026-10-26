// «Programa tu pedido»: franjas de una hora para hoy y mañana (la app de Rappi trae franjas de una hora, de 10:00 a
// 20:00, y con la tienda cerrada ofrece programar: docs/investigacion/app-rappi-2026-10-25.md).
//
// Un restaurante publica su horario (`/catalog/terms`: `spans` de hoy y mañana): las franjas caben en él. Una tienda no
// lo publica: se usa una ventana de entrega de ejemplo (SUPUESTO, rotulado) y, si estaba cerrada en la descarga, hoy
// solo desde la hora a la que abría (si Rappi la publicó) y si no, mañana.

const HOUR_MS = 3_600_000
const DAY_MS = 24 * HOUR_MS
export const SLOT_MS = HOUR_MS
// Supuesto: la ventana de entrega de una tienda sin horario publicado, y cuánto antes se programa como mínimo.
export const DEFAULT_WINDOW = { open: 10, close: 22 }
export const LEAD_MINUTES = 60
const DAYS = ['hoy', 'manana']

const minutesOf = (text) => {
  const [h, m] = String(text).split(':').map(Number)
  return h * 60 + m
}

/** ¿La franja que empieza a la hora `hour` del día `day` (0 hoy, 1 mañana) cabe en lo que publicó esta tienda? */
function fits({ spans, hours } = {}, day, hour) {
  const start = hour * 60
  const end = start + 60
  if (spans && (spans.hoy.length || spans.manana.length))
    return spans[DAYS[day]].some(([open, close]) => minutesOf(open) <= start && end <= minutesOf(close))
  if (start < DEFAULT_WINDOW.open * 60 || end > DEFAULT_WINDOW.close * 60) return false
  if (day === 0 && hours?.open === false)
    return hours.opens_at && !hours.opens_tomorrow ? start >= minutesOf(hours.opens_at) : false
  return true
}

/**
 * Las franjas de una hora de hoy y mañana que sirven a todas las tiendas de la compra (`stores`: `{ spans, hours }` de
 * cada una, o null si no se sabe), desde `LEAD_MINUTES` después de `now`: `[{ from, to, day }]` (ms; `day`: 'hoy' o
 * 'manana'), en orden.
 */
export function slotsFor(stores, now = Date.now()) {
  const today = new Date(now).setHours(0, 0, 0, 0)
  const slots = []
  for (const day of [0, 1]) {
    for (let hour = 0; hour < 24; hour += 1) {
      // Por la hora local de ese día (un cambio de horario no corre las franjas).
      const from = new Date(today + day * DAY_MS + HOUR_MS).setHours(hour, 0, 0, 0)
      if (from < now + LEAD_MINUTES * 60_000) continue
      if (stores.every((store) => fits(store ?? {}, day, hour)))
        slots.push({ from, to: from + SLOT_MS, day: DAYS[day] })
    }
  }
  return slots
}

/** ¿Alguna tienda de la compra está cerrada según lo publicado? Entonces solo se puede programar. */
export const anyClosed = (stores) => stores.some((store) => store?.hours?.open === false)
