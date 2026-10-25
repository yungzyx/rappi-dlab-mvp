import { useEffect, useRef, useState } from 'react'
import { menu as loadMenu } from '../../api/catalog'
import { cartEventFields } from '../../api/orders'
import { useApi } from '../../api/useApi'
import { useShopAisles } from '../../api/useShopAisles'
import BackButton from '../../components/BackButton'
import ProductRow from '../../components/ProductRow'
import Img from '../../components/Img'
import OfflineNotice from '../../components/OfflineNotice'
import { useToast } from '../../components/Toast'
import { HeartIcon } from '../../components/Icons'
import { useEvents } from '../../state/EventsContext'
import { useFavorites } from '../../state/FavoritesContext'
import { StoreMeta } from '../../components/StoreMeta'
import RealMenu from './RealMenu'
import './store.css'

const MODES = ['Envío', 'Retiro']
const SKELETON_ROWS = 5

/** Las tiendas del catálogo se abren por su id numérico; las que el agente abre solo por nombre no están en la base. */
const catalogId = (id) => (/^\d+$/.test(String(id ?? '')) ? Number(id) : null)

/** El menú de un restaurante, con su tarjeta como `store`. */
async function readMenu(id) {
  const { restaurant, sections } = await loadMenu(id)
  return { store: restaurant, sections }
}

/**
 * Página de tienda (funcionalidad agregada: no está en los videos). Todo sale de la API (`/catalog`):
 * un restaurante (`params.store.vertical === 'restaurants'`) con su menú, y una tienda con sus pasillos, de a una página.
 * Muestra la foto, los datos de la tarjeta y ♥ para favoritos.
 * `params.item`: el producto que se tocó para llegar aquí (en el buscador con el agente, «Para ti» o una vertical), si lo hubo.
 */
