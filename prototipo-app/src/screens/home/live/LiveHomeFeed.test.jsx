import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from '../../../test/api'
import { routeForScreen } from '../../../data/verticals'
import { today } from '../../../utils/today'

const events = vi.hoisted(() => ({ track: vi.fn(), flush: async () => {}, clear: () => {}, settled: async () => {} }))
vi.mock('../../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))

// La memoria de la escena vive en el módulo (lo que dura la pestaña): cada test, una pestaña nueva.
let HomeScreen
let useOrders
let useProfile
let Providers
let memory
let useAssistant
let api // el fetch simulado de cada test (las llamadas a la API)
beforeEach(async () => {
  events.track.mockClear()
  vi.resetModules()
  localStorage.setItem('rappi-proto-demo-mode', 'final')
  localStorage.setItem('rappi-proto-guia-vista', '1') // como quien ya vio la guía (sus tests la quitan)
  await import('../../../state/EventsContext')
  const demo = await import('../../../state/DemoContext')
  const profile = await import('../../../state/ProfileContext')
  const assistant = await import('../../../state/AssistantContext')
  const cart = await import('../../../state/CartContext')
  const address = await import('../../../state/AddressContext')
  const toast = await import('../../../components/Toast')
  const orders = await import('../../../state/OrdersContext')
  useOrders = orders.useOrders
  useProfile = profile.useProfile
  memory = await import('../../../state/liveMemory')
  useAssistant = assistant.useAssistant
  HomeScreen = (await import('../HomeScreen')).default
  Providers = function Providers({ children }) {
    return (
      <demo.DemoProvider>
        <profile.ProfileProvider>
          <assistant.AssistantProvider>
            <cart.CartProvider>
              <address.AddressProvider>
                <toast.ToastProvider>
                  <orders.OrdersProvider>{children}</orders.OrdersProvider>
                </toast.ToastProvider>
              </address.AddressProvider>
            </cart.CartProvider>
          </assistant.AssistantProvider>
        </profile.ProfileProvider>
      </demo.DemoProvider>
    )
  }
  // A mediodía: «en silencio por hoy» guarda la fecha y los tests adelantan el reloj; con la hora real, un test que
  // partía justo antes de la medianoche terminaba en otro día.
  vi.useFakeTimers({ now: new Date(2026, 9, 21, 12) })
  // La Home pide su catálogo a la API (sin respuestas, esas secciones no se ven) y a Mochi sus ocasiones y ofertas.
  api = stubAgent()
})

// Una oferta por momento, con los ejemplos del contrato; los momentos sin ejemplo responden 204.
const OFFER_FIXTURES = {
  plan: 'agent-offer-plan',
  carrito: 'agent-offer-carrito',
  vertical_por_probar: 'agent-offer-vertical-por-probar',
}
// Lo que dice Mochi al tocarlo: la burbuja no lleva productos, así que no promete «mira estas ofertas» como el texto de la API.
const POKE_LINE = '¿Y si pruebas algo de Súper?'
const stubAgent = (routes = {}) =>
  stubApi({
    '/agent/plans': fixture('agent-plans'),
    'POST /agent/offer': (req) => (OFFER_FIXTURES[req.body.moment] ? fixture(OFFER_FIXTURES[req.body.moment]) : 204),
    ...routes,
  })
const allOfferRequests = (mock = api) =>
  mock.mock.calls.filter(([url]) => url.endsWith('/agent/offer')).map(([, init]) => JSON.parse(init.body))
// La recompra (y, sin ella, «¿Volvemos a…?») se pide sola cada vez que la Home está arriba: sus tests la miran con
// `repeatRequests` y `winbackRequests`.
const SLOT_MOMENTS = ['recompra', 'volver']
const offerRequests = (mock = api) => allOfferRequests(mock).filter((body) => !SLOT_MOMENTS.includes(body.moment))
const repeatRequests = (mock = api) => allOfferRequests(mock).filter((body) => body.moment === 'recompra')
const winbackRequests = (mock = api) => allOfferRequests(mock).filter((body) => body.moment === 'volver')
// Con una recompra o un «¿Volvemos a…?» que ofrecer (los demás momentos, como siempre).
const stubSlot = (slot) =>
  stubAgent({
    'POST /agent/offer': (req) => {
      const name = slot[req.body.moment] ?? OFFER_FIXTURES[req.body.moment]
      return name ? fixture(name) : 204
    },
  })
const stubRepeat = () => stubSlot({ recompra: 'agent-offer-recompra' })
const stubWinback = (slot = {}) => stubSlot({ volver: 'agent-offer-volver', ...slot })
const LOOSE_CART = {
  id: 'cat-94001',
  name: 'Cerveza rubia lata 470 cc (prueba)',
  vertical: 'liquor',
  entityType: 'catalog_item',
  entityId: '94001',
}
const tracked = (type, origin) =>
  events.track.mock.calls.filter(([name, fields]) => name === type && fields.payload?.origen === origin)

beforeAll(() => {
  Element.prototype.scrollTo = () => {} // jsdom no implementa scroll ni animaciones
  Element.prototype.animate = () => ({ cancel() {} })
})
afterAll(() => {
  delete Element.prototype.scrollTo
  delete Element.prototype.animate
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  localStorage.clear()
})

const homeTree = ({ tab = 'home', push = vi.fn(), active = true } = {}) => (
  <Providers>
    <div className="phone">
      <div className="screen-wrap">
        <HomeScreen push={push} tab={tab} setTab={vi.fn()} active={active} />
      </div>
    </div>
  </Providers>
)
const renderHome = async (options) => render(homeTree(options))
// De a 100 ms, como en un navegador: entre paso y paso React aplica sus efectos (la máquina de escribir, por ejemplo).
const advance = async (ms) => {
  for (let elapsed = 0; elapsed < ms; elapsed += 100) await act(() => vi.advanceTimersByTimeAsync(100))
}
const blockOrder = (container) =>
  [...container.querySelectorAll('.live-block')].map((block) => block.className.match(/live-block--(\w+)/)[1])

describe('Home del prototipo final', () => {
  test('no tiene un ícono aparte: Mochi vive en la Home de cuerpo entero', async () => {
    await renderHome()
    expect(screen.queryByRole('button', { name: 'Hablar con Mochi' })).toBeNull()
  })

  test('la barra de la Home es el buscador con Mochi (no el plano) y tocarla lo abre', async () => {
    function Probe() {
      return <output data-testid="assistant">{useAssistant().isOpen ? 'abierto' : 'cerrado'}</output>
    }
    const { container } = render(
      <Providers>
        <div className="phone">
          <div className="screen-wrap">
            <HomeScreen push={vi.fn()} tab="home" setTab={vi.fn()} />
          </div>
        </div>
        <Probe />
      </Providers>,
    )
    expect(container.querySelector('.search-bar')).toBeNull()
    expect(screen.getByTestId('assistant').textContent).toBe('cerrado')
    fireEvent.click(screen.getByRole('button', { name: 'Abrir buscador con Mochi' }))
    expect(screen.getByTestId('assistant').textContent).toBe('abierto')
  })

  test('Mochi entra y saluda sin sugerir productos ni reordenar ni oscurecer la Home', async () => {
    const { container } = await renderHome()
    expect(blockOrder(container)).toEqual(['essentials', 'promos', 'turbo', 'plan', 'nearby', 'lower'])

    await advance(900 + 1000) // entra y empieza a saludar
    expect(container.querySelector('.live-bubble p').textContent).toMatch(/^¡Hola! Ahora vivo en tu Home/)

    await advance(12000) // nada sube ni se oscurece después del saludo
    expect(blockOrder(container)).toEqual(['essentials', 'promos', 'turbo', 'plan', 'nearby', 'lower'])
    expect(screen.queryByText(/^Tu rincón de/)).toBeNull()
    expect(screen.queryByText(/^Nuevo para ti:/)).toBeNull()
    expect(container.querySelector('.is-dim, .is-dimmed, [inert]')).toBeNull()
    expect(screen.queryByRole('button', { name: '¡Sí, tráelos!' })).toBeNull()
  })

  test('el globo mide desde la primera letra lo que medirá al terminar: lo que falta va invisible', async () => {
    const { container } = await renderHome()
    await advance(900 + 200) // entra y empieza a saludar
    const said = container.querySelector('.live-bubble p')
    const rest = () => said.querySelector('.live-bubble-rest')
    expect(said.textContent.length).toBeGreaterThan(0)
    expect(said.textContent + rest().dataset.rest).toBe(
      '¡Hola! Ahora vivo en tu Home 👋 Pídeme ideas o prueba una vertical nueva.',
    )

    await advance(2000) // terminó de escribir
    expect(rest()).toBeNull()
  })

  test('las listas de la API van en los bloques de siempre; si fallan, la Home sigue igual', async () => {
    stubApi({
      '/catalog/home': fixture('catalog-home'),
      '/catalog/restaurants': fixture('catalog-restaurants').slice(0, 6),
    })
    const { container } = await renderHome()
    await advance(300)
    const block = (id) => container.querySelector(`.live-block--${id}`)
    expect(within(block('turbo')).getByText('Restaurantes rápidos')).toBeTruthy()
    expect(within(block('nearby')).getByText('Cerca de ti')).toBeTruthy()
    expect(within(block('nearby')).getByText('Supermercado de prueba Centro')).toBeTruthy()
    expect(within(block('lower')).getByText('Mejor evaluados')).toBeTruthy()
    expect(blockOrder(container)).toEqual(['essentials', 'promos', 'turbo', 'plan', 'nearby', 'lower'])

    cleanup()
    stubApi({ '/catalog/home': 'offline', '/catalog/restaurants': 'offline' })
    const failed = await renderHome()
    await advance(300)
    expect(failed.container.querySelector('.live-block--nearby').textContent).toBe('')
    expect(failed.container.querySelector('.live-block--lower').textContent).toBe('')
    expect(blockOrder(failed.container)).toEqual(['essentials', 'promos', 'turbo', 'plan', 'nearby', 'lower'])
    expect(screen.queryByText('Sin conexión')).toBeNull()
  })

  test('la Home no muestra el pasaporte ni «Jugar»', async () => {
    const { container } = await renderHome()
    expect(screen.queryByText(/pasaporte/i)).toBeNull()
    expect(screen.queryByRole('button', { name: /Jugar/ })).toBeNull()
    expect(container.querySelector('.live-passport')).toBeNull()
  })

  describe('los momentos de Mochi salen de /agent/offer', () => {
    const status = (container) => container.querySelector('.live-layer [role="status"]').textContent

    test('el kit sale de la API y agregarlo registra una aceptación por producto', async () => {
      const kit = fixture('agent-offer-plan')
      await renderHome()
      await advance(100)
      // Las ocasiones son las del servidor, con su nombre.
      expect(screen.getByRole('radio', { name: 'Panorama en casa' })).toBeTruthy()
      expect(screen.queryByRole('radio', { name: 'Película' })).toBeNull()

      fireEvent.click(screen.getByRole('radio', { name: 'Carrete' }))
      await advance(100)
      expect(offerRequests()).toEqual([
        { moment: 'plan', user_id: expect.any(String), context: { occasion: 'carrete' } },
      ])
      expect(screen.getByText(/^Tu kit en \d+ verticales:/)).toBeTruthy()
      for (const product of kit.products) expect(screen.getByText(product.name)).toBeTruthy()
      expect(tracked('suggestion_shown', 'agent-plan')).toHaveLength(kit.products.length)

      fireEvent.click(screen.getByRole('button', { name: /^Agregar el kit/ }))
      const accepted = tracked('suggestion_accepted', 'agent-plan')
      expect(accepted).toHaveLength(kit.products.length) // una por producto, no por clic
      expect(accepted.map(([, fields]) => fields.concept_id).sort()).toEqual(kit.products.map((p) => p.concept).sort())
      expect(tracked('suggestion_shown', 'agent-plan')).toHaveLength(kit.products.length)
      expect(screen.getByRole('button', { name: /En tu carro · Ir a pagar/ })).toBeTruthy()
    })

    test('plans sends the user and shows Para ti for occasions with a reason', async () => {
      let asked
      stubAgent({
        '/agent/plans': (req) => {
          asked = req.query.get('user_id')
          return fixture('agent-plans-afin')
        },
      })
      await renderHome()
      await advance(100)
      expect(asked).toEqual(expect.any(String))
      expect(asked).not.toBe('')
      const chips = screen.getAllByRole('radio')
      expect(chips).toHaveLength(5)
      for (const chip of chips) expect(within(chip).getByText('Para ti')).toBeTruthy()

      // Sin perfil (las ocasiones de siempre) no hay etiqueta.
      cleanup()
      stubAgent()
      await renderHome()
      await advance(100)
      expect(screen.queryByText('Para ti')).toBeNull()
    })

    test('the offer has ¿Por qué?: el kit, el comentario del carrito y la vertical por probar', async () => {
      // El kit de la ocasión.
      await renderHome()
      await advance(100)
      fireEvent.click(screen.getByRole('radio', { name: 'Carrete' }))
      await advance(100)
      const kit = document.querySelector('.live-kit')
      fireEvent.click(within(kit).getByRole('button', { name: '¿Por qué?' }))
      expect(within(kit).getByText(fixture('agent-offer-plan').reason.text)).toBeTruthy()

      // El comentario del carrito, en el globo de Mochi.
      cleanup()
      memory.session.played = true
      memory.session.lastAdded = LOOSE_CART
      const home = await renderHome()
      await advance(4000)
      const bubble = home.container.querySelector('.live-bubble')
      fireEvent.click(within(bubble).getByRole('button', { name: '¿Por qué?' }))
      expect(within(bubble).getByText(fixture('agent-offer-carrito').reason.text)).toBeTruthy()

      // La vertical por probar, con el texto que arma la Home.
      cleanup()
      memory.session.lastAdded = null
      const poked = await renderHome()
      await advance(900 + 3400)
      fireEvent.click(screen.getByRole('button', { name: /^Mochi:/ }))
      await advance(3000)
      const talk = poked.container.querySelector('.live-bubble')
      fireEvent.click(within(talk).getByRole('button', { name: '¿Por qué?' }))
      expect(within(talk).getByText(fixture('agent-offer-vertical-por-probar').reason.text)).toBeTruthy()
    })

    test('the bubble stays while ¿Por qué? is open and goes away 12 s after it closes', async () => {
      memory.session.played = true
      memory.session.lastAdded = LOOSE_CART
      const { container } = await renderHome()
      await advance(4000)
      const why = () => within(container.querySelector('.live-bubble')).getByRole('button', { name: '¿Por qué?' })
      fireEvent.click(why())
      await advance(30_000) // mucho más que lo que dura un globo con botones
      expect(container.querySelector('.live-bubble')).not.toBeNull()
      expect(screen.getByText(fixture('agent-offer-carrito').reason.text)).toBeTruthy()

      fireEvent.click(why())
      await advance(11_000)
      expect(container.querySelector('.live-bubble')).not.toBeNull()
      await advance(1_500)
      expect(container.querySelector('.live-bubble')).toBeNull()
    })

    test('la Home muestra solo los 5 primeros planes, en el orden del servidor', async () => {
      await renderHome()
      await advance(100)
      const names = fixture('agent-plans').map((option) => option.name)
      expect(names.length).toBeGreaterThan(5)
      expect(screen.getAllByRole('radio').map((chip) => chip.lastChild.textContent)).toEqual(names.slice(0, 5))
    })

    test('si el servidor no arma el kit (204) o no contesta, el chip no se queda marcado y Mochi no dice nada', async () => {
      stubAgent({ 'POST /agent/offer': 204 })
      const { container } = await renderHome()
      await advance(900 + 3400 + 6000)
      fireEvent.click(screen.getByRole('radio', { name: 'Carrete' }))
      await advance(3000)
      expect(screen.getByRole('radio', { name: 'Carrete' }).getAttribute('aria-checked')).toBe('false')
      expect(screen.queryByText(/^Tu kit en/)).toBeNull()
      expect(status(container)).toBe('')

      stubAgent({ 'POST /agent/offer': 'offline' })
      fireEvent.click(screen.getByRole('radio', { name: 'Asado' }))
      await advance(3000)
      expect(screen.getByRole('radio', { name: 'Asado' }).getAttribute('aria-checked')).toBe('false')
      expect(status(container)).toBe('')
    })

    test('si no llegan las ocasiones, el bloque del plan no ofrece chips (no hay kits locales)', async () => {
      stubAgent({ '/agent/plans': 'offline' })
      await renderHome()
      await advance(300)
      expect(screen.queryByRole('radio')).toBeNull()
    })

    test('una oferta que llega con la Home inactiva no muestra globo, ni al volver', async () => {
      stubAgent({ 'POST /agent/offer': { slow: 2000, body: fixture('agent-offer-carrito') } })
      memory.session.played = true
      memory.session.lastAdded = LOOSE_CART
      const { container, rerender } = await renderHome()
      await advance(100) // la oferta ya se pidió
      rerender(homeTree({ active: false })) // se abrió una tienda encima
      await advance(3000) // la oferta llega con la Home tapada
      expect(container.querySelector('.live-bubble')).toBeNull()
      rerender(homeTree({ active: true }))
      await advance(1000)
      expect(container.querySelector('.live-bubble')).toBeNull()
    })

    test('el comentario del carrito usa la oferta de la API y calla en un 204', async () => {
      const push = vi.fn()
      const carrito = fixture('agent-offer-carrito')
      memory.session.played = true
      memory.session.lastAdded = LOOSE_CART
      const { container } = await renderHome({ push })
      await advance(4000)
      expect(status(container)).toBe(carrito.text)
      expect(offerRequests()).toEqual([
        {
          moment: 'carrito',
          user_id: expect.any(String),
          context: { product: { entity_type: 'catalog_item', entity_id: '94001' } },
        },
      ])
      expect(memory.session.lastAdded).toBeNull()
      expect(tracked('suggestion_shown', 'agent-carrito')).toHaveLength(1)
      fireEvent.click(screen.getByRole('button', { name: 'Ver snacks salados' }))
      expect(push).toHaveBeenLastCalledWith('vertical', { id: 'express' })

      cleanup()
      stubAgent({ 'POST /agent/offer': 204 })
      memory.session.lastAdded = LOOSE_CART
      const empty = await renderHome()
      await advance(4000)
      expect(status(empty.container)).toBe('')
      expect(memory.session.lastAdded).toBeNull()
    })

    test('tocar a Mochi propone la vertical por probar que dice la API, sin contexto', async () => {
      const push = vi.fn()
      const made = fixture('agent-offer-vertical-por-probar')
      const { container } = await renderHome({ push })
      await advance(900 + 3400)
      fireEvent.click(screen.getByRole('button', { name: /^Mochi:/ }))
      await advance(3000)
      expect(offerRequests()).toEqual([{ moment: 'vertical_por_probar', user_id: expect.any(String), context: {} }])
      expect(container.querySelector('.live-bubble p').textContent).toBe(POKE_LINE)
      expect(tracked('suggestion_shown', 'agent-vertical_por_probar').length).toBeLessThanOrEqual(1)
      expect(screen.queryByRole('button', { name: /Jugar/ })).toBeNull()
      fireEvent.click(screen.getByRole('button', { name: made.actions[0].label }))
      expect(push).toHaveBeenLastCalledWith(...routeForScreen(made.actions[0].route[0]))
    })

    test('si el paso es RappiFavor, Mochi lo presenta y su botón abre su pantalla y lo registra', async () => {
      const push = vi.fn()
      const made = fixture('agent-offer-vertical-por-probar-servicio')
      stubAgent({ 'POST /agent/offer': (req) => (req.body.moment === 'vertical_por_probar' ? made : 204) })
      const { container } = await renderHome({ push })
      await advance(900 + 3400)
      fireEvent.click(screen.getByRole('button', { name: /^Mochi:/ }))
      await advance(3000)
      expect(container.querySelector('.live-bubble p').textContent).toBe(made.text)
      const service = (type) => events.track.mock.calls.filter(([name]) => name === type).map(([, fields]) => fields)
      expect(service('service_shown')).toEqual([{ payload: { servicio: 'rappifavor' } }])
      fireEvent.click(screen.getByRole('button', { name: 'Abrir RappiFavor' }))
      expect(service('service_opened')).toEqual([{ payload: { servicio: 'rappifavor' } }])
      expect(push).toHaveBeenLastCalledWith('favor')
    })

    test('tocar a Mochi sin nada que ofrecer (204) calla', async () => {
      stubAgent({ 'POST /agent/offer': 204 })
      const { container } = await renderHome()
      await advance(900 + 3400 + 6000)
      fireEvent.click(screen.getByRole('button', { name: /^Mochi:/ }))
      await advance(3000)
      expect(status(container)).toBe('')
    })

    test('Mochi en silencio no pide ofertas', async () => {
      localStorage.setItem('rappi-proto-mochi-silencio', today())
      memory.session.played = true
      memory.session.lastAdded = LOOSE_CART
      await renderHome()
      await advance(4000)
      expect(allOfferRequests()).toEqual([]) // tampoco la recompra

      // Tampoco si lo ignoraron dos veces seguidas.
      cleanup()
      localStorage.removeItem('rappi-proto-mochi-silencio')
      const quiet = await import('../../../state/agentQuiet')
      quiet.noteDismissed()
      quiet.noteDismissed()
      memory.session.lastAdded = LOOSE_CART
      await renderHome()
      await advance(4000)
      expect(offerRequests()).toEqual([])
    })
  })

  describe('«¿Repetimos?» (la recompra)', () => {
    const repeatBlock = (container) => container.querySelector('.live-block--recompra')

    test('sin recompra (204) no hay bloque, y la Home la pidió sin contexto', async () => {
      const { container } = await renderHome()
      await advance(100)
      expect(repeatRequests()).toEqual([{ moment: 'recompra', user_id: expect.any(String), context: {} }])
      expect(repeatBlock(container)).toBeNull()
      expect(tracked('suggestion_shown', 'agent-recompra')).toEqual([])
    })

    test('con recompra, va justo después de los accesos, dice por qué y registra la mostrada una vez', async () => {
      api = stubRepeat()
      const made = fixture('agent-offer-recompra')
      const { container, rerender } = await renderHome()
      await advance(100)
      expect(blockOrder(container)).toEqual(['essentials', 'recompra', 'promos', 'turbo', 'plan', 'nearby', 'lower'])
      const block = repeatBlock(container)
      expect(within(block).getByText(made.text)).toBeTruthy()
      expect(within(block).getByText(made.products[0].name)).toBeTruthy()
      fireEvent.click(within(block).getByRole('button', { name: '¿Por qué?' }))
      expect(within(block).getByText(made.reason.text)).toBeTruthy()
      expect(tracked('suggestion_shown', 'agent-recompra')).toEqual([
        ['suggestion_shown', { concept_id: 'cafe', vertical: 'grocery', payload: { origen: 'agent-recompra' } }],
      ])

      // Al volver a la Home se pide otra vez, pero la mostrada no se cuenta de nuevo.
      rerender(homeTree({ active: false }))
      rerender(homeTree({ active: true }))
      await advance(100)
      expect(repeatRequests()).toHaveLength(2)
      expect(tracked('suggestion_shown', 'agent-recompra')).toHaveLength(1)
    })

    test('«Ver producto» lleva a su tienda con el producto destacado y no cuenta una aceptación', async () => {
      api = stubRepeat()
      const push = vi.fn()
      const made = fixture('agent-offer-recompra')
      const { container } = await renderHome({ push })
      await advance(100)
      fireEvent.click(within(repeatBlock(container)).getByRole('button', { name: 'Ver producto' }))
      // La aceptación cuenta al agregarlo al carro en la tienda (lleva su origen: StoreScreen.test.jsx).
      expect(tracked('suggestion_accepted', 'agent-recompra')).toEqual([])
      expect(push).toHaveBeenLastCalledWith(
        'store',
        expect.objectContaining({
          store: expect.objectContaining({ id: made.products[0].store_id }),
          item: expect.objectContaining({
            entityId: made.products[0].entity_id,
            fromSuggestion: true,
            suggestionOrigin: 'agent-recompra',
          }),
        }),
      )
    })

    test('«Después» quita el bloque, cuenta como ignorar a Mochi y no se vuelve a pedir', async () => {
      api = stubRepeat()
      const quiet = await import('../../../state/agentQuiet')
      const { container, rerender } = await renderHome()
      await advance(100)
      fireEvent.click(within(repeatBlock(container)).getByRole('button', { name: 'Después' }))
      expect(repeatBlock(container)).toBeNull()
      quiet.noteDismissed() // una segunda vez (desde el globo): Mochi se calla
      expect(quiet.isHushed()).toBe(true)

      rerender(homeTree({ active: false }))
      rerender(homeTree({ active: true }))
      await advance(100)
      expect(repeatRequests()).toHaveLength(1)
      expect(repeatBlock(container)).toBeNull()
    })
    // El buscador olvida (sube la generación) antes de que el servidor borre: pedir ahí traía la misma oferta y dejaba
    // otra `suggestion_shown`. Si el borrado sale bien la app se recarga; si falla, pide al volver a la Home.
    const forgetTree = (active) => {
      function Forget() {
        forget = useProfile().reset
        return null
      }
      return (
        <Providers>
          <Forget />
          <div className="phone">
            <div className="screen-wrap">
              <HomeScreen push={vi.fn()} tab="home" setTab={vi.fn()} active={active} />
            </div>
          </div>
        </Providers>
      )
    }
    let forget

    test('tras «Olvidar» no se vuelve a pedir ni a contar; si el borrado falla, pide al volver a la Home', async () => {
      api = stubRepeat()
      const { container, rerender } = render(forgetTree(true))
      await advance(100)
      expect(repeatRequests()).toHaveLength(1)
      act(() => forget())
      await advance(500)
      expect(repeatRequests()).toHaveLength(1)
      expect(tracked('suggestion_shown', 'agent-recompra')).toHaveLength(1)
      expect(repeatBlock(container)).not.toBeNull() // sin cambio a la vista: el buscador está encima

      rerender(forgetTree(false))
      rerender(forgetTree(true))
      await advance(100)
      expect(repeatRequests()).toHaveLength(2)
    })

    test('la recompra que venía en camino al «Olvidar» ni se muestra ni se cuenta', async () => {
      api = stubAgent({
        'POST /agent/offer': (req) =>
          req.body.moment === 'recompra'
            ? { slow: 300, body: fixture('agent-offer-recompra') }
            : OFFER_FIXTURES[req.body.moment]
              ? fixture(OFFER_FIXTURES[req.body.moment])
              : 204,
      })
      const { container } = render(forgetTree(true))
      await advance(100)
      act(() => forget())
      await advance(500)
      expect(repeatRequests()).toHaveLength(1)
      expect(repeatBlock(container)).toBeNull()
      expect(tracked('suggestion_shown', 'agent-recompra')).toEqual([])
    })
  })

  describe('«¿Volvemos a…?» (lo que dejó de pedir)', () => {
    const slotBlock = (container) => container.querySelector('.live-block--recompra')

    test('sin recompra, ocupa su lugar, dice por qué y registra la mostrada con su origen', async () => {
      api = stubWinback()
      const made = fixture('agent-offer-volver')
      const { container } = await renderHome()
      await advance(100)
      expect(winbackRequests()).toEqual([{ moment: 'volver', user_id: expect.any(String), context: {} }])
      const block = slotBlock(container)
      expect(within(block).getByRole('region', { name: 'Volver a pedir' })).toBeTruthy()
      expect(within(block).getByText(made.text)).toBeTruthy()
      fireEvent.click(within(block).getByRole('button', { name: '¿Por qué?' }))
      expect(within(block).getByText(made.reason.text)).toBeTruthy()
      expect(tracked('suggestion_shown', 'agent-volver')).toEqual([
        [
          'suggestion_shown',
          { concept_id: 'cafe', vertical: 'grocery', payload: { origen: 'agent-volver', kind: 'volver' } },
        ],
      ])
    })

    test('la recompra gana: con una, «¿Volvemos a…?» ni se pide', async () => {
      api = stubWinback({ recompra: 'agent-offer-recompra' })
      const { container } = await renderHome()
      await advance(100)
      expect(winbackRequests()).toEqual([])
      expect(within(slotBlock(container)).getByText(fixture('agent-offer-recompra').text)).toBeTruthy()
      expect(tracked('suggestion_shown', 'agent-volver')).toEqual([])
    })

    test('se pide una vez por pestaña: al volver a la Home sigue el mismo, sin contarlo otra vez', async () => {
      api = stubWinback()
      const { container, rerender } = await renderHome()
      await advance(100)
      rerender(homeTree({ active: false }))
      rerender(homeTree({ active: true }))
      await advance(100)
      expect(repeatRequests()).toHaveLength(2)
      expect(winbackRequests()).toHaveLength(1)
      expect(within(slotBlock(container)).getByText(fixture('agent-offer-volver').text)).toBeTruthy()
      expect(tracked('suggestion_shown', 'agent-volver')).toHaveLength(1)
    })

    test('«Ver producto» lleva a su tienda con el origen de la oferta', async () => {
      api = stubWinback()
      const push = vi.fn()
      const { container } = await renderHome({ push })
      await advance(100)
      fireEvent.click(within(slotBlock(container)).getByRole('button', { name: 'Ver producto' }))
      expect(tracked('suggestion_accepted', 'agent-volver')).toEqual([])
      expect(push).toHaveBeenLastCalledWith(
        'store',
        expect.objectContaining({ item: expect.objectContaining({ suggestionOrigin: 'agent-volver' }) }),
      )
    })

    test('«Después» registra el descarte (la API deja de ofrecerla con dos) y no se vuelve a pedir', async () => {
      api = stubWinback()
      const { container, rerender } = await renderHome()
      await advance(100)
      fireEvent.click(within(slotBlock(container)).getByRole('button', { name: 'Después' }))
      expect(slotBlock(container)).toBeNull()
      expect(tracked('suggestion_dismissed', 'agent-volver')).toEqual([
        [
          'suggestion_dismissed',
          { concept_id: 'cafe', vertical: 'grocery', payload: { origen: 'agent-volver', kind: 'volver' } },
        ],
      ])

      rerender(homeTree({ active: false }))
      rerender(homeTree({ active: true }))
      await advance(100)
      expect(winbackRequests()).toHaveLength(1)
      expect(slotBlock(container)).toBeNull()
    })

    test('un pedido nuevo la vuelve a pedir (no invita a volver a lo que se acaba de comprar)', async () => {
      api = stubWinback()
      let place
      function Orders() {
        place = useOrders().place
        return null
      }
      const tree = (active) => (
        <Providers>
          <Orders />
          <div className="phone">
            <div className="screen-wrap">
              <HomeScreen push={vi.fn()} tab="home" setTab={vi.fn()} active={active} />
            </div>
          </div>
        </Providers>
      )
      const { rerender } = render(tree(true))
      await advance(100)
      rerender(tree(false))
      act(() => place({ stores: [], items: [], total: 0 }))
      rerender(tree(true))
      await advance(100)
      expect(winbackRequests()).toHaveLength(2)
    })

    test('una API que no conoce el momento (422) no deja bloque, ni la recompra de antes, y no se vuelve a pedir', async () => {
      let repeats = 0
      api = stubAgent({
        'POST /agent/offer': (req) => {
          if (req.body.moment === 'recompra') return (repeats += 1) === 1 ? fixture('agent-offer-recompra') : 204
          if (req.body.moment === 'volver') return 422
          return OFFER_FIXTURES[req.body.moment] ? fixture(OFFER_FIXTURES[req.body.moment]) : 204
        },
      })
      const { container, rerender } = await renderHome()
      await advance(100)
      expect(slotBlock(container)).not.toBeNull() // la recompra
      rerender(homeTree({ active: false }))
      rerender(homeTree({ active: true }))
      await advance(100)
      expect(winbackRequests()).toHaveLength(1)
      expect(slotBlock(container)).toBeNull()
      rerender(homeTree({ active: false }))
      rerender(homeTree({ active: true }))
      await advance(100)
      expect(winbackRequests()).toHaveLength(1) // guardada como «no hay»
    })

    test('si la Home invitó a volver a una vertical, tocar a Mochi no dice «Vuelve a…» de esa misma', async () => {
      const back = fixture('agent-offer-volver')
      back.reason = { text: 'Porque pediste 3 veces en el súper…', basis: [{ kind: 'vuelta', id: 'supermercado' }] }
      const toTry = fixture('agent-offer-vertical-por-probar')
      toTry.reason.basis = [{ kind: 'vuelta', id: 'supermercado', source: 'pedidos' }]
      api = stubAgent({
        'POST /agent/offer': (req) =>
          ({ volver: back, vertical_por_probar: toTry })[req.body.moment] ??
          (OFFER_FIXTURES[req.body.moment] ? fixture(OFFER_FIXTURES[req.body.moment]) : 204),
      })
      const { container } = await renderHome()
      await advance(900 + 3400)
      fireEvent.click(screen.getByRole('button', { name: /^Mochi:/ }))
      await advance(3000)
      expect(offerRequests()).toEqual([{ moment: 'vertical_por_probar', user_id: expect.any(String), context: {} }])
      expect(container.querySelector('.live-bubble p')?.textContent ?? '').not.toBe(POKE_LINE)
      expect(tracked('suggestion_shown', 'agent-volver')).toEqual([
        [
          'suggestion_shown',
          { concept_id: 'cafe', vertical: 'grocery', payload: { origen: 'agent-volver', kind: 'vuelta' } },
        ],
      ])
    })

    test('«Después» en la recompra no registra un descarte de «¿Volvemos a…?»', async () => {
      api = stubRepeat()
      const { container } = await renderHome()
      await advance(100)
      fireEvent.click(within(slotBlock(container)).getByRole('button', { name: 'Después' }))
      expect(tracked('suggestion_dismissed', 'agent-volver')).toEqual([])
    })
  })

  test('la Home queda montada bajo la vertical abierta: al volver a estar arriba, comenta lo agregado', async () => {
    const { container, rerender } = await renderHome()
    await advance(900 + 3400 + 6000) // saluda y se calla
    rerender(homeTree({ active: false })) // se abrió una tienda encima
    memory.session.lastAdded = LOOSE_CART
    rerender(homeTree({ active: true })) // volvió
    await advance(4000)
    expect(container.querySelector('.live-layer [role="status"]').textContent).toBe(fixture('agent-offer-carrito').text)
  })

  test('al tocar a Mochi salta (aunque empiece a hablar) y después vuelve a su pose', async () => {
    const { container } = await renderHome()
    await advance(900 + 3400)
    const body = screen.getByRole('button', { name: /^Mochi:/ })
    fireEvent.pointerDown(body)
    fireEvent.click(body)
    await advance(300)
    expect(container.querySelector('.live-agent .mascot').classList).toContain('mascot--jump')
    await advance(1000)
    expect(container.querySelector('.live-agent .mascot').classList).not.toContain('mascot--jump')
  })

  describe('silenciado por hoy (desde Mochi flotante)', () => {
    const quietToday = () => localStorage.setItem('rappi-proto-mochi-silencio', today())
    const status = (container) => container.querySelector('.live-layer [role="status"]').textContent

    test('al volver no comenta lo agregado', async () => {
      quietToday()
      memory.session.played = true
      memory.session.lastAdded = {
        id: 'x',
        name: 'Cerveza Escudo Lata 470 cc',
        vertical: 'liquor',
        entityType: 'catalog_item',
        entityId: '94001',
      }
      const { container } = await renderHome()
      await advance(3000)
      expect(status(container)).toBe('')
      expect(offerRequests()).toEqual([]) // en silencio no pide la oferta
    })

    test('entra sin saludar, pero si lo tocan responde', async () => {
      quietToday()
      const { container } = await renderHome()
      await advance(900 + 3400)
      expect(status(container)).toBe('')
      fireEvent.click(screen.getByRole('button', { name: /^Mochi:/ }))
      await advance(3000)
      expect(status(container)).toBe(POKE_LINE)
    })
  })

  test('«Después» cuenta como ignorarlo: a la segunda, Mochi se calla', async () => {
    const quiet = await import('../../../state/agentQuiet')
    await renderHome()
    await advance(900 + 3400 + 6000)
    for (let i = 0; i < 2; i++) {
      fireEvent.click(screen.getByRole('button', { name: /^Mochi:/ }))
      await advance(3000)
      fireEvent.click(screen.getByRole('button', { name: 'Después' }))
      await advance(500)
    }
    expect(quiet.isHushed()).toBe(true)
  })

  describe('guía de la primera vez', () => {
    beforeEach(() => localStorage.removeItem('rappi-proto-guia-vista'))
    const status = (container) => container.querySelector('.live-layer [role="status"]').textContent
    const at = (container) => container.querySelector('.live-agent').dataset.at
    const AFTER_GREETING = 900 + 6000 + 3000 // entra, saluda y termina de escribir el primer paso
    const next = async (name) => {
      fireEvent.click(screen.getByRole('button', { name }))
      await advance(3000)
    }

    test('la primera vez, después del saludo, Mochi muestra el buscador y qué pasa al tocarlo', async () => {
      const { container } = await renderHome()
      await advance(AFTER_GREETING)
      expect(status(container)).toMatch(/^Arriba está mi buscador/)
      expect(at(container)).toBe('essentials')
      await next('Siguiente')
      expect(status(container)).toMatch(/si me tocas/)
      await next('Listo')
      expect(status(container)).toBe('')
      expect(localStorage.getItem(memory.TOUR_KEY)).toBeTruthy()
    })

    test('«Saltar» la termina y no vuelve', async () => {
      const { container } = await renderHome()
      await advance(AFTER_GREETING)
      await next('Saltar')
      expect(status(container)).toBe('')
      cleanup()
      memory.session.played = false
      const again = await renderHome()
      await advance(AFTER_GREETING + 6000)
      expect(status(again.container)).not.toMatch(/buscador|si me tocas/)
    })

    test('la segunda visita no la muestra', async () => {
      localStorage.setItem(memory.TOUR_KEY, '1')
      const { container } = await renderHome()
      await advance(AFTER_GREETING)
      expect(status(container)).not.toMatch(/^Arriba está mi buscador/)
    })

    test('«Repetir escena» la vuelve a mostrar', async () => {
      localStorage.setItem(memory.TOUR_KEY, '1')
      const { container } = await renderHome()
      await advance(AFTER_GREETING)
      act(() => memory.resetLive())
      await advance(AFTER_GREETING)
      expect(status(container)).toMatch(/^Arriba está mi buscador/)
    })

    test('si tocan a Mochi en medio, la guía termina (vista) y Mochi sigue comentando lo agregado al volver', async () => {
      const { container, rerender } = await renderHome()
      await advance(AFTER_GREETING)
      fireEvent.click(screen.getByRole('button', { name: /^Mochi:/ }))
      await advance(3000)
      expect(status(container)).toBe(POKE_LINE)
      expect(localStorage.getItem(memory.TOUR_KEY)).toBeTruthy()
      rerender(homeTree({ active: false }))
      memory.session.lastAdded = LOOSE_CART
      rerender(homeTree({ active: true }))
      await advance(4000)
      expect(status(container)).toBe(fixture('agent-offer-carrito').text)
    })

    test('no pisa lo que la persona pidió tocando a Mochi justo antes', async () => {
      const { container } = await renderHome()
      await advance(900 + 3400 + 700)
      fireEvent.click(screen.getByRole('button', { name: /^Mochi:/ }))
      await advance(5000)
      expect(status(container)).toBe(POKE_LINE)
    })

    test('el plan del día no interrumpe la guía', async () => {
      let seePlan
      globalThis.IntersectionObserver = class {
        constructor(callback) {
          seePlan = callback
        }
        observe() {}
        disconnect() {}
      }
      try {
        const { container } = await renderHome()
        await advance(AFTER_GREETING)
        act(() => seePlan([{ isIntersecting: true }]))
        await advance(1000)
        expect(status(container)).toMatch(/^Arriba está mi buscador/)
      } finally {
        delete globalThis.IntersectionObserver
      }
    })

    test('al terminar la guía, Mochi muestra lo pendiente de «al volver»', async () => {
      const { container, rerender } = await renderHome()
      await advance(AFTER_GREETING)
      rerender(homeTree({ active: false })) // se abrió algo encima en medio de la guía
      memory.session.lastAdded = LOOSE_CART
      rerender(homeTree({ active: true }))
      await advance(2000)
      expect(status(container)).toMatch(/^Arriba está mi buscador/) // la guía sigue
      await next('Siguiente')
      await next('Listo')
      await advance(4000)
      expect(status(container)).toBe(fixture('agent-offer-carrito').text)
    })

    test('con «reducir movimiento» también funciona', async () => {
      const original = window.matchMedia
      window.matchMedia = () => ({ matches: true, addEventListener() {}, removeEventListener() {} })
      try {
        const { container } = await renderHome()
        await advance(6000 + 3000)
        expect(status(container)).toMatch(/^Arriba está mi buscador/)
      } finally {
        window.matchMedia = original
      }
    })
  })

  test('tocar a Mochi después del saludo propone una vertical por probar', async () => {
    const { container } = await renderHome()
    await advance(900 + 3400)
    fireEvent.click(screen.getByRole('button', { name: /^Mochi:/ }))
    await advance(3000) // termina de escribir
    expect(container.querySelector('.live-bubble p').textContent).toBe(POKE_LINE)
  })

  test('«¿Por qué?» y los botones del globo ocupan su lugar mientras escribe, sin verse hasta terminar', async () => {
    const { container } = await renderHome()
    await advance(900 + 3400)
    fireEvent.click(screen.getByRole('button', { name: /^Mochi:/ }))
    await advance(400) // llegó la oferta y empezó a escribir
    const more = () => container.querySelector('.live-bubble-more')
    expect(container.querySelector('.live-bubble-rest')).not.toBeNull()
    expect(more().classList.contains('is-pending')).toBe(true)
    expect(more().getAttribute('aria-hidden')).toBe('true')
    expect(within(more()).getAllByRole('button', { hidden: true }).length).toBeGreaterThan(0)

    await advance(3000) // termina de escribir
    expect(more().classList.contains('is-pending')).toBe(false)
    expect(within(more()).getByRole('button', { name: '¿Por qué?' })).toBeTruthy()
  })

  test('«Repetir escena» vuelve a saludar', async () => {
    const { container } = await renderHome()
    await advance(900 + 3400 + 6000)
    act(() => memory.resetLive())
    await advance(900 + 1000)
    expect(container.querySelector('.live-bubble p').textContent).toMatch(/^¡Hola! Ahora vivo en tu Home/)
  })

  test('en reposo se asoma desde el borde y, al hacer scroll, se esconde hasta que se para', async () => {
    const { container } = await renderHome()
    await advance(900 + 3400 + 6000) // terminó de saludar
    const live = container.querySelector('.live-agent')
    expect(live.classList.contains('is-resting')).toBe(true)
    fireEvent.scroll(container.querySelector('.home--live'))
    expect(live.classList.contains('is-tucked')).toBe(true)
    await advance(800)
    expect(live.classList.contains('is-tucked')).toBe(false)
  })

  test('el kit agregado cambia el botón a «En tu carro»', async () => {
    await renderHome()
    await advance(100)
    fireEvent.click(screen.getByRole('radio', { name: 'Carrete' }))
    await advance(100)
    fireEvent.click(screen.getByRole('button', { name: /^Agregar el kit/ }))
    expect(screen.getByRole('button', { name: /En tu carro · Ir a pagar/ })).toBeTruthy()
  })

  test('en la cuenta, «Repetir escena de Mochi» aparece solo en el prototipo final', async () => {
    await renderHome({ tab: 'account' })
    expect(screen.getByRole('button', { name: /Repetir escena de Mochi/ })).toBeTruthy()
    cleanup()
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    await renderHome({ tab: 'account' })
    expect(screen.queryByRole('button', { name: /Repetir escena de Mochi/ })).toBeNull()
  })

  describe('orden de los accesos', () => {
    const tiles = (container) => [...container.querySelectorAll('.home-shortcut')].map((button) => button.textContent)
    const opened = () => events.track.mock.calls.filter(([type]) => type === 'vertical_open')

    test('con una persona que pide en Farmacia, Farmacia va primero y se ve por qué están así', async () => {
      stubAgent({ 'GET /profile/*': fixture('profile-verticales') })
      const { container } = await renderHome()
      await advance(300)
      expect(tiles(container).slice(0, 2)).toEqual(['Farmacia', 'Súper'])
      expect(tiles(container).slice(-2)).toEqual(['Lealtad', 'Beneficios Pro'])
      expect(screen.getByText('Ordenadas según lo que más usas')).toBeTruthy()
    })

    test('una persona nueva ve el orden fijo y sin el texto', async () => {
      stubAgent({ 'GET /profile/*': fixture('profile-verticales-nueva') })
      const { container } = await renderHome()
      await advance(300)
      expect(tiles(container).slice(0, 6)).toEqual([
        'Súper',
        'Farmacia',
        'Rappi Mall',
        'Licores',
        'Express',
        'Chocolates',
      ])
      expect(screen.queryByText('Ordenadas según lo que más usas')).toBeNull()
    })

    test('con la API caída, el orden fijo y sin el texto (Lealtad y Beneficios Pro al final)', async () => {
      stubAgent({ 'GET /profile/*': 'offline' })
      const { container } = await renderHome()
      await advance(300)
      expect(tiles(container)).toEqual([
        'Súper',
        'Farmacia',
        'Rappi Mall',
        'Licores',
        'Express',
        'Chocolates',
        'RappiTravel',
        '🛵RappiFavor',
        'Lealtad',
        'Beneficios Pro',
      ])
      expect(screen.queryByText('Ordenadas según lo que más usas')).toBeNull()
    })

    test('al volver a la Home manda los toques en cola y vuelve a pedir el orden, sin volver a montarse', async () => {
      const orderRequests = () => api.mock.calls.filter(([url]) => url.includes('/verticales')).length
      let calls = 0
      api = stubAgent({
        'GET /profile/*': () => (++calls === 1 ? fixture('profile-verticales-nueva') : fixture('profile-verticales')),
      })
      const flushed = [] // cuántas veces se había pedido el orden cuando se mandaron los eventos
      const flush = events.flush
      events.flush = async () => void flushed.push(orderRequests())
      try {
        const { container, rerender } = await renderHome()
        await advance(300)
        expect(tiles(container)[0]).toBe('Súper')
        const home = container.querySelector('.home--live')
        fireEvent.click(screen.getByText('Farmacia'))
        rerender(homeTree({ active: false })) // otra pantalla encima
        await advance(300)
        expect(orderRequests()).toBe(1)
        rerender(homeTree({ active: true })) // vuelve a la Home
        await advance(300)
        expect(flushed).toEqual([1]) // primero los toques, después el orden
        expect(orderRequests()).toBe(2)
        expect(tiles(container).slice(0, 2)).toEqual(['Farmacia', 'Súper'])
        expect(screen.getByText('Ordenadas según lo que más usas')).toBeTruthy()
        expect(container.querySelector('.home--live')).toBe(home) // la misma Home: no se volvió a montar
      } finally {
        events.flush = flush
      }
    })

    test('tocar un vertical manda vertical_open con su código; RappiTravel y RappiFavor, service_opened una vez; Lealtad nada', async () => {
      stubAgent({ 'GET /profile/*': fixture('profile-verticales') })
      const push = vi.fn()
      await renderHome({ push })
      await advance(300)
      fireEvent.click(screen.getByText('Farmacia'))
      expect(events.track).toHaveBeenCalledWith('vertical_open', { vertical: 'farmacia' })
      fireEvent.click(screen.getByText('Restaurantes'))
      fireEvent.click(screen.getByText('Turbo'))
      expect(opened().map(([, fields]) => fields.vertical)).toEqual(['farmacia', 'restaurantes', 'turbo'])
      for (const name of ['Lealtad', 'RappiTravel', 'RappiFavor', 'Beneficios Pro'])
        fireEvent.click(screen.getByText(name))
      expect(opened()).toHaveLength(3)
      // Abrir un servicio desde la Home cuenta igual que desde Mochi: así la escalera no lo vuelve a ofrecer.
      const services = events.track.mock.calls.filter(([type]) => type === 'service_opened').map(([, fields]) => fields)
      // Con `desde: 'home'` el panel no los cuenta como aperturas de lo que ofreció Mochi.
      expect(services).toEqual([
        { payload: { servicio: 'rappitravel', desde: 'home' } },
        { payload: { servicio: 'rappifavor', desde: 'home' } },
      ])
    })
  })
})
