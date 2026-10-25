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
