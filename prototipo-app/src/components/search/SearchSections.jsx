import { useEffect, useId, useRef, useState } from 'react'
import { envelope, placeList } from '../../api/attribution'
import { home } from '../../api/catalog'
import { offer } from '../../api/agent'
import { searchSuggestions } from '../../api/search'
import { noteAccepted, noteShown } from '../../api/suggestions'
import { userId } from '../../api/user'
import { useApi } from '../../api/useApi'
import { VERTICAL_NAMES } from '../../data/verticals'
import { useEvents } from '../../state/EventsContext'
import { useProfile } from '../../state/ProfileContext'
import Mascot from '../assistant/Mascot'
import OfferWhy from '../assistant/OfferWhy'
import OfflineNotice from '../OfflineNotice'
import ProductRow from '../ProductRow'
import StoreList from '../StoreList'

// Las mismas ideas que rota el buscador de la Home (PlainSearchBar).
const IDEAS = ['Plátano', 'Agua', 'Chocolate', 'Hamburguesa', 'Cerveza', 'Pizza']
const POPULAR_COUNT = 6
// Productos que se ven de cada vertical; "Ver más" muestra el resto de lo que trajo la API.
const GROUP_PREVIEW = 3
const NO_RESULT_ORIGIN = 'agent-sin_resultado'
const WHIM_ORIGIN = 'lo-que-sea'
// Tiendas o restaurantes que se ven de cada bloque; "Ver todos" muestra el resto.
const PLACES_PREVIEW = 3
// De qué población sale "Lo más buscado" (la API la declara; nunca se mezclan).
const POPULATION_NOTE = {
  synthetic: 'Entre las personas simuladas de la demo.',
  prototype: 'Entre quienes usan el prototipo.',
}

/**
 * Antes de escribir: las búsquedas recientes de la persona y "Lo más buscado" de la población que declara la API, o las
 * ideas fijas si no hay ninguna de las dos (o la API no responde). `onPick(term, fuente)`: `reciente`, `lo-mas-buscado`
 * o `sugerencia`.
 */
export function SearchIdeas({ onPick }) {
  const { data } = useApi(() => searchSuggestions(userId()).catch(() => null), [])
  const recent = data?.recent ?? []
  const top = data?.top ?? []
  return (
    <>
      {recent.length > 0 && <Chips title="Búsquedas recientes" terms={recent} onPick={(t) => onPick(t, 'reciente')} />}
      {top.length > 0 && (
        <Chips
          title="Lo más buscado"
          note={POPULATION_NOTE[data.population]}
          terms={top}
          onPick={(t) => onPick(t, 'lo-mas-buscado')}
        />
      )}
      {recent.length === 0 && top.length === 0 && (
        <Chips title="Ideas para buscar" terms={IDEAS} onPick={(t) => onPick(t, 'sugerencia')} />
      )}
    </>
  )
}

function Chips({ title, note, terms, onPick }) {
  return (
    <>
      <h2 className="search-heading">{title}</h2>
      {note && <p className="search-note">{note}</p>}
      <div className="search-chips">
        {terms.map((term) => (
          <button key={term} type="button" className="search-chip tap" onClick={() => onPick(term)}>
            {term}
          </button>
        ))}
      </div>
    </>
  )
}

/**
 * Las tiendas populares son las cercanas de la Home de la API; si no llega, la sección no aparece. Cada una con su lugar
 * en el buscador (`tiendas-populares`).
 */
export function PopularStores({ onOpen }) {
  const { data } = useApi(home, [])
  if (!data?.nearbyStores.length) return null
  const stores = placeList(data.nearbyStores.slice(0, POPULAR_COUNT), {
    surface: 'search',
    origin: 'tiendas-populares',
    requestId: data.requestId,
  })
  return (
    <>
      <h2 className="search-heading">Tiendas populares</h2>
      <StoreList stores={stores} onOpen={onOpen} impression />
    </>
  )
}

/**
 * Resultados de una búsqueda escrita (`data` de `useSearch`): un grupo por vertical con su nombre, o el aviso de que no
 * hay, o "Sin conexión". Un producto se abre en su tienda (`onOpenProduct`). Mientras carga se ven los resultados
 * anteriores. Con `onOpenVertical` (solo el buscador con el agente), sin resultados el agente no deja un callejón sin salida:
 * ofrece la vertical que tiene lo buscado o invita a buscar con otras palabras (`onTryAnother`). Si la API corrigió un
 * error de tipeo, dice qué buscó y, con `onSearchExact`, ofrece buscar lo escrito tal cual. Si la dieta o las
 * alergias de la persona sacaron algo (`data.preferencesNotice`, solo en la propuesta), lo dice; si sacaron todo, no
 * es "sin resultado" (ni Mochi ni "Lo que sea" lo ofrecen).
 * Antes de los productos van las tiendas y los restaurantes que se llaman así (`onOpenStore`), cada bloque con "Ver
 * todos". Con `onSeeAll(vertical)`, "Ver todos" de un grupo de productos abre la búsqueda solo en esa vertical (si no,
 * muestra el resto ahí mismo). Sin resultados y con `onOpenFavor(texto)`, ofrece "Lo que sea": pedirlo con RappiFavor,
 * si las guardias de la API lo permiten (`data.whimAllowed`).
 */
