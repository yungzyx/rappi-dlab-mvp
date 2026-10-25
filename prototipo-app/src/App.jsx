import { Suspense, lazy, useEffect } from 'react'
import AddressSheet from './components/AddressSheet'
import AssistantPanel from './components/assistant/AssistantPanel'
import CartBar from './components/CartBar'
import DemoToggle from './components/DemoToggle'
import ErrorBoundary from './components/ErrorBoundary'
import PrivacyNotice from './components/PrivacyNotice'
import AgentPresence from './components/assistant/AgentPresence'
import ProductSheet from './components/ProductSheet'
import StatusBar from './components/StatusBar'
import { ToastProvider } from './components/Toast'
import HomeScreen from './screens/home/HomeScreen'
import { useNavigation } from './hooks/useNavigation'
import { AddressProvider } from './state/AddressContext'
import { AssistantProvider } from './state/AssistantContext'
import { CartProvider } from './state/CartContext'
import { DemoProvider } from './state/DemoContext'
import { EventsProvider } from './state/EventsContext'
import { FavoritesProvider } from './state/FavoritesContext'
import { LoyaltyProvider } from './state/LoyaltyContext'
import { OrdersProvider } from './state/OrdersContext'
import { ProductSheetProvider } from './state/ProductSheetContext'
import { ProfileProvider } from './state/ProfileContext'

// «Panel de la demo»: solo en «Prototipo MVP.html» (build sin conexión); en los demás builds la condición se pliega y
// el panel no entra al bundle.
const OfflineDemoPanel =
  import.meta.env.VITE_OFFLINE_DEMO === '1' ? lazy(() => import('./components/demo/OfflineDemoPanel')) : null

// La Home va en el paquete principal (es la primera); el resto se baja al abrirse por primera vez.
const SCREENS = {
  home: HomeScreen,
  restaurants: lazy(() => import('./screens/restaurants/RestaurantsScreen')),
  turbo: lazy(() => import('./screens/turbo/TurboScreen')),
  store: lazy(() => import('./screens/store/StoreScreen')),
  search: lazy(() => import('./screens/search/SearchScreen')),
  vertical: lazy(() => import('./screens/vertical/VerticalScreen')),
  travel: lazy(() => import('./screens/travel/TravelScreen')),
  favor: lazy(() => import('./screens/favor/FavorScreen')),
  loyalty: lazy(() => import('./screens/loyalty/LoyaltyScreen')),
  list: lazy(() => import('./screens/list/ListScreen')),
  checkout: lazy(() => import('./screens/checkout/CheckoutScreen')),
  tracking: lazy(() => import('./screens/tracking/TrackingScreen')),
  orders: lazy(() => import('./screens/orders/OrdersScreen')),
}

// Mientras una pantalla se baja: el fondo del teléfono, sin spinner (dura un instante).
const LOADING = <div className="screen screen-loading" aria-hidden="true" />

// En el checkout y el seguimiento no se muestra la barra del carrito.
const SCREENS_WITHOUT_CART = new Set(['checkout', 'tracking'])

// Pantallas con barra inferior: ahí la barra del carrito flota más arriba.
const SCREENS_WITH_NAV = new Set(['home', 'turbo'])

// Vertical de la pantalla actual (ids del prototipo): el agente busca ahí primero. Turbo va con su código del
// backend: el 'express' del prototipo es conveniencia para la API.
export const screenVertical = (screen) =>
  screen.name === 'vertical' ? screen.params?.id : { restaurants: 'restaurants', turbo: 'turbo' }[screen.name]

const PHONE_HEIGHT_PX = 874
const STAGE_MARGIN_PX = 48

// Achica el teléfono si la ventana del notebook es más baja que el iPhone.
function usePhoneScale() {
  useEffect(() => {
    const update = () => {
      const scale = Math.min(1, (window.innerHeight - STAGE_MARGIN_PX) / PHONE_HEIGHT_PX)
      document.documentElement.style.setProperty('--phone-scale', String(scale))
    }
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])
}

export default function App() {
  // La pestaña de la Home vive en la navegación para no perderla al abrir una tienda y volver.
  const { stack, homeTab, direction, push, back, reset, setHomeTab } = useNavigation()
  usePhoneScale()

  const current = stack[stack.length - 1]
  const vertical = screenVertical(current)

  return (
    <DemoProvider>
      <EventsProvider>
        <main className="stage">
          <DemoToggle />
          {OfflineDemoPanel && (
            <Suspense fallback={null}>
              <OfflineDemoPanel />
            </Suspense>
          )}
          <div className="phone">
            <ProfileProvider>
              <AssistantProvider>
                <CartProvider>
                  <OrdersProvider>
                    <FavoritesProvider>
                      <AddressProvider>
                        <LoyaltyProvider>
                          <ToastProvider>
                            <ProductSheetProvider>
                              {/* Toda la pila queda montada: al volver, cada pantalla conserva su búsqueda y su scroll.
                                  Las de abajo quedan invisibles e inertes (no display:none, que pierde el scroll). */}
                              {stack.map((entry, i) => {
                                const isTop = i === stack.length - 1
                                // Un enlace viejo o un nombre desconocido no rompe la app: vuelve a la Home.
                                const Screen = SCREENS[entry.name] ?? HomeScreen
                                return (
                                  <div
                                    key={`${i}-${entry.name}`}
                                    className={isTop ? `screen-wrap enter-${direction}` : 'screen-wrap is-under'}
                                    inert={!isTop}
                                  >
                                    {/* Si una pantalla falla, el aviso queda dentro del teléfono y se vuelve al inicio. */}
                                    <ErrorBoundary onReset={reset}>
                                      <Suspense fallback={LOADING}>
                                        <Screen
                                          push={push}
                                          back={back}
                                          reset={reset}
                                          params={entry.params}
                                          tab={homeTab}
                                          setTab={setHomeTab}
                                          active={isTop}
                                        />
                                      </Suspense>
                                    </ErrorBoundary>
                                  </div>
                                )
                              })}
                              {!SCREENS_WITHOUT_CART.has(current.name) && (
                                <CartBar raised={SCREENS_WITH_NAV.has(current.name)} push={push} />
                              )}
                              <AgentPresence
                                screen={current.name}
                                homeTab={homeTab}
                                raised={SCREENS_WITH_NAV.has(current.name)}
                              />
                              <AssistantPanel push={push} vertical={vertical} depth={stack.length} />
                              <ProductSheet />
                              <AddressSheet />
                              <StatusBar />
                              <PrivacyNotice
                                onOpenAccount={() => {
                                  reset()
                                  setHomeTab('account')
                                }}
                              />
                            </ProductSheetProvider>
                          </ToastProvider>
                        </LoyaltyProvider>
                      </AddressProvider>
                    </FavoritesProvider>
                  </OrdersProvider>
                </CartProvider>
              </AssistantProvider>
            </ProfileProvider>
          </div>
        </main>
      </EventsProvider>
    </DemoProvider>
  )
}
