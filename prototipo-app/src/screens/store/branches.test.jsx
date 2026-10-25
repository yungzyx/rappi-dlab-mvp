import { StrictMode } from 'react'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, describe, expect, test, vi } from 'vitest'
import { toPrototypeProduct } from '../../api/client'
import { fixture, stubApi } from '../../test/api'
import { ToastProvider } from '../../components/Toast'
import { AssistantProvider } from '../../state/AssistantContext'
import { CartProvider } from '../../state/CartContext'
import { DemoProvider } from '../../state/DemoContext'
import { FavoritesProvider } from '../../state/FavoritesContext'
import { ProfileProvider } from '../../state/ProfileContext'
import StoreScreen from './StoreScreen'

const events = vi.hoisted(() => ({ track: vi.fn(), flush: async () => {}, clear: () => {}, settled: async () => {} }))
vi.mock('../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))

function Providers({ children }) {
  return (
    <StrictMode>
      <DemoProvider>
        <ProfileProvider>
          <AssistantProvider>
            <CartProvider>
              <FavoritesProvider>
                <ToastProvider>{children}</ToastProvider>
              </FavoritesProvider>
            </CartProvider>
          </AssistantProvider>
        </ProfileProvider>
      </DemoProvider>
    </StrictMode>
  )
}

/** Dos sucursales con el mismo nombre (9801 y 9805), cada una con su propio plato. */
function branchMenu(id, dish) {
  const menu = fixture('catalog-menu')
  const [first] = menu.sections[1].items
  return {
    restaurant: { ...menu.restaurant, id, name: 'Pizzería de prueba' },
    sections: [
      { name: 'Pizzas', items: [{ ...first, id: `menu-${id}`, entity_id: String(id), name: dish, store_id: id }] },
    ],
  }
}

const stubBranches = () =>
  stubApi({
    '/catalog/restaurants/9801/menu': branchMenu(9801, 'Pizza de Providencia (prueba)'),
    '/catalog/restaurants/9805/menu': branchMenu(9805, 'Pizza de Las Condes (prueba)'),
  })

const openStore = (params) =>
  render(<StoreScreen back={() => {}} push={() => {}} params={params} />, { wrapper: Providers })
const visits = () => events.track.mock.calls.filter(([type]) => type === 'view_store').map(([, fields]) => fields)

beforeAll(() => {
  Element.prototype.scrollIntoView = () => {} // jsdom no lo implementa (pestañas del menú)
})
afterAll(() => {
  delete Element.prototype.scrollIntoView
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  events.track.mockClear()
  localStorage.clear()
})

describe('sucursales con el mismo nombre (restaurantes de la API)', () => {
  test('abrir la segunda muestra sus propios platos: la tienda se identifica por id, no por nombre', async () => {
    stubBranches()
    openStore({ store: { id: 9805, name: 'Pizzería de prueba', vertical: 'restaurants' } })
    expect(await screen.findByText('Pizza de Las Condes (prueba)')).toBeTruthy()
    expect(screen.queryByText('Pizza de Providencia (prueba)')).toBeNull()
  })

  test('la visita va a restaurantes, con el id de esa sucursal', async () => {
    stubBranches()
    openStore({ store: { id: 9805, name: 'Pizzería de prueba', vertical: 'restaurants' } })
    await screen.findByText('Pizza de Las Condes (prueba)')
    // La visita la registra un efecto después de pintar el menú: se espera el evento, no el texto.
    await waitFor(() =>
      expect(visits()).toEqual([
        expect.objectContaining({ vertical: 'restaurants', entity_type: 'store', entity_id: '9805' }),
      ]),
    )
  })

  test('el plato de una sucursal abre esa sucursal por su menú, no como tienda', async () => {
    const fetchMock = stubBranches()
    const dish = toPrototypeProduct(branchMenu(9805, 'Pizza de Las Condes (prueba)').sections[0].items[0])
    // Lo mismo que arma «Ver tienda» del detalle del plato.
    openStore({ store: { id: dish.storeId, name: dish.store, vertical: dish.vertical }, item: dish })

    expect(await screen.findByText('Pizza de Las Condes (prueba)')).toBeTruthy()
    expect(fetchMock.mock.calls.map(([url]) => new URL(url).pathname)).toEqual(['/catalog/restaurants/9805/menu'])
    // Es el plato del menú: no se repite como «Lo que elegiste».
    expect(screen.queryByText('Lo que elegiste')).toBeNull()
  })
})
