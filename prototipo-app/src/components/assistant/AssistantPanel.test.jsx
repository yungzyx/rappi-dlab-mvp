import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, test, vi } from 'vitest'
import { AssistantProvider, useAssistant } from '../../state/AssistantContext'
import { CartProvider } from '../../state/CartContext'
import { DemoProvider } from '../../state/DemoContext'
import { ProductSheetProvider } from '../../state/ProductSheetContext'
import ProductSheet from '../ProductSheet'
import { ProfileProvider } from '../../state/ProfileContext'
import AssistantPanel from './AssistantPanel'
import { routeForScreen } from '../../data/verticals'
import { trackOrder } from '../../api/orders'
import { fixture, stubApi } from '../../test/api'
import { askAbout } from '../../assistant/agentAsk'
import { reloadToHome } from '../../state/reloadApp'

const api = vi.hoisted(() => ({
  health: vi.fn(),
  ask: vi.fn(),
  forget: vi.fn(),
  profile: vi.fn(),
}))
vi.mock('../../api/client', async (importOriginal) => ({ ...(await importOriginal()), ...api }))
const events = vi.hoisted(() => ({ track: vi.fn(), flush: vi.fn(), clear: vi.fn(), settled: vi.fn() }))
vi.mock('../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))

function deferred() {
  let resolve
  const promise = new Promise((res) => (resolve = res))
  return { promise, resolve }
}

const apiAnswer = (text, concept) => ({
  text,
  products: [],
  suggestion: concept
    ? { concept, vertical: 'supermercado', reason: 'Porque sí', question: '¿Algo más?', products: [] }
    : null,
})

const advance = (ms) => act(() => vi.advanceTimersByTimeAsync(ms))
/** Avanza hasta que no quedan temporizadores: "escribiendo…" y el texto letra por letra ya terminaron. */
async function runUntilIdle() {
  await advance(0) // promesas ya resueltas (sin temporizadores pendientes todavía)
  for (let i = 0; i < 100 && vi.getTimerCount() > 0; i++) await advance(250)
}
/** El catálogo de la API: la Home (tiendas populares) y la búsqueda agrupada («xyzzy» y «pizza hawaiana» no traen nada). */
function stubCatalog(routes = {}) {
  return stubApi({
    '/catalog/home': fixture('catalog-home'),
    '/search': (req) =>
      ['xyzzy', 'pizza hawaiana'].includes(req.query.get('q'))
        ? fixture('search-grouped-unmet')
        : fixture('search-grouped'),
    ...routes,
  })
}
/** Un producto de la API en el formato del prototipo, como el que se arrastra a Mochi. */
const BEER = {
  id: 'cat-94001',
  name: 'Cerveza negra botella 330 cc (prueba)',
  price: '$1.990',
  entityType: 'catalog_item',
  entityId: '94001',
  vertical: 'liquor',
  concept: 'cerveza',
}
const tracked = (type) => events.track.mock.calls.filter(([name]) => name === type).map(([, fields]) => fields)
const bubbles = () => [...document.querySelectorAll('.agent-msg-bubble')].map((el) => el.textContent)

/** Sin escribir una pregunta, a Mochi se le pregunta abriéndolo con una consulta (como el aviso del carrito o el seguimiento). */
function say(text) {
  const ask = screen.getByText('preguntar')
  ask.dataset.query = text
  fireEvent.click(ask)
}

/** «Olvidar» y su confirmación: la misma hoja de Cuenta → «Borrar mis datos». */
function clickForget() {
  fireEvent.click(screen.getByText('Olvidar'))
  fireEvent.click(screen.getByText('Sí, borrar'))
}
async function forget() {
  clickForget()
  await runUntilIdle()
}

function OpenButton() {
  const assistant = useAssistant()
  return (
    <>
      <button type="button" onClick={() => assistant.open()}>
        abrir
      </button>
      <button type="button" onClick={() => assistant.open({ search: 'cerveza' })}>
        abrir con búsqueda
      </button>
      <button type="button" onClick={(e) => assistant.open({ query: e.currentTarget.dataset.query })}>
        preguntar
      </button>
      <button type="button" onClick={() => assistant.open({ query: askAbout(BEER), product: BEER })}>
        arrastrar
      </button>
      <button
        type="button"
        onClick={() =>
          assistant.open({
            query: 'Muéstrame algo nuevo para probar',
            offer: { moment: 'vertical_por_probar', context: {} },
          })
        }
      >
        qué puedo probar
      </button>
    </>
  )
}

async function renderPanel({ push = () => {}, vertical, open = null, settle = true } = {}) {
  render(
    <DemoProvider>
      <ProfileProvider>
        <AssistantProvider>
          <CartProvider>
            <ProductSheetProvider>
              <OpenButton />
              <AssistantPanel push={push} vertical={vertical} />
              <ProductSheet />
            </ProductSheetProvider>
          </CartProvider>
        </AssistantProvider>
      </ProfileProvider>
    </DemoProvider>,
  )
  screen.getByText('abrir').focus() // como al tocarlo: el foco queda en quien abrió el asistente
  fireEvent.click(screen.getByText(open ? 'abrir con búsqueda' : 'abrir'))
  if (settle) await runUntilIdle()
}

beforeAll(() => {
  Element.prototype.scrollTo = () => {} // jsdom no lo implementa
})
afterAll(() => {
  delete Element.prototype.scrollTo
})
beforeEach(() => {
  vi.mocked(reloadToHome).mockClear()
  vi.useFakeTimers()
  stubCatalog()
  window.history.replaceState(null, '', '/') // cada test parte sin una entrada del asistente debajo
  api.health.mockResolvedValue({ voz: true, fotos: false })
  api.profile.mockResolvedValue({ interests: [] })
  api.forget.mockResolvedValue({})
  events.settled.mockResolvedValue(undefined)
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
  Object.values(api).forEach((mock) => mock.mockReset())
  localStorage.clear()
  sessionStorage.clear() // cada test es una pestaña nueva (otra sesión)
})

describe('las preguntas al agente van en orden', () => {
  test('las respuestas salen en el orden de las preguntas y la siguiente sabe qué tema ya se sugirió', async () => {
    const first = deferred()
    api.ask.mockReturnValueOnce(first.promise).mockResolvedValueOnce(apiAnswer('Respuesta B'))
    await renderPanel()
    say('pregunta A')
    await advance(10) // cada apertura lleva su hora: con el reloj simulado, dos en el mismo instante serían una
    say('pregunta B')
    await advance(1000)
    expect(api.ask).toHaveBeenCalledTimes(1) // B sale cuando A ya está en pantalla

    first.resolve(apiAnswer('Respuesta A', 'snacks-salados'))
    await runUntilIdle()
    expect(api.ask).toHaveBeenCalledTimes(2)
    expect(api.ask.mock.calls[0][0].message).toBe('pregunta A')
    expect(api.ask.mock.calls[1][0].shown_topics).toEqual(['snacks-salados'])
    // Mochi muestra su última respuesta (no un historial)
    expect(bubbles()).toContain('Respuesta B')
    expect(bubbles()).not.toContain('Respuesta A')
  })
})

describe('sugerencia cruzada', () => {
  test('dice de qué vertical viene y su botón abre esa vertical', async () => {
    const push = vi.fn()
    api.ask.mockResolvedValueOnce({
      text: 'Mira estas hamburguesas',
      products: [],
      suggestion: {
        concept: 'gaseosas',
        vertical: 'licores',
        prototype_vertical: 'liquor',
        reason: 'Porque llevas 🍔 hamburguesa',
        question: '¿Te tinca sumar gaseosas?',
        products: [
          {
            id: 'cat-1',
            entity_type: 'catalog_item',
            entity_id: '1',
            name: 'Bebida Pepsi 1,5 L',
            price: '$1.990',
            store: 'Botillería',
            vertical: 'licores',
            concept: 'gaseosas',
          },
        ],
      },
    })
    await renderPanel({ push })
    say('una hamburguesa')
    await runUntilIdle()

    expect(screen.getByText('De Licores')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Ver más en Licores/ }))
    await runUntilIdle()
    expect(push).toHaveBeenCalledWith('vertical', { id: 'liquor' })
  })

  test('tocar un producto abre su tienda con ese producto: la página registra que lo vio', async () => {
    const push = vi.fn()
    api.ask.mockResolvedValueOnce({
      ...apiAnswer('Mira estas hamburguesas', 'gaseosas'),
      suggestion: {
        ...apiAnswer('', 'gaseosas').suggestion,
        products: [
          {
            id: 'cat-1',
            entity_type: 'catalog_item',
            entity_id: '1',
            name: 'Bebida Pepsi 1,5 L',
            store: 'Botillería',
            store_id: 7, // sin tienda conocida la hoja no ofrece «Ver tienda»
            vertical: 'licores',
          },
        ],
      },
    })
    await renderPanel({ push })
    say('una hamburguesa')
    await runUntilIdle()

    fireEvent.click(screen.getByText('Bebida Pepsi 1,5 L'))
    fireEvent.click(screen.getByRole('button', { name: /Ver tienda/ })) // la tarjeta abre la hoja del producto
    await runUntilIdle()
    expect(push).toHaveBeenCalledWith('store', {
      // La tienda de la API se abre por su id, con la vertical del prototipo; no se busca por nombre en el catálogo local.
      store: { id: 7, name: 'Botillería', vertical: 'liquor' },
      item: expect.objectContaining({ entityId: '1', vertical: 'liquor', backendVertical: 'licores' }),
    })
  })

  test('el «Ver tienda» de un plato abre el menú de su restaurante por id', async () => {
    const push = vi.fn()
    api.ask.mockResolvedValueOnce({
      ...apiAnswer('Mira estas hamburguesas', 'hamburguesa'),
      suggestion: {
        ...apiAnswer('', 'hamburguesa').suggestion,
        products: [
          {
            id: 'menu-5',
            entity_type: 'menu_item',
            entity_id: '5',
            name: 'Hamburguesa clásica',
            store: 'Hamburguesería de prueba',
            store_id: 9803,
            vertical: 'restaurantes',
          },
        ],
      },
    })
    await renderPanel({ push })
    say('una hamburguesa')
    await runUntilIdle()

    fireEvent.click(screen.getByText('Hamburguesa clásica'))
    fireEvent.click(screen.getByRole('button', { name: /Ver tienda/ }))
    await runUntilIdle()
    expect(push).toHaveBeenCalledWith(
      'store',
      expect.objectContaining({
        store: { id: 9803, name: 'Hamburguesería de prueba', vertical: 'restaurants' },
      }),
    )
  })
})

