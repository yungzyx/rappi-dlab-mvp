import { beforeEach, describe, expect, test } from 'vitest'
import { route } from './index'
import { readState } from './state'
import { META, product } from '../../test/offlineMeta'

// «Pedir por mí» sin conexión (offers/autonomy.py en corto): los mismos límites que la API.
const coffee = product(1, { name: 'Café molido', price_value: 3990, store: 'Súper Centro', store_id: 11 })
const beer = product(2, { name: 'Cerveza lata', concept: 'cerveza', age_restricted: true, store_id: 11 })
const cookies = product(3, {
  name: 'Galletas',
  concept: 'galletas',
  price_value: 1290,
  store: 'Súper Norte',
  store_id: 12,
})
const snapshot = {
  meta: META,
  documents: 3,
  pool: [coffee, beer, cookies],
  byEntity: new Map(),
  catalog: { home: {}, restaurants: { rating: [] }, deals: {}, verticalStores: {}, stores: {}, menus: {} },
  recommendations: { rows: [] },
  complements: {},
}
const call = (method, path, body) => route(snapshot, { method, path, query: new URLSearchParams(), body })
const line = (p, qty = 1) => ({ entity_type: 'catalog_item', entity_id: p.entity_id, store_id: p.store_id, qty })
const order = (...lines) =>
  call('POST', '/orders', { user_id: 'u', vertical: 'supermercado', mode: 'propuesta', lines, cart_id: 'c' })
const say = (message, mode = 'propuesta') => call('POST', '/agent/ask', { message, user_id: 'u', mode }).body
const allow = (tiendas, tope = 20000) => call('PUT', '/profile/u/autonomia', { tiendas, tope })

beforeEach(() => localStorage.clear())

describe('pedir por mí sin conexión', () => {
  test('por defecto revisa antes; con permiso pide lo de siempre, y el pedido se vuelve a revisar', () => {
    order(line(coffee))
    expect(call('GET', '/profile/u/autonomia').body).toMatchObject({ modo: 'revisar', tiendas: [] })
    expect(say('pide lo de siempre en el super centro').autopedido).toMatchObject({
      modo: 'revisar',
      codigo: 'sin_permiso',
      subtotal: 3990,
    })

    expect(allow([11]).body.modo).toBe('pedir')
    const plan = say('lo de siempre').autopedido
    expect(plan).toMatchObject({ modo: 'pedir', tope: 20000, tienda: { id: 11, name: 'Súper Centro' } })
    expect(plan.basis.map((b) => b.kind)).toEqual(['permiso', 'tienda', 'tope', 'regla'])

    const placed = order(line(coffee))
    expect(placed.body.order_id).toBeTruthy()
    const auto = call('POST', '/orders', {
      user_id: 'u',
      vertical: 'supermercado',
      mode: 'propuesta',
      lines: [line(coffee)],
      autopedido: { request_id: 'r' },
    })
    expect(auto.body.order_id).toBeTruthy()
    expect(readState().orders.at(-1)).toMatchObject({ origin: 'agent-autopedido' })
    // Otra cantidad ya no es lo de siempre.
    const other = { user_id: 'u', vertical: 'supermercado', lines: [line(coffee, 3)], autopedido: {} }
    expect(call('POST', '/orders', other)).toMatchObject({ status: 409, body: { detail: { codigo: 'distinto' } } })
  })

  test('nunca sobre el tope, con alcohol ni en una tienda que no eligió', () => {
    order(line(coffee))
    allow([11], 3000)
    expect(say('lo de siempre').autopedido.codigo).toBe('tope')
    order(line(coffee), line(beer))
    allow([11])
    expect(say('lo de siempre').autopedido.codigo).toBe('guardia')
    call('POST', '/orders', { user_id: 'u', vertical: 'supermercado', lines: [line(cookies)], cart_id: 'c2' })
    expect(say('pide lo de siempre en el super norte').autopedido.codigo).toBe('tienda_no_elegida')
    expect(allow([99]).status).toBe(422)
  })

  test('se apaga en un toque, no corre en «Rappi hoy» y se va con «Olvidar»', () => {
    order(line(coffee))
    allow([11])
    expect(call('DELETE', '/profile/u/autonomia').body.modo).toBe('revisar')
    expect(say('lo de siempre').autopedido.codigo).toBe('sin_permiso')
    expect(say('lo de siempre', 'actual').autopedido).toBeUndefined()
    allow([11])
    call('DELETE', '/profile/u')
    expect(readState().autonomy).toBeUndefined()
  })
})

describe('las tiendas de sus pedidos en «Mis preferencias» (offers/preferences.py: ordered_stores)', () => {
  test('se ofrecen para marcarlas como favoritas, sin escribirlas, y marcarlas las guarda', () => {
    const stores = () => call('GET', '/profile/u/preferencias').body.opciones.filter((o) => o.tipo === 'tienda')
    expect(stores()).toEqual([])
    order(line(coffee))
    order(line(cookies))
    expect(stores().map((o) => o.nombre)).toEqual(['Súper Norte', 'Súper Centro'])
    const saved = call('PUT', '/profile/u/preferencias', { preferencias: [{ tipo: 'tienda', valor: 'Súper Norte' }] })
    expect(saved.body.preferencias).toEqual([{ tipo: 'tienda', valor: 'Súper Norte', nombre: 'Súper Norte' }])
  })

  test('una tienda que no encuentra no pide que se la escriban de nuevo', () => {
    const reply = say('mi tienda favorita es la inventada')
    expect(reply.text).not.toMatch(/dímela|escríbe/i)
    expect(reply.actions).toEqual([{ label: 'Ver mis preferencias', panel: 'preferencias' }])
  })
})
