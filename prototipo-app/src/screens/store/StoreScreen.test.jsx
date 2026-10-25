import { StrictMode } from 'react'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

const GROCERY = { id: 9101, name: 'Supermercado de prueba Centro', vertical: 'grocery' }
const PIZZERIA = { id: 9801, name: 'Pizzería de prueba Centro', vertical: 'restaurants' }

/** Una tienda grande: 30 productos en su primer pasillo, de a 24 por página. */
const bigStore = (req) => fixture(req.query.get('page') === '2' ? 'catalog-store-page-2' : 'catalog-store')

/** Las respuestas de ejemplo de la tienda 9101 y del menú de la pizzería. */
const stubCatalog = (extra = {}) =>
  stubApi({
    '/catalog/stores/9101': bigStore,
    '/catalog/restaurants/9801/menu': fixture('catalog-menu'),
    ...extra,
  })

const openStore = (params) =>
  render(<StoreScreen back={() => {}} push={() => {}} params={params} />, { wrapper: Providers })
const tracked = (type) => events.track.mock.calls.filter(([name]) => name === type).map(([, fields]) => fields)
const rows = () => [...document.querySelectorAll('.product-row strong')].map((node) => node.textContent)
/** Las peticiones hechas, como `{ path, query }`. */
const requests = (fetchMock) =>
  fetchMock.mock.calls.map(([url]) => {
    const { pathname, searchParams } = new URL(url)
    return { path: pathname, query: Object.fromEntries(searchParams) }
  })

