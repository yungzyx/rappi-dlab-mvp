// Cambios en vivo del Súper («Tus productos te necesitan»), de demostración: en «En tienda» un producto del pedido se
// agota (SIMULADO: no hay stock en vivo, y se rotula así) y la persona elige un sustituto del mismo concepto en la
// misma tienda (esos sí salen del catálogo), «Si no contesto, elijan por mí» o el reembolso, con el «Ajuste en el total».
import { parsePrice } from '../../state/CartContext'

/** Qué hacer si se agota: lo que se elige en el checkout de Súper y Turbo, por línea (rappi-ia: substitution). */
export const SUBSTITUTIONS = [
  { id: 'sustituto', label: 'Elegir un sustituto', detail: 'Uno parecido, de la misma tienda' },
  { id: 'elijan', label: 'Si no contesto, elijan por mí', detail: 'Tu shopper elige uno parecido' },
  { id: 'reembolso', label: 'Prefiero el reembolso', detail: 'Lo quitamos y no te lo cobramos' },
]
export const DEFAULT_SUBSTITUTION = 'elijan'
// Las verticales (código del backend) cuyo checkout pregunta qué hacer si un producto se agota.
export const SUBSTITUTION_VERTICALS = new Set(['supermercado', 'turbo'])

/** ¿Este pedido tiene cambios en vivo? Solo el Súper, mientras el shopper elige. */
export const hasLiveChanges = (order) => order?.vertical === 'supermercado' && !order.cancelled

/** La línea que se agota en la demo: el primer producto del catálogo del pedido (con su id y su tienda), o -1. */
export const soldOutIndex = (order) =>
  (order?.items ?? []).findIndex(
    (item) => item.entityType !== 'menu_item' && item.entityId != null && item.product?.storeId != null,
  )

/**
 * El cambio resuelto: `{ index, choice, product, delta }`. `delta` es el «Ajuste en el total»: el sustituto menos el
 * agotado (por sus unidades) o, con el reembolso, menos el agotado.
 */
export function resolveChange(item, index, choice, substitute) {
  const qty = item.qty ?? 1
  const before = parsePrice(item.price) * qty
  if (!substitute) return { index, choice: 'reembolso', product: null, delta: -before }
  return {
    index,
    choice,
    product: { name: substitute.name, img: substitute.img, price: substitute.price },
    delta: parsePrice(substitute.price) * qty - before,
  }
}
