import { useId, useState } from 'react'
import { home, restaurants } from '../../api/catalog'
import { useApi } from '../../api/useApi'
import Carousel, { Dots } from '../../components/Carousel'
import HScroll from '../../components/HScroll'
import { useToast } from '../../components/Toast'
import { ChevronRight } from '../../components/Icons'
import { RestaurantCard, StoreTile } from './StoreCards'
import { MAIN_TILES, PROMOS, PROMO_START_INDEX, SHORTCUTS, orderShortcuts } from '../../data/home'
import './home.css'

// Secciones de la Home que comparten «Rappi hoy» y el prototipo final.

/** Restaurantes y Turbo. `onOpen(vertical)` avisa cuál se tocó (código del backend). */
export function MainTiles({ push, onOpen }) {
  return (
    <section className="home-tiles">
      {MAIN_TILES.map((tile) => (
        <button
          key={tile.id}
          type="button"
          className={`home-tile home-tile--${tile.id} tap`}
          onClick={() => {
            onOpen?.(tile.vertical)
            push(tile.screen)
          }}
        >
          <img src={tile.img} alt="" />
          <span>{tile.label}</span>
        </button>
      ))}
    </section>
  )
}

/**
 * Fila de verticales. `proposal` es el prototipo final: RappiFavor (no disponible hoy) sí abre, y los 6 verticales siguen
 * `order` (códigos del backend; sin él, el orden fijo) con Lealtad y Beneficios Pro al final. `caption` va bajo la fila;
 * en el prototipo final su línea queda reservada (vacía si no hay leyenda) para que la fila no se mueva al aparecer.
 * `onOpen(vertical)` avisa qué vertical se tocó (código del backend); los accesos sin vertical no avisan.
 */
export function Shortcuts({ push, proposal = false, order = null, caption = null, onOpen, onService }) {
  const toast = useToast()
  return (
    <>
      <HScroll className="home-shortcuts">
        {orderShortcuts(SHORTCUTS, order, { final: proposal }).map((item) => {
          const enabled = proposal && item.proposalRoute
          const unavailable = item.unavailable && !enabled
          const route = enabled ? item.proposalRoute : item.route
          return (
            <button
              key={item.id}
              type="button"
              className={unavailable ? 'home-shortcut is-unavailable tap' : 'home-shortcut tap'}
              aria-label={unavailable ? `${item.label} (no disponible)` : undefined}
              onClick={() => {
                if (item.vertical) onOpen?.(item.vertical)
                if (unavailable) toast(`${item.label} no está disponible`)
                else if (route) {
                  if (item.service) onService?.(item.service) // abrir RappiFavor o RappiTravel: `service_opened`
                  push(...route)
                } else toast()
              }}
            >
              {enabled ? (
                <i className="home-shortcut-emoji" aria-hidden="true">
                  {item.emoji}
                </i>
              ) : (
                <img src={item.img} alt="" draggable="false" loading="lazy" />
              )}
              {!unavailable && <span>{item.label}</span>}
            </button>
          )
        })}
      </HScroll>
      {(proposal || caption) && <p className="home-shortcuts-caption">{caption}</p>}
    </>
  )
}

/** Carrusel de promociones con sus puntos (paginan con el carrusel). */
export function Promos({ push, autoplayMs = 4500 }) {
  const toast = useToast()
  const [index, setIndex] = useState(PROMO_START_INDEX)
  return (
    <>
      <Carousel
        className="home-promos"
        initialIndex={PROMO_START_INDEX}
        autoplayMs={autoplayMs}
        onIndexChange={setIndex}
      >
        {PROMOS.map((promo) => (
          <button
            key={promo.id}
            type="button"
            className={`home-promo home-promo--${promo.fit}`}
            aria-label={promo.label}
            onClick={() => (promo.route ? push(...promo.route) : toast())}
          >
            <img src={promo.img} alt="" draggable="false" loading="lazy" />
          </button>
        ))}
      </Carousel>
      <Dots count={PROMOS.length} active={index} className="dots--wide home-promo-dots" />
    </>
  )
}

const BEST_RATED_COUNT = 6

/**
 * Las listas de la Home que salen del catálogo (`/catalog`): restaurantes rápidos y tiendas cerca (una llamada) y los mejor
 * evaluados (otra). La Home nunca espera ni se bloquea: una lista que no llega, o que falla, queda vacía y su sección no se ve.
 */
export function useHomeCatalog() {
  const lists = useApi(home, [])
  const bestRated = useApi(() => restaurants({ sort: 'rating', limit: BEST_RATED_COUNT }), [])
  return {
    fastRestaurants: lists.data?.fastRestaurants ?? [],
    nearbyStores: lists.data?.nearbyStores ?? [],
    bestRated: bestRated.data ?? [],
  }
}

/** Una fila de tarjetas de restaurante con su título; un restaurante abre su menú. Sin restaurantes, no se ve. */
function RestaurantRow({ title, stores, push }) {
  const titleId = useId()
  if (stores.length === 0) return null
  return (
    <section aria-labelledby={titleId}>
      <h2 id={titleId} className="section-title home-list-title">
        {title}
      </h2>
      <HScroll className="home-cards home-cards--list">
        {stores.map((store) => (
          <RestaurantCard key={store.id} store={store} onClick={() => push('store', { store })} />
        ))}
      </HScroll>
    </section>
  )
}

export const FastRestaurants = ({ stores, push }) => (
  <RestaurantRow title="Restaurantes rápidos" stores={stores} push={push} />
)

export const BestRated = ({ stores, push }) => <RestaurantRow title="Mejor evaluados" stores={stores} push={push} />

export function NearbyStores({ stores, push }) {
  const toast = useToast()
  const titleId = useId()
  if (stores.length === 0) return null
  return (
    <section className="home-nearby" aria-labelledby={titleId}>
      <div className="home-section-head">
        <h2 id={titleId} className="section-title">
          Cerca de ti
        </h2>
        <button type="button" className="chevron-button tap" aria-label="Ver todas" onClick={() => toast()}>
          <ChevronRight size={20} />
        </button>
      </div>
      <div className="home-store-grid">
        {stores.map((store) => (
          <StoreTile key={store.id} store={store} onClick={() => push('store', { store })} />
        ))}
      </div>
    </section>
  )
}
