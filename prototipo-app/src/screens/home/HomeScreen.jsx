import { Suspense, lazy } from 'react'
import BottomNav from '../../components/BottomNav'
import { AccountIcon, FavoritesIcon, HomeIcon, OffersIcon } from '../../components/Icons'
import { useOpenSearch } from '../../hooks/useOpenSearch'
import { useDemo } from '../../state/DemoContext'
import HomeFeed from './HomeFeed'
import LiveHomeFeed from './live/LiveHomeFeed'

// Al abrir se ve Inicio: las otras pestañas se bajan al tocarlas por primera vez (como las pantallas de App.jsx).
const AccountScreen = lazy(() => import('../account/AccountScreen'))
const DealsScreen = lazy(() => import('../deals/DealsScreen'))
const FavoritesScreen = lazy(() => import('../favorites/FavoritesScreen'))
const LOADING = <div className="screen screen-loading" aria-hidden="true" />

const NAV_ITEMS = [
  { id: 'home', label: 'Inicio', Icon: HomeIcon },
  { id: 'offers', label: 'Ofertas', Icon: OffersIcon },
  { id: 'favorites', label: 'Favoritos', Icon: FavoritesIcon },
  { id: 'account', label: 'Cuenta', Icon: AccountIcon },
]

/** Contenedor de las 4 pestañas de la barra inferior. La pestaña activa la guarda App. */
export default function HomeScreen({ push, tab, setTab, active }) {
  const demo = useDemo()
  const openSearch = useOpenSearch(push)
  return (
    <>
      {tab === 'home' && (demo.isFinal ? <LiveHomeFeed push={push} active={active} /> : <HomeFeed push={push} />)}
      <Suspense fallback={LOADING}>
        {tab === 'offers' && <DealsScreen push={push} />}
        {tab === 'favorites' && <FavoritesScreen push={push} />}
        {tab === 'account' && <AccountScreen onBack={() => setTab('home')} push={push} />}
      </Suspense>
      <BottomNav items={NAV_ITEMS} active={tab} onSelect={setTab} onSearch={() => openSearch()} />
    </>
  )
}
