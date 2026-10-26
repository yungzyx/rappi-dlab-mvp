import { useEffect, useRef, useState } from 'react'
import { noteItemView, noteRecommendationClick, placeList, placementFields } from '../../api/attribution'
import { menu as loadMenu, storeForYou } from '../../api/catalog'
import { cartEventFields } from '../../api/orders'
import { useApi } from '../../api/useApi'
import { userId } from '../../api/user'
import { useShopAisles } from '../../api/useShopAisles'
import BackButton from '../../components/BackButton'
import ProductRow from '../../components/ProductRow'
import Img from '../../components/Img'
import OfflineNotice from '../../components/OfflineNotice'
import { ReorderCarousel } from '../../components/reorder/Reorder'
import ThresholdBar from '../../components/ThresholdBar'
import { useToast } from '../../components/Toast'
import { HeartIcon } from '../../components/Icons'
import { HOURS_SOURCE_NOTE, hoursLabel } from '../../components/storeHours'
import { parsePrice, useCart } from '../../state/CartContext'
import { useDemo } from '../../state/DemoContext'
import { useEvents } from '../../state/EventsContext'
import { useFavorites } from '../../state/FavoritesContext'
import { StoreMeta } from '../../components/StoreMeta'
import RealMenu from './RealMenu'
import './store.css'

