import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from '../../test/api'
import { ToastProvider } from '../../components/Toast'
import { AddressProvider } from '../../state/AddressContext'
import { AssistantProvider } from '../../state/AssistantContext'
import { CartProvider } from '../../state/CartContext'
import { DemoProvider } from '../../state/DemoContext'
import { FavoritesProvider } from '../../state/FavoritesContext'
import { ProductSheetProvider } from '../../state/ProductSheetContext'
import ProductSheet from '../../components/ProductSheet'
import { ProfileProvider } from '../../state/ProfileContext'
import SearchScreen from '../search/SearchScreen'
import StoreScreen from '../store/StoreScreen'
import { VERTICALS } from './data'
import VerticalScreen from './VerticalScreen'

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
              <AddressProvider>
                <ToastProvider>
                  <ProductSheetProvider>
                    {children}
                    <ProductSheet />
                  </ProductSheetProvider>
                </ToastProvider>
              </AddressProvider>
            </FavoritesProvider>
          </CartProvider>
        </AssistantProvider>
      </ProfileProvider>
    </DemoProvider>
  )
}

/** Las bajas de precio de una vertical (código del backend), como las devolvería la API. */
const dealsOf = (backendVertical) => fixture('catalog-deals').filter((deal) => deal.vertical === backendVertical)

/** Las respuestas de ejemplo para la vertical `id` del prototipo (Súper y Licores comparten las tiendas de ejemplo). */
function stubVertical(id, { stores = fixture('catalog-vertical-stores'), deals = dealsOf('supermercado') } = {}) {
  return stubApi({
    [`/catalog/verticals/${id}/stores`]: stores,
    '/catalog/deals': deals,
    '/catalog/stores/9101': fixture('catalog-store'),
  })
}

function renderVertical(id) {
  const push = vi.fn()
  render(<VerticalScreen back={() => {}} push={push} params={{ id }} />, { wrapper: Providers })
  return push
}

const shown = () => events.track.mock.calls.filter(([type]) => type === 'suggestion_shown').map(([, fields]) => fields)

