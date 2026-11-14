import { envelope } from '../../api/attribution'
import { storeOfProduct } from '../../api/catalog'
import { recommendations } from '../../api/client'
import { userId } from '../../api/user'
import { useApi } from '../../api/useApi'
import { SearchIcon } from '../../components/Icons'
import BackButton from '../../components/BackButton'
import DiscoverSection from '../../components/assistant/DiscoverSection'
import { PopularStores, SearchIdeas, SearchResults } from '../../components/search/SearchSections'
import { useSearch } from '../../components/search/useSearch'
import { VERTICAL_NAMES, routeForScreen } from '../../data/verticals'
import { useDemo } from '../../state/DemoContext'
import { useEvents } from '../../state/EventsContext'
import { useAgentEnabled } from '../../state/agentEnabled'
import '../../components/search/search.css'

const FOR_YOU_ROWS = 3

/**
 * Buscador (funcionalidad agregada): busca en vivo en el catálogo de todas las verticales, agrupado por vertical, con las
 * tiendas y los restaurantes que se llaman así. Con `params.only`, busca solo en `params.vertical` ("Ver todos en…").
 * Con Mochi apagado (el grupo de control, en el prototipo final) es el buscador de la persona: antes de escribir suma
 * "Para ti" (/recommendations, que el control conserva) y, sin resultados, pide igual la oferta de Mochi para que la API
 * la anote como en el buscador con Mochi (no se muestra).
 */
export default function SearchScreen({ back, push, params }) {
  const only = Boolean(params.only && params.vertical)
  const final = useDemo()?.isFinal === true
  const enabled = useAgentEnabled()
  const agentOff = final && !enabled
  const { query, setQuery, data, loading, error, retry, hasQuery, logSearch, pick, searchExact } = useSearch({
    initial: params.query ?? '',
    vertical: params.vertical,
    only,
  })
  const openStore = (store) => push('store', { store })
  // El producto tocado va con la tienda: la página registra que se vio.
  const openProduct = (product) => push('store', { store: storeOfProduct(product), item: product })
  const seeAll = (vertical) => push('search', { query: query.trim(), vertical, only: true })
  // "Lo que sea": RappiFavor con lo buscado ya escrito.
  const openFavor = (text) => push('favor', { text })

  return (
    <div className="screen search">
      <header className="search-header">
        <BackButton className="search-back" onClick={back} />
        <label className="search-field">
          <SearchIcon size={19} />
          <input
            autoFocus
            type="search"
            placeholder={only ? `Buscar en ${VERTICAL_NAMES[params.vertical] ?? params.vertical}` : '¿Qué quieres hoy?'}
            value={query}
            maxLength={500}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && logSearch(query)}
            onBlur={() => logSearch(query)}
          />
          {hasQuery && (
            <button type="button" className="search-clear" aria-label="Borrar" onClick={() => setQuery('')}>
              ×
            </button>
          )}
        </label>
      </header>

      {!hasQuery && (
        <>
          <SearchIdeas onPick={pick} />
          {agentOff && !only && <ForYou push={push} />}
          <PopularStores onOpen={openStore} />
        </>
      )}

      <SearchResults
        query={query}
        data={data}
        loading={loading}
        error={error}
        onRetry={retry}
        onOpenProduct={openProduct}
        onOpenStore={openStore}
        onSearchExact={searchExact}
        onSeeAll={only ? undefined : seeAll}
        onOpenFavor={openFavor}
        agentOff={agentOff && !only}
      />
    </div>
  )
}

/**
 * "Para ti" en el buscador de siempre del grupo de control: las filas de /recommendations (las mismas de "Descubre con
 * Mochi" en el buscador con Mochi), sin el nombre de Mochi. Tocar una abre su vertical, con su lugar en la lista.
 * Si la API no contesta o no tiene nada, no aparece.
 */
function ForYou({ push }) {
  const events = useEvents()
  const { data: rows } = useApi(
    () =>
      recommendations(userId()).then(
        (reply) => reply.rows.filter((row) => row.products.length > 0),
        () => null,
      ),
    [],
  )
  if (!rows?.length) return null
  return (
    <DiscoverSection
      title="Para ti"
      rows={rows.slice(0, FOR_YOU_ROWS)}
      onOpen={(screen, { row, position }) => {
        events.track('vertical_open', {
          vertical: row.vertical,
          ...envelope({
            surface: 'search',
            origin: 'para-ti',
            position,
            requestId: row.products[0]?.placement?.requestId,
          }),
        })
        push(...routeForScreen(screen))
      }}
    />
  )
}
