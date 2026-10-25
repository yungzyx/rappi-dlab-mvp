import BottomNav from '../../components/BottomNav'
import { AccountIcon, FavoritesIcon, HomeIcon, OffersIcon } from '../../components/Icons'
import { useOpenSearch } from '../../hooks/useOpenSearch'
import { useDemo } from '../../state/DemoContext'
import AccountScreen from '../account/AccountScreen'
import DealsScreen from '../deals/DealsScreen'
import FavoritesScreen from '../favorites/FavoritesScreen'
import HomeFeed from './HomeFeed'
import LiveHomeFeed from './live/LiveHomeFeed'

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
      {tab === 'offers' && <DealsScreen push={push} />}
      {tab === 'favorites' && <FavoritesScreen push={push} />}
      {tab === 'account' && <AccountScreen onBack={() => setTab('home')} push={push} />}
      <BottomNav items={NAV_ITEMS} active={tab} onSelect={setTab} onSearch={() => openSearch()} />
    </>
  )
}
