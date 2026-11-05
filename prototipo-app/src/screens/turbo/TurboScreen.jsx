import { useId, useRef, useState } from 'react'
import { placeList } from '../../api/attribution'
import { deals as loadDeals, storeOfProduct } from '../../api/catalog'
import { useApi } from '../../api/useApi'
import BackButton from '../../components/BackButton'
import BottomNav from '../../components/BottomNav'
import HScroll from '../../components/HScroll'
import OfflineNotice from '../../components/OfflineNotice'
import { ProductCard } from '../../components/ProductCard'
import TabPage from '../../components/TabPage'
import ThresholdBar from '../../components/ThresholdBar'
import { useToast } from '../../components/Toast'
import { useOpenSearch } from '../../hooks/useOpenSearch'
import { useRovingGroup } from '../../hooks/useRovingGroup'
import { useCart } from '../../state/CartContext'
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
      {offers.data?.length > 0 && (
        <ProductGrid
          products={placeList(offers.data, { surface: 'turbo', origin: 'ofertas' })}
          onOpenStore={onOpenStore}
        />
      )}
    </TabPage>
  )
}

/** Si la tienda Turbo no llegó: "Sin conexión" con Reintentar, o que no hay tienda en el catálogo. */
function ShopStatus({ shop }) {
  if (shop.status === 'offline') return <OfflineNotice onRetry={shop.retry} />
  if (shop.status === 'empty')
    return <p className="turbo-page-note">Todavía no hay productos de Turbo en el catálogo.</p>
  return null
}

/** La grilla de productos Turbo, cada uno con su lugar (pantalla `turbo`): abrirlo, agregarlo y verlo lo dicen. */
function ProductGrid({ products, onOpenStore }) {
  return (
    <div className="turbo-grid">
      {products.map((product) => (
        <ProductCard key={product.id} product={product} onOpenStore={() => onOpenStore(product)} impression />
      ))}
    </div>
  )
}

function TurboFeed({ back, toast, shop, onOpenStore, onSearch }) {
  const cart = useCart()
  const gridRef = useRef(null)
  const eta = shop.info?.eta
  // Las pestañas de pasillos controlan la grilla de productos (su tabpanel).
  const ids = useId()
  const tabId = (aisle) => `${ids}-tab-${aisle}`
  const panelId = `${ids}-panel`
  const current = shop.aisles.findIndex((aisle) => aisle.id === shop.aisle)
  const tabs = useRovingGroup(shop.aisles.length, current, (i) => shop.setAisle(shop.aisles[i].id))

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

        <HScroll className="turbo-tabs" role="tablist" onKeyDown={tabs.onKeyDown}>
          {shop.aisles.map((aisle, i) => (
            <button
              key={aisle.id}
              id={tabId(aisle.id)}
              type="button"
              role="tab"
              aria-selected={aisle.id === shop.aisle}
              aria-controls={panelId}
              className={aisle.id === shop.aisle ? 'turbo-tab is-active' : 'turbo-tab'}
              onClick={() => shop.setAisle(aisle.id)}
              {...tabs.itemProps(i)}
            >
              {aisle.name}
            </button>
          ))}
        </HScroll>
      </div>

      <button type="button" className="turbo-hero" onClick={goToProducts}>
        <img src={turboHero} alt="Todo tu súper y más en minutos" />
      </button>

      <ThresholdBar
        goal={FEE_GOAL}
        total={cart.total}
        icon={turboCrown}
        title="100% de descuento en la tarifa de servicio"
        pending={(amount) => <>Agrega {amount} para tener este descuento.</>}
        done="Descuento activado."
      />

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

      <section
        ref={gridRef}
        id={panelId}
        className="turbo-products"
        aria-label="Productos"
        {...(current >= 0 && { role: 'tabpanel', 'aria-labelledby': tabId(shop.aisle) })}
      >
        <ShopStatus shop={shop} />
        {shop.status === 'loading' && <div className="turbo-skeleton" aria-hidden="true" />}
        {shop.status === 'ready' && (
          <>
            {shop.aisleName && <h2 className="section-title turbo-products-title">{shop.aisleName}</h2>}
            {shop.products.length > 0 ? (
              <>
                <ProductGrid
                  products={placeList(shop.products, { surface: 'turbo', origin: 'pasillo' })}
                  onOpenStore={onOpenStore}
                />
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
