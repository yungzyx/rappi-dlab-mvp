import { useId } from 'react'
import { deals as loadDeals, restaurants, storeOfProduct } from '../../api/catalog'
import { useApi } from '../../api/useApi'
import HScroll from '../../components/HScroll'
import OfflineNotice from '../../components/OfflineNotice'
import { ProductCard } from '../../components/ProductCard'
import TabPage from '../../components/TabPage'
import { useToast } from '../../components/Toast'
import { VERTICAL_NAMES, screenForBackend } from '../../data/verticals'
import dealsCrown from '../../assets/deals-crown.webp'
import { RestaurantCard } from '../home/StoreCards'
import { DEAL_VERTICALS } from './data'
import './deals.css'

const BEST_RATED_COUNT = 6

/**
 * Las bajas de precio de cada vertical, en el orden de la pantalla: `[{ vertical, products }]`. Una vertical sin bajas, o
 * cuya llamada falla, no sale; solo si fallan todas se lanza el error (la pantalla dice «Sin conexión»).
 */
async function loadAllDeals() {
  const results = await Promise.allSettled(DEAL_VERTICALS.map((vertical) => loadDeals(vertical)))
  if (results.every((result) => result.status === 'rejected')) throw results[0].reason
  return DEAL_VERTICALS.map((vertical, i) => ({ vertical, products: results[i].value ?? [] })).filter(
    (group) => group.products.length > 0,
  )
}

/** Pestaña Offers → "Deals" (video del 26-09-2026). Las bajas de precio y los restaurantes salen de la API. */
export default function DealsScreen({ push }) {
  const toast = useToast()
  const deals = useApi(loadAllDeals, [])
  const bestRated = useApi(() => restaurants({ sort: 'rating', limit: BEST_RATED_COUNT }), [])
  // Con el producto tocado: la tienda registra que se vio.
  const openProductStore = (item) => push('store', { store: storeOfProduct(item), item })

  const offline = deals.error && deals.error.status !== 404
  const loaded = (deals.data || deals.error) && (bestRated.data || bestRated.error)
  const empty = loaded && !offline && !deals.data?.length && !bestRated.data?.length

  return (
    <TabPage
      title="Ofertas"
      color="#1f84f5"
      className="deals"
      action={
        <button type="button" className="tap" aria-label="Rappi Pro" onClick={() => toast()}>
          <img className="deals-crown" src={dealsCrown} alt="" />
        </button>
      }
    >
      {offline && (
        <OfflineNotice
          onRetry={() => {
            deals.retry()
            bestRated.retry()
          }}
        />
      )}
      {empty && <p className="deals-empty">Todavía no hay ofertas en el catálogo.</p>}

      {deals.data?.map(({ vertical, products }) => (
        <DealsSection key={vertical} vertical={vertical} products={products} onOpenStore={openProductStore} />
      ))}

      {/* Los restaurantes son un extra: si no vienen (o falló esa llamada), la sección no aparece. */}
      {bestRated.data?.length > 0 && <BestRated stores={bestRated.data} push={push} />}
    </TabPage>
  )
}

/** «Bajaron de precio» de una vertical: sus productos con el precio anterior y el descuento. */
function DealsSection({ vertical, products, onOpenStore }) {
  const titleId = useId()
  const name = VERTICAL_NAMES[screenForBackend(vertical)] ?? vertical
  return (
    <section className="deals-vertical" aria-labelledby={titleId}>
      <h2 id={titleId} className="section-title deals-vertical-title">
        Bajaron de precio en {name}
      </h2>
      <HScroll className="deals-product-row">
        {products.map((product) => (
          <ProductCard key={product.id} product={product} onOpenStore={() => onOpenStore(product)} />
        ))}
      </HScroll>
    </section>
  )
}

/** Los restaurantes de mejor nota; uno abre su menú. */
function BestRated({ stores, push }) {
  const titleId = useId()
  return (
    <section className="deals-restaurants" aria-labelledby={titleId}>
      <h2 id={titleId} className="section-title deals-restaurants-title">
        Mejor evaluados
      </h2>
      <HScroll className="card-row deals-card-row">
        {stores.map((store) => (
          <RestaurantCard key={store.id} store={store} onClick={() => push('store', { store })} />
        ))}
      </HScroll>
    </section>
  )
}
