import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from '../../test/api'
import ProductSheet from '../../components/ProductSheet'
import { AssistantProvider } from '../../state/AssistantContext'
import { CartProvider } from '../../state/CartContext'
import { DemoProvider } from '../../state/DemoContext'
import { ProductSheetProvider } from '../../state/ProductSheetContext'
import { ProfileProvider } from '../../state/ProfileContext'
import SearchScreen from './SearchScreen'

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
            <ProductSheetProvider>
              {children}
              <ProductSheet />
            </ProductSheetProvider>
          </CartProvider>
        </AssistantProvider>
      </ProfileProvider>
    </DemoProvider>
  )
}

const searches = () => events.track.mock.calls.filter(([type]) => type === 'search').map(([, fields]) => fields)
const advance = (ms) => act(async () => vi.advanceTimersByTimeAsync(ms))

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  events.track.mockClear()
  localStorage.clear()
})

/** `/search` con el ejemplo agrupado, sin coincidencias si la consulta es "xyzzy" o se pide tal cual, y corregido si es
 * "cervezaaaa". */
const searchRoute = (req) => {
  if (req.query.get('q') === 'xyzzy' || req.query.get('correct') === 'false') return fixture('search-grouped-unmet')
  return req.query.get('q') === 'cervezaaaa' ? fixture('search-grouped-corrected') : fixture('search-grouped')
}