beforeAll(() => {
  Element.prototype.scrollTo = () => {} // jsdom no lo implementa
  Element.prototype.scrollIntoView = () => {} // ni este (pestañas del menú)
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

describe('tienda con pasillos', () => {
  test('la tienda muestra los pasillos y Ver más trae la página siguiente sin repetir', async () => {
    const fetchMock = stubCatalog()
    openStore({ store: GROCERY })

    expect(await screen.findByRole('heading', { name: 'Supermercado de prueba Centro' })).toBeTruthy()
    const tabs = within(await screen.findByRole('navigation', { name: 'Pasillos' }))
    expect(tabs.getAllByRole('button').map((tab) => tab.textContent)).toEqual([
      'Despensa',
      'Snacks y Dulces',
      'Bebidas',
      'Cuidado del bebé',
      'Cervezas',
    ])
    expect(tabs.getByRole('button', { name: 'Despensa' }).getAttribute('aria-current')).toBe('true')
    expect(rows()).toHaveLength(24)

    fireEvent.click(screen.getByRole('button', { name: 'Ver más' }))
    await waitFor(() => expect(rows()).toHaveLength(30))
    expect(new Set(rows()).size).toBe(30) // ninguno repetido
    expect(rows().slice(24)).toEqual(fixture('catalog-store-page-2').products.map((product) => product.name))
    // Pide la página 2 del pasillo que se ve, y la primera sola una vez.
    expect(requests(fetchMock).map(({ query }) => [query.aisle, query.page])).toEqual([
      [undefined, undefined],
      ['100', '2'],
    ])
    // Era la última página: ya no hay más que traer.
    expect(screen.queryByRole('button', { name: 'Ver más' })).toBeNull()
  })

  test('elegir otro pasillo muestra sus productos desde la primera página', async () => {
    const fetchMock = stubCatalog({
      '/catalog/stores/9101': (req) => {
        if (req.query.get('aisle') !== '300') return bigStore(req)
        const reply = fixture('catalog-store')
        const cola = fixture('catalog-deals').find((deal) => deal.name.startsWith('Gaseosa'))
        return { ...reply, aisle: reply.aisles[2], products: [cola], has_more: false }
      },
    })
    openStore({ store: GROCERY })
    const tabs = within(await screen.findByRole('navigation', { name: 'Pasillos' }))
    await waitFor(() => expect(rows()).toHaveLength(24))
    fireEvent.click(screen.getByRole('button', { name: 'Ver más' }))
    await waitFor(() => expect(rows()).toHaveLength(30))

    fireEvent.click(tabs.getByRole('button', { name: 'Bebidas' }))
    await waitFor(() => expect(rows()).toEqual(['Gaseosa cola 1,5 L (prueba)']))
    expect(tabs.getByRole('button', { name: 'Bebidas' }).getAttribute('aria-current')).toBe('true')
    expect(tabs.getByRole('button', { name: 'Despensa' }).getAttribute('aria-current')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Ver más' })).toBeNull()
    expect(requests(fetchMock).at(-1).query).toEqual({ aisle: '300' })
  })

  test('un pasillo que no existe (200 sin pasillo ni productos) dice que no hay qué mostrar', async () => {
    stubCatalog({ '/catalog/stores/9101': { ...fixture('catalog-store'), aisle: null, products: [], has_more: false } })
    openStore({ store: GROCERY })
    expect(await screen.findByText('No hay productos para mostrar.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Ver más' })).toBeNull()
  })

  test('si falla Ver más se avisa y los productos que ya estaban se quedan', async () => {
    stubCatalog({ '/catalog/stores/9101': (req) => (req.query.get('page') === '2' ? 'offline' : bigStore(req)) })
    openStore({ store: GROCERY })
    await waitFor(() => expect(rows()).toHaveLength(24))

    fireEvent.click(screen.getByRole('button', { name: 'Ver más' }))
    expect(await screen.findByText('No se pudo cargar más productos')).toBeTruthy()
    expect(rows()).toHaveLength(24)
    expect(screen.getByRole('button', { name: 'Ver más' })).toBeTruthy()
  })

  test('muestra la foto y los datos de la tienda que trae la API, no los del enlace', async () => {
    stubCatalog()
    openStore({ store: { id: 9101, name: 'Nombre viejo', vertical: 'grocery' } })
    expect(await screen.findByRole('heading', { name: 'Supermercado de prueba Centro' })).toBeTruthy()
    expect(screen.getByText('25 min')).toBeTruthy()
    expect(document.querySelector('.store-hero').className).toContain('is-logo')
    expect(document.querySelector('.store-hero img').getAttribute('src')).toBe(
      'https://images.rappi.cl/marketplace/prueba-9101.png',
    )
  })
})

describe('restaurante', () => {
  test('un restaurante muestra su menú con Lo más pedido primero', async () => {
    const fetchMock = stubCatalog()
    openStore({ store: PIZZERIA })

    const tabs = within(await screen.findByRole('navigation', { name: 'Secciones del menú' }))
    expect(tabs.getAllByRole('button').map((tab) => tab.textContent)).toEqual([
      'Lo más pedido',
      'Pizzas',
      'Bebidas',
      'Postres',
    ])
    expect([...document.querySelectorAll('.menu-section h2')].map((title) => title.textContent)).toEqual([
      'Lo más pedido',
      'Pizzas',
      'Bebidas',
      'Postres',
    ])
    // Un plato puede estar en «Lo más pedido» y en su sección: sale en las dos, cada uno en su lista.
    expect(screen.getAllByText('Pizza margarita mediana (prueba)')).toHaveLength(2)
    expect(screen.getByRole('heading', { name: 'Pizzería de prueba Centro' })).toBeTruthy()
    expect(screen.getByText('★ 4.6')).toBeTruthy()
    // La foto es la de un plato, no un logo; un restaurante se abre por su menú y nunca como tienda.
    expect(document.querySelector('.store-hero').className).not.toContain('is-logo')
    expect(requests(fetchMock).map(({ path }) => path)).toEqual(['/catalog/restaurants/9801/menu'])
  })

  test('un plato sin foto no rompe el menú', async () => {
    stubCatalog()
    openStore({ store: PIZZERIA })
    expect(await screen.findByText('Bebida cola 500 cc (prueba)')).toBeTruthy()
  })
})

describe('tienda que no está en el catálogo', () => {
  test('una tienda que no está en la base dice «Esta tienda no está en el catálogo»', async () => {
    stubCatalog() // 404 en /catalog/stores/424242, como en la API
    openStore({ store: { id: 424242, name: 'Tienda cerrada', vertical: 'grocery' } })

    expect(await screen.findByText('Esta tienda no está en el catálogo')).toBeTruthy()
    expect(screen.queryByText('Sin conexión')).toBeNull()
    expect(screen.getByRole('heading', { name: 'Tienda cerrada' })).toBeTruthy()
    // Se puede volver: la pantalla no se rompe.
    expect(screen.getByRole('button', { name: 'Volver' })).toBeTruthy()
    expect(tracked('view_store')).toEqual([]) // no se cuenta como visita
  })

  test('un restaurante cerrado también dice que no está', async () => {
    stubCatalog()
    openStore({ store: { id: 424242, name: 'Restaurante cerrado', vertical: 'restaurants' } })
    expect(await screen.findByText('Esta tienda no está en el catálogo')).toBeTruthy()
  })

  test.each([
    ['solo con su nombre (como las abre Mochi)', { name: 'Unimarc' }],
    ['con un id que no es numérico', { id: 'real-2', name: 'Délice - Las Condes', vertical: 'restaurants' }],
    ['con un id vacío', { id: '', name: 'Unimarc' }],
  ])('una tienda %s no pide nada a la API y dice que no está', (_label, given) => {
    const fetchMock = stubCatalog()
    openStore({ store: given })
    expect(screen.getByText('Esta tienda no está en el catálogo')).toBeTruthy()
    expect(fetchMock).not.toHaveBeenCalled()
    expect(tracked('view_store')).toEqual([])
  })
})

describe('sin la API', () => {
  test('sin API la tienda muestra Sin conexión y Reintentar la carga', async () => {
    let online = false
    stubCatalog({ '/catalog/stores/9101': (req) => (online ? bigStore(req) : 'offline') })
    openStore({ store: GROCERY })

    expect(await screen.findByText('Sin conexión')).toBeTruthy()
    expect(screen.queryByText('Esta tienda no está en el catálogo')).toBeNull()
    // La pantalla sigue siendo la de la tienda: nombre del enlace y botón para volver.
    expect(screen.getByRole('heading', { name: 'Supermercado de prueba Centro' })).toBeTruthy()

    online = true
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByRole('navigation', { name: 'Pasillos' })).toBeTruthy()
    expect(screen.queryByText('Sin conexión')).toBeNull()
    await waitFor(() => expect(rows()).toHaveLength(24))
  })

  test('un restaurante sin API también muestra Sin conexión', async () => {
    stubCatalog({ '/catalog/restaurants/9801/menu': 'offline' })
    openStore({ store: PIZZERIA })
    expect(await screen.findByText('Sin conexión')).toBeTruthy()
  })

  test('un error del servidor se puede reintentar: no es «no está en el catálogo»', async () => {
    stubCatalog({ '/catalog/stores/9101': 500 })
    openStore({ store: GROCERY })
    expect(await screen.findByText('Sin conexión')).toBeTruthy()
    expect(screen.queryByText('Esta tienda no está en el catálogo')).toBeNull()
  })
})

describe('visita a una tienda (embudo del panel)', () => {
  test('view_store lleva la vertical y el id de la tienda que trae la API, una sola vez', async () => {
    stubCatalog()
    openStore({ store: GROCERY })
    await screen.findByRole('navigation', { name: 'Pasillos' })
    expect(tracked('view_store')).toEqual([
      expect.objectContaining({
        vertical: 'grocery',
        entity_type: 'store',
        entity_id: '9101',
        payload: { name: 'Supermercado de prueba Centro' },
      }),
    ])
  })

  test('cambiar de pasillo o traer más productos no cuenta otra visita', async () => {
    stubCatalog()
    openStore({ store: GROCERY })
    const tabs = within(await screen.findByRole('navigation', { name: 'Pasillos' }))
    await waitFor(() => expect(rows()).toHaveLength(24))
    fireEvent.click(screen.getByRole('button', { name: 'Ver más' }))
    await waitFor(() => expect(rows()).toHaveLength(30))
    fireEvent.click(tabs.getByRole('button', { name: 'Bebidas' }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Bebidas' }).getAttribute('aria-current')).toBe('true'),
    )
    expect(tracked('view_store')).toHaveLength(1)
  })

  test('la de un restaurante va a restaurantes', async () => {
    stubCatalog()
    openStore({ store: PIZZERIA })
    await screen.findByRole('navigation', { name: 'Secciones del menú' })
    expect(tracked('view_store')).toEqual([
      expect.objectContaining({
        vertical: 'restaurants',
        entity_id: '9801',
        payload: { name: 'Pizzería de prueba Centro' },
      }),
    ])
  })

  test('abrirla desde un producto es ver ese producto: view_item con su vertical y su concepto, una vez', async () => {
    stubCatalog()
    const item = toPrototypeProduct(fixture('catalog-product'))
    openStore({ store: GROCERY, item })
    // view_store y view_item salen del mismo efecto, que corre después de pintar.
    await waitFor(() => expect(tracked('view_store')).toHaveLength(1))
    expect(tracked('view_item')).toEqual([
      expect.objectContaining({
        vertical: 'grocery',
        concept_id: 'snacks-salados',
        entity_type: 'catalog_item',
        entity_id: '91001',
      }),
    ])
    expect(tracked('view_store')).toHaveLength(1)
  })

  test('abrirla sin tocar un producto no es ver un producto', async () => {
    stubCatalog()
    openStore({ store: GROCERY })
    await waitFor(() => expect(tracked('view_store')).toHaveLength(1))
    expect(tracked('view_item')).toEqual([])
  })
})

describe('producto que llegó tocándolo', () => {
  const deal = (prefix) =>
    toPrototypeProduct(fixture('catalog-deals').find((candidate) => candidate.name.startsWith(prefix)))
  // Galletas es de la tienda 9102 y Café, del primer pasillo de la 9101.
  const elsewhere = () => deal('Galletas')
  const listed = () => deal('Café molido')

  test('si no está en lo que se ve, aparece destacado arriba con su botón de agregar', async () => {
    const item = elsewhere()
    stubCatalog()
    openStore({ store: GROCERY, item })
    const chosen = await screen.findByText('Lo que elegiste')
    expect(screen.getAllByText(item.name).length).toBeGreaterThan(0)
    expect(screen.getAllByLabelText(/Agregar/).length).toBeGreaterThan(0)
    // Va antes que los productos del pasillo.
    await waitFor(() => expect(rows()).toHaveLength(25))
    expect(chosen.compareDocumentPosition(document.querySelectorAll('.product-row')[1])).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    )
  })

  test('un producto que sí está en el pasillo no se duplica', async () => {
    const item = listed()
    stubCatalog()
    openStore({ store: GROCERY, item })
    await waitFor(() => expect(rows()).toHaveLength(24))
    expect(screen.queryByText('Lo que elegiste')).toBeNull()
  })

  test('una sugerencia del agente que está en el pasillo cuenta su aceptación al agregarla, una vez', async () => {
    // Como llega desde «¿Repetimos?» en la Home (api/agent.js): el café de la 9101, con su origen.
    const offered = fixture('agent-offer-recompra').products[0]
    const item = { ...toPrototypeProduct(offered), fromSuggestion: true, suggestionOrigin: 'agent-recompra' }
    stubCatalog()
    openStore({ store: GROCERY, item })
    await waitFor(() => expect(rows()).toHaveLength(24))
    expect(tracked('suggestion_accepted')).toEqual([])

    const row = [...document.querySelectorAll('.product-row')].find((node) => node.textContent.includes(offered.name))
    fireEvent.click(within(row).getByLabelText(`Agregar ${offered.name}`))
    fireEvent.click(within(row).getByLabelText(/^Agregar uno de/)) // otra unidad: no es otra aceptación
    const accepted = tracked('suggestion_accepted')
    expect(accepted).toEqual([expect.objectContaining({ concept_id: 'cafe', payload: { origen: 'agent-recompra' } })])
  })

  test('también se destaca en un restaurante si el plato no está en su menú', async () => {
    stubCatalog()
    openStore({ store: PIZZERIA, item: elsewhere() })
    expect(await screen.findByText('Lo que elegiste')).toBeTruthy()
  })
})

describe('tienda sin productos', () => {
  test('una tienda sin pasillos dice que no hay productos para mostrar', async () => {
    stubCatalog({
      '/catalog/stores/9101': { ...fixture('catalog-store'), aisles: [], aisle: null, products: [], has_more: false },
    })
    openStore({ store: GROCERY })
    expect(await screen.findByText('No hay productos para mostrar.')).toBeTruthy()
    expect(screen.queryByRole('navigation', { name: 'Pasillos' })).toBeNull()
  })
})

describe('favoritos', () => {
  test('marcar una tienda con ♥ guarda la de la API, con su id y su vertical para volver a abrirla', async () => {
    stubCatalog()
    openStore({ store: GROCERY })
    await screen.findByRole('navigation', { name: 'Pasillos' })
    fireEvent.click(screen.getByRole('button', { name: 'Agregar a favoritos' }))
    expect(JSON.parse(localStorage.getItem('rappi-proto-favorites'))).toEqual([
      expect.objectContaining({ id: 9101, name: 'Supermercado de prueba Centro', vertical: 'grocery' }),
    ])
    expect(screen.getByRole('button', { name: 'Quitar de favoritos' }).getAttribute('aria-pressed')).toBe('true')
  })
})
