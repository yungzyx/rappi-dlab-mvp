import { useRef } from 'react'
import BackToTop from '../../components/BackToTop'
import DemoDisclaimer from '../../components/DemoDisclaimer'
import PlainSearchBar from '../../components/PlainSearchBar'
import { ChevronDown } from '../../components/Icons'
import { useScrollState } from '../../hooks/useScrollState'
import { useAddress } from '../../state/AddressContext'
import { useEvents } from '../../state/EventsContext'
import CreditsBanner from './CreditsBanner'
import { BestRated, FastRestaurants, MainTiles, NearbyStores, Promos, Shortcuts, useHomeCatalog } from './HomeSections'
import { CREDITS } from '../../data/home'
import './home.css'

// A partir de cuánto scroll aparece el encabezado compacto, y desde dónde se ofrece "Back to top" al subir.
const COLLAPSE_AT_PX = 150
const BACK_TO_TOP_FROM_PX = 600

/** La Home de «Rappi hoy»: tal como es la app, sin el agente. La del prototipo final es LiveHomeFeed. */
export default function HomeFeed({ push }) {
  const address = useAddress()
  const catalog = useHomeCatalog()
  const events = useEvents()
  const openVertical = (vertical) => events.track('vertical_open', { vertical })
  const openService = (servicio) => events.track('service_opened', { payload: { servicio, desde: 'home' } })
  const openSearch = () => push('search')
  const screenRef = useRef(null)
  const [{ collapsed: isCollapsed, showBackToTop }, onScroll] = useScrollState({
    collapseAt: COLLAPSE_AT_PX,
    backToTopFrom: BACK_TO_TOP_FROM_PX,
  })

  const scrollToTop = () => screenRef.current.scrollTo({ top: 0, behavior: 'smooth' })

  return (
    <>
      <header className={isCollapsed ? 'home-compact is-visible' : 'home-compact'} inert={!isCollapsed}>
        <button type="button" className="home-compact-address tap" onClick={address.openSheet}>
          <strong>{address.selected.label}</strong>
          <span>{address.selected.line}</span>
        </button>
        <PlainSearchBar className="search-bar--compact" onClick={openSearch} />
      </header>

      <BackToTop visible={showBackToTop} onClick={scrollToTop} />

      <div ref={screenRef} className="screen home" onScroll={onScroll}>
        <section className="home-top">
          <button type="button" className="home-address tap" onClick={address.openSheet}>
            <span className="home-address-line">{address.selected.line}</span>
            <span className="home-address-label">
              {address.selected.label}
              <span className="chevron-chip">
                <ChevronDown size={16} />
              </span>
            </span>
          </button>
          <PlainSearchBar onClick={openSearch} />
          <CreditsBanner credits={CREDITS} onClick={() => push('vertical', { id: 'pharmacy' })} />
        </section>
        <DemoDisclaimer />

        <MainTiles push={push} onOpen={openVertical} />
        <Shortcuts push={push} onOpen={openVertical} onService={openService} />
        <Promos push={push} />
        <FastRestaurants stores={catalog.fastRestaurants} push={push} />
        <NearbyStores stores={catalog.nearbyStores} push={push} />
        <BestRated stores={catalog.bestRated} push={push} />
      </div>
    </>
  )
}