beforeAll(() => {
  Element.prototype.scrollTo = () => {} // jsdom no lo implementa
  Element.prototype.scrollIntoView = () => {} // ni este (pestañas del menú de la tienda)
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

describe('catálogo real en la vertical', () => {
  test('la vertical muestra las tiendas y las bajas de precio de la API', async () => {
    const fetchMock = stubVertical('grocery')
    renderVertical('grocery')

    const stores = within(await screen.findByRole('region', { name: 'Tiendas' }))
    expect(stores.getByText('Supermercado de prueba Centro')).toBeTruthy()
    expect(stores.getByText('Supermercado de prueba Norte')).toBeTruthy()
    expect(stores.getByText('25 min')).toBeTruthy()
    const deals = within(await screen.findByRole('region', { name: 'Bajaron de precio' }))
    for (const name of ['Galletas de vainilla 200 g (prueba)', 'Café molido tostado 250 g (prueba)']) {
      expect(deals.getByText(name)).toBeTruthy()
    }
    expect(deals.queryByText('Cerveza rubia lata 470 cc (prueba)')).toBeNull() // la baja de otra vertical no entra
    // El resto de la pantalla es la de siempre: búsqueda y categorías.
    expect(screen.getByText('Carnes y pescados')).toBeTruthy()
    expect(screen.getByText('Busca tiendas o productos')).toBeTruthy()

    const urls = fetchMock.mock.calls.map(([url]) => new URL(url))
    expect(urls.find((url) => url.pathname === '/catalog/deals').searchParams.get('vertical')).toBe('grocery')
  })

  test('las bajas de precio se ocultan si no viene ninguna', async () => {
    stubVertical('grocery', { deals: [] })
    renderVertical('grocery')
    expect(await screen.findByRole('region', { name: 'Tiendas' })).toBeTruthy()
    expect(screen.queryByText('Bajaron de precio')).toBeNull()
  })

  test('la categoría Cervezas y sidras busca «cerveza» en Licores (en «Rappi hoy», el buscador plano)', async () => {
    stubVertical('liquor')
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    const push = renderVertical('liquor')
    fireEvent.click(screen.getByText('Cervezas y sidras'))
    expect(push).toHaveBeenCalledWith('search', { query: 'cerveza', vertical: 'liquor' })
  })

  test('la búsqueda de una categoría muestra primero el grupo de esa vertical', async () => {
    // La API pone primero la vertical de la pantalla (`current`): aquí, Express.
    const grouped = fixture('search-grouped')
    grouped.groups = [grouped.groups[1], grouped.groups[0], grouped.groups[2]]
    const fetchMock = stubApi({ '/search': grouped, '/catalog/home': fixture('catalog-home') })
    render(<SearchScreen back={() => {}} push={() => {}} params={{ query: 'cerveza', vertical: 'express' }} />, {
      wrapper: Providers,
    })
    expect(await screen.findByRole('heading', { name: 'Express' })).toBeTruthy()
    expect(new URL(fetchMock.mock.calls.find(([u]) => u.includes('/search'))[0]).searchParams.get('current')).toBe(
      'express',
    )
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual([
      'Express',
      'Licores',
      'Súper',
    ])
  })

  test('en la Propuesta, la categoría abre el buscador con Mochi ya con «cerveza»', async () => {
    stubVertical('liquor')
    const push = renderVertical('liquor')
    fireEvent.click(screen.getByText('Cervezas y sidras'))
    expect(push).not.toHaveBeenCalled()
    expect(window.history.state).toMatchObject({ assistant: true })
  })

  test('toda categoría de toda vertical trae una consulta en español', () => {
    for (const [id, vertical] of Object.entries(VERTICALS))
      for (const row of vertical.categoryRows.flat())
        expect(row.query, `${id}: ${row.label}`).toMatch(/^[a-záéíóúñ ]+$/)
  })

  test('Ver más abre la lista con todas las tiendas y la tienda tocada lleva su id y su vertical', async () => {
    stubVertical('grocery')
    const push = renderVertical('grocery')
    const stores = within(await screen.findByRole('region', { name: 'Tiendas' }))

    fireEvent.click(stores.getByRole('button', { name: 'Ver más' }))
    const [name, params] = push.mock.calls.at(-1)
    expect(name).toBe('list')
    expect(params.title).toBe('Tiendas')
    expect(params.stores.map((store) => [store.id, store.vertical])).toEqual([
      [9101, 'grocery'],
      [9102, 'grocery'],
      [9111, 'grocery'],
    ])

    fireEvent.click(stores.getByText('Supermercado de prueba Norte'))
    expect(push).toHaveBeenLastCalledWith('store', {
      store: expect.objectContaining({ id: 9102, name: 'Supermercado de prueba Norte', vertical: 'grocery' }),
    })
  })

  test('una tienda de la lista abre su página y su visita va a la vertical de la pantalla', async () => {
    stubVertical('grocery')
    const push = renderVertical('grocery')
    const section = within(await screen.findByRole('region', { name: 'Tiendas' }))
    fireEvent.click(section.getByRole('button', { name: 'Ver más' }))
    const [, { stores }] = push.mock.calls.at(-1)
    cleanup()

    // La primera de la lista abierta (lista → tienda): su visita va a Súper y no se rechaza el lote en rappi-ia.
    render(<StoreScreen back={() => {}} push={() => {}} params={{ store: stores[0] }} />, { wrapper: Providers })
    expect(await screen.findByText('Despensa')).toBeTruthy()
    // La visita se registra cuando llega la tienda de la API, que puede llegar después de sus pasillos: se espera a
    // ella (en el CI a veces se leía antes y salía vacía).
    const visits = () => events.track.mock.calls.filter(([type]) => type === 'view_store').map(([, fields]) => fields)
    await waitFor(() =>
      expect(visits()).toEqual([
        expect.objectContaining({ vertical: 'grocery', entity_id: '9101', payload: { name: stores[0].name } }),
      ]),
    )
  })

  test('Ver tienda del detalle abre la tienda del producto', async () => {
    stubVertical('grocery')
    const push = renderVertical('grocery')
    const deals = within(await screen.findByRole('region', { name: 'Bajaron de precio' }))
    fireEvent.click(deals.getByText('Galletas de vainilla 200 g (prueba)'))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /Ver tienda/ })) // la tarjeta abre la hoja del producto

    // Con el producto tocado: así la tienda registra que se vio.
    expect(push).toHaveBeenCalledWith('store', {
      store: { id: 9102, name: 'Supermercado de prueba Norte', vertical: 'grocery' },
      item: expect.objectContaining({ id: 'cat-91002', storeId: 9102 }),
    })
  })

  test('un producto sin tienda conocida no ofrece Ver tienda', async () => {
    const [deal] = dealsOf('supermercado')
    stubVertical('grocery', { deals: [{ ...deal, store_id: null }] })
    renderVertical('grocery')
    const deals = within(await screen.findByRole('region', { name: 'Bajaron de precio' }))
    fireEvent.click(deals.getByText('Galletas de vainilla 200 g (prueba)'))
    expect(within(screen.getByRole('dialog')).queryByRole('button', { name: /Ver tienda/ })).toBeNull()
  })
})

