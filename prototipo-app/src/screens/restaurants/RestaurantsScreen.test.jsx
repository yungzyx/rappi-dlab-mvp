import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from '../../test/api'
import { ToastProvider } from '../../components/Toast'
import { AddressProvider } from '../../state/AddressContext'
import { AssistantProvider } from '../../state/AssistantContext'
import { DemoProvider } from '../../state/DemoContext'
import { ProfileProvider } from '../../state/ProfileContext'
import RestaurantsScreen from './RestaurantsScreen'

function Providers({ children }) {
  return (
    <DemoProvider>
      <ProfileProvider>
        <AssistantProvider>
          <AddressProvider>
            <ToastProvider>{children}</ToastProvider>
          </AddressProvider>
        </AssistantProvider>
      </ProfileProvider>
    </DemoProvider>
  )
}

/** `/catalog/restaurants` como la API: los de una cocina si se pide, si no todos. */
const byCuisine = (req) => {
  const cuisine = req.query.get('cuisine')
  return fixture('catalog-restaurants').filter((restaurant) => !cuisine || restaurant.cuisines.includes(cuisine))
}

const renderRestaurants = () => {
  const push = vi.fn()
  render(<RestaurantsScreen back={() => {}} push={push} />, { wrapper: Providers })
  return push
}
const listed = () => [...document.querySelectorAll('.rest-list .featured-title')].map((node) => node.textContent)
/** Las peticiones hechas a un camino, como su query. */
const queries = (fetchMock, path) =>
  fetchMock.mock.calls
    .map(([url]) => new URL(url))
    .filter((url) => url.pathname === path)
    .map((url) => Object.fromEntries(url.searchParams))
const category = (name) => screen.getByRole('button', { name })