const MODES = ['Envío', 'Retiro']
const SKELETON_ROWS = 5
const FOR_YOU = 'Para ti'
const FOR_YOU_TAB = 'para-ti' // la pestaña «Para ti» entre los pasillos de una tienda

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
 * Muestra la foto, los datos de la tarjeta, si está cerrada según lo publicado en la descarga, sus promos (con la barra
 * «Agrega $X» si la promo dice su mínimo) y ♥ para favoritos. En la propuesta suma «Para ti»: lo de la tienda que calza
 * con los intereses de la persona (una pestaña más, o la primera sección del menú). «Lo más pedido» del menú es la señal
 * de Rappi (sus platos populares); una tienda no publica una, así que no tiene esa pestaña.
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
  const final = useDemo()?.isFinal === true
  const forYou = useApi(() => (final && id !== null ? storeForYou(id, userId()).catch(() => null) : null), [final, id])
  const forYouProducts = forYou.data?.products ?? []
  const [forYouTab, setForYouTab] = useState(false)
  const cart = useCart()

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
    // Con el sobre de dónde se tocó la tienda (una lista de la Home, por ejemplo), si venía de una.
    events.track('view_store', {
      ...placementFields(given),
      vertical: loaded.vertical,
      entity_type: 'store',
      entity_id: String(loaded.id),
      payload: { name: loaded.name },
    })
    // Llegar tocando un producto es verlo (el prototipo no tiene página de producto): mismos campos que el carro, con
    // su sobre. Si venía de una recomendación (Mochi, «Para ti») es además su clic: una vez, aunque ya se abriera en la
    // hoja del producto.
    if (item) {
      const fields = { ...cartEventFields(item), vertical: item.vertical ?? loaded.vertical }
      noteItemView(events.track, item, fields) // si ya se vio en la hoja («Ver tienda»), no se cuenta otra vez
      noteRecommendationClick(events.track, item, fields)
    }
  }, [loaded, item, given, events])

  const toggleFavorite = () => {
    favorites.toggle(store)
    toast(isFavorite ? 'Quitada de favoritos' : 'Agregada a favoritos')
  }

  // Un producto que llegó por parámetro y no está en lo que se ve se muestra destacado arriba.
  const listed = (candidate) => candidate.id === item?.id || candidate.name === item?.name
  const visible = data?.sections ? data.sections.flatMap((section) => section.items) : products
  const chosen = item && data && !visible.some(listed) ? item : null
  // Una sugerencia del agente que sí está en lo que se ve lleva su origen a esa fila: agregarla desde ahí cuenta la
  // aceptación (useAddToCart), como desde «Lo que elegiste», y el carro dice que salió de la oferta (su lugar).
  const withOrigin = (product) =>
    item?.fromSuggestion && listed(product)
      ? {
          ...product,
          fromSuggestion: true,
          suggestionOrigin: item.suggestionOrigin,
          placement: item.placement ?? product.placement,
        }
      : product
  // Cada producto de la tienda con su lugar: el pasillo (o el menú, de corrido entre secciones) y su posición.
  const inStore = (list, start = 0) =>
    placeList(list, { surface: 'store', origin: restaurant ? 'menu' : 'pasillo', start }).map(withOrigin)
  const menuSections = data?.sections?.reduce(
    ({ sections, start }, section) => ({
      sections: [...sections, { ...section, items: inStore(section.items, start) }],
      start: start + section.items.length,
    }),
    // «Para ti» abre el menú con su propio lugar (`para-ti`, de su respuesta).
    { sections: forYouProducts.length ? [{ name: FOR_YOU, items: forYouProducts }] : [], start: 0 },
  ).sections
  const showingForYou = forYouTab && forYouProducts.length > 0
  // La promo con un mínimo publicado en su texto y lo que el carro ya suma en esta tienda.
  const thresholdPromo = store.promos?.find((promo) => promo.threshold > 0)
  const inThisStore = cart.items
    .filter((line) => line.product.storeId === store.id)
    .reduce((sum, line) => sum + line.qty * parsePrice(line.product.price), 0)
  const hours = hoursLabel(store.hours)

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
            {store.eta && <StoreMeta store={{ ...store, hours: null }} className="store-meta" />}
            {hours && (
              <p className={store.hours.open ? 'store-hours' : 'store-hours is-closed'}>
                {hours}
                <small>{HOURS_SOURCE_NOTE[store.hours.source]}</small>
              </p>
            )}
            {store.promos?.length > 0 && (
              <div className="store-promos">
                <ul aria-label="Promociones de la tienda">
                  {store.promos.map((promo) => (
                    <li key={promo.title}>{promo.title}</li>
                  ))}
                </ul>
                <small>Promos publicadas por la tienda en Rappi el día de la descarga.</small>
              </div>
            )}
            {thresholdPromo && (
              <ThresholdBar
                className="store-threshold"
                goal={thresholdPromo.threshold}
                total={inThisStore}
                title={thresholdPromo.title}
                pending={(amount) => <>Agrega {amount} en esta tienda para lograrlo.</>}
                done="Tu carro ya llega al mínimo de la promo."
                note="El mínimo es el del texto de la promo; esta demo no la descuenta al pagar."
              />
            )}

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

            {/* «Pídelo de nuevo»: lo que la persona ya compró en esta tienda y sigue a la venta. */}
            <ReorderCarousel storeId={id} />

            {chosen && (
              <>
                <h2 className="section-title store-title">Lo que elegiste</h2>
                <ul className="store-products">
                  <ProductRow product={chosen} />
                </ul>
              </>
            )}

            {aisles.length > 0 && (
              <AisleTabs
                aisles={aisles}
                active={showingForYou ? FOR_YOU_TAB : aisle}
                forYou={forYouProducts.length > 0}
                onChoose={(chosenAisle) => {
                  setForYouTab(chosenAisle === FOR_YOU_TAB)
                  if (chosenAisle !== FOR_YOU_TAB) setAisle(chosenAisle)
                }}
              />
            )}
            {error && <OfflineNotice onRetry={retry} />}
            {!data && !error && <MenuSkeleton tabs={aisles.length === 0} />}
            {data?.sections && <RealMenu sections={menuSections} scrollRef={scrollRef} />}
            {showingForYou && !restaurant && (
              <ul className="store-products" aria-label={FOR_YOU}>
                {forYouProducts.map((product) => (
                  <ProductRow key={product.id} product={product} impression />
                ))}
              </ul>
            )}
            {data?.products &&
              !showingForYou &&
              (products.length > 0 ? (
                <>
                  <ul className="store-products">
                    {inStore(products).map((product) => (
                      <ProductRow key={product.id} product={product} impression />
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

/**
 * Los pasillos de una tienda: al tocar uno se piden sus productos (no hay scroll entre pasillos, como en el menú de un
 * restaurante). Con `forYou`, la primera pestaña es «Para ti» (`FOR_YOU_TAB`).
 */
function AisleTabs({ aisles, active, forYou, onChoose }) {
  const tabs = forYou ? [{ id: FOR_YOU_TAB, name: FOR_YOU }, ...aisles] : aisles
  return (
    <nav className="menu-tabs" aria-label="Pasillos">
      {tabs.map((aisle) => (
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
