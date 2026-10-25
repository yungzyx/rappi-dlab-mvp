import { storeOfProduct } from '../../api/catalog'
import { SearchIcon } from '../../components/Icons'
import BackButton from '../../components/BackButton'
import { PopularStores, SearchIdeas, SearchResults } from '../../components/search/SearchSections'
import { useSearch } from '../../components/search/useSearch'
import '../../components/search/search.css'

/** Buscador (funcionalidad agregada): busca en vivo en el catálogo de todas las verticales, agrupado por vertical. */
export default function SearchScreen({ back, push, params }) {
  const { query, setQuery, data, loading, error, retry, hasQuery, logSearch, pick, searchExact } = useSearch({
    initial: params.query ?? '',
    vertical: params.vertical,
  })
  const openStore = (store) => push('store', { store })
  // El producto tocado va con la tienda: la página registra que se vio.
  const openProduct = (product) => push('store', { store: storeOfProduct(product), item: product })

  return (
    <div className="screen search">
      <header className="search-header">
        <BackButton className="search-back" onClick={back} />
        <label className="search-field">
          <SearchIcon size={19} />
          <input
            autoFocus
            type="search"
            placeholder="¿Qué quieres hoy?"
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
        onSearchExact={searchExact}
      />
    </div>
  )
}
