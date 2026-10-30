// "Cancelar pedido" con rescate (la pantalla de la app de Rappi: "Aún tiene solución" antes de "Continuar con la
// cancelación"). Los motivos son los que acepta rappi-ia (events/store.py: CANCEL_REASONS) y las etapas, CANCEL_STAGES.
//
// El costo de cancelar un pedido que la tienda ya empezó es un SUPUESTO de la demo (la app de Rappi lo calcula en su
// servidor y no se sabe cómo): se rotula "de ejemplo" y nunca se presenta como política de Rappi.
import { parsePrice } from '../../state/CartContext'
import { flowFor, isAhead, secondsSince } from './progress'

export const CANCEL_REASONS = [
  { id: 'direccion', label: 'Me equivoqué de dirección', rescue: 'address' },
  { id: 'pago', label: 'Quiero cambiar el medio de pago', rescue: 'payment' },
  { id: 'demora', label: 'Está tardando mucho' },
  { id: 'productos', label: 'Quiero cambiar productos' },
  { id: 'ya_no', label: 'Ya no lo necesito' },
  { id: 'otro', label: 'Otro motivo' },
]

// Supuesto: desde que la tienda empieza el pedido, cancelar cuesta el 30 % de los productos (al menos $990).
export const CANCEL_FEE = { rate: 0.3, min: 990 }

// Medios de pago de ejemplo para "cambiar el pago" (no se ingresan datos).
export const PAYMENTS = ['Visa •••• 4242', 'Efectivo al recibir']

const round10 = (value) => Math.round(value / 10) * 10

/**
 * En qué momento está el pedido para cancelarlo: `programado` (aún no empieza), `antes_de_tienda` (la tienda todavía no
 * lo empieza), `en_tienda` (la tienda o el shopper ya lo preparan: tiene costo) o null si ya va en camino, se entregó o
 * ya se canceló (no se puede).
 */
export function cancelStage(order, now) {
  if (!order || order.cancelled) return null
  if (isAhead(order, now)) return 'programado'
  const flow = flowFor(order)
  const seconds = secondsSince(order, now)
  const started = flow.steps[1].at
  const riding = flow.steps.find((step) => step.id === 'on-the-way').at
  if (seconds < started) return 'antes_de_tienda'
  if (seconds < riding) return 'en_tienda'
  return null
}

/** Lo que cuesta cancelar en esa etapa (de ejemplo): $0 antes de que la tienda empiece el pedido. */
export function cancelFee(order, stage) {
  if (stage !== 'en_tienda') return 0
  const products = order.items.reduce((sum, item) => sum + parsePrice(item.price) * (item.qty ?? 1), 0)
  return Math.max(CANCEL_FEE.min, round10(products * CANCEL_FEE.rate))
}