export default function StoreScreen({ back, params }) {
  const given = params.store
  const id = catalogId(given.id)
  const restaurant = given.vertical === 'restaurants'
  const item = params.item
  const toast = useToast()
  const favorites = useFavorites()
  const events = useEvents()
  const [mode, setMode] = useState(MODES[0])
  const scrollRef = useRef(null)
  // Un restaurante trae su menú; una tienda, sus pasillos de a una página (cada uno pide solo lo suyo).
  const menu = useApi(() => (id === null || !restaurant ? null : readMenu(id)), [id, restaurant])
  const shop = useShopAisles(restaurant ? null : id)
  const { data, error, retry } = restaurant ? menu : shop
  const { aisles, aisle, setAisle, products, hasMore, loadMore, loadingMore } = shop

  const notInCatalog = id === null || error?.status === 404
  // Lo que manda la API (foto, tiempo, nota) reemplaza al enlace; mientras llega se ve lo que traía el enlace.
  const store = data?.store ?? given
  const isFavorite = favorites.isFavorite(store)

  // Una vez por tienda: StrictMode monta dos veces en desarrollo, y cambiar de pasillo vuelve a traer la misma tienda.
  const tracked = useRef(null)
  const loaded = data?.store
  useEffect(() => {
    if (!loaded || tracked.current === loaded.id) return
    tracked.current = loaded.id
    events.track('view_store', {
      vertical: loaded.vertical,
      entity_type: 'store',
      entity_id: String(loaded.id),
      payload: { name: loaded.name },
    })
    // Llegar tocando un producto es verlo (el prototipo no tiene página de producto): mismos campos que el carro.
    if (item) events.track('view_item', { ...cartEventFields(item), vertical: item.vertical ?? loaded.vertical })
  }, [loaded, item, events])

  const toggleFavorite = () => {
    favorites.toggle(store)
    toast(isFavorite ? 'Quitada de favoritos' : 'Agregada a favoritos')
  }

  // Un producto que llegó por parámetro y no está en lo que se ve se muestra destacado arriba.
  const listed = (candidate) => candidate.id === item?.id || candidate.name === item?.name
  const visible = data?.sections ? data.sections.flatMap((section) => section.items) : products
  const chosen = item && data && !visible.some(listed) ? item : null
  // Una sugerencia del agente que sí está en lo que se ve lleva su origen a esa fila: agregarla desde ahí cuenta la
  // aceptación (useAddToCart), como desde «Lo que elegiste».
  const withOrigin = (product) =>
    item?.fromSuggestion && listed(product)
      ? { ...product, fromSuggestion: true, suggestionOrigin: item.suggestionOrigin }
      : product

  return (
    <div ref={scrollRef} className="screen store">
      <div className={store.logo ? 'store-hero is-logo' : 'store-hero'}>
        <Img src={store.img} eager />
      </div>
      <BackButton className="store-round store-round--back" onClick={back} />
      {!notInCatalog && (
        <button
          type="button"
          className={isFavorite ? 'store-round store-round--fav is-on tap' : 'store-round store-round--fav tap'}
          aria-label={isFavorite ? 'Quitar de favoritos' : 'Agregar a favoritos'}
          aria-pressed={isFavorite}
          onClick={toggleFavorite}
        >
          <HeartIcon size={20} />
        </button>
      )}

      <section className="store-sheet">
        {store.name && <h1>{store.name}</h1>}
        {notInCatalog ? (
          <p className="store-empty">Esta tienda no está en el catálogo</p>
        ) : (
          <>
            {store.rating && <p className="store-rating">★ {store.rating}</p>}
            {store.eta && <StoreMeta store={store} className="store-meta" />}

            <div className="store-modes" role="tablist">
              {MODES.map((option) => (
                <button
                  key={option}
                  type="button"
                  role="tab"
                  aria-selected={option === mode}
                  className={option === mode ? 'store-mode is-active' : 'store-mode'}
                  onClick={() => setMode(option)}
                >
                  {option}
                </button>
              ))}
            </div>

            {chosen && (
              <>
                <h2 className="section-title store-title">Lo que elegiste</h2>
                <ul className="store-products">
                  <ProductRow product={chosen} />
                </ul>
              </>
            )}

            {aisles.length > 0 && <AisleTabs aisles={aisles} active={aisle} onChoose={setAisle} />}
            {error && <OfflineNotice onRetry={retry} />}
            {!data && !error && <MenuSkeleton tabs={aisles.length === 0} />}
            {data?.sections && (
              <RealMenu
                sections={data.sections.map((section) => ({ ...section, items: section.items.map(withOrigin) }))}
                scrollRef={scrollRef}
              />
            )}
            {data?.products &&
              (products.length > 0 ? (
                <>
                  <ul className="store-products">
                    {products.map((product) => (
                      <ProductRow key={product.id} product={withOrigin(product)} />
                    ))}
                  </ul>
                  {hasMore && (
                    <button type="button" className="store-more tap" disabled={loadingMore} onClick={loadMore}>
                      Ver más
                    </button>
                  )}
                </>
              ) : (
                <p className="store-empty">No hay productos para mostrar.</p>
              ))}
          </>
        )}
      </section>
    </div>
  )
}

/** Los pasillos de una tienda: al tocar uno se piden sus productos (no hay scroll entre pasillos, como en el menú de un restaurante). */
function AisleTabs({ aisles, active, onChoose }) {
  return (
    <nav className="menu-tabs" aria-label="Pasillos">
      {aisles.map((aisle) => (
        <button
          key={aisle.id}
          type="button"
          className={aisle.id === active ? 'menu-tab is-active' : 'menu-tab'}
          aria-current={aisle.id === active ? 'true' : undefined}
          onClick={() => onChoose(aisle.id)}
        >
          {aisle.name}
        </button>
      ))}
    </nav>
  )
}

function MenuSkeleton({ tabs }) {
  return (
    <div className="menu-skeleton" aria-label="Cargando" role="status">
      {tabs && (
        <div className="menu-skeleton-tabs">
          <span />
          <span />
          <span />
        </div>
      )}
      {Array.from({ length: SKELETON_ROWS }, (_, i) => (
        <div key={i} className="menu-skeleton-row">
          <span className="menu-skeleton-lines">
            <span />
            <span />
            <span />
          </span>
          <span className="menu-skeleton-photo" />
        </div>
      ))}
    </div>
  )
}
