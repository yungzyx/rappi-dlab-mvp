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

/** `/search` con el ejemplo agrupado, sin coincidencias si la consulta es «xyzzy» o se pide tal cual, y corregido si es
 * «cervezaaaa». */
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

  test('escribir «cerveza» muestra los grupos de la API con Licores primero', async () => {
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

    expect(screen.getByText(/Mostrando resultados para «cerveza»/)).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Licores' })).toBeTruthy()

    fireEvent.keyDown(input, { key: 'Enter' })
    expect(searches().at(-1)).toMatchObject({ query: 'cervezaaaa', unmet: false, payload: { corregida: 'cerveza' } })

    fireEvent.click(screen.getByRole('button', { name: 'Buscar «cervezaaaa» tal cual' }))
    await advance(0)
    // La búsqueda tal cual también se registra, sin corrección y sin resultado.
    expect(searches().at(-1)).toMatchObject({ query: 'cervezaaaa', unmet: true })
    expect(searches().at(-1).payload).toBeUndefined()
    const last = new URL(fetchMock.mock.calls.at(-1)[0])
    expect(last.searchParams.get('correct')).toBe('false')
    expect(screen.getByText('Sin resultados para «cervezaaaa».')).toBeTruthy()
    expect(screen.queryByText(/Mostrando resultados/)).toBeNull()

    await type(input, 'cervezaaa') // con otro texto, la API vuelve a poder corregir
    expect(new URL(fetchMock.mock.calls.at(-1)[0]).searchParams.has('correct')).toBe(false)
  })

  test('el título de sugerencias no dice recientes: son ideas fijas, no un historial', () => {
    setup()
    expect(screen.getByRole('heading', { name: 'Ideas para buscar' })).toBeTruthy()
    expect(screen.queryByText(/recent/i)).toBeNull()
  })

  test('la búsqueda manda la vertical de la pantalla de origen como «current»', async () => {
    const { input, fetchMock } = setup({ vertical: 'liquor' })
    await type(input, 'cerveza')
    const url = new URL(fetchMock.mock.calls.find(([u]) => u.includes('/search'))[0])
    expect(url.searchParams.get('q')).toBe('cerveza')
    expect(url.searchParams.get('current')).toBe('liquor')
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

  test('sin resultados del catálogo dice que no hay (sin Mochi en «Rappi hoy»)', async () => {
    const { input } = setup()
    await type(input, 'xyzzy')
    expect(screen.getByText('Sin resultados para «xyzzy».')).toBeTruthy()
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
    // 2 en Licores + 1 en Express + 1 en Súper.
    expect(searches()).toEqual([{ query: 'cerveza', modality: 'texto', results: 4, unmet: false, vertical: 'liquor' }])

    await type(input, 'xyzzy')
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(searches()[1]).toEqual({ query: 'xyzzy', modality: 'texto', results: 0, unmet: true, vertical: 'liquor' })
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
