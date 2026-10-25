import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from '../../test/api'
import ProductSheet from '../../components/ProductSheet'
import { ToastProvider } from '../../components/Toast'
import { AssistantProvider } from '../../state/AssistantContext'
import { CartProvider } from '../../state/CartContext'
import { DemoProvider } from '../../state/DemoContext'
import { FavoritesProvider } from '../../state/FavoritesContext'
import { ProductSheetProvider } from '../../state/ProductSheetContext'
import { ProfileProvider } from '../../state/ProfileContext'
import DealsScreen from './DealsScreen'

const events = vi.hoisted(() => ({ track: vi.fn(), flush: async () => {}, clear: () => {}, settled: async () => {} }))
vi.mock('../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))

beforeAll(() => {
  Element.prototype.scrollTo = () => {} // jsdom no lo implementa
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

function Providers({ children }) {
  return (
    <DemoProvider>
      <ProfileProvider>
        <AssistantProvider>
          <CartProvider>
            <FavoritesProvider>
              <ToastProvider>
                <ProductSheetProvider>
                  {children}
                  <ProductSheet />
                </ProductSheetProvider>
              </ToastProvider>
            </FavoritesProvider>
          </CartProvider>
        </AssistantProvider>
      </ProfileProvider>
    </DemoProvider>
  )
}

/** Las bajas de precio de la vertical que se pida (código del backend), como la API. */
const dealsOf = (req) => fixture('catalog-deals').filter((deal) => deal.vertical === req.query.get('vertical'))

const stubDeals = (extra = {}) =>
  stubApi({ '/catalog/deals': dealsOf, '/catalog/restaurants': fixture('catalog-restaurants').slice(0, 6), ...extra })

const renderDeals = () => {
  const push = vi.fn()
  render(<DealsScreen push={push} />, { wrapper: Providers })
  return push
}
const headings = () => [...document.querySelectorAll('.tab-page h2')].map((node) => node.textContent)
const dealsSections = () => headings().filter((text) => text.startsWith('Bajaron de precio'))
const askedDeals = (fetchMock) =>
  fetchMock.mock.calls
    .map(([url]) => new URL(url))
    .filter((url) => url.pathname === '/catalog/deals')
    .map((url) => url.searchParams.get('vertical'))

describe('Ofertas con el catálogo real', () => {
  test('Ofertas agrupa las bajas reales por vertical', async () => {
    const fetchMock = stubDeals()
    renderDeals()

    await waitFor(() => expect(dealsSections()).toHaveLength(6))
    expect(dealsSections()).toEqual([
      'Bajaron de precio en Súper',
      'Bajaron de precio en Licores',
      'Bajaron de precio en Express',
      'Bajaron de precio en Rappi Mall',
      'Bajaron de precio en Chocolatería',
      'Bajaron de precio en Turbo',
    ])
    expect(askedDeals(fetchMock).sort()).toEqual(
      ['chocolateria', 'conveniencia', 'licores', 'mall', 'supermercado', 'turbo'].sort(),
    )

    // Cada sección tiene solo las bajas de su vertical.
    const grocery = within(screen.getByRole('region', { name: 'Bajaron de precio en Súper' }))
    for (const name of [
      'Galletas de vainilla 200 g (prueba)',
      'Café molido tostado 250 g (prueba)',
      'Gaseosa cola 1,5 L (prueba)',
    ])
      expect(grocery.getByText(name)).toBeTruthy()
    expect(grocery.queryByText('Cerveza rubia lata 470 cc (prueba)')).toBeNull()
    const express = within(screen.getByRole('region', { name: 'Bajaron de precio en Express' }))
    expect(express.getAllByText('Tienda express de prueba Centro')).toHaveLength(2)
  })

  test('una vertical sin bajas no deja una sección vacía, y una que falla tampoco', async () => {
    stubDeals({
      '/catalog/deals': (req) => {
        const vertical = req.query.get('vertical')
        if (vertical === 'turbo') return 'offline' // esa llamada falla; las demás siguen
        return vertical === 'mall' || vertical === 'licores' ? [] : dealsOf(req)
      },
    })
    renderDeals()

    await waitFor(() => expect(dealsSections()).toHaveLength(3))
    expect(dealsSections()).toEqual([
      'Bajaron de precio en Súper',
      'Bajaron de precio en Express',
      'Bajaron de precio en Chocolatería',
    ])
    expect(screen.queryByText('Sin conexión')).toBeNull()
  })

  test('Mejor evaluados trae los seis de mejor nota; no hay «Envío más barato» ni envío gratis', async () => {
    const fetchMock = stubDeals()
    renderDeals()

    const best = within(await screen.findByRole('region', { name: 'Mejor evaluados' }))
    await waitFor(() => expect(best.getAllByRole('button')).toHaveLength(6))
    const asked = fetchMock.mock.calls
      .map(([url]) => new URL(url))
      .find((url) => url.pathname === '/catalog/restaurants')
    expect(Object.fromEntries(asked.searchParams)).toEqual({ sort: 'rating', limit: '6' })

    expect(screen.queryByText(/Envío más barato|lower fees|free|gratis|\$0/i)).toBeNull()
    // Nada del catálogo transcrito: ni Crazy Deals, ni Top 10 Pizzas, ni Most Ordered, ni New in Rappi.
    expect(screen.queryByText(/Crazy Deals|Top 10|Most Ordered|New in Rappi/)).toBeNull()
  })

  test('ninguna tienda tocable en Restaurantes, Ofertas ni Home es local: Ofertas, cada push de tienda lleva un id numérico', async () => {
    stubDeals()
    const push = renderDeals()
    const best = within(await screen.findByRole('region', { name: 'Mejor evaluados' }))
    await waitFor(() => expect(best.getAllByRole('button')).toHaveLength(6))

    // Una tarjeta de restaurante abre su menú.
    fireEvent.click(best.getByText('Pizzería de prueba Centro'))
    expect(push).toHaveBeenLastCalledWith('store', {
      store: expect.objectContaining({ id: 9801, name: 'Pizzería de prueba Centro', vertical: 'restaurants' }),
    })

    // Un producto en baja abre su tienda desde la hoja del producto.
    fireEvent.click(await screen.findByText('Gaseosa cola 1,5 L (prueba)'))
    fireEvent.click(screen.getByRole('button', { name: /Ver tienda/ }))
    expect(push).toHaveBeenLastCalledWith('store', {
      store: { id: 9101, name: 'Supermercado de prueba Centro', vertical: 'grocery' },
      item: expect.objectContaining({ entityId: '91003', vertical: 'grocery' }),
    })
    const stores = push.mock.calls.filter(([name]) => name === 'store').map(([, params]) => params.store)
    expect(stores.every((store) => Number.isInteger(store.id))).toBe(true)
  })

  test('sin conexión dice «Sin conexión» con Reintentar, y al reintentar llegan las bajas', async () => {
    let online = false
    stubDeals({
      '/catalog/deals': (req) => (online ? dealsOf(req) : 'offline'),
      '/catalog/restaurants': () => 'offline',
    })
    renderDeals()

    const notice = (await screen.findByText('Sin conexión')).closest('.offline-notice')
    expect(dealsSections()).toEqual([])
    online = true
    fireEvent.click(within(notice).getByRole('button', { name: 'Reintentar' }))
    await waitFor(() => expect(dealsSections()).toHaveLength(6))
    expect(screen.queryByText('Sin conexión')).toBeNull()
  })

  test('sin bajas ni restaurantes lo dice', async () => {
    stubDeals({ '/catalog/deals': [], '/catalog/restaurants': [] })
    renderDeals()
    expect(await screen.findByText('Todavía no hay ofertas en el catálogo.')).toBeTruthy()
  })
})
