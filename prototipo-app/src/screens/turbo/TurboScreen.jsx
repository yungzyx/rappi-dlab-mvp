import { useRef, useState } from 'react'
import { deals as loadDeals, storeOfProduct } from '../../api/catalog'
import { useApi } from '../../api/useApi'
import BackButton from '../../components/BackButton'
import BottomNav from '../../components/BottomNav'
import HScroll from '../../components/HScroll'
import OfflineNotice from '../../components/OfflineNotice'
import { ProductCard } from '../../components/ProductCard'
import TabPage from '../../components/TabPage'
import { useToast } from '../../components/Toast'
import { useOpenSearch } from '../../hooks/useOpenSearch'
import { formatPrice, useCart } from '../../state/CartContext'
import FavoritesScreen from '../favorites/FavoritesScreen'
import { BadgePercentIcon, GridIcon, HeartIcon, MoreIcon, SearchIcon, SpeedBoltIcon } from '../../components/Icons'
import turboLogo from '../../assets/turbo-logo.webp'
import turboHero from '../../assets/turbo-hero.webp'
import turboCrown from '../../assets/turbo-crown.webp'
import promo18Chico from '../../assets/promo-18chico.webp'
import promoHealthy from '../../assets/promo-healthy.webp'
import { useTurboShop } from './useTurboShop'
import './turbo.css'

// Publicidad de la captura: no apunta a ningún pasillo del catálogo.
const PROMOS = [
  { id: 'chico', img: promo18Chico, label: 'Fiestas Patrias: picoteo' },
  { id: 'healthy', img: promoHealthy, label: 'Saludable: frescos' },
]

const NAV_ITEMS = [
  { id: 'turbo', label: 'Turbo', Icon: SpeedBoltIcon },
  { id: 'favorites', label: 'Favoritos', Icon: HeartIcon },
  { id: 'offers', label: 'Ofertas', Icon: BadgePercentIcon },
  { id: 'categories', label: 'Categorías', Icon: GridIcon },
]

// Monto del carro para el 100 % de descuento en la tarifa de servicio (el de la app iOS del 26-09-2026).
const FEE_GOAL = 29900

export default function TurboScreen({ back, push }) {
  const toast = useToast()
  const openSearch = useOpenSearch(push)
  const shop = useTurboShop()
  const [tab, setTab] = useState('turbo')
  // Con el producto tocado: la tienda registra que se vio.
  const openStore = (item) => push('store', { store: storeOfProduct(item), item })
  // Categorías lleva al pasillo que se tocó.
  const showAisle = (id) => {
    shop.setAisle(id)
    setTab('turbo')
  }

  return (
    <>
      {tab === 'turbo' && (
        <TurboFeed back={back} toast={toast} shop={shop} onOpenStore={openStore} onSearch={() => openSearch('turbo')} />
      )}
      {tab === 'favorites' && <FavoritesScreen push={push} />}
      {tab === 'offers' && <TurboOffers onOpenStore={openStore} />}
      {tab === 'categories' && (
        <TabPage title="Categorías" color="#3e7b4b" className="turbo-page">
          <ShopStatus shop={shop} />
          <ul className="turbo-categories">
            {shop.aisles.map((aisle) => (
              <li key={aisle.id}>
                <button type="button" className="turbo-category tap" onClick={() => showAisle(aisle.id)}>
                  <span>{aisle.name}</span>
                  <small>
                    {aisle.products} {aisle.products === 1 ? 'producto' : 'productos'}
                  </small>
                </button>
              </li>
            ))}
          </ul>
        </TabPage>
      )}
      <BottomNav
        items={NAV_ITEMS}
        active={tab}
        onSelect={setTab}
        onSearch={() => openSearch('turbo')}
        className="bottom-nav--turbo"
      />
    </>
  )
}

/** Las bajas de precio de los productos Turbo (pestaña Ofertas). */
function TurboOffers({ onOpenStore }) {
  const offers = useApi(() => loadDeals('turbo'), [])
  return (
    <TabPage title="Ofertas" color="#3e7b4b" className="turbo-page">
      <p className="turbo-page-note">Productos con descuento en Turbo</p>
      {offers.error && <OfflineNotice onRetry={offers.retry} />}
      {offers.data?.length === 0 && <p className="turbo-page-note">Todavía no hay ofertas en Turbo.</p>}
      {offers.data?.length > 0 && <ProductGrid products={offers.data} onOpenStore={onOpenStore} />}
    </TabPage>
  )
}

