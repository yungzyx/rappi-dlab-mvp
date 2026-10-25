import { useEffect, useId, useState } from 'react'
import { home } from '../../api/catalog'
import { offer } from '../../api/agent'
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
// Productos que se ven de cada vertical; «Ver más» muestra el resto de lo que trajo la API.
const GROUP_PREVIEW = 3
const NO_RESULT_ORIGIN = 'agent-sin_resultado'

export function SearchIdeas({ onPick }) {
  return (
    <>
      <h2 className="search-heading">Ideas para buscar</h2>
      <div className="search-chips">
        {IDEAS.map((term) => (
          <button key={term} type="button" className="search-chip tap" onClick={() => onPick(term)}>
            {term}
          </button>
        ))}
      </div>
    </>
  )
}

/** Las tiendas populares son las cercanas de la Home de la API; si no llega, la sección no aparece. */
export function PopularStores({ onOpen }) {
  const { data } = useApi(home, [])
  if (!data?.nearbyStores.length) return null
  return (
    <>
      <h2 className="search-heading">Tiendas populares</h2>
      <StoreList stores={data.nearbyStores.slice(0, POPULAR_COUNT)} onOpen={onOpen} />
    </>
  )
}

/**
 * Resultados de una búsqueda escrita (`data` de `useSearch`): un grupo por vertical con su nombre, o el aviso de que no
 * hay, o «Sin conexión». Un producto se abre en su tienda (`onOpenProduct`). Mientras carga se ven los resultados
 * anteriores. Con `onOpenVertical` (solo el buscador con el agente), sin resultados el agente no deja un callejón sin salida:
 * ofrece la vertical que tiene lo buscado o invita a buscar con otras palabras (`onTryAnother`). Si la API corrigió un
 * error de tipeo, dice qué buscó y, con `onSearchExact`, ofrece buscar lo escrito tal cual.
 */
export function SearchResults({
  query,
  data,
  loading = false,
  error = null,
  onRetry,
  onOpenProduct,
  onOpenVertical,
  onTryAnother,
  onSearchExact,
}) {
  if (error) return <OfflineNotice onRetry={onRetry} />
  if (!data)
    return loading ? (
      <p className="search-loading" role="status">
        Buscando…
      </p>
    ) : null

  const text = query.trim()
  // Sin nada que mostrar, el aviso espera a que llegue la respuesta de lo escrito (no se mezcla con lo de antes).
  if (data.groups.length === 0)
    return loading ? null : onOpenVertical ? (
      <AgentEmpty key={text} query={text} onOpenVertical={onOpenVertical} onTryAnother={onTryAnother} />
    ) : (
      <p className="search-empty">Sin resultados para «{text}».</p>
    )

  return (
    <>
      {data.correctedQuery && (
        <p className="search-corrected" role="status">
          Mostrando resultados para «{data.correctedQuery}».
          {onSearchExact && (
            <button type="button" className="search-exact tap" onClick={() => onSearchExact(data.query)}>
              Buscar «{data.query}» tal cual
            </button>
          )}
        </p>
      )}
      {data.groups.map((group) => (
        <ResultGroup key={`${data.query}|${group.vertical}`} group={group} onOpenProduct={onOpenProduct} />
      ))}
    </>
  )
}

function ResultGroup({ group, onOpenProduct }) {
  const titleId = useId()
  const [expanded, setExpanded] = useState(false)
  const hidden = group.products.length - GROUP_PREVIEW
  const shown = expanded ? group.products : group.products.slice(0, GROUP_PREVIEW)
  return (
    <section aria-labelledby={titleId}>
      <h2 id={titleId} className="search-heading">
        {VERTICAL_NAMES[group.vertical] ?? group.vertical}
      </h2>
      <ul className="search-products">
        {shown.map((product) => (
          <ProductRow
            key={product.id}
            product={product}
            showStore
            onOpenStore={onOpenProduct && product.storeId != null ? () => onOpenProduct(product) : undefined}
          />
        ))}
      </ul>
      {!expanded && hidden > 0 && (
        <button type="button" className="search-more tap" onClick={() => setExpanded(true)}>
          Ver más ({hidden})
        </button>
      )}
    </section>
  )
}

/**
 * La oferta `sin_resultado` del agente. Si no tiene nada (204) o falla, solo invita a buscar con otras palabras. Como las
 * demás ofertas, registra su mostrada; tocar «Ver en…» cuenta una aceptada (una, con el concepto de la oferta: no se
 * agregó ningún producto), que noteAccepted cuenta una sola vez.
 */
function AgentEmpty({ query, onOpenVertical, onTryAnother }) {
  const { data: found, loading } = useApi(
    () => offer('sin_resultado', { query }, { userId: userId() }).catch(() => null),
    [query],
  )
  const events = useEvents()
  const generation = useProfile()?.resets ?? 0
  useEffect(() => {
    if (!found?.vertical) return
    const offered = { concept: found.reason?.concept, vertical: found.backendVertical }
    noteShown(events.track, found.products, { origin: NO_RESULT_ORIGIN, ...offered, generation })
  }, [found, events, generation])
  if (loading) return null
  const verticalName = found?.vertical ? VERTICAL_NAMES[found.vertical] : null
  const see = () => {
    const offered = { concept: found.reason?.concept, vertical: found.backendVertical }
    noteAccepted(events.track, [offered], { origin: NO_RESULT_ORIGIN, generation })
    onOpenVertical(found.vertical)
  }
  return (
    <div className="search-agent" role="status">
      <Mascot size={56} mood="listen" />
      <div>
        <p>{verticalName ? found.text : `No encontré «${query}». ¿Lo buscamos con otras palabras?`}</p>
        {verticalName && <OfferWhy reason={found.reason} />}
        <button type="button" className="search-agent-action tap" onClick={verticalName ? see : () => onTryAnother()}>
          {verticalName ? `Ver en ${verticalName}` : 'Probar otra búsqueda'}
        </button>
      </div>
    </div>
  )
}