describe('también en otras verticales', () => {
  test('muestra las verticales con sus tiendas (logo o inicial) y cada una abre su vertical', async () => {
    const push = vi.fn()
    api.ask.mockResolvedValueOnce({
      text: 'Mira estas cervezas',
      products: [],
      also_in: {
        concept: 'cerveza',
        label: '🍺 Cerveza',
        verticals: [
          {
            vertical: 'supermercado',
            prototype_vertical: 'grocery',
            items: 262,
            stores: [
              { name: 'Unimarc', logo: 'https://x/u.png' },
              { name: 'Lider', logo: null },
            ],
          },
        ],
      },
    })
    await renderPanel({ push })
    say('cerveza')
    await runUntilIdle()

    expect(screen.getByText('También en')).toBeTruthy()
    const button = screen.getByRole('button', { name: /Súper.*Unimarc · Lider.*262 productos/ })
    expect(button.querySelector('img').getAttribute('src')).toBe('https://x/u.png')
    expect(button.textContent).toContain('L') // Lider sin logo: su inicial
    fireEvent.click(button)
    await runUntilIdle()
    expect(push).toHaveBeenCalledWith('vertical', { id: 'grocery' })
  })
})

describe('teclado y lector de pantalla', () => {
  test('al abrir, el foco entra al buscador (sin abrir el teclado); Escape lo cierra y el foco vuelve a quien lo abrió', async () => {
    await renderPanel()
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Volver' }))

    fireEvent.keyDown(document.activeElement, { key: 'Escape' })
    await runUntilIdle()

    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(screen.getByText('abrir'))
  })

  test('Tab no se sale del asistente', async () => {
    await renderPanel()
    const dialog = screen.getByRole('dialog')
    const focusable = dialog.querySelectorAll('button:not([disabled]), input:not([disabled]):not([hidden])')
    focusable[focusable.length - 1].focus()

    fireEvent.keyDown(document.activeElement, { key: 'Tab' })

    expect(document.activeElement).toBe(focusable[0])
  })

  test('con el panel y la hoja de producto abiertos, Tab llega al segundo control de la hoja y Escape cierra solo la hoja', async () => {
    await renderPanel()
    fireEvent.change(screen.getByLabelText('Buscar en Rappi'), { target: { value: 'cerveza' } })
    await runUntilIdle()
    fireEvent.click(screen.getByText('Cerveza negra botella 330 cc (prueba)')) // la hoja del producto, sobre el panel
    await runUntilIdle()
    const sheet = document.querySelector('.product-sheet')
    const inSheet = [...sheet.querySelectorAll('button:not([disabled]), [href], input:not([disabled])')]
    expect(inSheet.length).toBeGreaterThan(1)
    expect(document.activeElement).toBe(inSheet[0])
    // Tab desde el primer control no se cancela ni lo recoge el panel: el navegador sigue al segundo.
    expect(fireEvent.keyDown(inSheet[0], { key: 'Tab' })).toBe(true)
    inSheet[1].focus()
    expect(sheet.contains(document.activeElement)).toBe(true)

    fireEvent.keyDown(document.activeElement, { key: 'Escape' })
    await runUntilIdle()
    expect(document.querySelector('.product-sheet')).toBeNull()
    expect(screen.getByRole('dialog')).toBeTruthy() // el panel de Mochi sigue abierto
  })

  test('cada respuesta completa se anuncia una vez al lector de pantalla', async () => {
    api.ask.mockResolvedValueOnce(apiAnswer('Mira estas cervezas'))
    await renderPanel()
    say('cerveza')
    await runUntilIdle()

    expect(screen.getByTestId('assistant-announcer').textContent).toBe('Mira estas cervezas')
  })
})