/** Si la tienda Turbo no llegó: «Sin conexión» con Reintentar, o que no hay tienda en el catálogo. */
function ShopStatus({ shop }) {
  if (shop.status === 'offline') return <OfflineNotice onRetry={shop.retry} />
  if (shop.status === 'empty')
    return <p className="turbo-page-note">Todavía no hay productos de Turbo en el catálogo.</p>
  return null
}

function ProductGrid({ products, onOpenStore }) {
  return (
    <div className="turbo-grid">
      {products.map((product) => (
        <ProductCard key={product.id} product={product} onOpenStore={() => onOpenStore(product)} />
      ))}
    </div>
  )
}

function TurboFeed({ back, toast, shop, onOpenStore, onSearch }) {
  const cart = useCart()
  const gridRef = useRef(null)
  const remaining = Math.max(FEE_GOAL - cart.total, 0)
  const progress = Math.min(cart.total / FEE_GOAL, 1)
  const eta = shop.info?.eta

  // El hero lleva a la grilla de productos.
  const goToProducts = () => gridRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })

  return (
    <div className="screen turbo">
      <div className="turbo-green">
        <header className="turbo-header">
          <BackButton className="turbo-round" onClick={back} />
          <img className="turbo-logo" src={turboLogo} alt="Turbo" />
          <button type="button" className="turbo-round turbo-round--more tap" aria-label="Más" onClick={() => toast()}>
            <MoreIcon size={22} />
          </button>
        </header>

        {eta && (
          <div className="turbo-eta">
            <SpeedBoltIcon size={22} />
            Llega en <strong>{eta}</strong>
          </div>
        )}

        <button type="button" className="turbo-search tap" onClick={onSearch}>
          <SearchIcon size={21} />
          Busca en Turbo
        </button>

        <HScroll className="turbo-tabs" role="tablist">
          {shop.aisles.map((aisle) => (
            <button
              key={aisle.id}
              type="button"
              role="tab"
              aria-selected={aisle.id === shop.aisle}
              className={aisle.id === shop.aisle ? 'turbo-tab is-active' : 'turbo-tab'}
              onClick={() => shop.setAisle(aisle.id)}
            >
              {aisle.name}
            </button>
          ))}
        </HScroll>
      </div>

      <button type="button" className="turbo-hero" onClick={goToProducts}>
        <img src={turboHero} alt="Todo tu súper y más en minutos" />
      </button>

      <div className="turbo-fee">
        <img src={turboCrown} alt="" loading="lazy" />
        <div>
          <p className="turbo-fee-title">100% de descuento en la tarifa de servicio</p>
          <p className="turbo-fee-sub">
            {remaining > 0 ? (
              <>
                Agrega <strong>{formatPrice(remaining)}</strong> para tener este descuento.
              </>
            ) : (
              <>Descuento activado.</>
            )}
          </p>
        </div>
        <div className="turbo-fee-track">
          <span className="turbo-fee-fill" style={{ width: `${progress * 100}%` }} />
          <span className={progress >= 1 ? 'turbo-fee-check is-done' : 'turbo-fee-check'} />
        </div>
      </div>

      <HScroll className="turbo-promos">
        {PROMOS.map((promo) => (
          <button
            key={promo.id}
            type="button"
            className="turbo-promo tap"
            aria-label={promo.label}
            onClick={() => toast()}
          >
            <img src={promo.img} alt="" draggable="false" loading="lazy" />
          </button>
        ))}
      </HScroll>

      <section ref={gridRef} className="turbo-products" aria-label="Productos">
        <ShopStatus shop={shop} />
        {shop.status === 'loading' && <div className="turbo-skeleton" aria-hidden="true" />}
        {shop.status === 'ready' && (
          <>
            {shop.aisleName && <h2 className="section-title turbo-products-title">{shop.aisleName}</h2>}
            {shop.products.length > 0 ? (
              <>
                <ProductGrid products={shop.products} onOpenStore={onOpenStore} />
                {shop.hasMore && (
                  <button type="button" className="turbo-more tap" disabled={shop.loadingMore} onClick={shop.loadMore}>
                    Ver más
                  </button>
                )}
              </>
            ) : (
              <p className="turbo-page-note">No hay productos para mostrar.</p>
            )}
          </>
        )}
      </section>
    </div>
  )
}
