// Línea de tiempo simulada del pedido (segundos desde que se hizo) y ruta del repartidor en el mapa.
export const STEPS = [
  { id: 'confirmed', label: 'Pedido confirmado', at: 0 },
  { id: 'preparing', label: 'Preparando tu pedido', at: 4 },
  { id: 'on-the-way', label: 'En camino', at: 9 },
  { id: 'delivered', label: 'Entregado', at: 20 },
]

const RIDE_START = STEPS[2].at
const RIDE_END = STEPS[3].at
const RIDE_MINUTES = 12

// Ruta por calles (coordenadas del SVG del mapa, 400 × 300).
export const ROUTE = [
  [62, 236],
  [62, 168],
  [178, 168],
  [178, 100],
  [322, 100],
  [322, 66],
]

/** Paso actual (índice en STEPS) según los segundos transcurridos. */
export function stepAt(seconds) {
  return STEPS.reduce((current, step, i) => (seconds >= step.at ? i : current), 0)
}

/** Avance del viaje entre 0 y 1. */
export function rideProgress(seconds) {
  return Math.min(1, Math.max(0, (seconds - RIDE_START) / (RIDE_END - RIDE_START)))
}

/** Minutos que faltan (escala simulada: el viaje de 11 s "dura" 12 min). */
export function minutesLeft(seconds) {
  if (seconds >= RIDE_END) return 0
  if (seconds < RIDE_START) return RIDE_MINUTES + 10
  return Math.max(1, Math.ceil((1 - rideProgress(seconds)) * RIDE_MINUTES))
}

/** Punto de la ruta para un avance entre 0 y 1, interpolando por largo de cada tramo. */
export function pointOnRoute(progress, route = ROUTE) {
  const segments = route.slice(1).map((point, i) => {
    const [x0, y0] = route[i]
    return { from: route[i], to: point, length: Math.hypot(point[0] - x0, point[1] - y0) }
  })
  const total = segments.reduce((sum, segment) => sum + segment.length, 0)
  let remaining = Math.min(1, Math.max(0, progress)) * total
  for (const { from, to, length } of segments) {
    if (remaining <= length) {
      const t = length === 0 ? 0 : remaining / length
      return [from[0] + (to[0] - from[0]) * t, from[1] + (to[1] - from[1]) * t]
    }
    remaining -= length
  }
  return route[route.length - 1]
}
