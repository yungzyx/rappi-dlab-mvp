import { useId } from 'react'
import { deals as loadDeals, verticalStores } from '../../api/catalog'
import { useApi } from '../../api/useApi'
import BackButton from '../../components/BackButton'
import HScroll from '../../components/HScroll'
import Img from '../../components/Img'
import OfflineNotice from '../../components/OfflineNotice'
import { ProductCard } from '../../components/ProductCard'
import { StoreMeta } from '../../components/StoreMeta'
import { ChevronDown, SearchIcon } from '../../components/Icons'
import { useOpenSearch } from '../../hooks/useOpenSearch'
import { useAddress } from '../../state/AddressContext'
import { VERTICALS } from './data'
import './vertical.css'

// Las tiendas que se ven en la pantalla; «Ver más» abre la lista con todas.
const VISIBLE_STORES = 4

/** Plantilla común de Súper, Farmacia, Rappi Mall, Licores, Express y Chocolates: la UI es de aquí, las tiendas y las bajas de precio, de la API. */
export default function VerticalScreen({ back, push, params }) {
  // Un id desconocido (enlace viejo) no rompe la pantalla: muestra un estado vacío más abajo y no pide nada.
  const vertical = VERTICALS[params.id]
  const address = useAddress()
  const openSearch = useOpenSearch(push)
  const stores = useApi(() => (vertical ? verticalStores(params.id) : null), [params.id])
  const deals = useApi(() => (vertical ? loadDeals(params.id) : null), [params.id])

  const openCategory = (category) => openSearch(params.id, category.query)
  const openStore = (store) => push('store', { store })
  // Con el producto tocado: la tienda registra que se vio.
  const openProductStore = (item) =>
    push('store', { store: { id: item.storeId, name: item.store, vertical: item.vertical }, item })
  const retry = () => {
    stores.retry()
    deals.retry()
  }

  if (!vertical)
    return (
      <div className="screen vertical">
        <header className="vertical-header">
          <BackButton className="round-button" onClick={back} />
        </header>
        <p className="vertical-empty">Esta categoría no está en el prototipo.</p>
      </div>
    )

  return (
    <div className="screen vertical">
      <header className="vertical-header">
        <BackButton className="round-button" onClick={back} />
        <button type="button" className="vertical-address tap" onClick={address.openSheet}>
          <span>{address.selected.line}</span>
          <ChevronDown size={18} />
        </button>
      </header>

      <div className="vertical-search-wrap">
        <button type="button" className="search-bar tap" onClick={() => openSearch(params.id)}>
          <SearchIcon size={21} />
          <span className="vertical-search-hint">Busca tiendas o productos</span>
        </button>
      </div>

      {vertical.categoryRows.length > 0 && (
        <CategoryGrid rows={vertical.categoryRows} scrollable={vertical.scrollCategories} onOpen={openCategory} />
      )}

      {stores.error && stores.error.status !== 404 && <OfflineNotice onRetry={retry} />}
      {(stores.error?.status === 404 || stores.data?.stores.length === 0) && (
        <p className="vertical-empty">Todavía no hay tiendas de esta categoría en el catálogo.</p>
      )}
      {stores.data?.stores.length > 0 && (
        <StoreSection
          stores={stores.data.stores}
          onOpen={openStore}
          onMore={() => push('list', { title: 'Tiendas', stores: stores.data.stores })}
        />
      )}

      {/* Las bajas de precio son un extra: si no vienen (o falló esa llamada), la sección no aparece. */}
      {deals.data?.length > 0 && (
        <DealsSection
          deals={deals.data}
          onOpenStore={openProductStore}
          onSeeAll={() => push('list', { title: 'Bajaron de precio', products: deals.data })}
        />
      )}
    </div>
  )
}

function CategoryGrid({ rows, scrollable, onOpen }) {
  const grid = (
    <div className="vertical-cats-grid" style={{ gridTemplateColumns: `repeat(${rows[0].length}, 84px)` }}>
      {rows.flat().map((category) => (
        <button key={category.id} type="button" className="vertical-cat tap" onClick={() => onOpen(category)}>
          <span className={category.partial ? 'vertical-cat-img is-partial' : 'vertical-cat-img'}>
            <img src={category.img} alt="" draggable="false" />
          </span>
          <span className="vertical-cat-label">{category.label}</span>
        </button>
      ))}
    </div>
  )
  // Filas cortadas en el borde de la captura no hacen scroll: al deslizar se vería el recorte.
  return scrollable ? <HScroll className="vertical-cats">{grid}</HScroll> : <div className="vertical-cats">{grid}</div>
}

function DealsSection({ deals, onOpenStore, onSeeAll }) {
  const titleId = useId()
  return (
    <section className="vertical-section vertical-section--products" aria-labelledby={titleId}>
      <div className="section-head">
        <h2 id={titleId} className="vertical-title-strong">
          Bajaron de precio
        </h2>
        <button type="button" className="see-all tap" onClick={onSeeAll}>
          Ver todo
        </button>
      </div>
      <HScroll className="vertical-product-row">
        {deals.map((item) => (
          <ProductCard key={item.id} product={item} onOpenStore={() => onOpenStore(item)} />
        ))}
      </HScroll>
    </section>
  )
}

function StoreSection({ stores, onOpen, onMore }) {
  const titleId = useId()
  return (
    <section className="vertical-section vertical-section--stores" aria-labelledby={titleId}>
      <div className="section-head">
        <h2 id={titleId} className="section-title">
          Tiendas
        </h2>
        <button type="button" className="see-more tap" onClick={onMore}>
          Ver más
        </button>
      </div>
      <div className="vertical-store-list">
        {stores.slice(0, VISIBLE_STORES).map((store) => (
          <button key={store.id} type="button" className="vertical-store tap" onClick={() => onOpen(store)}>
            <Img src={store.img} className="vertical-store-logo" />
            <span className="vertical-store-text">
              <span className="vertical-store-name">
                <strong>{store.name}</strong>
              </span>
              {store.eta && <StoreMeta store={store} className="vertical-store-meta" />}
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}