describe('si la pregunta al agente falla', () => {
  test('si ask falla se ve Sin conexión y Reintentar reenvía la pregunta', async () => {
    api.ask.mockRejectedValueOnce(new Error('API caída')).mockResolvedValueOnce(apiAnswer('Desde la API'))
    await renderPanel()
    say('cerveza')
    await runUntilIdle()

    expect(bubbles()).toContain('Sin conexión')
    expect(screen.queryByText('Respuesta local')).toBeNull() // no hay respaldo local
    expect(screen.getByTestId('assistant-announcer').textContent).toBe('Sin conexión')

    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    await runUntilIdle()

    expect(api.ask).toHaveBeenCalledTimes(2)
    expect(api.ask.mock.calls[1][0]).toEqual(api.ask.mock.calls[0][0]) // la misma pregunta, el mismo pedido
    expect(bubbles()).toContain('Desde la API')
    expect(screen.queryByRole('button', { name: 'Reintentar' })).toBeNull()
    expect(screen.getAllByText(/Elegiste/)).toHaveLength(1) // reintentar no es otra pregunta
  })

  test('dos toques en Reintentar piden la respuesta una sola vez', async () => {
    api.ask.mockRejectedValueOnce(new Error('API caída')).mockResolvedValue(apiAnswer('Desde la API'))
    await renderPanel()
    say('cerveza')
    await runUntilIdle()

    const retry = screen.getByRole('button', { name: 'Reintentar' })
    fireEvent.click(retry)
    fireEvent.click(retry)
    await runUntilIdle()

    expect(api.ask).toHaveBeenCalledTimes(2) // la pregunta y un solo reintento
    expect(bubbles().filter((text) => text.includes('Desde la API'))).toHaveLength(1)
  })

  test('Reintentar sigue fallando: vuelve a decir Sin conexión', async () => {
    api.ask.mockRejectedValue(new Error('API caída'))
    await renderPanel()
    say('cerveza')
    await runUntilIdle()
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    await runUntilIdle()

    expect(api.ask).toHaveBeenCalledTimes(2)
    expect(bubbles()).toContain('Sin conexión')
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeTruthy()
  })
})

describe('temas ya sugeridos', () => {
  test('recargar la página no olvida lo ya sugerido en la sesión', async () => {
    api.ask.mockResolvedValueOnce(apiAnswer('Mira estos jugos', 'jugos')).mockResolvedValueOnce(apiAnswer('Ok'))
    await renderPanel()
    say('algo para el desayuno')
    await runUntilIdle()
    cleanup() // recarga: el panel se monta de nuevo y la sesión sigue en sessionStorage
    await renderPanel()
    say('y algo más')
    await runUntilIdle()

    expect(api.ask.mock.calls[1][0].shown_topics).toEqual(['jugos'])
  })
})

const VINO = { concept: 'vino', label: '🍷 Vino' }

describe('lo aprendido y Olvidar', () => {
  test('Aprendiendo de ti usa solo el perfil del servidor', async () => {
    localStorage.setItem('rappi-proto-profile', JSON.stringify({ cerveza: 3 })) // el perfil local ya no cuenta
    api.profile.mockResolvedValue({ interests: [VINO] })
    await renderPanel()
    expect(screen.getByText('Aprendiendo de ti:')).toBeTruthy()
    expect(screen.getByText('🍷 Vino')).toBeTruthy()
    expect(screen.queryByText('🍺 Cerveza')).toBeNull()
    expect(screen.getByText('Olvidar')).toBeTruthy()
  })

  test('Aprendiendo de ti se oculta si el servidor no aprendió nada o no contesta, pero Olvidar sigue ahí', async () => {
    localStorage.setItem('rappi-proto-profile', JSON.stringify({ cerveza: 3 }))
    await renderPanel() // interests: []
    expect(screen.queryByText('Aprendiendo de ti:')).toBeNull()
    // Aunque no haya intereses que mostrar, se enviaron búsquedas y eventos: borrarlos no depende del perfil.
    expect(screen.getByText('Olvidar')).toBeTruthy()

    cleanup()
    api.profile.mockRejectedValue(new Error('API caída'))
    await renderPanel()
    expect(screen.queryByText('Aprendiendo de ti:')).toBeNull()
    expect(screen.queryByText('🍺 Cerveza')).toBeNull()
    expect(screen.getByText('Olvidar')).toBeTruthy()
  })

  test('Olvidar pide la misma confirmación que «Borrar mis datos» y solo borra al confirmar', async () => {
    api.profile.mockResolvedValue({ interests: [VINO] })
    stubCatalog({ '/recommendations': fixture('recommendations') })
    await renderPanel()
    expect(screen.getByText('Gaseosa cola 500 cc (prueba)')).toBeTruthy()
    fireEvent.click(screen.getByText('Olvidar'))
    await runUntilIdle()
    expect(screen.getByRole('dialog', { name: 'Borrar mis datos' })).toBeTruthy()
    expect(screen.getByText(/No se puede deshacer/)).toBeTruthy()
    expect(api.forget).not.toHaveBeenCalled()
    expect(screen.getByText('Gaseosa cola 500 cc (prueba)')).toBeTruthy() // nada se tocó todavía

    fireEvent.click(screen.getByText('Cancelar'))
    await runUntilIdle()
    expect(api.forget).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog', { name: 'Borrar mis datos' })).toBeNull()

    await forget()
    expect(screen.queryByText('Descubre con Mochi')).toBeNull()
    expect(api.forget).toHaveBeenCalledTimes(1)
    expect(reloadToHome).toHaveBeenCalledTimes(1) // la app se recarga en la Home: no queda un mensaje que mostrar
  })

  test('Olvidar espera la pregunta en curso y el lote de eventos antes del DELETE, y mientras no se envía nada', async () => {
    api.profile.mockResolvedValue({ interests: [VINO] })
    const pendingAsk = deferred()
    const pendingFlush = deferred()
    api.ask.mockReturnValueOnce(pendingAsk.promise)
    events.settled.mockReturnValueOnce(pendingFlush.promise)
    await renderPanel()
    say('pregunta A')
    await advance(500) // sale al terminar de abrir
    clickForget()
    await advance(100)
    say('pregunta mientras se olvida')
    await advance(500)
    expect(api.ask).toHaveBeenCalledTimes(1)
    expect(api.forget).not.toHaveBeenCalled()

    pendingAsk.resolve(apiAnswer('Respuesta A'))
    await runUntilIdle()
    expect(events.clear).toHaveBeenCalled() // lo que dejó en cola la respuesta no se envía
    expect(api.forget).not.toHaveBeenCalled() // falta que termine el lote en camino

    pendingFlush.resolve()
    await advance(0)
    expect(api.forget).toHaveBeenCalledTimes(1)
    expect(events.settled.mock.invocationCallOrder[0]).toBeLessThan(api.forget.mock.invocationCallOrder[0])
  })

  test('si el DELETE falla, Olvidar no recarga la app: no se borró nada', async () => {
    api.profile.mockResolvedValue({ interests: [VINO] })
    api.forget.mockRejectedValueOnce(new Error('API caída'))
    await renderPanel()
    clickForget()
    await runUntilIdle()
    expect(reloadToHome).not.toHaveBeenCalled() // no se borró nada: la app sigue como estaba
  })

  test('Olvidar waits for an order in flight', async () => {
    api.profile.mockResolvedValue({ interests: [VINO] })
    const sending = deferred()
    trackOrder(sending.promise)
    await renderPanel()
    clickForget()
    await advance(100)
    expect(api.forget).not.toHaveBeenCalled() // el pedido todavía va en camino

    sending.resolve()
    await runUntilIdle()
    expect(api.forget).toHaveBeenCalledTimes(1)
  })

  test('Olvidar recarga la app en la Home solo si el servidor borró', async () => {
    api.profile.mockResolvedValue({ interests: [VINO] })
    await renderPanel()
    clickForget()
    await runUntilIdle()
    expect(api.forget).toHaveBeenCalledTimes(1)
    expect(reloadToHome).toHaveBeenCalledTimes(1) // borrado todo, la app arranca de cero en la Home
  })

  test('un perfil remoto que llega después de Olvidar no revive lo olvidado', async () => {
    api.profile.mockResolvedValueOnce({ interests: [VINO] })
    await renderPanel()
    fireEvent.click(screen.getByRole('button', { name: 'Volver' }))
    await runUntilIdle()

    const remote = deferred()
    api.profile.mockReturnValueOnce(remote.promise) // al reabrir, esta respuesta queda pendiente
    fireEvent.click(screen.getByText('abrir'))
    await runUntilIdle()
    clickForget()
    remote.resolve({ interests: [{ concept: 'pisco', label: '🍸 Pisco' }] })
    await runUntilIdle()
    expect(screen.queryByText('🍸 Pisco')).toBeNull()
    expect(screen.queryByText('Aprendiendo de ti:')).toBeNull()
  })
})

