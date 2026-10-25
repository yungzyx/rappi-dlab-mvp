import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from '../../test/api'
import { ToastProvider } from '../../components/Toast'
import { FavoritesProvider } from '../../state/FavoritesContext'
import FavoritesScreen from './FavoritesScreen'

const SAVED = [
  { id: 9801, name: 'Pizzería de prueba Centro', vertical: 'restaurants', img: 'https://x/pizza.png', logo: false },
  { id: 9101, name: 'Supermercado de prueba Centro', vertical: 'grocery', img: 'https://x/super.png', logo: true },
]
const save = (stores) => localStorage.setItem('rappi-proto-favorites', JSON.stringify(stores))

/** Los supermercados, y la API respeta `limit` (el fixture trae tres: sin él serían los tres). */
const supermarkets = (req) => {
  const reply = fixture('catalog-vertical-stores')
  return { ...reply, stores: reply.stores.slice(0, Number(req.query.get('limit') ?? 30)) }
}

const stubFavorites = (extra = {}) =>
  stubApi({
    // La API respeta `limit`: sin él serían 7.
    '/catalog/restaurants': (req) => fixture('catalog-restaurants').slice(0, Number(req.query.get('limit') ?? 30)),
    '/catalog/verticals/supermercado/stores': supermarkets,
    ...extra,
  })

function Providers({ children }) {
  return (
    <FavoritesProvider>
      <ToastProvider>{children}</ToastProvider>
    </FavoritesProvider>
  )
}
const renderFavorites = () => {
  const push = vi.fn()
  render(<FavoritesScreen push={push} />, { wrapper: Providers })
  return push
}
const region = (name) => within(screen.getByRole('region', { name }))

beforeAll(() => {
  Element.prototype.scrollTo = () => {} // jsdom no lo implementa
})
afterAll(() => {
  delete Element.prototype.scrollTo
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('Favoritos con el catálogo real', () => {
  test('«Tus favoritos» son las tiendas que se marcaron con ♥, y tocar una abre su página por id', async () => {
    save(SAVED)
    stubFavorites()
    const push = renderFavorites()

    const mine = region('Tus favoritos')
    expect(mine.getAllByRole('button').map((button) => button.querySelector('img').alt)).toEqual([
      'Pizzería de prueba Centro',
      'Supermercado de prueba Centro',
    ])
    fireEvent.click(mine.getByAltText('Pizzería de prueba Centro'))
    expect(push).toHaveBeenCalledWith('store', {
      store: expect.objectContaining({ id: 9801, vertical: 'restaurants', name: 'Pizzería de prueba Centro' }),
    })
    // Ya no hay tiendas inventadas entre los favoritos.
    expect(screen.queryByAltText("McDonald's")).toBeNull()
    await screen.findByRole('region', { name: 'Los mejores restaurantes' })
  })

  test('sin favoritos dice cómo agregar uno', async () => {
    stubFavorites()
    renderFavorites()
    expect(region('Tus favoritos').getByText('Marca una tienda con ♥ y aparece aquí.')).toBeTruthy()
    await screen.findByRole('region', { name: 'Los mejores restaurantes' })
  })

  test('los favoritos guardados antes con una tienda local (sin id numérico) ya no se muestran: no existen', async () => {
    save([{ name: 'Délice', img: 'x.webp' }, { id: 'delice', name: 'Délice 2', img: 'y.webp' }, ...SAVED])
    stubFavorites()
    renderFavorites()
    expect(
      region('Tus favoritos')
        .getAllByRole('button')
        .map((button) => button.querySelector('img').alt),
    ).toEqual(['Pizzería de prueba Centro', 'Supermercado de prueba Centro'])
    expect(screen.queryByAltText('Délice')).toBeNull()
    await screen.findByRole('region', { name: 'Los mejores restaurantes' })

    cleanup()
    save([{ name: 'Délice', img: 'x.webp' }])
    renderFavorites()
    expect(region('Tus favoritos').getByText('Marca una tienda con ♥ y aparece aquí.')).toBeTruthy()
    await screen.findByRole('region', { name: 'Los mejores restaurantes' })
  })

  test('«Los mejores» salen de la API: cuatro restaurantes por nota y dos supermercados', async () => {
    const fetchMock = stubFavorites()
    renderFavorites()

    await screen.findByRole('region', { name: 'Los mejores restaurantes' })
    await screen.findByRole('region', { name: 'Los mejores supermercados' })
    const titles = (name) =>
      region(name)
        .getAllByRole('button')
        .map((button) => button.querySelector('.featured-title').textContent)
    expect(titles('Los mejores restaurantes')).toEqual([
      'Parrilla de prueba',
      'Pizzería de prueba Centro',
      'Pastelería de prueba',
      'Sándwiches de prueba',
    ])
    expect(titles('Los mejores supermercados')).toEqual([
      'Supermercado de prueba Centro',
      'Supermercado de prueba Norte',
    ])
    // Pide solo lo que muestra.
    const askedPath = (path) =>
      Object.fromEntries(
        fetchMock.mock.calls.map(([url]) => new URL(url)).find((url) => url.pathname === path).searchParams,
      )
    expect(askedPath('/catalog/restaurants')).toEqual({ sort: 'rating', limit: '4' })
    expect(askedPath('/catalog/verticals/supermercado/stores')).toEqual({ limit: '2' })
  })

  test('ninguna tienda tocable en Favoritos es local (como en Restaurantes, Ofertas y Home): cada push de tienda lleva un id numérico', async () => {
    save(SAVED)
    stubFavorites()
    const push = renderFavorites()
    await screen.findByRole('region', { name: 'Los mejores supermercados' })
    await screen.findByRole('region', { name: 'Los mejores restaurantes' })

    for (const name of ['Tus favoritos', 'Los mejores supermercados', 'Los mejores restaurantes'])
      for (const button of region(name).getAllByRole('button')) fireEvent.click(button)
    const stores = push.mock.calls.filter(([name]) => name === 'store').map(([, params]) => params.store)
    expect(stores).toHaveLength(2 + 2 + 4)
    expect(stores.every((store) => Number.isInteger(store.id))).toBe(true)
  })

  test('sin conexión «Tus favoritos» sigue y «Los mejores» no se muestran', async () => {
    save(SAVED)
    const fetchMock = stubFavorites({
      '/catalog/restaurants': 'offline',
      '/catalog/verticals/supermercado/stores': 'offline',
    })
    renderFavorites()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Los mejores restaurantes' })).toBeNull())
    expect(screen.queryByRole('region', { name: 'Los mejores supermercados' })).toBeNull()
    expect(region('Tus favoritos').getAllByRole('button')).toHaveLength(2)
    expect(screen.queryByText('Sin conexión')).toBeNull()
  })
})
