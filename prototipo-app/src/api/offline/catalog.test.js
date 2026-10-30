import { beforeEach, expect, test } from 'vitest'
import { catalogRoute, restaurantHours } from './catalog'
import { route } from './index'
import { META } from '../../test/offlineMeta'

// Jueves 22-10-2026 en Santiago (UTC−3).
const at = (hour, minute = 0, day = 22) => Date.UTC(2026, 9, day, hour + 3, minute)
const EVERY_DAY = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'].map((day) => ({
  day,
  open: '11:00',
  close: '23:00',
}))

test('el horario publicado se compara con la hora de Santiago, como catalog/hours.py', () => {
  expect(restaurantHours(EVERY_DAY, at(13))).toMatchObject({ open: true, closes_at: '23:00' })
  expect(restaurantHours(EVERY_DAY, at(9))).toMatchObject({ open: false, opens_at: '11:00', opens_tomorrow: false })
  expect(restaurantHours(EVERY_DAY, at(23, 30))).toMatchObject({ open: false, opens_at: '11:00', opens_tomorrow: true })
  const late = [{ day: 'wed', open: '19:00', close: '02:00' }]
  expect(restaurantHours(late, at(1)).open).toBe(true) // jueves 1:00: un solo día publicado vale para todos
  expect(restaurantHours([], at(13)).open).toBeNull()
})

test('la lista de restaurantes filtra como la API y deja los cerrados al final', () => {
  const card = (id, extra) => ({ id, name: `R${id}`, eta: '30 min', rating: 4.6, reviews: 120, promo: false, ...extra })
  const snapshot = {
    catalog: {
      restaurants: {
        rating: [
          card(1, { schedule: [{ day: 'thu', open: '20:00', close: '23:00' }] }),
          card(2, { eta: '40 min', promo: true }),
          card(3, { rating: 4.2, reviews: 500 }),
        ],
      },
    },
  }
  const list = (search) =>
    catalogRoute(snapshot, 'GET', '/catalog/restaurants', new URLSearchParams(search), at(13)).body.map((r) => r.id)
  expect(list('')).toEqual([2, 3, 1])
  expect(list('max_eta=35')).toEqual([3, 1])
  expect(list('top=true')).toEqual([2, 1])
  expect(list('promo=true')).toEqual([2])
  expect(list('sort=recommended')).toEqual([3, 2, 1])
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
