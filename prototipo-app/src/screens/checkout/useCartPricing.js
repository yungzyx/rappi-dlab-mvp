import { basketsOf } from '../../api/orders'
import { usePro } from '../../state/pro'
import { DEFAULT_TIP, checkoutTotals, pricedBasket } from './pricing'
import { useStoreTerms } from './useStoreTerms'

/**
 * Los montos del carro como los calcula el checkout: una canasta por tienda con las condiciones del catálogo (o sus
 * supuestos), Rappi Pro de la persona y la propina. Sin cupón ni créditos: esos se eligen en el pago.
 * `{ isPro, priced, totals }` (pricing.js: pricedBasket y checkoutTotals).
 */
export function useCartPricing(items, { tip = DEFAULT_TIP, pickup = false } = {}) {
  const isPro = usePro()
  const baskets = basketsOf(items)
  const termsOf = useStoreTerms(baskets)
  const priced = baskets.map((basket) => pricedBasket(basket, termsOf(basket), { isPro, pickup }))
  return { isPro, priced, totals: checkoutTotals(priced, { tip, pickup }) }
}