describe('sin la API', () => {
  test('la vertical muestra Sin conexión dentro de la pantalla y Reintentar vuelve a pedir las tiendas', async () => {
    let online = false
    stubApi({
      '/catalog/verticals/grocery/stores': () => (online ? fixture('catalog-vertical-stores') : 'offline'),
      '/catalog/deals': () => (online ? dealsOf('supermercado') : 'offline'),
    })
    renderVertical('grocery')

    expect(await screen.findByText('Sin conexión')).toBeTruthy()
    // El resto de la pantalla sigue usable: se puede buscar y abrir una categoría.
    expect(screen.getByText('Busca tiendas o productos')).toBeTruthy()
    expect(screen.getByText('Carnes y pescados')).toBeTruthy()
    expect(screen.queryByText('Tiendas')).toBeNull()

    online = true
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByRole('region', { name: 'Tiendas' })).toBeTruthy()
    expect(screen.queryByText('Sin conexión')).toBeNull()
    expect(await screen.findByRole('region', { name: 'Bajaron de precio' })).toBeTruthy()
  })

  test('si fallan solo las bajas de precio, las tiendas se ven y esa sección no aparece', async () => {
    stubApi({ '/catalog/verticals/grocery/stores': fixture('catalog-vertical-stores'), '/catalog/deals': 'offline' })
    renderVertical('grocery')
    expect(await screen.findByRole('region', { name: 'Tiendas' })).toBeTruthy()
    expect(screen.queryByText('Sin conexión')).toBeNull()
    expect(screen.queryByText('Bajaron de precio')).toBeNull()
  })

  test('una vertical que la API no tiene no se confunde con estar sin conexión', async () => {
    stubApi({ '/catalog/verticals/grocery/stores': 404, '/catalog/deals': [] })
    renderVertical('grocery')
    expect(await screen.findByText('Todavía no hay tiendas de esta categoría en el catálogo.')).toBeTruthy()
    expect(screen.queryByText('Sin conexión')).toBeNull()
  })
})

describe('entradas al embudo desde una vertical', () => {
  test('el buscador se abre con la vertical de la pantalla (en «Rappi hoy», el plano)', () => {
    stubVertical('liquor')
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    const push = renderVertical('liquor')
    fireEvent.click(screen.getByText('Busca tiendas o productos'))
    expect(push).toHaveBeenCalledWith('search', { vertical: 'liquor' })
  })

  test('en la Propuesta, el buscador de la vertical es el de Mochi', () => {
    stubVertical('liquor')
    const push = renderVertical('liquor')
    fireEvent.click(screen.getByText('Busca tiendas o productos'))
    expect(push).not.toHaveBeenCalled()
    expect(window.history.state).toMatchObject({ assistant: true })
  })
})

describe('sin «Para ti, de otras tiendas»', () => {
  test('en el prototipo final, entrar a una vertical no muestra sugerencias de otras tiendas', async () => {
    stubVertical('liquor')
    renderVertical('liquor')
    await screen.findByRole('region', { name: 'Tiendas' })
    expect(screen.queryByText('Para ti, de otras tiendas')).toBeNull()
    expect(document.querySelector('.for-you')).toBeNull()
    expect(shown()).toEqual([])
  })
})

describe('vertical desconocida', () => {
  test('un id que no existe muestra un estado vacío en vez de romper, sin pedir nada a la API', () => {
    const fetchMock = stubApi({})
    renderVertical('no-existe')
    expect(screen.getByText('Esta categoría no está en el prototipo.')).toBeTruthy()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  test('Mascotas ya no es una vertical de la app: no hay tiendas locales que mostrar', () => {
    const fetchMock = stubApi({})
    renderVertical('pet')
    expect(screen.getByText('Esta categoría no está en el prototipo.')).toBeTruthy()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
