import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useEffect } from 'react'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, test, vi } from 'vitest'
import { forgetStoreTerms } from '../../api/catalog'
import { AssistantProvider, useAssistant } from '../../state/AssistantContext'
import { CartProvider, useCart } from '../../state/CartContext'
import { DemoProvider } from '../../state/DemoContext'
import { OrdersProvider, useOrders } from '../../state/OrdersContext'
import { ProductSheetProvider } from '../../state/ProductSheetContext'
import { ProfileProvider } from '../../state/ProfileContext'
import { UNDO_MS } from '../../screens/checkout/undo'
import { fixture, stubApi } from '../../test/api'
import AssistantPanel from './AssistantPanel'

// "Pedir por mí" (fase 7): con permiso, Mochi pide solo lo de siempre y el pedido sale recién al cerrarse la ventana de
// "Deshacer pedido"; sin permiso, o si algo no calza, lo deja para revisar antes.
const api = vi.hoisted(() => ({ health: vi.fn(), ask: vi.fn(), forget: vi.fn(), profile: vi.fn() }))
vi.mock('../../api/client', async (importOriginal) => ({ ...(await importOriginal()), ...api }))
const events = vi.hoisted(() => ({ track: vi.fn(), flush: vi.fn(), clear: vi.fn(), settled: vi.fn() }))
vi.mock('../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))

const advance = (ms) => act(() => vi.advanceTimersByTimeAsync(ms))
async function untilShown() {
  // La respuesta, su texto letra por letra y la tarjeta ya a la vista (ahí se abre la ventana de deshacer).
  const shown = () => document.querySelector('.agent-msg-extras:not(.is-pending) .agent-auto')
  for (let i = 0; i < 100 && !shown(); i++) await advance(100)
}

let cartItems = []
let demoOrders = []
function Controls() {
  const assistant = useAssistant()
  const { items } = useCart()
  const { orders } = useOrders()
  useEffect(() => {
    cartItems = items
    demoOrders = orders
  })
  return (
    <button type="button" onClick={(e) => assistant.open({ query: e.currentTarget.dataset.query })}>
      preguntar
    </button>
  )
}

async function ask(text, push = vi.fn()) {
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
  const button = screen.getByText('preguntar')
  button.dataset.query = text
  fireEvent.click(button)
  await untilShown()
  return push
}

const orderCalls = () =>
  fetchMock.mock.calls.filter(([url, init]) => url.endsWith('/orders') && init?.method === 'POST')

let fetchMock
let ordersReply
beforeAll(() => {
  Element.prototype.scrollTo = () => {}
})
afterAll(() => {
  delete Element.prototype.scrollTo
})
beforeEach(() => {
  vi.useFakeTimers()
  ordersReply = { order_id: 'ord-1', lineas_omitidas: 0 }
  fetchMock = stubApi({
    '/catalog/home': fixture('catalog-home'),
    '/catalog/terms': fixture('catalog-terms'),
    'POST /agent/offer': 204,
    'GET /profile/*': (req) => (req.path.endsWith('/autonomia') ? fixture('profile-autonomia') : undefined),
    'DELETE /profile/*': () => ({ ...fixture('profile-autonomia'), modo: 'revisar', tiendas: [], tope: null }),
    'POST /orders': () => ordersReply,
  })
  api.health.mockResolvedValue({})
  api.profile.mockResolvedValue({ interests: [] })
  events.settled.mockResolvedValue(undefined)
  events.flush.mockResolvedValue(undefined)
})
afterEach(() => {
  cleanup()
  forgetStoreTerms()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
  Object.values(api).forEach((mock) => mock.mockReset())
  localStorage.clear()
  sessionStorage.clear()
})

describe('pedir por mí', () => {
  test('con permiso: el resumen ya enviado, y el pedido sale recién al cerrarse la ventana', async () => {
    api.ask.mockResolvedValue(fixture('agent-ask-autopedido'))
    await ask('pide lo de siempre en el supermercado de prueba centro')

    expect(document.querySelector('.agent-auto-window').textContent).toContain('Pedido enviado.')
    expect(screen.getByRole('button', { name: 'Deshacer pedido' })).toBeTruthy()
    expect(screen.getByText('$6.470')).toBeTruthy() // café $3.990 + envío $1.990 + tarifa de ejemplo $490
    expect(orderCalls()).toHaveLength(0)

    await advance(UNDO_MS)
    await advance(0)
    const [[, init]] = orderCalls()
    const body = JSON.parse(init.body)
    expect(body.autopedido).toEqual({ request_id: 'contrato-agent-ask-autopedido' })
    expect(body.mode).toBe('propuesta')
    expect(body.lines).toEqual([expect.objectContaining({ entity_id: '91004', store_id: 9101, qty: 1 })])
    await advance(0)
    expect(screen.getByText(/lo pedí por ti/)).toBeTruthy()
    expect(demoOrders).toHaveLength(1)
    expect(demoOrders[0]).toMatchObject({
      stores: ['Supermercado de prueba Centro'],
      storeId: 9101,
      vertical: 'supermercado',
      total: 6470,
      byAgent: true,
    })
  })

  test('"Deshacer pedido" no manda nada', async () => {
    api.ask.mockResolvedValue(fixture('agent-ask-autopedido'))
    await ask('pide lo de siempre')
    fireEvent.click(screen.getByRole('button', { name: 'Deshacer pedido' }))
    await advance(UNDO_MS * 2)
    expect(orderCalls()).toHaveLength(0)
    expect(screen.getByText('Deshiciste el pedido: no se pidió nada.')).toBeTruthy()
    expect(demoOrders).toHaveLength(0)
  })

  test('si la API no lo toma (409), queda para revisar con su motivo', async () => {
    api.ask.mockResolvedValue(fixture('agent-ask-autopedido'))
    ordersReply = new Response(
      JSON.stringify({ detail: { codigo: 'tope', motivo: 'pasa tu tope de $20.000 por pedido' } }),
      {
        status: 409,
        headers: { 'content-type': 'application/json' },
      },
    )
    await ask('pide lo de siempre')
    await advance(UNDO_MS)
    await advance(0)
    await advance(0)
    expect(screen.getByText('Esta vez lo revisas tú: pasa tu tope de $20.000 por pedido.')).toBeTruthy()
    expect(demoOrders).toHaveLength(0)
  })

  test('con envío y tarifa sobre el tope, no abre la ventana: lo deja para revisar', async () => {
    const reply = fixture('agent-ask-autopedido')
    reply.autopedido.tope = 6000
    api.ask.mockResolvedValue(reply)
    await ask('pide lo de siempre')
    expect(screen.queryByRole('button', { name: 'Deshacer pedido' })).toBeNull()
    expect(document.querySelector('.agent-msg-bubble').textContent).toBe(
      'Te armé lo de siempre en Supermercado de prueba Centro. Esta vez lo revisas tú: con envío y tarifa son $6.470: ' +
        'pasa tu tope de $6.000.',
    )
    await advance(UNDO_MS * 2)
    expect(orderCalls()).toHaveLength(0)
  })

  test('sin permiso: el resumen lleva al checkout de siempre con lo de siempre en el carro', async () => {
    api.ask.mockResolvedValue(fixture('agent-ask-autopedido-revisar'))
    const push = await ask('pide lo de siempre en el supermercado de prueba centro')
    expect(screen.queryByRole('button', { name: 'Deshacer pedido' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Revisar y pagar →' }))
    expect(cartItems.map((line) => [line.product.entityId, line.qty])).toEqual([['91004', 1]])
    expect(push).toHaveBeenCalledWith('checkout', undefined)
    await advance(UNDO_MS * 2)
    expect(orderCalls()).toHaveLength(0)
  })

  test('se apaga en un toque, y lo que estaba en su ventana no sale', async () => {
    api.ask.mockResolvedValue(fixture('agent-ask-autopedido'))
    await ask('pide lo de siempre')
    fireEvent.click(screen.getByRole('button', { name: 'Apagar "Pedir por mí"' }))
    await advance(UNDO_MS * 2)
    const deletes = fetchMock.mock.calls.filter(
      ([url, init]) => url.endsWith('/autonomia') && init?.method === 'DELETE',
    )
    expect(deletes).toHaveLength(1)
    expect(orderCalls()).toHaveLength(0)
  })

  test('otra respuesta no se lleva el "Deshacer pedido": la tarjeta queda fija y se puede deshacer', async () => {
    api.ask.mockResolvedValueOnce(fixture('agent-ask-autopedido')).mockResolvedValue(fixture('agent-ask'))
    await ask('pide lo de siempre')
    fireEvent.click(screen.getByRole('button', { name: '🍫 Algo dulce' }))
    await advance(1000)
    expect(api.ask).toHaveBeenCalledTimes(2)
    expect(document.querySelectorAll('.agent-auto')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Deshacer pedido' }))
    await advance(UNDO_MS * 2)
    expect(orderCalls()).toHaveLength(0)
    expect(demoOrders).toHaveLength(0)
  })

  test('si no se deshace, sale igual aunque haya llegado otra respuesta', async () => {
    api.ask.mockResolvedValueOnce(fixture('agent-ask-autopedido')).mockResolvedValue(fixture('agent-ask'))
    await ask('pide lo de siempre')
    fireEvent.click(screen.getByRole('button', { name: '🍫 Algo dulce' }))
    await advance(UNDO_MS)
    await advance(0)
    await advance(0)
    expect(orderCalls()).toHaveLength(1)
    expect(demoOrders).toHaveLength(1)
    // Ya salió: la tarjeta deja de estar fija y queda la última respuesta.
    expect(document.querySelector('.agent-auto')).toBeNull()
  })

  test('cerrar el buscador con el pedido en su ventana lo deshace: nada sale sin que se vea', async () => {
    api.ask.mockResolvedValue(fixture('agent-ask-autopedido'))
    await ask('pide lo de siempre')
    fireEvent.click(screen.getByRole('button', { name: 'Volver' }))
    await advance(UNDO_MS * 2)
    expect(orderCalls()).toHaveLength(0)
    expect(demoOrders).toHaveLength(0)
  })
})