beforeAll(() => {
  Element.prototype.scrollTo = () => {} // jsdom no lo implementa (carrusel de banners)
})
afterAll(() => {
  delete Element.prototype.scrollTo
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Restaurantes con el catálogo real', () => {
  test('Restaurantes lista los de la API y filtra por cocina', async () => {
    const fetchMock = stubApi({ '/catalog/restaurants': byCuisine })
    renderRestaurants()

    await waitFor(() => expect(listed()).toHaveLength(7))
    expect(listed()[0]).toBe('Parrilla de prueba')
    expect(queries(fetchMock, '/catalog/restaurants')).toEqual([{ sort: 'rating' }])

    fireEvent.click(category('Pizzas'))
    await waitFor(() => expect(listed()).toEqual(['Pizzería de prueba Centro']))
    expect(queries(fetchMock, '/catalog/restaurants').at(-1)).toEqual({ sort: 'rating', cuisine: 'Pizzas' })
    expect(category('Pizzas').getAttribute('aria-pressed')).toBe('true')

    // Otra cocina reemplaza a la anterior; la misma otra vez la quita.
    fireEvent.click(category('Hamburguesa'))
    await waitFor(() => expect(listed()).toEqual(['Sushi y hamburguesas de prueba Norte']))
    expect(queries(fetchMock, '/catalog/restaurants').at(-1)).toEqual({ sort: 'rating', cuisine: 'Hamburguesa' })
    expect(category('Pizzas').getAttribute('aria-pressed')).toBe('false')

    fireEvent.click(category('Hamburguesa'))
    await waitFor(() => expect(listed()).toHaveLength(7))
    expect(queries(fetchMock, '/catalog/restaurants').at(-1)).toEqual({ sort: 'rating' })
  })

  test('una cocina sin restaurantes lo dice', async () => {
    stubApi({ '/catalog/restaurants': (req) => (req.query.get('cuisine') ? [] : fixture('catalog-restaurants')) })
    renderRestaurants()
    await waitFor(() => expect(listed()).toHaveLength(7))

    fireEvent.click(category('Pizzas'))
    expect(await screen.findByText('Todavía no hay restaurantes de esta cocina en el catálogo.')).toBeTruthy()
    expect(listed()).toEqual([])
  })

  test('tocar un restaurante abre su menú: lleva su id, su vertical y su foto', async () => {
    stubApi({ '/catalog/restaurants': byCuisine })
    const push = renderRestaurants()
    await waitFor(() => expect(listed()).toHaveLength(7))

    fireEvent.click(screen.getByText('Pizzería de prueba Centro'))
    expect(push).toHaveBeenCalledWith('store', {
      store: expect.objectContaining({
        id: 9801,
        name: 'Pizzería de prueba Centro',
        vertical: 'restaurants',
        logo: false,
      }),
    })
  })

  test('ninguna tienda tocable en Restaurantes, Ofertas ni Home es local: Restaurantes, cada push de tienda lleva un id numérico', async () => {
    stubApi({ '/catalog/restaurants': byCuisine })
    const push = renderRestaurants()
    await waitFor(() => expect(listed()).toHaveLength(7))

    // Las tarjetas, los banners y «Volver a pedir» (que ya no está): todo lo tocable que no sea el filtro de cocina.
    for (const button of document.querySelectorAll('.rest-list button, .rest-banners button, .rest-again button'))
      fireEvent.click(button)
    const stores = push.mock.calls.filter(([name]) => name === 'store').map(([, params]) => params.store)
    expect(stores.map((store) => store.id)).toEqual([9804, 9801, 9806, 9803, 9805, 9802, 9807])
    expect(stores.every((store) => Number.isInteger(store.id) && store.vertical === 'restaurants')).toBe(true)
    expect(screen.queryByText('Order again')).toBeNull()
  })

  test('los banners ya no apuntan a tiendas inventadas: avisan que no están en el prototipo', async () => {
    stubApi({ '/catalog/restaurants': byCuisine })
    const push = renderRestaurants()
    await waitFor(() => expect(listed()).toHaveLength(7))

    fireEvent.click(screen.getByText('Hasta 40% de descuento'))
    expect(push).not.toHaveBeenCalled()
    expect(await screen.findByText('Esta sección no está en el prototipo')).toBeTruthy()
  })

  test('sin tiempo de entrega la tarjeta no deja un punto suelto, y un envío de $0 no se muestra como gratis', async () => {
    stubApi({ '/catalog/restaurants': byCuisine })
    renderRestaurants()
    await waitFor(() => expect(listed()).toHaveLength(7))

    const card = (name) => screen.getByText(name).closest('.featured-card')
    const meta = (name) => card(name).querySelector('.featured-meta')
    expect(meta('Café de prueba').textContent).toBe('$1.990') // sin tiempo: sin «•» al principio
    expect(meta('Café de prueba').querySelector('.meta-sep')).toBeNull()
    expect(meta('Pizzería de prueba Centro').textContent).toBe('25 min•$1.490')
    expect(meta('Cevichería de prueba').textContent).toBe('30 min') // envío $0: dato que falta, no «envío gratis»
    expect(screen.queryByText(/free|gratis|\$0/i)).toBeNull()
  })

  test('sin conexión la lista dice «Sin conexión» y Reintentar la trae; el resto de la pantalla sigue', async () => {
    let online = false
    stubApi({ '/catalog/restaurants': () => (online ? fixture('catalog-restaurants') : 'offline') })
    renderRestaurants()

    const notice = (await screen.findByText('Sin conexión')).closest('.offline-notice')
    expect(screen.getByText('Busca platos o restaurantes')).toBeTruthy()

    online = true
    fireEvent.click(within(notice).getByRole('button', { name: 'Reintentar' }))
    await waitFor(() => expect(listed()).toHaveLength(7))
    expect(screen.queryByText('Sin conexión')).toBeNull()
  })

  test('Turbo Restaurantes sigue abriendo el buscador (no es una cocina)', async () => {
    stubApi({ '/catalog/restaurants': byCuisine })
    const push = renderRestaurants()
    fireEvent.click(category('Turbo Restaurantes'))
    expect(push).toHaveBeenCalledWith('search', { query: 'turbo', vertical: 'restaurants' })
  })
})