describe('sin escribir una pregunta', () => {
  test('no hay dónde escribirle a Mochi: se le pide con un toque y se ve lo elegido', async () => {
    api.ask.mockResolvedValueOnce(apiAnswer('Para el carrete'))
    await renderPanel()
    expect(screen.queryByPlaceholderText(/Escríbele/)).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '🍻 Arma un carrete' }))
    await runUntilIdle()
    expect(api.ask.mock.calls[0][0].message).toBe('Arma un carrete')
    expect(screen.getByText('Elegiste «Arma un carrete»')).toBeTruthy()
    expect(bubbles()).toContain('Para el carrete')
  })

  test('lo escrito en el buscador busca en el catálogo de la API (como en «Rappi hoy»), no le pregunta a Mochi', async () => {
    await renderPanel()
    const field = screen.getByLabelText('Buscar en Rappi')
    expect(field.maxLength).toBe(500)
    fireEvent.change(field, { target: { value: 'cerveza' } })
    await runUntilIdle()
    fireEvent.keyDown(field, { key: 'Enter' })

    expect(api.ask).not.toHaveBeenCalled()
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual([
      'Licores',
      'Express',
      'Súper',
    ])
    expect(screen.queryByText('Descubre con Mochi')).toBeNull()
    expect(events.track).toHaveBeenCalledWith(
      'search',
      expect.objectContaining({ query: 'cerveza', modality: 'texto', results: 4, unmet: false }),
    )
  })

  test('abierto desde una categoría, busca de una vez con la vertical de la pantalla', async () => {
    const fetchMock = stubCatalog()
    await renderPanel({ vertical: 'liquor', open: true })
    expect(screen.getByLabelText('Buscar en Rappi').value).toBe('cerveza')
    const url = new URL(fetchMock.mock.calls.map(([u]) => u).find((u) => u.includes('/search')))
    expect(Object.fromEntries(url.searchParams)).toMatchObject({ q: 'cerveza', current: 'liquor' })
    expect(screen.getByRole('heading', { name: 'Licores' })).toBeTruthy()
  })

  test('sin API el buscador de Mochi muestra Sin conexión y Reintentar', async () => {
    let online = false
    stubCatalog({ '/search': () => (online ? fixture('search-grouped') : 'offline') })
    await renderPanel()
    fireEvent.change(screen.getByLabelText('Buscar en Rappi'), { target: { value: 'cerveza' } })
    await runUntilIdle()
    expect(screen.getByText('Sin conexión')).toBeTruthy()

    online = true
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    await runUntilIdle()
    expect(screen.queryByText('Sin conexión')).toBeNull()
    expect(screen.getByRole('heading', { name: 'Licores' })).toBeTruthy()
  })
})

