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
const call = (method, path, body) => {
  const [pathname, search = ''] = path.split('?')
  return route(snapshot, { method, path: pathname, query: new URLSearchParams(search), body })
}

beforeEach(() => localStorage.clear())

test('la sesión, los eventos y los pedidos ordenan la Home; «Rappi hoy» no; «Olvidar» lo borra', () => {
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
  expect(readState().events.map((e) => e.vertical)).toEqual(['chocolateria', 'farmacia'])
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

  expect(call('DELETE', `/profile/${id}`).body.eventos_borrados).toBe(3)
  expect(call('GET', `/profile/${id}/verticales`).body.personalized).toBe(false)
})

test('una oferta sin nada que decir es un 204; una ruta desconocida, un 404', () => {
  expect(call('POST', '/agent/offer', { moment: 'recompra', context: {} })).toEqual({ status: 204, body: null })
  // «¿Volvemos a…?» necesita semanas de pedidos (el panel de la demo siembra personas con ellas)
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

test('«Pídelo de nuevo»: lo que la muestra tiene en esa tienda, con su precio; lo demás no está disponible', () => {
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