describe('SearchScreen', () => {
  const setup = (params = {}, routes = {}) => {
    const push = vi.fn()
    const fetchMock = stubApi({ '/search': searchRoute, '/catalog/home': fixture('catalog-home'), ...routes })
    render(<SearchScreen back={() => {}} push={push} params={params} />, { wrapper: Providers })
    return { input: screen.getByPlaceholderText('¿Qué quieres hoy?'), push, fetchMock }
  }
  const type = async (input, text) => {
    fireEvent.change(input, { target: { value: text } })
    await advance(250)
  }

  test('escribir "cerveza" muestra los grupos de la API con Licores primero', async () => {
    const { input } = setup()
    await type(input, 'cerveza')

    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)
    expect(headings).toEqual(['Licores', 'Express', 'Súper'])
    expect(screen.getAllByText('Cerveza rubia lata 470 cc (prueba)')).toHaveLength(3)
    expect(screen.getByText('Cerveza negra botella 330 cc (prueba)')).toBeTruthy()
  })

  test('un error de tipeo corregido dice qué se buscó y deja buscar lo escrito tal cual', async () => {
    const { input, fetchMock } = setup()
    await type(input, 'cervezaaaa')

    expect(screen.getByText(/Mostrando resultados para "cerveza"/)).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Licores' })).toBeTruthy()

    fireEvent.keyDown(input, { key: 'Enter' })
    expect(searches().at(-1)).toMatchObject({
      query: 'cervezaaaa',
      unmet: false,
      payload: { fuente: 'tipeada', corregida: 'cerveza' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Buscar "cervezaaaa" tal cual' }))
    await advance(0)
    // La búsqueda tal cual también se registra, sin corrección y sin resultado; su fuente es el aviso de la corrección.
    expect(searches().at(-1)).toMatchObject({ query: 'cervezaaaa', unmet: true })
    expect(searches().at(-1).payload).toEqual({ alcance: 'global', fuente: 'correccion' })
    const last = new URL(fetchMock.mock.calls.at(-1)[0])
    expect(last.searchParams.get('correct')).toBe('false')
    expect(screen.getByText('Sin resultados para "cervezaaaa".')).toBeTruthy()
    expect(screen.queryByText(/Mostrando resultados/)).toBeNull()

    await type(input, 'cervezaaa') // con otro texto, la API vuelve a poder corregir
    expect(new URL(fetchMock.mock.calls.at(-1)[0]).searchParams.has('correct')).toBe(false)
  })

  test('sin historial ni "Lo más buscado", el buscador muestra las ideas fijas', async () => {
    setup()
    await advance(0)
    expect(screen.getByRole('heading', { name: 'Ideas para buscar' })).toBeTruthy()
    expect(screen.queryByText('Búsquedas recientes')).toBeNull()
  })

  test('antes de escribir: las recientes de la persona y lo más buscado con su población', async () => {
    setup(
      {},
      {
        'GET /profile/*': { recientes: ['pizza', 'agua'], mas_buscado: ['papas fritas'], poblacion: 'synthetic' },
      },
    )
    await advance(0)
    expect(screen.getByRole('heading', { name: 'Búsquedas recientes' })).toBeTruthy()
    expect(screen.getByText('Entre las personas simuladas de la demo.')).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'Ideas para buscar' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'papas fritas' }))
    await advance(250)
    expect(searches()).toEqual([
      expect.objectContaining({
        query: 'papas fritas',
        payload: expect.objectContaining({ fuente: 'lo-mas-buscado' }),
      }),
    ])
  })

  test('las tiendas y los restaurantes que se llaman así salen antes de los productos, con "Ver todos"', async () => {
    const store = (id) => ({ ...fixture('catalog-vertical-stores').stores[0], id, name: `Tienda ${id}` })
    const withPlaces = (req) => ({
      ...searchRoute(req),
      places: { stores: [store(1), store(2), store(3), store(4)], restaurants: [] },
    })
    const { input, push } = setup({}, { '/search': withPlaces })
    await type(input, 'cerveza')
    const block = screen.getByRole('heading', { name: 'Tiendas' }).parentElement
    expect(within(block).getAllByRole('listitem')).toHaveLength(3)
    fireEvent.click(within(block).getByRole('button', { name: 'Ver todos (4)' }))
    expect(within(block).getAllByRole('listitem')).toHaveLength(4)
    fireEvent.click(within(block).getByText('Tienda 4'))
    expect(push).toHaveBeenCalledWith(
      'store',
      expect.objectContaining({
        store: expect.objectContaining({ id: 4, placement: expect.objectContaining({ origin: 'resultados-tiendas' }) }),
      }),
    )
  })

  test('"Ver todos en…" de un grupo busca solo en esa vertical', async () => {
    const { input, push } = setup()
    await type(input, 'cerveza')
    fireEvent.click(screen.getByRole('button', { name: 'Ver todos en Licores' }))
    expect(push).toHaveBeenCalledWith('search', { query: 'cerveza', vertical: 'liquor', only: true })
  })

  test('en "Ver todos en…" (una sola vertical), "Buscar … tal cual" vuelve a buscar sin corregir en esa vertical', async () => {
    const licores = fixture('search-grouped').groups[0]
    const oneVertical = (req) =>
      req.query.get('correct') === 'false'
        ? { vertical: licores.vertical, products: [], unmet: true }
        : { vertical: licores.vertical, products: licores.products, corrected_query: 'cerveza' }
    const fetchMock = stubApi({ '/search': oneVertical, '/catalog/home': fixture('catalog-home') })
    const params = { query: 'cervesa', vertical: 'liquor', only: true }
    render(<SearchScreen back={() => {}} push={() => {}} params={params} />, { wrapper: Providers })
    await advance(0)
    expect(screen.getByText(/Mostrando resultados para "cerveza"/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Buscar "cervesa" tal cual' }))
    await advance(0)
    const last = new URL(fetchMock.mock.calls.at(-1)[0])
    expect(last.pathname).toBe('/search')
    expect(Object.fromEntries(last.searchParams)).toMatchObject({ q: 'cervesa', vertical: 'liquor', correct: 'false' })
    expect(screen.queryByText(/Mostrando resultados/)).toBeNull()
  })

  test('sin resultados y con permiso de la API, "Lo que sea" abre RappiFavor con lo escrito', async () => {
    const { input, push } = setup() // "xyzzy" no tiene nada que las guardias bloqueen
    await type(input, 'xyzzy')
    expect(screen.getByText('¿No lo encuentras? Te lo conseguimos')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Pedir "xyzzy" con RappiFavor' }))
    expect(push).toHaveBeenCalledWith('favor', { text: 'xyzzy' })
    const services = events.track.mock.calls.filter(([type]) => type.startsWith('service_'))
    expect(services.map(([type, fields]) => [type, fields.origin, fields.payload.servicio])).toEqual([
      ['service_shown', 'lo-que-sea', 'rappifavor'],
      ['service_opened', 'lo-que-sea', 'rappifavor'],
    ])
  })

  test('sin el permiso de la API (las guardias), no ofrece "Lo que sea"', async () => {
    const { input } = setup({}, { '/search': (req) => ({ ...searchRoute(req), whim_allowed: false }) })
    await type(input, 'xyzzy')
    expect(screen.queryByText('¿No lo encuentras? Te lo conseguimos')).toBeNull()
  })

  test('la búsqueda manda la vertical de la pantalla de origen como "current"', async () => {
    const { input, fetchMock } = setup({ vertical: 'liquor' })
    await type(input, 'cerveza')
    const url = new URL(fetchMock.mock.calls.find(([u]) => u.includes('/search'))[0])
    expect(url.searchParams.get('q')).toBe('cerveza')
    expect(url.searchParams.get('current')).toBe('liquor')
  })

  test('en el prototipo final la búsqueda va con la persona (su dieta filtra); en "Rappi hoy", no', async () => {
    const { input, fetchMock } = setup()
    await type(input, 'cerveza')
    const sent = () => new URL(fetchMock.mock.calls.filter(([u]) => u.includes('/search')).at(-1)[0]).searchParams
    expect(sent().get('user_id')).toMatch(/^proto-/)
    cleanup()
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    const today = setup()
    await type(today.input, 'cerveza')
    expect(
      new URL(today.fetchMock.mock.calls.find(([u]) => u.includes('/search'))[0]).searchParams.has('user_id'),
    ).toBe(false)
  })

  test('una consulta que viene en los parámetros (una categoría) se busca de inmediato', async () => {
    const { input, fetchMock } = setup({ query: 'cerveza', vertical: 'liquor' })
    expect(input.value).toBe('cerveza')
    await advance(0)
    expect(fetchMock.mock.calls.some(([u]) => u.includes('/search?q=cerveza'))).toBe(true)
    expect(screen.getAllByRole('heading', { level: 2 })[0].textContent).toBe('Licores')
  })

  test('los productos se abren en su tienda por id, con el producto tocado', async () => {
    const { input, push } = setup()
    await type(input, 'cerveza')
    const liquor = screen.getByRole('heading', { name: 'Licores' }).parentElement
    fireEvent.click(within(liquor).getByText('Cerveza negra botella 330 cc (prueba)'))
    fireEvent.click(document.querySelector('.product-sheet-store'))
    expect(push).toHaveBeenCalledWith(
      'store',
      expect.objectContaining({
        store: expect.objectContaining({ id: 9401, vertical: 'liquor' }),
        item: expect.objectContaining({ entityId: '94002' }),
      }),
    )
  })

  test('sin resultados del catálogo dice que no hay (sin Mochi en "Rappi hoy")', async () => {
    const { input } = setup()
    await type(input, 'xyzzy')
    expect(screen.getByText('Sin resultados para "xyzzy".')).toBeTruthy()
    expect(document.querySelector('.mascot')).toBeNull()
  })

  test('sin buscar, las tiendas populares salen de la Home de la API', async () => {
    setup()
    await advance(0)
    expect(screen.getByText('Botillería de prueba Oriente')).toBeTruthy()
    expect(screen.getByText('Tiendas populares')).toBeTruthy()
  })

  test('sin API el buscador muestra Sin conexión y Reintentar vuelve a buscar', async () => {
    let online = false
    const { input } = setup({}, { '/search': (req) => (online ? searchRoute(req) : 'offline') })
    await type(input, 'cerveza')
    expect(screen.getByText('Sin conexión')).toBeTruthy()

    online = true
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    await advance(0)
    expect(screen.queryByText('Sin conexión')).toBeNull()
    expect(screen.getByRole('heading', { name: 'Licores' })).toBeTruthy()
  })

  test('el evento search lleva los resultados y unmet de la API', async () => {
    const { input } = setup({ vertical: 'liquor' })
    await type(input, 'cerveza')
    fireEvent.blur(input)
    // 2 en Licores + 1 en Express + 1 en Súper. El id de la búsqueda es el `request_id` de su respuesta; buscó en
    // todas las verticales (global) lo que se escribió.
    const typed = { alcance: 'global', fuente: 'tipeada' }
    expect(searches()).toEqual([
      {
        query: 'cerveza',
        modality: 'texto',
        results: 4,
        unmet: false,
        vertical: 'liquor',
        surface: 'search',
        request_id: 'contrato-search-grouped',
        payload: typed,
      },
    ])

    await type(input, 'xyzzy')
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(searches()[1]).toEqual({
      query: 'xyzzy',
      modality: 'texto',
      results: 0,
      unmet: true,
      vertical: 'liquor',
      surface: 'search',
      request_id: 'contrato-search-grouped-unmet',
      payload: typed,
    })
  })

  test('una idea para buscar se registra como sugerencia', async () => {
    setup()
    fireEvent.click(screen.getByRole('button', { name: 'Cerveza' }))
    await advance(250)
    expect(searches()).toEqual([
      expect.objectContaining({ query: 'Cerveza', payload: expect.objectContaining({ fuente: 'sugerencia' }) }),
    ])
  })

  test('agregar desde los resultados lleva el id de la búsqueda y la posición del producto', async () => {
    const { input } = setup()
    await type(input, 'cerveza')
    const add = document.querySelectorAll('.search-products .add-button')
    expect(add.length).toBeGreaterThan(1)
    fireEvent.click(add[1])
    const [added] = events.track.mock.calls.filter(([type]) => type === 'cart_add').map(([, fields]) => fields)
    expect(added).toMatchObject({
      surface: 'search',
      origin: 'resultados',
      position: 1,
      request_id: 'contrato-search-grouped',
    })
  })

  test('si Enter llega antes que la respuesta, se registra al llegar con su cantidad real', async () => {
    const { input } = setup({}, { '/search': { slow: 400, body: fixture('search-grouped') } })
    fireEvent.change(input, { target: { value: 'cerveza' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(searches()).toEqual([])
    await advance(250) // sale la consulta
    expect(searches()).toEqual([])
    await advance(400) // llega la respuesta
    expect(searches()).toEqual([expect.objectContaining({ query: 'cerveza', results: 4, unmet: false })])
  })

  test('una palabra a medio escribir no es una búsqueda: se registra al dar Enter, una vez', async () => {
    const { input } = setup()
    await type(input, 'cer')
    await advance(2000)
    expect(searches()).toEqual([])
    fireEvent.keyDown(input, { key: 'Enter' })
    fireEvent.blur(input)
    expect(searches()).toHaveLength(1)
    expect(searches()[0]).toMatchObject({ query: 'cer', modality: 'texto', results: 4, unmet: false })
  })

  test('sin API no se registra una búsqueda (no hay una cantidad real que contar)', async () => {
    const { input } = setup({}, { '/search': 'offline' })
    await type(input, 'cerveza')
    fireEvent.blur(input)
    expect(searches()).toEqual([])
  })

  test('borrar el texto no registra nada', async () => {
    const { input } = setup()
    await type(input, 'cerveza')
    fireEvent.blur(input)
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.blur(input)
    expect(searches()).toHaveLength(1)
  })

  test('tocar una búsqueda sugerida cuenta como buscarla', async () => {
    setup()
    fireEvent.click(screen.getByText('Pizza'))
    await advance(250)
    expect(searches()).toEqual([expect.objectContaining({ query: 'Pizza', modality: 'texto' })])
  })

  test('el campo no acepta más de lo que guarda el servidor', () => {
    expect(setup().input.maxLength).toBe(500)
  })
})
