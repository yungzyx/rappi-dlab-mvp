import { beforeEach, expect, test } from 'vitest'
import { route } from './index'
import { readState } from './state'
import { META, product } from '../../test/offlineMeta'

const snapshot = {
  meta: META,
  documents: 3,
  pool: [],
  byEntity: new Map(),
  catalog: { home: {}, restaurants: { rating: [] }, deals: {}, verticalStores: {}, stores: {}, menus: {} },
  recommendations: { rows: [] },
  complements: {},
}
const call = (method, path, body, now) => {
  const [pathname, search = ''] = path.split('?')
  return route(snapshot, { method, path: pathname, query: new URLSearchParams(search), body }, now)
}

beforeEach(() => localStorage.clear())

test('la sesión, los eventos y los pedidos ordenan la Home; "Rappi hoy" no; "Olvidar" lo borra', () => {
  const { body: session } = call('POST', '/session', {})
  expect(session.user_id).toMatch(/^proto-/)
  const id = session.user_id
  call('POST', '/events', {
    user_id: id,
    events: [
      { type: 'vertical_open', vertical: 'chocolateria', payload: { mode: 'actual' } },
      { type: 'vertical_open', vertical: 'pharmacy' },
    ],
  })
  // Otro toque a Farmacia, de ayer: la Home pide uso en dos días distintos (motor.js: MIN_USE_DAYS).
  const yesterday = Date.now() - 86_400_000
  call('POST', '/events', { user_id: id, events: [{ type: 'vertical_open', vertical: 'pharmacy' }] }, yesterday)
  expect(readState().events.map((e) => e.vertical)).toEqual(['chocolateria', 'farmacia', 'farmacia'])
  const order = call('POST', `/profile/${id}/verticales`)
  expect(order.status).toBe(404)
  const home = call('GET', `/profile/${id}/verticales`).body
  expect(home.order[0].id).toBe('farmacia')

  const coffee = product(1)
  const placed = call('POST', '/orders', {
    user_id: id,
    vertical: 'grocery',
    mode: 'propuesta',
    lines: [{ entity_type: 'catalog_item', entity_id: '1', concept_id: coffee.concept, qty: 1 }],
  })
  expect(placed.body.order_id).toMatch(/^o-/)
  expect(readState().orders[0].vertical).toBe('supermercado')
  expect(call('POST', '/orders', { user_id: id, vertical: 'pet', lines: [{}] }).status).toBe(400)

  expect(call('DELETE', `/profile/${id}`).body.eventos_borrados).toBe(4)
  expect(call('GET', `/profile/${id}/verticales`).body.personalized).toBe(false)
})

test('una oferta sin nada que decir es un 204; una ruta desconocida, un 404', () => {
  expect(call('POST', '/agent/offer', { moment: 'recompra', context: {} })).toEqual({ status: 204, body: null })
  // "¿Volvemos a…?" necesita semanas de pedidos (el panel de la demo siembra personas con ellas)
  expect(call('POST', '/agent/offer', { moment: 'volver', context: {} })).toEqual({ status: 204, body: null })
  expect(call('GET', '/analytics/kpis').status).toBe(404)
  expect(call('GET', '/health').body).toMatchObject({ ok: true, documentos: 3 })
})

test('las respuestas que ordenan cosas traen su request_id, como la API; las demás no', () => {
  const id = call('POST', '/session', {}).body.user_id
  for (const path of [`/profile/${id}/verticales`, '/catalog/home', `/recommendations?user_id=${id}`])
    expect(call('GET', path).body.request_id).toMatch(/^offline-[0-9a-f]{16}$/)
  expect(call('GET', '/health').body.request_id).toBeUndefined()
  expect(call('POST', '/agent/offer', { moment: 'recompra', context: {} })).toEqual({ status: 204, body: null })
})

test('el origen de un evento se guarda de la columna nueva o del payload de antes', () => {
  const id = call('POST', '/session', {}).body.user_id
  call('POST', '/events', {
    user_id: id,
    events: [
      { type: 'suggestion_shown', origin: 'agent-volver', payload: { kind: 'volver' } },
      { type: 'suggestion_shown', payload: { origen: 'agent-recompra' } },
    ],
  })
  expect(readState().events.map((e) => e.origin)).toEqual(['agent-volver', 'agent-recompra'])
})