export function SearchResults({
  query,
  data,
  loading = false,
  error = null,
  onRetry,
  onOpenProduct,
  onOpenStore,
  onOpenVertical,
  onTryAnother,
  onSearchExact,
  onSeeAll,
  onOpenFavor,
}) {
  if (error) return <OfflineNotice onRetry={onRetry} />
  if (!data)
    return loading ? (
      <p className="search-loading" role="status">
        Buscando…
      </p>
    ) : null

  const text = query.trim()
  const stores = data.places?.stores ?? []
  const restaurants = data.places?.restaurants ?? []
  // La dieta y las alergias que la persona le dijo a Mochi filtran la búsqueda de la propuesta: la API lo dice.
  const filtered = data.preferencesNotice && (
    <p className="search-preferences" role="status">
      {data.preferencesNotice}
    </p>
  )
  // Sin nada que mostrar, el aviso espera a que llegue la respuesta de lo escrito (no se mezcla con lo de antes).
  if (data.groups.length === 0 && stores.length === 0 && restaurants.length === 0) {
    if (loading) return null
    // Lo encontrado lo sacaron sus preferencias: el catálogo sí lo tiene, así que no es "sin resultado".
    if (filtered && !data.unmet)
      return (
        <>
          <p className="search-empty">Nada de lo que encontré para "{text}" calza con tus preferencias.</p>
          {filtered}
        </>
      )
    const whim = data.whimAllowed && onOpenFavor && (
      <WhimOffer key={`whim|${text}`} query={text} requestId={data.requestId} onOpenFavor={onOpenFavor} />
    )
    // Solo en "Prototipo MVP.html" (`npm run demo:html`): la API simulada busca por palabras en una muestra y dice por
    // qué no encontró (`unmetReason`); sin esto, una falta de tipeo parece la app rota.
    const offline = import.meta.env.VITE_OFFLINE_DEMO === '1' && data.unmetReason && (
      <p className="search-offline">
        Demo sin conexión: busca solo en una muestra y no corrige faltas de tipeo; en dlab-mvp.com sí.
      </p>
    )
    return onOpenVertical ? (
      <>
        <AgentEmpty key={text} query={text} onOpenVertical={onOpenVertical} onTryAnother={onTryAnother} />
        {offline}
        {whim}
      </>
    ) : (
      <>
        <p className="search-empty">Sin resultados para "{text}".</p>
        {offline}
        {whim}
      </>
    )
  }

  return (
    <>
      {filtered}
      {data.correctedQuery && (
        <p className="search-corrected" role="status">
          Mostrando resultados para "{data.correctedQuery}".
          {onSearchExact && (
            <button type="button" className="search-exact tap" onClick={() => onSearchExact(data.query)}>
              Buscar "{data.query}" tal cual
            </button>
          )}
        </p>
      )}
      {onOpenStore && stores.length > 0 && (
        <PlaceGroup key={`${data.query}|tiendas`} title="Tiendas" places={stores} onOpen={onOpenStore} />
      )}
      {onOpenStore && restaurants.length > 0 && (
        <PlaceGroup key={`${data.query}|restaurantes`} title="Restaurantes" places={restaurants} onOpen={onOpenStore} />
      )}
      {data.groups.map((group) => (
        <ResultGroup
          key={`${data.query}|${group.vertical}`}
          group={group}
          onOpenProduct={onOpenProduct}
          onSeeAll={onSeeAll}
        />
      ))}
    </>
  )
}

/** Un bloque de tiendas o de restaurantes de la búsqueda (ya con su lugar): los primeros y "Ver todos". */
function PlaceGroup({ title, places, onOpen }) {
  const titleId = useId()
  const [expanded, setExpanded] = useState(false)
  const hidden = places.length - PLACES_PREVIEW
  return (
    <section aria-labelledby={titleId}>
      <h2 id={titleId} className="search-heading">
        {title}
      </h2>
      <StoreList stores={expanded ? places : places.slice(0, PLACES_PREVIEW)} onOpen={onOpen} impression />
      {!expanded && hidden > 0 && (
        <button type="button" className="search-more tap" onClick={() => setExpanded(true)}>
          Ver todos ({places.length})
        </button>
      )}
    </section>
  )
}

