import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, test, vi } from 'vitest'
import { AGENT_NAME } from '../../agent/name'
import { AssistantProvider, useAssistant } from '../../state/AssistantContext'
import { CartProvider, formatPrice, useCart } from '../../state/CartContext'
import { DemoProvider } from '../../state/DemoContext'
import { OrdersProvider } from '../../state/OrdersContext'
import { ProductSheetProvider } from '../../state/ProductSheetContext'
import { ProfileProvider } from '../../state/ProfileContext'
import { DEFAULT_TIP, checkoutTotals, pricedBasket } from '../../screens/checkout/pricing'
import { fixture, stubApi } from '../../test/api'
import AssistantPanel from './AssistantPanel'

// Lo que Mochi sabe hacer al abrir, el resumen antes de pagar, el último pedido, cancelar una respuesta en curso y
// «Mis preferencias» (fase 5: la app de Rappi frente a Mochi).
const api = vi.hoisted(() => ({ health: vi.fn(), ask: vi.fn(), forget: vi.fn(), profile: vi.fn() }))
vi.mock('../../api/client', async (importOriginal) => ({ ...(await importOriginal()), ...api }))
const events = vi.hoisted(() => ({ track: vi.fn(), flush: vi.fn(), clear: vi.fn(), settled: vi.fn() }))
vi.mock('../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))

const advance = (ms) => act(() => vi.advanceTimersByTimeAsync(ms))
async function runUntilIdle() {
  await advance(0)
  for (let i = 0; i < 100 && vi.getTimerCount() > 0; i++) await advance(250)
}
const bubbles = () => [...document.querySelectorAll('.agent-msg-bubble')].map((el) => el.textContent)

const SUSHI = {
  id: 'menu-98005',
  name: 'Roll california 10 piezas (prueba)',
  price: '$6.990',
  entityType: 'menu_item',
  entityId: '98005',
  vertical: 'restaurants',
  concept: 'sushi',
  store: 'Sushi y hamburguesas de prueba Norte',
  storeId: 9802,
}

function Controls() {
  const assistant = useAssistant()
  const cart = useCart()
  return (
    <>
      <button type="button" onClick={() => assistant.open()}>
        abrir
      </button>
      <button type="button" onClick={(e) => assistant.open({ query: e.currentTarget.dataset.query })}>
        preguntar
      </button>
      <button type="button" onClick={() => cart.add(SUSHI)}>
        agregar sushi
      </button>
    </>
  )
}

function say(text) {
  const ask = screen.getByText('preguntar')
  ask.dataset.query = text
  fireEvent.click(ask)
}

async function renderPanel(push = vi.fn()) {
  render(
    <DemoProvider>
      <ProfileProvider>
        <AssistantProvider>
          <OrdersProvider>
            <CartProvider>
              <ProductSheetProvider>
                <Controls />
                <AssistantPanel push={push} />
              </ProductSheetProvider>
            </CartProvider>
          </OrdersProvider>
        </AssistantProvider>
      </ProfileProvider>
    </DemoProvider>,
  )
  fireEvent.click(screen.getByText('abrir'))
  await runUntilIdle()
  return push
}

let fetchMock
beforeAll(() => {
  Element.prototype.scrollTo = () => {}
})
afterAll(() => {
  delete Element.prototype.scrollTo
})
beforeEach(() => {
  vi.useFakeTimers()
  fetchMock = stubApi({
    '/catalog/home': fixture('catalog-home'),
    '/search': fixture('search-grouped'),
    'GET /agent/plans': fixture('agent-plans'),
    'POST /agent/offer': (req) => (req.body.moment === 'plan' ? fixture('agent-offer-plan') : 204),
    'GET /profile/*': (req) => (req.path.endsWith('/preferencias') ? fixture('profile-preferencias') : undefined),
    'PUT /profile/*': (req) => ({ ...fixture('profile-preferencias'), preferencias: req.body.preferencias }),
  })
  api.health.mockResolvedValue({})
  api.profile.mockResolvedValue({ interests: [] })
  events.settled.mockResolvedValue(undefined)
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
  Object.values(api).forEach((mock) => mock.mockReset())
  localStorage.clear()
  sessionStorage.clear()
})

describe('lo que Mochi sabe hacer', () => {
  test('al abrir muestra los atajos de lo que sabe hacer, sin salud, y el aviso de IA con su nombre', async () => {
    await renderPanel()
    expect(screen.getByText('Puedo ayudarte a:')).toBeTruthy()
    for (const label of ['🔁 Repite lo de siempre', '🧺 Arma un kit', '✨ Algo para ti'])
      expect(screen.getByRole('button', { name: label })).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/fiebre/i)
    expect(document.querySelector('.agent-ai-notice').textContent).toContain(`${AGENT_NAME} usa IA`)
  })

  test('«Repite lo de siempre» pide la recompra; sin nada que repetir, lo dice', async () => {
    await renderPanel()
    fireEvent.click(screen.getByRole('button', { name: '🔁 Repite lo de siempre' }))
    await runUntilIdle()
    const offerBody = JSON.parse(fetchMock.mock.calls.find(([url]) => url.endsWith('/agent/offer'))[1].body)
    expect(offerBody.moment).toBe('recompra')
    expect(bubbles().at(-1)).toMatch(/Todavía no veo algo que pidas seguido/)
  })

  test('«Arma un kit» deja elegir la ocasión y trae su kit', async () => {
    await renderPanel()
    fireEvent.click(screen.getByRole('button', { name: '🧺 Arma un kit' }))
    await runUntilIdle()
    expect(bubbles().at(-1)).toMatch(/¿Para qué te armo el kit\?/)
    const [first] = fixture('agent-plans')
    fireEvent.click(screen.getByRole('button', { name: new RegExp(first.name) }))
    await runUntilIdle()
    const sent = fetchMock.mock.calls.filter(([url]) => url.endsWith('/agent/offer')).map(([, init]) => init.body)
    expect(JSON.parse(sent.at(-1))).toMatchObject({ moment: 'plan', context: { occasion: first.id } })
    expect(bubbles().at(-1)).toBe(fixture('agent-offer-plan').text)
  })

  test('la ayuda trae los mismos atajos y tocarlos hace lo mismo', async () => {
    api.ask.mockResolvedValueOnce(fixture('agent-ask-ayuda'))
    await renderPanel()
    say('¿qué puedes hacer?')
    await runUntilIdle()
    const message = document.querySelector('.agent-msg-extras')
    fireEvent.click(within(message).getByRole('button', { name: /Repite lo de siempre/ }))
    await runUntilIdle()
    expect(bubbles().at(-1)).toMatch(/Todavía no veo algo que pidas seguido/)
  })
})