test('"Pídelo de nuevo": lo que la muestra tiene en esa tienda, con su precio; lo demás no está disponible', () => {
  const coffee = product(1)
  snapshot.pool = [coffee]
  const lines = [
    { entity_type: 'catalog_item', entity_id: coffee.entity_id, store_id: coffee.store_id },
    { entity_type: 'catalog_item', entity_id: coffee.entity_id, store_id: 999 },
    { entity_type: 'menu_item', entity_id: '42' },
  ]
  const { body } = call('POST', '/catalog/availability', { lines })
  expect(body.lines).toEqual([
    { ...lines[0], available: true, price: coffee.price_value },
    { ...lines[1], available: false, price: null },
    { ...lines[2], store_id: null, available: false, price: null },
  ])
  snapshot.pool = []
})

test('la calificación queda con su carro y el pedido guarda el suyo: con eso se pausa la recompra', () => {
  call('POST', '/orders', {
    user_id: 'u',
    cart_id: 'c-1',
    vertical: 'supermercado',
    lines: [{ entity_type: 'catalog_item', entity_id: '1' }],
  })
  call('POST', '/events', { user_id: 'u', events: [{ type: 'order_rated', cart_id: 'c-1', payload: { stars: 2 } }] })
  const saved = readState()
  expect(saved.orders[0].cart_id).toBe('c-1')
  expect(saved.events.find((e) => e.type === 'order_rated')).toMatchObject({ cart_id: 'c-1', payload: { stars: 2 } })
})

test('acepta los eventos de la pregunta in-app (survey_shown, survey_answer y survey_dismissed)', () => {
  const asked = (type, payload) => ({
    type,
    request_id: 'offline-1',
    payload: { question: 'p1', trigger: 'carro', ...payload },
  })
  const reply = call('POST', '/events', {
    user_id: 'u',
    events: [asked('survey_shown'), asked('survey_answer', { answer: 'si' }), asked('survey_dismissed')],
  })
  expect(reply.body).toEqual({ guardados: 3 })
  expect(readState().events.map((e) => [e.type, e.payload.answer])).toEqual([
    ['survey_shown', undefined],
    ['survey_answer', 'si'],
    ['survey_dismissed', undefined],
  ])
})

test('order_cancelled cancela el pedido de su carro y su tienda (en los dos modos); el otro de la compra sigue', () => {
  const placed = (vertical, store) =>
    call('POST', '/orders', {
      user_id: 'u',
      cart_id: 'c-2',
      vertical,
      lines: [{ entity_type: 'catalog_item', entity_id: '1', store_id: store }],
    })
  placed('supermercado', 1)
  placed('turbo', 2)
  const cancel = { type: 'order_cancelled', cart_id: 'c-2', payload: { reason: 'ya_no', stage: 'antes_de_tienda' } }
  call('POST', '/events', {
    user_id: 'u',
    events: [{ ...cancel, payload: { ...cancel.payload, store_id: 2, mode: 'actual' } }],
  })
  expect(readState().orders.map((o) => [o.vertical, o.status ?? 'confirmado'])).toEqual([
    ['supermercado', 'confirmado'],
    ['turbo', 'cancelado'],
  ])
})

test('/catalog/terms sin conexión: el envío de los restaurantes grabados y null en lo demás; un pedido es de una tienda', () => {
  const sample = {
    ...snapshot,
    catalog: {
      ...snapshot.catalog,
      menus: { 9801: { restaurant: { id: 9801, fee: '$1.490' }, sections: [] } },
      stores: { 9101: { store: { id: 9101 }, aisles: [], pages: {} } },
    },
  }
  const { body } = route(sample, {
    method: 'GET',
    path: '/catalog/terms',
    query: new URLSearchParams('stores=9801,9101,1'),
  })
  expect(body.stores).toEqual([
    { store_id: 9801, delivery_fee: 1490, min_order: null, service_pct: null },
    { store_id: 9101, delivery_fee: null, min_order: null, service_pct: null },
  ])
  const line = (store_id) => ({ entity_type: 'catalog_item', entity_id: '1', store_id })
  const order = { user_id: 'u', vertical: 'supermercado', lines: [line(9101), line(9102)] }
  expect(call('POST', '/orders', order)).toMatchObject({ status: 400 })
  expect(call('POST', '/orders', { ...order, lines: [line(9101), line(9101)] }).status ?? 200).toBe(200)
})

