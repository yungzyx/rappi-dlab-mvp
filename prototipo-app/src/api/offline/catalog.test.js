import { beforeEach, expect, test } from 'vitest'
import { catalogRoute } from './catalog'
import { route } from './index'
import { META } from '../../test/offlineMeta'

// Jueves 22-10-2026 en Santiago (UTC−3).
const at = (hour, minute = 0, day = 22) => Date.UTC(2026, 9, day, hour + 3, minute)
const CLOSED = { source: 'horario', open: false, closes_at: null, opens_at: '11:00', opens_tomorrow: true, today: null }

test('sin conexión todo está abierto, a cualquier hora, aunque la muestra lo grabara cerrado', () => {
  const restaurant = { id: 1, name: 'R1', hours: CLOSED, schedule: [{ day: 'thu', open: '11:00', close: '15:00' }] }
  const snapshot = {
    meta: META,
    catalog: {
      home: { fast_restaurants: [restaurant], nearby_stores: [{ id: 11, name: 'Súper', hours: CLOSED }] },
      restaurants: { rating: [restaurant] },
      menus: { 1: { restaurant, sections: [] } },
      stores: { 11: { store: { id: 11, name: 'Súper', hours: CLOSED }, aisles: [], pages: {} } },
    },
  }
  const get = (path) => route(snapshot, { method: 'GET', path, query: new URLSearchParams() }, at(23, 30)).body
  const open = { source: 'horario', open: true, closes_at: null, opens_at: null, opens_tomorrow: false }
  expect(get('/catalog/home').fast_restaurants[0].hours).toMatchObject(open)
  expect(get('/catalog/home').nearby_stores[0].hours).toMatchObject(open)
  expect(get('/catalog/restaurants')[0].hours).toMatchObject(open)
  expect(get('/catalog/restaurants/1/menu').restaurant.hours).toMatchObject(open)
  expect(get('/catalog/stores/11').store.hours).toMatchObject(open)
  // La muestra no cambia: lo abierto se arma en cada respuesta.
  expect(snapshot.catalog.stores[11].store.hours.open).toBe(false)
})

test('la lista de restaurantes filtra como la API', () => {
  const card = (id, extra) => ({ id, name: `R${id}`, eta: '30 min', rating: 4.6, reviews: 120, promo: false, ...extra })
  const snapshot = {
    catalog: {
      restaurants: {
        rating: [card(1), card(2, { eta: '40 min', promo: true }), card(3, { rating: 4.2, reviews: 500 })],
      },
    },
  }
  const list = (search) =>
    catalogRoute(snapshot, 'GET', '/catalog/restaurants', new URLSearchParams(search)).body.map((r) => r.id)
  expect(list('')).toEqual([1, 2, 3])
  expect(list('max_eta=35')).toEqual([1, 3])
  expect(list('top=true')).toEqual([1, 2])
  expect(list('promo=true')).toEqual([2])
  expect(list('sort=recommended')).toEqual([3, 1, 2])
})

test('la Home de la demo dice la fecha de los precios de su muestra, y nada si la muestra no la grabó', () => {
  const catalogo = { desde: '2026-09-24', hasta: '2026-10-18', verticales: {} }
  const home = (recorded) =>
    catalogRoute({ catalog: { home: recorded } }, 'GET', '/catalog/home', new URLSearchParams()).body
  expect(home({ nearby_stores: [], catalogo }).catalogo).toEqual(catalogo)
  expect(home({ nearby_stores: [] })).not.toHaveProperty('catalogo')
})

beforeEach(() => localStorage.clear())

test('las búsquedas recientes salen de los eventos de este navegador, sin "Lo más buscado"', () => {
  const snapshot = { meta: META, catalog: { home: {}, restaurants: { rating: [] } } }
  const call = (method, path, body) => route(snapshot, { method, path, query: new URLSearchParams(), body })
  call('POST', '/events', {
    user_id: 'p',
    events: [
      { type: 'search', query: 'pizza' },
      { type: 'search', query: 'agua' },
      { type: 'search', query: 'Pizza' },
    ],
  })
  const reply = call('GET', '/profile/p/busquedas').body
  expect(reply.recientes).toEqual(['Pizza', 'agua'])
  expect(reply.mas_buscado).toEqual([])
  expect(reply.request_id).toMatch(/^offline-/)
})

test('una tienda o un restaurante cuya página no se grabó se abre con los productos que la muestra trae de él', () => {
  const item = (type, id, store, extra = {}) => ({
    id: `${type === 'menu_item' ? 'menu' : 'cat'}-${id}`,
    entity_type: type,
    entity_id: String(id),
    name: `Producto ${id}`,
    vertical: type === 'menu_item' ? 'restaurantes' : 'supermercado',
    price: '$1.000',
    store: type === 'menu_item' ? 'Sushi de prueba' : 'Súper de prueba',
    store_id: store,
    img: `foto-${id}.webp`,
    ...extra,
  })
  const snapshot = {
    catalog: { stores: {}, menus: {} },
    pool: [
      item('catalog_item', 1, 77),
      item('catalog_item', 1, 77),
      item('catalog_item', 2, 77),
      item('menu_item', 3, 88),
    ],
  }
  const get = (path) => catalogRoute(snapshot, 'GET', path, new URLSearchParams())

  const shop = get('/catalog/stores/77').body
  expect(shop.store).toMatchObject({ id: 77, name: 'Súper de prueba', vertical: 'supermercado' })
  expect(shop.aisles).toEqual([{ id: 0, name: 'En la muestra de la demo', products: 2 }])
  expect(shop.products.map((p) => p.entity_id)).toEqual(['1', '2'])
  expect(shop.has_more).toBe(false)

  const menu = get('/catalog/restaurants/88/menu').body
  expect(menu.restaurant).toMatchObject({ id: 88, name: 'Sushi de prueba', cover: 'foto-3.webp' })
  expect(menu.sections).toEqual([{ name: 'En la muestra de la demo', items: [snapshot.pool[3]] }])

  // Sin nada de ella en la muestra sigue siendo un 404, y un plato no abre una tienda (ni al revés).
  expect(get('/catalog/stores/99').status).toBe(404)
  expect(get('/catalog/stores/88').status).toBe(404)
  expect(get('/catalog/restaurants/77/menu').status).toBe(404)
})

test('con una cocina elegida, la lista de restaurantes se ordena como se pide', () => {
  const card = (id, eta, fee) => ({ id, name: `R${id}`, eta, fee, cuisines: ['Pizzas'], reviews: id })
  const pizzas = [card(1, '45 min', '$2.990'), card(2, '15 min', '$990')]
  const snapshot = { catalog: { restaurants: { rating: pizzas, 'rating|Pizzas': pizzas } } }
  const list = (search) =>
    catalogRoute(snapshot, 'GET', '/catalog/restaurants', new URLSearchParams(search)).body.map((r) => r.id)
  expect(list('cuisine=Pizzas')).toEqual([1, 2])
  expect(list('cuisine=Pizzas&sort=eta')).toEqual([2, 1])
  expect(list('cuisine=Pizzas&sort=fee')).toEqual([2, 1])
  expect(list('cuisine=pizzas&sort=recommended')).toEqual([2, 1]) // sin lista grabada para ella: la filtra de la general
  expect(snapshot.catalog.restaurants['rating|Pizzas'].map((r) => r.id)).toEqual([1, 2]) // la muestra no cambia
})