describe('preguntarle a Mochi desde el buscador', () => {
  const QUESTION = '¿qué llevo para un asado de 6?'

  test('el campo invita a preguntar y lo escrito trae primero «Pregúntale a Mochi»', async () => {
    await renderPanel()
    const field = screen.getByLabelText('Buscar en Rappi')
    expect(field.placeholder).toBe('Busca o pregúntale a Mochi')
    fireEvent.change(field, { target: { value: 'cerveza' } })
    await runUntilIdle()
    const row = screen.getByRole('button', { name: 'Pregúntale a Mochi: «cerveza»' })
    // Antes que los resultados de la búsqueda, y sin resaltar: «cerveza» es un producto.
    expect(row.compareDocumentPosition(screen.getByRole('heading', { name: 'Licores' }))).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    )
    expect(row.classList.contains('is-question')).toBe(false)
  })

  test('con un error de tipeo corregido, conviven «Pregúntale a Mochi» y «Mostrando resultados para…»', async () => {
    stubCatalog({ '/search': fixture('search-grouped-corrected') })
    await renderPanel()
    fireEvent.change(screen.getByLabelText('Buscar en Rappi'), { target: { value: 'cervezaaaa' } })
    await runUntilIdle()
    const row = screen.getByRole('button', { name: 'Pregúntale a Mochi: «cervezaaaa»' })
    const notice = screen.getByText(/^Mostrando resultados para «cerveza»/)
    expect(row.compareDocumentPosition(notice)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  })

  test('una pregunta va resaltada y Enter se la pregunta a Mochi, no la busca', async () => {
    api.ask.mockResolvedValueOnce(apiAnswer('Mira estas opciones de asado 🔥 en el súper.'))
    await renderPanel()
    const field = screen.getByLabelText('Buscar en Rappi')
    fireEvent.change(field, { target: { value: QUESTION } })
    await runUntilIdle()
    expect(screen.getByRole('button', { name: `Pregúntale a Mochi: «${QUESTION}»` }).classList).toContain('is-question')

    fireEvent.keyDown(field, { key: 'Enter' })
    await runUntilIdle()
    expect(api.ask.mock.calls[0][0].message).toBe(QUESTION)
    expect(field.value).toBe('')
    expect(screen.getByText(`Preguntaste «${QUESTION}»`)).toBeTruthy()
    expect(bubbles()).toContain('Mira estas opciones de asado 🔥 en el súper.')
    expect(tracked('search')).toEqual([]) // es una pregunta a Mochi, no una búsqueda
  })

  test('la fila resaltada dice que Enter pregunta, también al lector de pantalla; sin resaltar, no', async () => {
    await renderPanel()
    const field = screen.getByLabelText('Buscar en Rappi')
    fireEvent.change(field, { target: { value: QUESTION } })
    await runUntilIdle()
    expect(screen.getByText('Enter')).toBeTruthy()
    expect(document.getElementById(field.getAttribute('aria-describedby')).textContent).toBe(
      'Enter le pregunta a Mochi',
    )
    fireEvent.change(field, { target: { value: 'cerveza' } })
    await runUntilIdle()
    expect(screen.queryByText('Enter')).toBeNull()
    expect(field.getAttribute('aria-describedby')).toBeNull()
  })

  test('pasar con Tab a la fila no registra la búsqueda', async () => {
    await renderPanel()
    const field = screen.getByLabelText('Buscar en Rappi')
    fireEvent.change(field, { target: { value: QUESTION } })
    await runUntilIdle()
    const row = screen.getByRole('button', { name: `Pregúntale a Mochi: «${QUESTION}»` })
    fireEvent.blur(field, { relatedTarget: row })
    await runUntilIdle()
    expect(tracked('search')).toEqual([])
  })

  test('bajo una respuesta de salud no salen las ideas de siempre («Arma un carrete»)', async () => {
    api.ask.mockResolvedValueOnce({ ...apiAnswer('No puedo decirte qué remedio tomar…'), intent: { symptom: true } })
    await renderPanel()
    const field = screen.getByLabelText('Buscar en Rappi')
    fireEvent.change(field, { target: { value: 'mi hijo tiene fiebre, ¿qué le doy?' } })
    await runUntilIdle()
    fireEvent.keyDown(field, { key: 'Enter' })
    await runUntilIdle()
    expect(bubbles()).toContain('No puedo decirte qué remedio tomar…')
    expect(screen.queryByRole('button', { name: '🍻 Arma un carrete' })).toBeNull()
  })

  test('tocar «Pregúntale a Mochi» pregunta aunque lo escrito sea un producto', async () => {
    api.ask.mockResolvedValueOnce(apiAnswer('Mira estas cervezas'))
    await renderPanel()
    const field = screen.getByLabelText('Buscar en Rappi')
    fireEvent.change(field, { target: { value: 'cerveza' } })
    await runUntilIdle()
    fireEvent.click(screen.getByRole('button', { name: 'Pregúntale a Mochi: «cerveza»' }))
    await runUntilIdle()
    expect(api.ask.mock.calls[0][0].message).toBe('cerveza')
    expect(screen.getByText('Preguntaste «cerveza»')).toBeTruthy()
    expect(tracked('search')).toEqual([])
  })
})