test('POST /orders: un pedido de Mochi no se programa y una franja es de hoy o mañana (api/app.py)', () => {
  const { body: session } = call('POST', '/session', {})
  const base = {
    user_id: session.user_id,
    vertical: 'grocery',
    mode: 'propuesta',
    lines: [{ entity_type: 'catalog_item', entity_id: '1', qty: 1 }],
  }
  const soon = new Date(Date.now() + 2 * 3_600_000).toISOString()
  expect(call('POST', '/orders', { ...base, scheduled_for: soon }).body.order_id).toMatch(/^o-/)
  expect(call('POST', '/orders', { ...base, scheduled_for: soon, autopedido: {} })).toMatchObject({ status: 400 })
  const later = new Date(Date.now() + 5 * 86_400_000).toISOString()
  expect(call('POST', '/orders', { ...base, scheduled_for: later })).toMatchObject({
    status: 400,
    body: { detail: 'Solo se programa para hoy o mañana' },
  })
})

test('un pedido no suma interés aparte de sus eventos, como en la API', () => {
  const { body: session } = call('POST', '/session', {})
  const id = session.user_id
  call('POST', '/orders', {
    user_id: id,
    vertical: 'grocery',
    mode: 'propuesta',
    lines: [{ entity_type: 'catalog_item', entity_id: '1', concept_id: 'cafe', qty: 1 }],
  })
  expect(call('GET', `/profile/${id}`).body.interests).toEqual([])
})

test('el tope diario: con 5 sugerencias de las respuestas vistas hoy, Mochi responde sin la suya (rappi_agent.py)', () => {
  const recorded = {
    text: 'Mira lo que encontré de "cerveza" en Licores.',
    products: [],
    reason: 'Porque llevas 🍺 cerveza',
    suggestion: { concept: 'snacks-salados', vertical: 'supermercado', products: [] },
  }
  const withAsk = { ...snapshot, ask: { cerveza: recorded } }
  const at = (now) => (method, path, body) => route(withAsk, { method, path, query: new URLSearchParams(), body }, now)
  const today = Date.parse('2026-11-03T15:00:00-03:00')
  const id = at(today)('POST', '/session', {}).body.user_id
  const shown = (origin) => ({ type: 'suggestion_shown', concept_id: 'pizza', origin })
  const ask = { message: 'cerveza', user_id: id, mode: 'propuesta' }

  // la de anoche (otro día en Santiago) y la oferta de un momento no cuentan
  at(today - 16 * 3_600_000)('POST', '/events', { user_id: id, events: [shown('agent-ask')] })
  at(today)('POST', '/events', {
    user_id: id,
    events: [...Array.from({ length: 4 }, () => shown('agent-ask')), shown('agent-plan')],
  })
  expect(at(today)('POST', '/agent/ask', ask).body.suggestion.concept).toBe('snacks-salados')

  at(today)('POST', '/events', { user_id: id, events: [shown('agent-ask')] })
  const capped = at(today)('POST', '/agent/ask', ask).body
  expect(capped.suggestion).toBeUndefined()
  expect(capped.reason).toBeNull()
  expect(capped.text).toBe(recorded.text)
})

test('preguntarle a Mochi suma al interés como en la API (un `ask` con su concepto); en "Rappi hoy", no', () => {
  // La respuesta grabada de la API real a esa pregunta, con lo que entendió.
  const recorded = {
    text: 'Mira lo que encontré de "café".',
    products: [],
    intent: { kind: 'buscar', concepts: ['cafe'] },
  }
  const withAsk = { ...snapshot, ask: { 'quiero un cafe': recorded } }
  const asks = (body) => route(withAsk, { method: 'POST', path: '/agent/ask', query: null, body })
  const id = call('POST', '/session', {}).body.user_id
  asks({ message: 'quiero un café', user_id: id, mode: 'actual' })
  expect(call('GET', `/profile/${id}`).body.interests).toEqual([])
  asks({ message: 'quiero un café', user_id: id, mode: 'propuesta' })
  expect(
    readState()
      .events.filter((e) => e.type === 'ask')
      .map((e) => [e.concept_id, e.payload.mode]),
  ).toEqual([
    [null, 'actual'],
    ['cafe', 'propuesta'],
  ])
  expect(call('GET', `/profile/${id}`).body.interests.map((i) => i.concept)).toEqual(['cafe'])
})

test('el concepto de una búsqueda sale del texto (el corregido si lo hay), no del que manda la app', () => {
  const id = call('POST', '/session', {}).body.user_id
  call('POST', '/events', {
    user_id: id,
    events: [
      { type: 'search', query: 'cafe', concept_id: 'galletas' },
      { type: 'search', query: 'galeta', payload: { corregida: 'galleta' } },
      { type: 'search', query: 'cerveza', payload: { mode: 'actual' } },
    ],
  })
  expect(readState().events.map((e) => e.concept_id)).toEqual(['cafe', 'galletas', null])
})