describe('la conversación y lo que no es de ella', () => {
  test('después de una oferta o un kit, «más barato» ya no refina la respuesta de antes', async () => {
    const beers = { ...fixture('agent-ask'), conversation: { query: 'cerveza', concepts: ['cerveza'] } }
    api.ask.mockResolvedValue(beers)
    await renderPanel()
    say('cerveza')
    await runUntilIdle()
    fireEvent.click(screen.getByRole('button', { name: '🔁 Repite lo de siempre' }))
    await runUntilIdle()
    say('más barato')
    await runUntilIdle()
    expect(api.ask.mock.calls.at(-1)[0].previous).toBeUndefined()
  })
})

describe('el resumen antes de pagar', () => {
  test('con el carro: productos, envío, tarifa, propina, total y tiempo, como el checkout; lleva a pagar', async () => {
    api.ask.mockResolvedValueOnce(fixture('agent-ask-resumen'))
    const push = await renderPanel()
    fireEvent.click(screen.getByText('agregar sushi'))
    say('quiero pagar')
    await runUntilIdle()
    const summary = screen.getByRole('region', { name: 'Resumen del pedido' })
    // Como el checkout: un restaurante sin condiciones del catálogo (sus supuestos), sin Pro y con la propina de siempre.
    const basket = { key: 'r', vertical: 'restaurantes', subtotal: 6990, lines: [] }
    const price = checkoutTotals([pricedBasket(basket, null)], { tip: DEFAULT_TIP })
    expect(summary.textContent).toContain('1 × Roll california 10 piezas (prueba)')
    for (const label of ['Productos', 'Envío', 'Tarifa de servicio', 'Propina', 'Total'])
      expect(within(summary).getByText(label)).toBeTruthy()
    expect(summary.textContent).toContain(formatPrice(price.total))
    expect(summary.textContent).toMatch(/de ejemplo/)
    fireEvent.click(screen.getByRole('button', { name: 'Revisar y pagar →' }))
    await runUntilIdle()
    expect(push).toHaveBeenCalledWith('checkout', undefined)
  })

  test('sin carro dice que está vacío y no lleva al checkout', async () => {
    api.ask.mockResolvedValueOnce(fixture('agent-ask-resumen'))
    await renderPanel()
    say('quiero pagar')
    await runUntilIdle()
    expect(screen.getByText(/Tu carro está vacío/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Revisar y pagar →' })).toBeNull()
  })

  test('el texto dice lo de hoy: con «Pedir por mí» Mochi sí pide; el pedido se cancela en su seguimiento', async () => {
    api.ask.mockResolvedValueOnce(fixture('agent-ask-resumen')).mockResolvedValueOnce(fixture('agent-ask-pedido'))
    await renderPanel()
    say('quiero pagar')
    await runUntilIdle()
    expect(bubbles().at(-1)).toMatch(/si no me diste permiso con «Pedir por mí», el pedido lo haces tú/)
    expect(bubbles().at(-1)).not.toMatch(/nunca hago el pedido/)
    say('¿dónde viene mi pedido?')
    await runUntilIdle()
    expect(bubbles().at(-1)).toMatch(/lo cancelas antes de que salga/)
    expect(bubbles().at(-1)).not.toMatch(/chat/)
  })
})

describe('el estado del pedido', () => {
  test('muestra el último pedido de la demo con su estado y lleva al seguimiento', async () => {
    const placedAt = Date.now() - 10_000 // en camino (progress.js)
    const order = { id: 'order-1', placedAt, stores: ['Pizzería'], items: [{ name: 'Pizza', qty: 2 }], total: 9990 }
    localStorage.setItem('rappi-proto-orders', JSON.stringify([order]))
    api.ask.mockResolvedValueOnce(fixture('agent-ask-pedido'))
    const push = await renderPanel()
    say('¿dónde viene mi pedido?')
    await runUntilIdle()
    const card = screen.getByRole('region', { name: 'Tu último pedido' })
    expect(card.textContent).toMatch(/En camino · llega en \d+ min/)
    expect(card.textContent).toContain('2 productos')
    fireEvent.click(within(card).getByRole('button', { name: 'Ver seguimiento →' }))
    await runUntilIdle()
    expect(push).toHaveBeenCalledWith('tracking', { orderId: 'order-1' })
  })
})

describe('el último pedido, con un botón', () => {
  const placedAt = () => Date.now() - 10_000
  const order = () => ({
    id: 'order-1',
    placedAt: placedAt(),
    stores: ['Pizzería'],
    items: [{ name: 'Pizza' }],
    total: 9990,
  })

  test('sin pedidos no hay botón; con uno, «Mi último pedido» lo muestra sin preguntarle a la API', async () => {
    await renderPanel()
    expect(screen.queryByRole('button', { name: '📦 Mi último pedido' })).toBeNull()
    cleanup()
    localStorage.setItem('rappi-proto-orders', JSON.stringify([order()]))
    const push = await renderPanel()
    fireEvent.click(screen.getByRole('button', { name: '📦 Mi último pedido' }))
    await runUntilIdle()
    expect(api.ask).not.toHaveBeenCalled()
    expect(bubbles().at(-1)).toBe('Así va tu último pedido 🛵')
    const card = screen.getByRole('region', { name: 'Tu último pedido' })
    fireEvent.click(within(card).getByRole('button', { name: 'Ver seguimiento →' }))
    await runUntilIdle()
    expect(push).toHaveBeenCalledWith('tracking', { orderId: 'order-1' })
  })

  test('con un pedido en curso muestra ese, no uno cancelado después; uno cancelado lo dice', async () => {
    const active = order()
    const cancelled = { ...order(), id: 'order-2', stores: ['Súper'], cancelled: { reason: 'ya_no', fee: 0 } }
    localStorage.setItem('rappi-proto-orders', JSON.stringify([cancelled, active]))
    await renderPanel()
    fireEvent.click(screen.getByRole('button', { name: '📦 Mi último pedido' }))
    await runUntilIdle()
    expect(bubbles().at(-1)).toBe('Así va tu último pedido 🛵')
    expect(screen.getByRole('region', { name: 'Tu último pedido' }).textContent).toContain('Pizzería')
    cleanup()
    localStorage.setItem('rappi-proto-orders', JSON.stringify([cancelled]))
    await renderPanel()
    fireEvent.click(screen.getByRole('button', { name: '📦 Mi último pedido' }))
    await runUntilIdle()
    expect(bubbles().at(-1)).toBe('Tu último pedido se canceló.')
  })

  test('en «Rappi hoy» el buscador con Mochi no se abre: es el buscador de siempre', async () => {
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    localStorage.setItem('rappi-proto-orders', JSON.stringify([order()]))
    await renderPanel()
    expect(screen.queryByRole('dialog', { name: /Buscador con/ })).toBeNull()
    expect(screen.queryByRole('button', { name: '📦 Mi último pedido' })).toBeNull()
  })
})

describe('mientras espera la respuesta', () => {
  test('dice qué hace y «Cancelar» corta la respuesta en curso', async () => {
    let signal
    api.ask.mockImplementationOnce((_payload, options) => {
      signal = options.signal
      return new Promise(() => {})
    })
    await renderPanel()
    say('sushi')
    await advance(500) // la pregunta sale cuando el panel terminó de abrirse
    expect(screen.getByText('Entendiendo tu pedido…')).toBeTruthy()
    await advance(1500)
    expect(screen.getByText('Buscando opciones…')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
    await runUntilIdle()
    expect(signal.aborted).toBe(true)
    expect(bubbles().at(-1)).toBe('Listo, paré aquí.')
  })
})

describe('mis preferencias', () => {
  test('se abren con su botón y todo se elige con opciones, también las tiendas de sus pedidos', async () => {
    const withStore = {
      ...fixture('profile-preferencias'),
      preferencias: [],
      opciones: [...fixture('profile-preferencias').opciones, { tipo: 'tienda', valor: 'Jumbo', nombre: 'Jumbo' }],
    }
    fetchMock = stubApi({
      '/catalog/home': fixture('catalog-home'),
      'GET /profile/*': (req) => (req.path.endsWith('/preferencias') ? withStore : undefined),
      'PUT /profile/*': (req) => ({ ...withStore, preferencias: req.body.preferencias }),
    })
    await renderPanel()
    fireEvent.click(screen.getByRole('button', { name: 'Mis preferencias' }))
    await runUntilIdle()
    const sheet = screen.getByRole('dialog', { name: 'Mis preferencias' })
    expect(sheet.querySelector('input, textarea')).toBeNull()
    expect(sheet.textContent).not.toMatch(/chat|dímel/i)
    fireEvent.click(within(sheet).getByRole('button', { name: 'Jumbo' }))
    fireEvent.click(within(sheet).getByRole('button', { name: 'Guardar' }))
    await runUntilIdle()
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
    expect(JSON.parse(put[1].body).preferencias).toEqual([{ tipo: 'tienda', valor: 'Jumbo' }])
  })

  test('sin tiendas de sus pedidos, dice que aparecen al pedir (no que se las escriba)', async () => {
    await renderPanel()
    fireEvent.click(screen.getByRole('button', { name: 'Mis preferencias' }))
    await runUntilIdle()
    const sheet = screen.getByRole('dialog', { name: 'Mis preferencias' })
    expect(sheet.textContent).toContain('Cuando pidas en una tienda, aparece aquí para marcarla.')
  })

  test('se abren desde la respuesta, muestran lo guardado y se guardan', async () => {
    api.ask.mockResolvedValueOnce(fixture('agent-ask-preferencia'))
    await renderPanel()
    say('soy vegetariano')
    await runUntilIdle()
    fireEvent.click(screen.getByRole('button', { name: 'Ver mis preferencias →' }))
    await runUntilIdle()
    const sheet = screen.getByRole('dialog', { name: 'Mis preferencias' })
    expect(within(sheet).getByRole('button', { name: 'Vegetariano' }).getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(within(sheet).getByRole('button', { name: 'Alergia al maní' }))
    fireEvent.click(within(sheet).getByRole('button', { name: 'Guardar' }))
    await runUntilIdle()
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
    expect(JSON.parse(put[1].body).preferencias).toEqual([
      { tipo: 'dieta', valor: 'vegetariano' },
      { tipo: 'alergia', valor: 'mani' },
    ])
  })
})
