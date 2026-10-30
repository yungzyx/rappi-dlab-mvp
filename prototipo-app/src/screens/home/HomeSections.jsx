import { useId, useLayoutEffect, useRef, useState } from 'react'
import { place, placeList } from '../../api/attribution'
import { verticalItem } from '../../api/impressions'
import { home, restaurants } from '../../api/catalog'
import { useApi } from '../../api/useApi'
import Carousel, { Dots } from '../../components/Carousel'
import HScroll from '../../components/HScroll'
import { useToast } from '../../components/Toast'
import { useImpressions } from '../../hooks/useImpressions'
import { useReducedMotion } from '../../hooks/useReducedMotion'
import { ChevronRight } from '../../components/Icons'
import { RestaurantCard, StoreTile } from './StoreCards'
import { MAIN_TILES, PROMOS, PROMO_START_INDEX, SHORTCUTS, orderShortcuts } from '../../data/home'
import './home.css'

// Secciones de la Home que comparten "Rappi hoy" y el prototipo final.

/**
 * Restaurantes y Turbo. `onOpen(vertical, where)` avisa cuál se tocó (código del backend) y dónde estaba (`where`:
 * `{ origin: 'accesos-grandes', position }`, para el sobre del evento).
 */
export function MainTiles({ push, onOpen }) {
  const watch = useImpressions()
  return (
    <section className="home-tiles">
      {MAIN_TILES.map((tile, position) => (
        <button
          key={tile.id}
          type="button"
          className={`home-tile home-tile--${tile.id} tap`}
          ref={watch(
            place(tile, { surface: 'home', origin: 'accesos-grandes', position }),
            verticalItem(tile.vertical),
          )}
          onClick={() => {
            onOpen?.(tile.vertical, { origin: 'accesos-grandes', position })
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

const GLIDE_MS = 650
const MOVED_MS = 1800

/**
 * Los accesos se deslizan a su lugar nuevo cuando cambia `glide.key` (FLIP: cada uno parte de donde estaba, medido en la
 * fila, no en la pantalla, así que el scroll no lo engaña), y el que subió (`glide.vertical`) brilla un momento si
 * `glide.highlight`. Con `glide.delay` (ms) esperan en su lugar de antes: Mochi llega primero y después los mueve. Con
 * movimiento reducido no se deslizan: solo brilla.
 */
function useGlide(glide) {
  const reduceMotion = useReducedMotion()
  const tiles = useRef(new Map()) // id del acceso → su botón
  const lefts = useRef(new Map()) // id del acceso → su lugar en la fila en el último render
  const played = useRef(null)
  useLayoutEffect(() => {
    const now = new Map([...tiles.current].map(([id, element]) => [id, element.offsetLeft]))
    if (glide && glide.key !== played.current) {
      played.current = glide.key
      const delay = reduceMotion ? 0 : (glide.delay ?? 0)
      for (const [id, element] of tiles.current) {
        const before = lefts.current.get(id)
        const shift = before === undefined ? 0 : before - now.get(id)
        if (shift && !reduceMotion)
          element.animate?.([{ transform: `translateX(${shift}px)` }, { transform: 'none' }], {
            duration: GLIDE_MS,
            delay,
            fill: 'backwards', // mientras espera, en su lugar de antes
            easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
          })
        if (glide.highlight && element.dataset.vertical === glide.vertical)
          setTimeout(() => {
            element.classList.remove('is-moved')
            void element.offsetWidth // para que la animación vuelva a empezar si ya lo tenía
            element.classList.add('is-moved')
            setTimeout(() => element.classList.remove('is-moved'), MOVED_MS)
          }, delay)
      }
    }
    lefts.current = now
  })
  return (id) => (element) => {
    if (element) tiles.current.set(id, element)
    else tiles.current.delete(id)
  }
}

/**
 * Fila de verticales. `proposal` es el prototipo final: RappiFavor (no disponible hoy) sí abre, y los 6 verticales siguen
 * `order` (códigos del backend; sin él, el orden fijo) con Lealtad y Beneficios Pro al final. `caption` va bajo la fila;
 * en el prototipo final su línea queda reservada (vacía si no hay leyenda) para que la fila no se mueva al aparecer.
 * `onOpen(vertical, where)` avisa qué vertical se tocó (código del backend) y dónde estaba (`where`: `{ origin:
 * 'accesos', position }`, su lugar en la fila tal como se ve); los accesos sin vertical no avisan. Cada acceso con
 * vertical cuenta como visto en la fila (api/impressions.js), con `requestId`, la respuesta que ordenó la fila.
 * `glide` (prototipo final): el último cambio de orden, para que los accesos se deslicen (ver useGlide).
 */
export function Shortcuts({
  push,
  proposal = false,
  order = null,
  caption = null,
  onOpen,
  onService,
  requestId,
  glide = null,
}) {
  const toast = useToast()
  const watch = useImpressions()
  const tile = useGlide(glide)
  return (
    <>
      <HScroll className="home-shortcuts">
        {orderShortcuts(SHORTCUTS, order, { final: proposal }).map((item, position) => {
          const enabled = proposal && item.proposalRoute
          const unavailable = item.unavailable && !enabled
          const route = enabled ? item.proposalRoute : item.route
          const seen = item.vertical
            ? watch(
                place(item, { surface: 'home', origin: 'accesos', position, requestId }),
                verticalItem(item.vertical),
              )
            : null
          const mine = tile(item.id)
          return (
            <button
              key={item.id}
              type="button"
              className={unavailable ? 'home-shortcut is-unavailable tap' : 'home-shortcut tap'}
              data-vertical={item.vertical}
              ref={(element) => {
                mine(element)
                const unwatch = seen?.(element)
                return () => {
                  mine(null)
                  unwatch?.()
                }
              }}
              aria-label={unavailable ? `${item.label} (no disponible)` : undefined}
              onClick={() => {
                if (item.vertical) onOpen?.(item.vertical, { origin: 'accesos', position })
                if (unavailable) toast(`${item.label} no está disponible`)
                else if (route) {
                  // abrir RappiFavor o RappiTravel: `service_opened`, con su lugar en los accesos
                  if (item.service) onService?.(item.service, { origin: 'accesos', position })
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
 * Cada tienda lleva su lugar (`placement`): abrirla lo dice en `view_store`.
 */
export function useHomeCatalog() {
  const lists = useApi(home, [])
  const bestRated = useApi(() => restaurants({ sort: 'rating', limit: BEST_RATED_COUNT }), [])
  return {
    fastRestaurants: lists.data?.fastRestaurants ?? [],
    nearbyStores: lists.data?.nearbyStores ?? [],
    // Solo los que tienen nota: uno sin nota no es de los mejor evaluados.
    bestRated: placeList(
      (bestRated.data ?? []).filter((store) => store.rating),
      { surface: 'home', origin: 'mejor-evaluados' },
    ),
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
          <RestaurantCard key={store.id} store={store} onClick={() => push('store', { store })} impression />
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
          <StoreTile key={store.id} store={store} onClick={() => push('store', { store })} impression />
        ))}
      </div>
    </section>
  )
}
