import { useId } from 'react'
import { placeList } from '../../api/attribution'
import { restaurants, verticalStores } from '../../api/catalog'
import { storeItem } from '../../api/impressions'
import { useApi } from '../../api/useApi'
import HScroll from '../../components/HScroll'
import Img from '../../components/Img'
import TabPage from '../../components/TabPage'
import { useImpressions } from '../../hooks/useImpressions'
import { useFavorites } from '../../state/FavoritesContext'
import { RestaurantCard } from '../home/StoreCards'
import './favorites.css'

const BEST_RESTAURANTS = 4
const BEST_SUPERMARKETS = 2

/**
 * Pestaña Favoritos. "Tus favoritos" son las tiendas marcadas con ♥ en la página de tienda (se guardan en el navegador);
 * "Los mejores" salen del catálogo: son un extra, y si no llegan (o falla la API) no se muestran. Cada fila lleva su
 * lugar (pantalla `favorites`): abrir una tienda y verla lo dicen.
 */
export default function FavoritesScreen({ push }) {
  const favorites = useFavorites()
  const bestRestaurants = useApi(() => restaurants({ sort: 'rating', limit: BEST_RESTAURANTS }), [])
  const supermarkets = useApi(() => verticalStores('supermercado', { limit: BEST_SUPERMARKETS }), [])
  const openStore = (store) => push('store', { store })
  const watch = useImpressions()
  const mine = placeList(favorites.stores, { surface: 'favorites', origin: 'tus-favoritos' })

  return (
    <TabPage title="Mis favoritos" color="#ee7d3e" className="favorites">
      <Section title="Tus favoritos" modifier="first">
        {favorites.stores.length > 0 ? (
          <HScroll className="favorites-logos">
            {mine.map((store) => (
              <button
                key={store.id ?? store.name}
                ref={watch(store, storeItem(store))}
                type="button"
                className={store.logo ? 'favorite-logo is-logo tap' : 'favorite-logo tap'}
                onClick={() => openStore(store)}
              >
                <Img src={store.img} alt={store.name} />
              </button>
            ))}
          </HScroll>
        ) : (
          <p className="favorites-empty">Marca una tienda con ♥ y aparece aquí.</p>
        )}
      </Section>

      {supermarkets.data?.stores.length > 0 && (
        <Section title="Los mejores supermercados">
          <CardRow
            stores={placeList(supermarkets.data.stores, { surface: 'favorites', origin: 'mejores-supermercados' })}
            onOpen={openStore}
          />
        </Section>
      )}

      {bestRestaurants.data?.length > 0 && (
        <Section title="Los mejores restaurantes" modifier="restaurants">
          <CardRow
            stores={placeList(bestRestaurants.data, { surface: 'favorites', origin: 'mejores-restaurantes' })}
            onOpen={openStore}
            modifier="restaurants"
          />
        </Section>
      )}
    </TabPage>
  )
}

/** Una sección con su título; `modifier` ajusta el espacio de arriba (first, restaurants). */
function Section({ title, modifier, children }) {
  const titleId = useId()
  return (
    <section aria-labelledby={titleId}>
      <h2 id={titleId} className={modifier ? `favorites-heading favorites-heading--${modifier}` : 'favorites-heading'}>
        {title}
      </h2>
      {children}
    </section>
  )
}

function CardRow({ stores, onOpen, modifier }) {
  return (
    <HScroll className={modifier ? `card-row favorites-row favorites-row--${modifier}` : 'card-row favorites-row'}>
      {stores.map((store) => (
        <RestaurantCard key={store.id} store={store} onClick={() => onOpen(store)} impression />
      ))}
    </HScroll>
  )
}