function ResultGroup({ group, onOpenProduct, onSeeAll }) {
  const titleId = useId()
  const [expanded, setExpanded] = useState(false)
  const hidden = group.products.length - GROUP_PREVIEW
  const shown = expanded ? group.products : group.products.slice(0, GROUP_PREVIEW)
  const name = VERTICAL_NAMES[group.vertical] ?? group.vertical
  return (
    <section aria-labelledby={titleId}>
      <h2 id={titleId} className="search-heading">
        {name}
      </h2>
      <ul className="search-products">
        {shown.map((product) => (
          <ProductRow
            key={product.id}
            product={product}
            showStore
            impression
            onOpenStore={onOpenProduct && product.storeId != null ? () => onOpenProduct(product) : undefined}
          />
        ))}
      </ul>
      {onSeeAll ? (
        <button type="button" className="search-more tap" onClick={() => onSeeAll(group.vertical)}>
          Ver todos en {name}
        </button>
      ) : (
        !expanded &&
        hidden > 0 && (
          <button type="button" className="search-more tap" onClick={() => setExpanded(true)}>
            Ver más ({hidden})
          </button>
        )
      )}
    </section>
  )
}

/**
 * "Lo que sea": lo buscado no está en el catálogo y la app ofrece conseguirlo con RappiFavor, con el texto ya escrito.
 * Solo aparece si la API lo permite (las guardias y las palabras bloqueadas del encargo). Mostrarlo es un
 * `service_shown` y tocarlo un `service_opened` (`rappifavor`), los dos con su lugar (`lo-que-sea`) y la búsqueda.
 */
function WhimOffer({ query, requestId, onOpenFavor }) {
  const events = useEvents()
  const shown = useRef(false)
  const fields = envelope({ surface: 'search', origin: WHIM_ORIGIN, requestId })
  useEffect(() => {
    if (shown.current) return
    shown.current = true
    events.track('service_shown', { ...fields, payload: { servicio: 'rappifavor' } })
    // Una vez por búsqueda: el sobre es de la misma respuesta.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const open = () => {
    events.track('service_opened', { ...fields, payload: { servicio: 'rappifavor' } })
    onOpenFavor(query)
  }
  return (
    <div className="search-whim" role="status">
      <p>
        <strong>¿No lo encuentras? Te lo conseguimos</strong>
        Un Rappitendero lo busca y te lo lleva con RappiFavor.
      </p>
      <button type="button" className="search-whim-action tap" onClick={open}>
        Pedir "{query}" con RappiFavor
      </button>
    </div>
  )
}

/**
 * La oferta `sin_resultado` del agente. Si no tiene nada (204) o falla, solo invita a buscar con otras palabras. Como las
 * demás ofertas, registra su mostrada; tocar "Ver en…" cuenta una aceptada (una, con el concepto de la oferta: no se
 * agregó ningún producto), que noteAccepted cuenta una sola vez, y la vertical abierta (`vertical_open`).
 */
function AgentEmpty({ query, onOpenVertical, onTryAnother }) {
  const { data: found, loading } = useApi(
    () => offer('sin_resultado', { query }, { userId: userId(), surface: 'search' }).catch(() => null),
    [query],
  )
  const events = useEvents()
  const generation = useProfile()?.resets ?? 0
  useEffect(() => {
    if (!found?.vertical) return
    const offered = { concept: found.reason?.concept, vertical: found.backendVertical }
    noteShown(events.track, found.products, { origin: NO_RESULT_ORIGIN, ...offered, reason: found.reason, generation })
  }, [found, events, generation])
  if (loading) return null
  const verticalName = found?.vertical ? VERTICAL_NAMES[found.vertical] : null
  const see = () => {
    const offered = {
      concept: found.reason?.concept,
      vertical: found.backendVertical,
      placement: { surface: 'search', requestId: found.requestId },
    }
    noteAccepted(events.track, [offered], { origin: NO_RESULT_ORIGIN, generation })
    // Abrir la vertical desde la oferta cuenta como abrirla (`vertical_open`), con el origen de la oferta.
    if (found.backendVertical)
      events.track('vertical_open', {
        vertical: found.backendVertical,
        ...envelope({ surface: 'search', origin: NO_RESULT_ORIGIN, requestId: found.requestId }),
      })
    onOpenVertical(found.vertical)
  }
  return (
    <div className="search-agent" role="status">
      <Mascot size={56} mood="listen" />
      <div>
        <p>{verticalName ? found.text : `No encontré "${query}". ¿Lo buscamos con otras palabras?`}</p>
        {verticalName && <OfferWhy reason={found.reason} origin={NO_RESULT_ORIGIN} />}
        <button type="button" className="search-agent-action tap" onClick={verticalName ? see : () => onTryAnother()}>
          {verticalName ? `Ver en ${verticalName}` : 'Probar otra búsqueda'}
        </button>
      </div>
    </div>
  )
}
