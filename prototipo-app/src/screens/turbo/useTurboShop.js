import { verticalStores } from '../../api/catalog'
import { useApi } from '../../api/useApi'
import { useShopAisles } from '../../api/useShopAisles'

/**
 * La tienda Turbo de la que sale la pantalla: la primera de `verticalStores('turbo')` (la de más productos vigentes), con sus
 * pasillos (las pestañas) y de a una página de productos de uno: ver `useShopAisles`.
 * Devuelve `{ info, aisles, aisle, aisleName, setAisle, products, hasMore, loadMore, loadingMore, status, retry }`:
 * - `info`: la tarjeta de la tienda (`eta`, nombre…), apenas llega la lista;
 * - `aisleName`: el nombre del pasillo que se ve;
 * - `status`: 'loading', 'ready', 'empty' (no hay tienda Turbo en el catálogo) o 'offline' (la API no contesta).
 */
export function useTurboShop() {
  const stores = useApi(() => verticalStores('turbo'), [])
  const shopId = stores.data?.stores[0]?.id ?? null
  const shop = useShopAisles(shopId)

  // Un 404 (la tienda ya no está) es «no hay», no «sin conexión»; cualquier otro fallo, sí.
  const unavailable = (error) => (error.status === 404 ? 'empty' : 'offline')
  let status = 'loading'
  if (stores.error) status = unavailable(stores.error)
  else if (stores.data && shopId === null) status = 'empty'
  else if (shop.error) status = unavailable(shop.error)
  else if (shop.data) status = 'ready'

  return {
    info: stores.data?.stores[0] ?? null,
    aisles: shop.aisles,
    aisle: shop.aisle,
    aisleName: shop.data?.aisle?.name ?? null,
    setAisle: shop.setAisle,
    products: shop.products,
    hasMore: shop.hasMore,
    loadMore: shop.loadMore,
    loadingMore: shop.loadingMore,
    status,
    retry: () => (stores.error ? stores.retry() : shop.retry()),
  }
}
