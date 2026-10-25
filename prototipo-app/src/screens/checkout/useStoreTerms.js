import { storeTerms } from '../../api/catalog'
import { useApi } from '../../api/useApi'

/**
 * Lo que el catálogo sabe de las condiciones de compra de las tiendas de estas canastas (`/catalog/terms`): una función
 * canasta → `{ deliveryFee, minOrder, servicePct }` o null. Mientras carga, o si la API falla, null (el checkout usa sus
 * supuestos rotulados).
 */
export function useStoreTerms(baskets) {
  const ids = baskets
    .map((basket) => basket.storeId)
    .filter((id) => Number.isInteger(id))
    .sort((a, b) => a - b)
  const key = ids.join(',')
  const { data } = useApi(() => (key ? storeTerms(ids) : Promise.resolve(new Map())), [key], { keepPrevious: true })
  return (basket) => data?.get(basket.storeId) ?? null
}
