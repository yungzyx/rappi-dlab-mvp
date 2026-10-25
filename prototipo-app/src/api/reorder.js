// «Pídelo de nuevo»: volver a armar el carro con un pedido anterior, con el precio de hoy en la misma tienda
// (`POST /catalog/availability`: `v_latest_offers` o, en un plato, `latest_menu_prices`) y lo que ya no está marcado.
import { formatPrice } from '../state/CartContext'
import { place } from './attribution'
import { request } from './client'

const AVAILABILITY_TIMEOUT_MS = 5_000
export const REORDER_ORIGIN = 'pidelo-de-nuevo'

/** Las líneas de un pedido que se pueden volver a pedir: las que guardaron su producto con su id del catálogo. */
export const reorderLines = (order) =>
  (order?.items ?? []).filter((item) => item.product?.entityId != null && Number.isInteger(item.qty) && item.qty > 0)

/** ¿Tiene algo que volver a pedir? (Los pedidos de antes no guardaban el producto.) */
export const canReorder = (order) => reorderLines(order).length > 0

/** La disponibilidad de hoy de esas líneas, en su orden: `[{ available, price }]`. Si falla, lanza el `ApiError`. */
export async function availability(lines) {
  const reply = await request('/catalog/availability', {
    method: 'POST',
    body: {
      lines: lines.map(({ product }) => ({
        entity_type: product.entityType === 'menu_item' ? 'menu_item' : 'catalog_item',
        entity_id: String(product.entityId),
        ...(product.storeId != null ? { store_id: product.storeId } : {}),
      })),
    },
    timeout: AVAILABILITY_TIMEOUT_MS,
  })
  return reply.lines
}

/**
 * El plan de «Pídelo de nuevo»: `{ available: [{ product, qty }], unavailable: [{ product, qty }] }`. Lo disponible
 * lleva el precio de hoy (si cambió, sin el «antes» ni el descuento de esa vez) y su lugar (`placement`: la pantalla,
 * «Pídelo de nuevo» y su posición en el pedido); lo que ya no está a la venta en esa tienda queda aparte.
 */
export function reorderPlan(lines, replies, { surface }) {
  const plan = { available: [], unavailable: [] }
  lines.forEach(({ product, qty }, position) => {
    const reply = replies[position]
    if (!reply?.available) {
      plan.unavailable.push({ product, qty })
      return
    }
    const price = reply.price == null ? product.price : formatPrice(Math.round(reply.price))
    const same = price === product.price
    const current = same ? product : { ...product, price, before: undefined, discount: undefined }
    plan.available.push({ product: place(current, { surface, origin: REORDER_ORIGIN, position }), qty })
  })
  return plan
}
