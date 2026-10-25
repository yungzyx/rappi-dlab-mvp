// Cálculo del total del checkout. Valores de la demo (supuestos): Rappi Pro no paga envío.
export const TIPS = [0, 500, 1000, 1500]
export const DEFAULT_TIP = 1000
const SERVICE_FEE_RATE = 0.03
const MIN_SERVICE_FEE = 490
const DELIVERY_FEE = 1990

/** Desglose del pedido. `isPro`: envío gratis; `pickup`: sin envío ni propina. */
export function priceBreakdown({ subtotal, tip, pickup, isPro = true }) {
  const delivery = pickup || isPro ? 0 : DELIVERY_FEE
  const service = subtotal === 0 ? 0 : Math.max(MIN_SERVICE_FEE, Math.round((subtotal * SERVICE_FEE_RATE) / 10) * 10)
  const appliedTip = pickup ? 0 : tip
  return { subtotal, delivery, service, tip: appliedTip, total: subtotal + delivery + service + appliedTip }
}
