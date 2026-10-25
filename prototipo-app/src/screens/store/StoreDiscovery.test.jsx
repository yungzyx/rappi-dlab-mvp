import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, describe, expect, test, vi } from 'vitest'
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
  )
}

const GROCERY = { id: 9101, name: 'Supermercado de prueba Centro', vertical: 'grocery' }
const PIZZERIA = { id: 9801, name: 'Pizzería de prueba Centro', vertical: 'restaurants' }
const PROMOS = [
  { type: 'free_shipping', title: 'Envío gratis sobre $15.000 (prueba)', value: 0, threshold: 15000 },
  { type: 'percentage', title: '10% OFF en despensa (prueba)', value: 10, threshold: null },
]
const CLOSED = {
  source: 'descarga',
  open: false,
  closes_at: null,
  opens_at: '10:00',
  opens_tomorrow: false,
  today: null,
}

const withStore = (extra) => {
  const page = fixture('catalog-store')
  return { ...page, store: { ...page.store, ...extra } }
}
const forYou = (products) => ({ products, basis: [], request_id: 'rid-para-ti' })
const openStore = (store) =>
  render(<StoreScreen back={() => {}} push={() => {}} params={{ store }} />, { wrapper: Providers })

beforeAll(() => {
  Element.prototype.scrollTo = () => {}
  Element.prototype.scrollIntoView = () => {}
})
afterAll(() => {
  delete Element.prototype.scrollTo
  delete Element.prototype.scrollIntoView
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  events.track.mockClear()
  localStorage.clear()
})

describe('promos, horario y «Para ti» en la tienda', () => {
  test('las promos publicadas se ven y la del mínimo trae la barra «Agrega $X»', async () => {
    stubApi({ '/catalog/stores/9101': withStore({ promos: PROMOS }), '/catalog/stores/9101/para-ti': forYou([]) })
    openStore(GROCERY)
    const promos = within(await screen.findByRole('list', { name: 'Promociones de la tienda' }))
    expect(promos.getAllByRole('listitem').map((item) => item.textContent)).toEqual(PROMOS.map((p) => p.title))
    expect(screen.getByText(/publicadas por la tienda en Rappi el día de la descarga/)).toBeTruthy()
    const bar = document.querySelector('.store-threshold')
    expect(bar.textContent).toContain('Agrega $15.000 en esta tienda para lograrlo.')
    expect(bar.textContent).toContain('esta demo no la descuenta al pagar')
  })

  test('una tienda cerrada en la descarga lo dice, con la aclaración de que no es en vivo', async () => {
    stubApi({ '/catalog/stores/9101': withStore({ hours: CLOSED }), '/catalog/stores/9101/para-ti': forYou([]) })
    openStore(GROCERY)
    expect(await screen.findByText('Cerrado · Abre a las 10:00')).toBeTruthy()
    expect(screen.getByText(/lo que Rappi publicó el día de la descarga, no el estado en vivo/)).toBeTruthy()
  })

  test('en la propuesta, «Para ti» es la primera pestaña de la tienda y muestra lo suyo', async () => {
    const [mine] = fixture('catalog-store').products
    stubApi({ '/catalog/stores/9101': fixture('catalog-store'), '/catalog/stores/9101/para-ti': forYou([mine]) })
    openStore(GROCERY)
    const tabs = within(await screen.findByRole('navigation', { name: 'Pasillos' }))
    await waitFor(() => expect(tabs.getAllByRole('button')[0].textContent).toBe('Para ti'))
    fireEvent.click(tabs.getByRole('button', { name: 'Para ti' }))
    const list = within(screen.getByRole('list', { name: 'Para ti' }))
    expect(list.getAllByRole('listitem')).toHaveLength(1)
    expect(list.getByText(mine.name)).toBeTruthy()
  })

  test('en un restaurante, «Para ti» abre el menú antes de «Lo más pedido»', async () => {
    const [dish] = fixture('catalog-menu').sections[0].items
    stubApi({
      '/catalog/restaurants/9801/menu': fixture('catalog-menu'),
      '/catalog/stores/9801/para-ti': forYou([dish]),
    })
    openStore(PIZZERIA)
    const tabs = within(await screen.findByRole('navigation', { name: 'Secciones del menú' }))
    await waitFor(() => expect(tabs.getAllByRole('button')[0].textContent).toBe('Para ti'))
    expect(tabs.getAllByRole('button')[1].textContent).toBe('Lo más pedido')
  })

  test('en «Rappi hoy» no hay «Para ti»: ni se pide', async () => {
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    const fetchMock = stubApi({ '/catalog/stores/9101': fixture('catalog-store') })
    openStore(GROCERY)
    await screen.findByRole('navigation', { name: 'Pasillos' })
    expect(fetchMock.mock.calls.some(([url]) => url.includes('/para-ti'))).toBe(false)
  })
})