describe('sin resultados', () => {
  const type = async (text) => {
    fireEvent.change(screen.getByLabelText('Buscar en Rappi'), { target: { value: text } })
    await runUntilIdle()
  }

  test('sin resultados, Mochi ofrece la vertical que sí lo tiene', async () => {
    stubCatalog({ 'POST /agent/offer': fixture('agent-offer-sin-resultado') })
    const push = vi.fn()
    await renderPanel({ push })
    await type('pizza hawaiana')
    expect(screen.getByText('No encontré «pizza hawaiana», pero pizza sí hay en restaurantes.')).toBeTruthy()
    expect(document.querySelector('.search-agent .mascot')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Ver en Restaurantes' }))
    expect(push.mock.calls[0][0]).toBe(routeForScreen('restaurants')[0])
  })

  test('sin una oferta (204), Mochi lo dice y ofrece otra búsqueda', async () => {
    stubCatalog({ 'POST /agent/offer': 204 })
    await renderPanel()
    await type('xyzzy')
    expect(screen.getByText('No encontré «xyzzy». ¿Lo buscamos con otras palabras?')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Probar otra búsqueda' }))
    const field = screen.getByLabelText('Buscar en Rappi')
    expect(field.value).toBe('')
    expect(document.activeElement).toBe(field)
  })
})

describe('Para ti y Descubre con Mochi', () => {
  // Concepto propio de este test: lo mostrado se recuerda en la pestaña y otros tests usan la fila de ejemplo tal cual.
  const rows = () => {
    const data = fixture('recommendations')
    data.rows[0].concept = 'jugos'
    data.rows[0].products[0].concept = 'jugos'
    return data
  }

  test('Para ti sale de recommendations y se cuenta como mostrado una vez', async () => {
    const fetchMock = stubCatalog({ '/recommendations': rows() })
    await renderPanel()

    expect(bubbles()[0]).toBe('¡Hola! Soy Mochi, tu asistente de compras 🧡 ¿Qué se te antoja hoy?')
    expect(screen.getByText('Gaseosa cola 500 cc (prueba)')).toBeTruthy()
    expect(document.querySelector('.agent-msg-reason').textContent).toBe('Por tu interés en 🍕 pizza')
    // Una sola petición sirve a «Para ti» y a «Descubre con Mochi».
    expect(fetchMock.mock.calls.filter(([url]) => url.includes('/recommendations'))).toHaveLength(1)
    const shown = tracked('suggestion_shown').filter((fields) => fields.payload.origen === 'para-ti')
    expect(shown).toEqual([{ concept_id: 'jugos', vertical: 'express', payload: { origen: 'para-ti' } }])

    // Cerrar y volver a abrir (o recargar la pantalla) no la cuenta otra vez.
    cleanup()
    stubCatalog({ '/recommendations': rows() })
    await renderPanel()
    expect(screen.getByText('Gaseosa cola 500 cc (prueba)')).toBeTruthy()
    expect(tracked('suggestion_shown').filter((fields) => fields.payload.origen === 'para-ti')).toHaveLength(1)
  })

  test('la fila «Lo más pedido» de Para ti se cuenta como mostrada con su tipo', async () => {
    const data = fixture('recommendations')
    data.rows = data.rows.filter((row) => row.kind === 'lo_mas_pedido')
    stubCatalog({ '/recommendations': data })
    await renderPanel()

    expect(document.querySelector('.agent-msg-reason').textContent).toBe('Lo más pedido estas semanas en el súper')
    const shown = tracked('suggestion_shown').filter((fields) => fields.payload.origen === 'para-ti')
    expect(shown).toEqual([
      { concept_id: 'cafe', vertical: 'grocery', payload: { origen: 'para-ti', kind: 'lo_mas_pedido' } },
    ])
  })

  test('lo que se agrega desde Para ti se cuenta como aceptado con ese origen', async () => {
    stubCatalog({ '/recommendations': rows() })
    await renderPanel()
    fireEvent.click(screen.getByLabelText('Agregar Gaseosa cola 500 cc (prueba)'))
    expect(tracked('suggestion_accepted')).toContainEqual(
      expect.objectContaining({ concept_id: 'jugos', payload: { origen: 'para-ti' } }),
    )
  })

  test('Para ti se oculta si recommendations viene vacío o falla', async () => {
    stubCatalog({ '/recommendations': { user_id: 'u', interests: [], rows: [] } })
    await renderPanel()
    expect(bubbles()[0]).toBe('¡Hola! Soy Mochi, tu asistente de compras 🧡 ¿Qué se te antoja hoy?')
    expect(document.querySelector('.agent-msg-products')).toBeNull()
    expect(screen.queryByText('Descubre con Mochi')).toBeNull()

    cleanup()
    stubCatalog({ '/recommendations': 'offline' })
    await renderPanel()
    expect(bubbles().at(-1)).toMatch(/Soy Mochi/)
    expect(document.querySelector('.agent-msg-products')).toBeNull()
    expect(screen.queryByText('Descubre con Mochi')).toBeNull()
    expect(tracked('suggestion_shown')).toEqual([])
  })

  test('Descubre con Mochi muestra hasta 3 filas y cada tarjeta abre su vertical', async () => {
    const data = fixture('recommendations')
    const [row] = data.rows
    data.rows = [
      row,
      {
        ...row,
        concept: 'helados',
        prototype_vertical: 'grocery',
        vertical: 'supermercado',
        reason: 'Por tu interés en 🍫 chocolate',
      },
      { ...row, concept: 'snacks-salados', prototype_vertical: 'liquor', vertical: 'licores' },
      { ...row, concept: 'jugos', prototype_vertical: 'restaurants', vertical: 'restaurantes' },
    ]
    stubCatalog({ '/recommendations': data })
    const push = vi.fn()
    await renderPanel({ push })

    const cards = document.querySelectorAll('.discover-card')
    expect(cards).toHaveLength(3)
    expect(cards[0].textContent).toContain('Gaseosas en Express')
    expect(cards[1].textContent).toContain('Helados en Súper')
    fireEvent.click(cards[1])
    await runUntilIdle()
    expect(push).toHaveBeenCalledWith(...routeForScreen('grocery'))
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

describe('¿Con qué acompaño…?', () => {
  const dropBeer = async () => {
    fireEvent.click(screen.getByText('arrastrar'))
    await runUntilIdle()
  }

  test('arrastrar un producto a Mochi muestra su complemento de la API', async () => {
    const fetchMock = stubCatalog({ 'POST /agent/offer': fixture('agent-offer-carrito') })
    await renderPanel()
    await dropBeer()

    expect(api.ask).not.toHaveBeenCalled()
    const call = fetchMock.mock.calls.find(([url]) => url.includes('/agent/offer'))
    expect(JSON.parse(call[1].body)).toMatchObject({
      moment: 'carrito',
      context: { product: { entity_type: 'catalog_item', entity_id: '94001' } },
    })
    expect(screen.getByText(`Elegiste «${askAbout(BEER)}»`)).toBeTruthy()
    expect(bubbles()).toContain('Para completar tu pedido: snacks salados, en Express.')
    fireEvent.click(screen.getByLabelText('Agregar Papas fritas clásicas 180 g (prueba)'))
    expect(tracked('suggestion_accepted')).toContainEqual(
      expect.objectContaining({ concept_id: 'snacks-salados', payload: { origen: 'agent-carrito' } }),
    )
  })

  test('the offer has ¿Por qué?', async () => {
    stubCatalog({ 'POST /agent/offer': fixture('agent-offer-carrito') })
    await renderPanel()
    await dropBeer()
    await runUntilIdle()
    fireEvent.click(screen.getByRole('button', { name: '¿Por qué?' }))
    expect(screen.getByText(fixture('agent-offer-carrito').reason.text)).toBeTruthy()
  })

  test('sin una oferta (204), Mochi dice que no se le ocurre nada', async () => {
    stubCatalog({ 'POST /agent/offer': 204 })
    await renderPanel()
    await dropBeer()
    expect(bubbles()).toContain('No se me ocurre nada para acompañar eso')
  })

  test('si la API no contesta, Sin conexión y Reintentar vuelve a pedir la oferta', async () => {
    let online = false
    stubCatalog({ 'POST /agent/offer': () => (online ? fixture('agent-offer-carrito') : 'offline') })
    await renderPanel()
    await dropBeer()
    expect(bubbles()).toContain('Sin conexión')

    online = true
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    await runUntilIdle()
    expect(bubbles()).toContain('Para completar tu pedido: snacks salados, en Express.')
  })
})

describe('«¿Qué puedo probar?» (una oferta pedida desde fuera)', () => {
  const askToTry = async () => {
    fireEvent.click(screen.getByText('qué puedo probar'))
    await runUntilIdle()
  }

  test('muestra la vertical por probar de la API, sin pasar por una pregunta al agente', async () => {
    const push = vi.fn()
    const fetchMock = stubCatalog({ 'POST /agent/offer': fixture('agent-offer-vertical-por-probar') })
    await renderPanel({ push })
    await askToTry()

    expect(api.ask).not.toHaveBeenCalled()
    const call = fetchMock.mock.calls.find(([url]) => url.includes('/agent/offer'))
    expect(JSON.parse(call[1].body)).toMatchObject({ moment: 'vertical_por_probar', context: {} })
    expect(screen.getByText('Elegiste «Muéstrame algo nuevo para probar»')).toBeTruthy()
    const made = fixture('agent-offer-vertical-por-probar')
    expect(bubbles()).toContain(made.text)
    fireEvent.click(screen.getByRole('button', { name: new RegExp('^' + made.actions[0].label) }))
    expect(push).toHaveBeenCalledWith(...routeForScreen(made.actions[0].route[0]))
  })

  test('el paso a RappiFavor no trae productos: su texto, su acción a su pantalla y el servicio ofrecido y abierto', async () => {
    const push = vi.fn()
    const made = fixture('agent-offer-vertical-por-probar-servicio')
    stubCatalog({ 'POST /agent/offer': made })
    await renderPanel({ push })
    await askToTry()

    expect(made.products).toEqual([])
    expect(bubbles()).toContain(made.text)
    expect(tracked('service_shown')).toEqual([{ payload: { servicio: 'rappifavor' } }])
    fireEvent.click(screen.getByRole('button', { name: /^Abrir RappiFavor/ }))
    expect(tracked('service_opened')).toEqual([{ payload: { servicio: 'rappifavor' } }])
    expect(push).toHaveBeenCalledWith('favor', undefined)
  })

  test('sin una oferta (204) lo dice, y si la API no contesta, Sin conexión y Reintentar', async () => {
    let online = false
    stubCatalog({
      'POST /agent/offer': () => (online ? 204 : 'offline'),
    })
    await renderPanel()
    await askToTry()
    expect(bubbles()).toContain('Sin conexión')

    online = true
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    await runUntilIdle()
    expect(bubbles()).toContain('No se me ocurre nada nuevo para probar')
  })
})

describe('servicios sin catálogo', () => {
  test('RappiTravel queda registrado como ofrecido y abierto, y su gancho con su origen', async () => {
    const push = vi.fn()
    api.ask.mockResolvedValueOnce({
      text: 'Para eso está ✈️ RappiTravel',
      products: [],
      service: 'rappitravel',
      actions: [{ label: 'Abrir RappiTravel', route: ['travel'], service: 'rappitravel' }],
      suggestion: {
        concept: 'dermocosmetica',
        vertical: 'farmacia',
        reason: 'Para tu viaje ✈️',
        question: '¿Llevas protector solar?',
        products: [],
      },
    })
    await renderPanel({ push })
    say('me voy de vacaciones')
    await runUntilIdle()

    expect(tracked('service_shown')).toEqual([{ payload: { servicio: 'rappitravel' } }])
    expect(tracked('suggestion_shown')).toContainEqual({
      concept_id: 'dermocosmetica',
      vertical: 'farmacia',
      payload: { origen: 'rappitravel' },
    })

    fireEvent.click(screen.getByText('Abrir RappiTravel →'))
    await runUntilIdle()
    expect(tracked('service_opened')).toEqual([{ payload: { servicio: 'rappitravel' } }])
    expect(push).toHaveBeenCalledWith('travel', undefined)
  })
})

describe('sugerencias mostradas', () => {
  test('la misma sugerencia mostrada dos veces en la pestaña cuenta una sola vez para el panel', async () => {
    api.ask.mockResolvedValue(apiAnswer('Aquí tienes cervezas', 'helados'))
    await renderPanel()
    say('cerveza')
    await runUntilIdle()
    say('otra cerveza')
    await runUntilIdle()
    const shown = events.track.mock.calls.filter(
      ([name, f]) => name === 'suggestion_shown' && f.concept_id === 'helados',
    )
    expect(shown).toHaveLength(1)
  })
})

describe('aceptar una sugerencia de la API', () => {
  test('la pregunta y el «+» cuentan la mostrada una sola vez, aunque la vertical llegue como código del backend y como id del prototipo', async () => {
    api.ask.mockResolvedValueOnce({
      text: 'Mira estas hamburguesas',
      products: [],
      suggestion: {
        // Concepto propio de este test: lo mostrado se recuerda en la pestaña y otros tests ya usaron «gaseosas».
        concept: 'jugos',
        vertical: 'licores', // el código del backend, como lo deja toMessage en la sugerencia
        prototype_vertical: 'liquor',
        reason: 'Porque llevas 🍔 hamburguesa',
        question: '¿Te tinca sumar jugos?',
        products: [
          {
            id: 'cat-1',
            entity_type: 'catalog_item',
            entity_id: '1',
            name: 'Jugo de naranja 1 L',
            price: '$1.990',
            store: 'Botillería',
            vertical: 'licores',
            concept: 'jugos',
          },
        ],
      },
    })
    await renderPanel()
    say('una hamburguesa')
    await runUntilIdle()

    fireEvent.click(screen.getByLabelText('Agregar Jugo de naranja 1 L'))
    expect(tracked('suggestion_shown')).toHaveLength(1)
    expect(tracked('suggestion_accepted')).toHaveLength(1)
    expect(tracked('suggestion_accepted')[0]).toMatchObject({ concept_id: 'jugos', payload: { origen: 'agent-ask' } })
  })
})

describe('conversación', () => {
  test('el mensaje siguiente lleva el pedido anterior: «más barata» se lee sobre «cerveza»', async () => {
    api.ask.mockResolvedValueOnce({
      text: 'Mira estas cervezas',
      vertical: 'licores',
      intent: { query: 'cerveza', concepts: ['cerveza'] },
      products: [{ id: 'cat-1', entity_type: 'catalog_item', entity_id: '1', name: 'Escudo', price: '$1.290' }],
    })
    api.ask.mockResolvedValueOnce({ text: 'Las más baratas', products: [] })
    await renderPanel()
    say('cerveza')
    await runUntilIdle()
    say('más barata')
    await runUntilIdle()

    expect(api.ask.mock.calls[0][0].previous).toBeUndefined()
    expect(api.ask.mock.calls[1][0].previous).toEqual({
      query: 'cerveza',
      concepts: ['cerveza'],
      vertical: 'licores',
      product_ids: ['1'],
    })
  })
})

describe('volver a Mochi desde una tienda', () => {
  test('abrir una tienda apila la pantalla y, al volver, el panel se reabre con la búsqueda que tenía', async () => {
    const push = vi.fn()
    await renderPanel({ push })
    const assistantEntry = window.history.state
    expect(assistantEntry.assistant).toBe(true)

    const input = screen.getByLabelText('Buscar en Rappi')
    fireEvent.change(input, { target: { value: 'cerveza' } })
    await runUntilIdle()
    fireEvent.click(screen.getByText('Cerveza negra botella 330 cc (prueba)')) // la hoja del producto
    fireEvent.click(document.querySelector('.product-sheet-store')) // «Ver tienda»
    expect(push).toHaveBeenCalledWith(
      'store',
      expect.objectContaining({ store: expect.objectContaining({ id: 9401 }), item: expect.anything() }),
    )
    // La entrada del asistente sigue en el historial, con su búsqueda; la tienda se apila encima (sin replace).
    expect(window.history.state).toMatchObject({ assistant: true, assistantSearch: 'cerveza' })
    await runUntilIdle()
    expect(screen.queryByRole('dialog')).toBeNull()

    // Gesto volver desde la tienda: el navegador vuelve a la entrada del asistente.
    act(() => window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state })))
    await runUntilIdle()
    expect(screen.getByRole('dialog')).toBeTruthy()
    expect(screen.getByLabelText('Buscar en Rappi').value).toBe('cerveza')
  })
})

describe('barra del carrito dentro del panel', () => {
  test('con productos en el carro el panel deja espacio abajo para la barra', async () => {
    await renderPanel()
    expect(document.querySelector('.assistant.has-cart')).toBeNull()
    fireEvent.change(screen.getByLabelText('Buscar en Rappi'), { target: { value: 'cerveza' } })
    await runUntilIdle()
    fireEvent.click(screen.getAllByLabelText(/^Agregar /)[0])
    expect(document.querySelector('.assistant.has-cart')).toBeTruthy()
  })
})

// Lo de abajo del saludo no debe moverse mientras el panel carga (los «escribiendo…» miden menos que el saludo y su
// «Para ti»): espera sin verse hasta el saludo y aparece con él, ya en su lugar.
describe('al abrir, nada se mueve', () => {
  test('hasta el saludo, lo de abajo de «escribiendo…» espera sin verse y aparece con él', async () => {
    stubCatalog({ '/recommendations': { slow: 1000, body: fixture('recommendations') } })
    await renderPanel({ settle: false })
    await advance(600)
    const panel = screen.getByRole('dialog')
    expect(document.querySelector('.agent-msg-typing')).toBeTruthy()
    expect(panel.classList.contains('is-waiting')).toBe(true)

    await runUntilIdle()
    expect(bubbles()[0]).toMatch(/Soy Mochi/)
    expect(panel.classList.contains('is-waiting')).toBe(false)
  })

  test('los resultados de una búsqueda no esperan el saludo', async () => {
    stubCatalog({ '/recommendations': { slow: 1000, body: fixture('recommendations') } })
    await renderPanel({ open: 'búsqueda', settle: false })
    await advance(100)
    expect(document.querySelector('.agent-msg-typing')).toBeNull() // con búsqueda no se ve la franja de Mochi
    expect(screen.getByRole('dialog').classList.contains('is-waiting')).toBe(false)
  })

  test('el saludo espera también lo aprendido: «Aprendiendo de ti» aparece con él', async () => {
    api.profile.mockReturnValue(
      new Promise((resolve) =>
        setTimeout(() => resolve({ interests: [{ concept: 'pizza', label: '🍕 Pizza' }] }), 1500),
      ),
    )
    await renderPanel({ settle: false })
    await advance(1000)
    expect(document.querySelector('.agent-msg-typing')).toBeTruthy()
    expect(screen.getByRole('dialog').classList.contains('is-waiting')).toBe(true)

    await runUntilIdle()
    expect(bubbles()[0]).toMatch(/Soy Mochi/)
    expect(screen.getByText('🍕 Pizza')).toBeTruthy()
    expect(screen.getByRole('dialog').classList.contains('is-waiting')).toBe(false)
  })

  test('si lo aprendido tarda más que el tope, el saludo sale igual con «Para ti» si ya llegó', async () => {
    const data = fixture('recommendations')
    data.rows = data.rows.slice(0, 1)
    data.rows[0].concept = 'jugos-tope' // propio: lo mostrado se recuerda en la pestaña
    stubCatalog({ '/recommendations': data })
    api.profile.mockReturnValue(new Promise((resolve) => setTimeout(() => resolve({ interests: [] }), 8000)))
    await renderPanel({ settle: false })
    for (let ms = 0; ms < 5000; ms += 250) await advance(250) // el tope del saludo son 3 s; después se escribe
    expect(bubbles()[0]).toMatch(/Soy Mochi/)
    expect(document.querySelector('.agent-msg-products')).not.toBeNull()
    expect(screen.getByRole('dialog').classList.contains('is-waiting')).toBe(false)
  })

  test('el saludo espera también el perfil de gusto: el perfil y su escalera aparecen con él', async () => {
    // Conceptos propios: lo mostrado se recuerda en la pestaña y los tests del perfil cuentan los de la fixture.
    const ladder = fixture('agent-offer-perfil')
    for (const step of ladder.escalera)
      for (const product of step.products) product.concept = `${product.concept}-espera`
    stubCatalog({
      'GET /profile/*': fixture('profile-gustos'),
      'POST /agent/offer': (req) => (req.body.moment === 'perfil' ? { slow: 1500, body: ladder } : 204),
    })
    await renderPanel({ settle: false })
    await advance(1000)
    expect(document.querySelector('.agent-msg-typing')).toBeTruthy()
    expect(screen.getByRole('dialog').classList.contains('is-waiting')).toBe(true)

    await runUntilIdle()
    expect(bubbles()[0]).toMatch(/Soy Mochi/)
    expect(screen.getByRole('region', { name: 'Tu perfil' })).toBeTruthy()
    expect(screen.getByRole('region', { name: 'Para ti en otras verticales' })).toBeTruthy()
    expect(screen.getByRole('dialog').classList.contains('is-waiting')).toBe(false)
  })
})

describe('perfil de gusto', () => {
  const offers = () => tracked('suggestion_shown').filter((fields) => fields.payload.origen === 'agent-perfil')

  test('con un perfil activo, muestra el perfil, su escalera de verticales con productos y la idea para RappiTravel', async () => {
    const push = vi.fn()
    const fetchMock = stubCatalog({
      'GET /profile/*': fixture('profile-gustos'),
      'POST /agent/offer': (req) => (req.body.moment === 'perfil' ? fixture('agent-offer-perfil') : 204),
    })
    await renderPanel({ push })

    const card = screen.getByRole('region', { name: 'Tu perfil' })
    expect(card.textContent).toContain('Amante de lo asiático')
    expect(card.textContent).toContain('Nivel medio')
    expect(card.textContent).toContain('Pediste 🍣 sushi 2 veces')
    // Pide la escalera del perfil principal, como esta persona.
    const asked = fetchMock.mock.calls.find(
      ([url, init]) => url.endsWith('/agent/offer') && init.body.includes('perfil'),
    )
    expect(JSON.parse(asked[1].body)).toMatchObject({ moment: 'perfil', context: { perfil: 'asiatico' } })

    const ladder = screen.getByRole('region', { name: 'Para ti en otras verticales' })
    const steps = [...ladder.querySelectorAll('.taste-step')].map((step) => step.getAttribute('aria-label'))
    expect(steps).toEqual([
      '1. Restaurantes',
      '2. Turbo',
      '3. Express',
      '4. Súper',
      '5. Chocolatería',
      '6. RappiTravel',
    ])
    expect(ladder.textContent).toContain('Roll salmón palta 10 piezas (prueba)')
    expect(ladder.textContent).toContain('Idea para RappiTravel')
    expect(ladder.textContent).toContain('¿Y si un día vas a Japón?')
    // Cada peldaño cuenta como sugerencia mostrada de Mochi.
    expect(offers().map((fields) => fields.concept_id)).toEqual([
      'sushi',
      'despensa-asiatica',
      'snacks-asiaticos',
      'bebidas-asiaticas',
      'chocolates',
    ])

    fireEvent.click(screen.getByText('Ver Súper ›'))
    await runUntilIdle()
    expect(push).toHaveBeenCalledWith(...routeForScreen('grocery'))
  })

  test('«Olvidar» quita el perfil del panel', async () => {
    stubCatalog({
      'GET /profile/*': fixture('profile-gustos'),
      'POST /agent/offer': (req) => (req.body.moment === 'perfil' ? fixture('agent-offer-perfil') : 204),
    })
    await renderPanel()
    expect(screen.getByRole('region', { name: 'Tu perfil' })).toBeTruthy()
    await forget()
    expect(screen.queryByRole('region', { name: 'Tu perfil' })).toBeNull()
    expect(screen.queryByText('Para ti en otras verticales')).toBeNull()
  })

  test('sin perfil activo, el panel queda como siempre', async () => {
    const fetchMock = stubCatalog({ 'GET /profile/*': { perfiles: [] } })
    await renderPanel()
    expect(screen.queryByRole('region', { name: 'Tu perfil' })).toBeNull()
    expect(screen.queryByText('Para ti en otras verticales')).toBeNull()
    expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/agent/offer'))).toBe(false)
    expect(offers()).toEqual([])
  })

  test('si la API no responde los gustos, tampoco hay perfil', async () => {
    stubCatalog({ 'GET /profile/*': 'offline' })
    await renderPanel()
    expect(screen.queryByRole('region', { name: 'Tu perfil' })).toBeNull()
  })
})
