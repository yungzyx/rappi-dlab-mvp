import { afterAll, afterEach, beforeAll, describe, expect, test, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { fixture, stubApi } from '../../test/api'
import { ToastProvider } from '../../components/Toast'
import { AddressProvider } from '../../state/AddressContext'
import { AssistantProvider } from '../../state/AssistantContext'
import { CartProvider } from '../../state/CartContext'
import { DemoProvider } from '../../state/DemoContext'
import { ProfileProvider } from '../../state/ProfileContext'
import HomeFeed from './HomeFeed'

const events = vi.hoisted(() => ({ track: vi.fn(), flush: async () => {}, clear: () => {}, settled: async () => {} }))
vi.mock('../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))

function Providers({ children }) {
  return (
    <DemoProvider>
      <ProfileProvider>
        <AssistantProvider>
          <CartProvider>
            <AddressProvider>
              <ToastProvider>{children}</ToastProvider>
            </AddressProvider>
          </CartProvider>
        </AssistantProvider>
      </ProfileProvider>
    </DemoProvider>
  )
}

beforeAll(() => {
  Element.prototype.scrollTo = () => {} // jsdom no lo implementa (carruseles)
})
afterAll(() => {
  delete Element.prototype.scrollTo
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

/** Lo que la Home pide a la API: las listas de `/catalog/home` y los seis mejor evaluados. */
const homeRoutes = (extra = {}) => ({
  '/catalog/home': fixture('catalog-home'),
  '/catalog/restaurants': fixture('catalog-restaurants').slice(0, 6),
  ...extra,
})

describe('Home de «Rappi hoy»', () => {
  const renderHome = (routes = {}) => {
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    const fetchMock = stubApi(routes)
    const push = vi.fn()
    render(<HomeFeed push={push} />, { wrapper: Providers })
    return { push, fetchMock }
  }
  const section = (name) => within(screen.getByRole('region', { name }))

  test('es la app como es hoy: buscador plano, sin Mochi ni fila «Para ti»', () => {
    renderHome()
    expect(screen.queryByRole('button', { name: 'Abrir buscador con Mochi' })).toBeNull()
    expect(document.querySelector('.for-you')).toBeNull()
    expect(document.querySelector('.search-bar')).not.toBeNull()
  })

  test('mantiene el orden de hoy sin pedir el orden a la API, y tocar un vertical manda vertical_open', () => {
    events.track.mockClear()
    const { fetchMock } = renderHome({ 'GET /profile/*': fixture('profile-verticales') })
    expect([...document.querySelectorAll('.home-shortcut')].map((button) => button.textContent).slice(0, 2)).toEqual([
      'Súper',
      'Farmacia',
    ])
    expect(fetchMock.mock.calls.some(([url]) => url.includes('/verticales'))).toBe(false)
    expect(screen.queryByText('Ordenadas según lo que más usas')).toBeNull()
    fireEvent.click(screen.getByText('Farmacia'))
    expect(events.track).toHaveBeenCalledWith('vertical_open', { vertical: 'farmacia' })
    // RappiTravel también se anota (en «Rappi hoy» el evento va marcado y el motor no aprende de él).
    fireEvent.click(screen.getByText('RappiTravel'))
    expect(events.track.mock.calls.filter(([type]) => type === 'vertical_open')).toHaveLength(1)
    expect(events.track.mock.calls.filter(([type]) => type === 'service_opened')).toEqual([
      ['service_opened', { payload: { servicio: 'rappitravel', desde: 'home' } }],
    ])
  })

  test('la Home muestra el aviso de demo no oficial', () => {
    renderHome()
    expect(screen.getByText('Demo no oficial · prototipo independiente, no afiliado a Rappi')).toBeTruthy()
  })

  test('RappiFavor sigue no disponible, como en la app', () => {
    renderHome()
    expect(screen.getByLabelText('RappiFavor (no disponible)')).toBeTruthy()
  })

  test('la Home muestra Cerca de ti de la API y se oculta si falla', async () => {
    const { fetchMock } = renderHome(homeRoutes())

    await screen.findByRole('region', { name: 'Cerca de ti' })
    const nearby = section('Cerca de ti')
    for (const name of [
      'Botillería de prueba Oriente',
      'Supermercado de prueba Norte',
      'Tienda turbo de prueba Centro',
    ])
      expect(nearby.getByText(name)).toBeTruthy()
    expect(nearby.getAllByText('30 min').length).toBeGreaterThan(0)
    // Restaurantes rápidos y Mejor evaluados salen de la API; no hay «Envío más barato» (casi todos traen $0: falta el dato).
    expect(section('Restaurantes rápidos').getByText('Sándwiches de prueba')).toBeTruthy()
    expect(section('Restaurantes rápidos').getByText('Pastelería de prueba')).toBeTruthy()
    await screen.findByRole('region', { name: 'Mejor evaluados' })
    expect(section('Mejor evaluados').getAllByRole('button')).toHaveLength(6)
    expect(screen.queryByText(/lower fees|Envío más barato|Stores near by you/)).toBeNull()
    const asked = fetchMock.mock.calls
      .map(([url]) => new URL(url))
      .filter((url) => url.pathname === '/catalog/restaurants')
    expect(asked.map((url) => Object.fromEntries(url.searchParams))).toEqual([{ sort: 'rating', limit: '6' }])
  })

  test('si /catalog/home falla, esas secciones se ocultan y la Home sigue entera', async () => {
    const { fetchMock } = renderHome(homeRoutes({ '/catalog/home': 'offline' }))
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => new URL(url).pathname === '/catalog/home')).toBe(true),
    )
    await screen.findByRole('region', { name: 'Mejor evaluados' }) // la otra llamada es independiente
    expect(screen.queryByRole('region', { name: 'Cerca de ti' })).toBeNull()
    expect(screen.queryByRole('region', { name: 'Restaurantes rápidos' })).toBeNull()
    expect(screen.queryByText('Sin conexión')).toBeNull() // la Home nunca se bloquea
    expect(screen.getByLabelText('RappiFavor (no disponible)')).toBeTruthy()
    expect(document.querySelector('.search-bar')).not.toBeNull()
  })

  test('mientras llegan las listas la Home ya se ve entera', () => {
    renderHome(homeRoutes({ '/catalog/home': { slow: 5000, body: fixture('catalog-home') } }))
    expect(document.querySelector('.search-bar')).not.toBeNull()
    expect(screen.getByLabelText('RappiFavor (no disponible)')).toBeTruthy()
    expect(screen.queryByRole('region', { name: 'Cerca de ti' })).toBeNull()
  })

  test('sin restaurantes para la nota, solo se oculta Mejor evaluados', async () => {
    renderHome(homeRoutes({ '/catalog/restaurants': 'offline' }))
    await screen.findByRole('region', { name: 'Cerca de ti' })
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Mejor evaluados' })).toBeNull())
  })

  test('ninguna tienda tocable en Restaurantes, Ofertas ni Home es local: Home, cada push de tienda lleva un id numérico', async () => {
    const { push } = renderHome(homeRoutes())
    await screen.findByRole('region', { name: 'Mejor evaluados' })
    await screen.findByRole('region', { name: 'Cerca de ti' })

    for (const name of ['Cerca de ti', 'Restaurantes rápidos', 'Mejor evaluados'])
      for (const button of section(name).getAllByRole('button')) if (button.textContent) fireEvent.click(button)
    const stores = push.mock.calls.filter(([screenName]) => screenName === 'store').map(([, params]) => params.store)
    // 6 cercanas + 2 rápidas + 6 mejor evaluados (el botón «Ver todas» de Cerca de ti solo avisa).
    expect(stores).toHaveLength(14)
    expect(stores.every((store) => Number.isInteger(store.id))).toBe(true)
    expect(stores.filter((store) => store.vertical === 'restaurants')).toHaveLength(8)
    expect(stores.find((store) => store.id === 9402)).toMatchObject({
      vertical: 'liquor',
      name: 'Botillería de prueba Oriente',
    })
  })
})
