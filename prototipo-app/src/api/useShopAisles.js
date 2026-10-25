import { useState } from 'react'
import { useToast } from '../components/Toast'
import { store as loadShop } from './catalog'
import { useApi } from './useApi'

/**
 * Una tienda del catálogo con sus pasillos y de a una página de productos de uno (el que se elige; si no, el primero),
 * como la ven la página de tienda y Turbo. Con `shopId` en `null` no pide nada.
 * Devuelve:
 * - `data` y `error` (un `ApiError`: 404 = la tienda no está) tal como los entrega `useApi`, y `retry`;
 * - `aisles`: los pasillos, que se siguen viendo mientras llegan los productos del que se acaba de elegir;
 * - `aisle` y `setAisle`: el id del pasillo que se ve (el primero mientras no se elija otro) y cómo cambiarlo;
 * - `products`: los de ese pasillo que lleva cargados (la primera página y las que sumó `loadMore`, sin repetir ids);
 * - `hasMore`, `loadMore` y `loadingMore`: «Ver más» pide la página siguiente; si falla, avisa con un toast y se queda lo que ya había.
 */
export function useShopAisles(shopId) {
  const toast = useToast()
  const [chosen, setChosen] = useState(null) // el pasillo que se eligió; sin elegir, la API trae el primero
  const [aisles, setAisles] = useState([])
  // Las páginas que se sumaron con «Ver más», de un pasillo: valen solo mientras sea el que se ve.
  const [more, setMore] = useState(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const { data, error, retry } = useApi(
    () => (shopId === null ? null : loadShop(shopId, { aisle: chosen })),
    [shopId, chosen],
  )
  if (data?.aisles && data.aisles !== aisles) setAisles(data.aisles)

  const aisleKey = data?.products ? `${data.store.id}:${data.aisle?.id}` : null
  const added = more?.key === aisleKey ? more : null
  const products = data?.products ? [...data.products, ...(added?.products ?? [])] : []
  const hasMore = added ? added.hasMore : Boolean(data?.hasMore)

  const loadMore = async () => {
    const page = (added?.page ?? data.page) + 1
    setLoadingMore(true)
    try {
      const next = await loadShop(data.store.id, { aisle: data.aisle.id, page })
      const seen = new Set(products.map((product) => product.id))
      setMore({
        key: aisleKey,
        products: [...(added?.products ?? []), ...next.products.filter((product) => !seen.has(product.id))],
        page: next.page,
        hasMore: next.hasMore,
      })
    } catch {
      toast('No se pudo cargar más productos')
    } finally {
      setLoadingMore(false)
    }
  }

  return {
    data,
    error,
    retry,
    aisles,
    aisle: chosen ?? data?.aisle?.id ?? null,
    setAisle: setChosen,
    products,
    hasMore,
    loadMore,
    loadingMore,
  }
}
