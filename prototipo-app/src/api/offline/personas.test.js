import { afterEach, expect, test, vi } from 'vitest'
import { homeVerticals, targetStep } from './motor'
import {
  clearHistory,
  ladderReadout,
  personaHistory,
  personas,
  startingHistory,
  startingPersona,
  switchPersona,
} from './personas'
import { route } from './index'
import { readState, writeState } from './state'
import { profileOffer, tastesReply } from './tastes'
import { COMBOS, LABELS, META, product } from '../../test/offlineMeta'

const NOW = Date.UTC(2026, 9, 17, 15)

afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})
const VERTICALS = ['restaurantes', 'turbo', 'supermercado', 'conveniencia', 'mall', 'chocolateria', 'farmacia']
const sushi = product(9, {
  name: 'Roll de salmón',
  concept: 'sushi',
  vertical: 'restaurantes',
  entity_type: 'menu_item',
})
const tacos = product(10, {
  name: 'Tacos al pastor',
  concept: 'mexicana',
  vertical: 'restaurantes',
  entity_type: 'menu_item',
})
const snapshot = {
  meta: {
    ...META,
    concepts: {
      ...META.concepts,
      sushi: { name: 'Sushi', emoji: '🍣', group: 'comida', offerable: true },
      mexicana: { name: 'Comida mexicana', emoji: '🌮', group: 'comida', offerable: true },
    },
    profiles: {
      asiatico: { name: 'Amante de lo asiático', emoji: '🥢', main: false, concepts: ['sushi', 'asiatica'] },
      mexicano: { name: 'Amante de lo mexicano', emoji: '🌮', main: true, concepts: ['mexicana'] },
    },
  },
  pool: VERTICALS.map((vertical, i) => product(i + 1, { vertical })),
  tastes: {
    asiatico: {
      gustos: { id: 'asiatico', nombre: 'Amante de lo asiático', emoji: '🥢', nivel: 'medio', principal: true },
      ladder: { moment: 'perfil', escalera: [] },
      seed: [sushi, sushi, sushi],
    },
    mexicano: {
      gustos: { id: 'mexicano', nombre: 'Amante de lo mexicano', emoji: '🌮', nivel: 'medio', principal: true },
      ladder: { moment: 'perfil', escalera: [] },
      seed: [tacos, { ...tacos, entity_id: '11' }, { ...tacos, entity_id: '12' }],
    },
  },
}
const persona = (id) => personas(snapshot).find((p) => p.id === id)
const stateOf = (id) => ({ userId: 'proto-test', ...personaHistory(snapshot, persona(id), NOW) })

test('las personas de la escalera están donde dice su nombre, y la línea del panel lo muestra', () => {
  expect(targetStep(COMBOS, stateOf('restaurantes'), NOW).vertical).toBe('turbo')
  expect(targetStep(COMBOS, stateOf('rest-turbo'), NOW).vertical).toBe('supermercado')
  expect(targetStep(COMBOS, stateOf('todo'), NOW).vertical).toBe('favor')
  expect(ladderReadout(snapshot, stateOf('rest-turbo'), NOW)).toBe('Hoy: Restaurantes y Turbo → siguiente: Súper')
  expect(ladderReadout(snapshot, stateOf('rest-turbo-super'), NOW)).toBe(
    'Hoy: Restaurantes, Turbo y Súper → siguiente: Rappi Mall',
  )
  expect(ladderReadout(snapshot, stateOf('todo'), NOW)).toMatch(/→ siguiente: RappiFavor$/)
  expect(ladderReadout(snapshot, stateOf('nueva'), NOW)).toMatch(/^Hoy: sin pedidos/)
})

test('"Usa mucho Farmacia" la sube primera en la Home y Mochi igual nunca la ofrece', () => {
  const state = stateOf('farmacia')
  expect(homeVerticals(state, NOW, LABELS, META.concepts).order[0].id).toBe('farmacia')
  expect(targetStep(COMBOS, state, NOW).vertical).toBe('turbo')
})

test('una persona de gusto activa su perfil (tres pedidos de sus conceptos) y recibe su escalera grabada', () => {
  const taste = persona('gusto-asiatico')
  expect(taste.label).toBe('🥢 Amante de lo asiático')
  const state = stateOf('gusto-asiatico')
  expect(tastesReply(snapshot, state).perfiles.map((p) => p.id)).toEqual(['asiatico'])
  expect(profileOffer(snapshot, state)).toEqual({ moment: 'perfil', escalera: [] })
  const two = { ...state, orders: state.orders.slice(1) }
  expect(tastesReply(snapshot, two).perfiles).toEqual([])
  expect(profileOffer(snapshot, two)).toBeNull()
})

test('una muestra grabada sin `gusto` ni `conceptos` los toma de meta, y sin `gusto` en meta no lo inventa', () => {
  const state = stateOf('gusto-asiatico')
  const basis = [
    { kind: 'concepto', id: 'sushi', score: 2, source: 'segmento:sushi' },
    { kind: 'concepto', id: 'sushi', score: 3, source: 'pedidos' },
  ]
  const recorded = { ...snapshot, tastes: { asiatico: { ...snapshot.tastes.asiatico } } }
  recorded.tastes.asiatico.gustos = { ...snapshot.tastes.asiatico.gustos, basis }
  const [old] = tastesReply(recorded, state).perfiles
  expect(old.gusto).toBeUndefined()
  expect(old.conceptos).toEqual({ sushi: { nombre: 'Sushi', emoji: '🍣' } })

  const withMeta = {
    ...recorded,
    meta: { ...recorded.meta, profiles: { asiatico: { ...recorded.meta.profiles.asiatico, gusto: 'lo asiático' } } },
  }
  expect(tastesReply(withMeta, state).perfiles[0].gusto).toBe('lo asiático')
})

test('una persona de la escalera pide un concepto distinto en cada vertical (sin "¿Repetimos?" por accidente)', () => {
  // El primer producto de Rappi Mall es del mismo concepto que el de Restaurantes: se elige el siguiente.
  const pool = VERTICALS.map((vertical, i) => product(i + 1, { vertical, concept: `c${i}` }))
  const clash = product(20, { vertical: 'mall', concept: 'c0' })
  const withClash = { ...snapshot, pool: [clash, ...pool] }
  const all = personas(withClash).find((p) => p.id === 'todo')
  const concepts = personaHistory(withClash, all, NOW).orders.map((o) => o.lines[0].concept_id)
  expect(concepts).toEqual(['c0', 'c1', 'c2', 'c3', 'c4', 'c5'])
})

test('el plato que pide es de un restaurante que está en la muestra', () => {
  const dish = (id, concept, store) =>
    product(id, { concept, vertical: 'restaurantes', entity_type: 'menu_item', store_id: store })
  const pool = [dish(50, 'pizza', 7), dish(51, 'sushi', 8)]
  const concepts = {
    ...snapshot.meta.concepts,
    pizza: { name: 'Pizza', emoji: '🍕', group: 'comida', offerable: true },
  }
  const withMenus = {
    ...snapshot,
    meta: { ...snapshot.meta, concepts },
    pool,
    catalog: { menus: { 8: {} }, stores: {} },
  }
  const persona = personas(withMenus).find((p) => p.id === 'restaurantes')
  const ordered = personaHistory(withMenus, persona, NOW).orders.map((o) => o.lines[0].concept_id)
  // La pizza va antes en la lista, pero su restaurante no está en la muestra.
  expect(ordered).toEqual(['sushi'])
})

test('las personas del panel piden lo que lo destacado mostraría: un plato principal con foto y, en Turbo, comida', () => {
  const img = 'https://imagenes.prueba.invalid/p.png'
  const dish = (id, name, concept, price) =>
    product(id, { name, concept, price_value: price, vertical: 'restaurantes', entity_type: 'menu_item', img })
  const pool = [
    dish(60, 'Tomate cherry', 'pizza', 1300), // un agregado de la pizzería, con el concepto de su cocina
    dish(61, 'Bebida cola 1,5 L', 'pizza', 3990), // cuesta como un plato: la sección del menú dice que es bebida
    dish(62, 'Brownie', 'postres', 4300),
    dish(63, 'Pizza napolitana', 'pizza', 9990),
    product(64, { name: 'Vaso de cotillón', concept: 'juguetes', vertical: 'turbo', img }),
    product(65, { name: 'Galletas de avena', concept: 'galletas', vertical: 'turbo' }), // sin foto
    product(66, { name: 'Café en grano', concept: 'cafe', vertical: 'turbo', img }),
  ]
  const concepts = {
    ...snapshot.meta.concepts,
    pizza: { name: 'Pizza', emoji: '🍕', group: 'comida', offerable: true },
    postres: { name: 'Postres', emoji: '🍰', group: 'comida', offerable: true },
  }
  const menu = {
    sections: [
      { name: 'Lo más pedido', items: [pool[1]] },
      { name: 'Bebidas', items: [pool[1]] },
      { name: 'Pizzas', items: [pool[0], pool[2], pool[3]] },
    ],
  }
  const withPool = { ...snapshot, meta: { ...snapshot.meta, concepts }, pool, catalog: { menus: { 1: menu } } }
  const history = personaHistory(
    withPool,
    personas(withPool).find((p) => p.id === 'rest-turbo'),
    NOW,
  )
  expect(history.orders.map((o) => o.lines[0].entity_id)).toEqual(['63', '66'])
})

test('cada persona trae su marca Rappi Pro, coherente con lo que pide: quien combina verticales es Pro', () => {
  const all = personas(snapshot)
  all.forEach((p) => expect(typeof p.pro).toBe('boolean'))
  expect(persona('nueva').pro).toBe(false)
  expect(persona('restaurantes').pro).toBe(false)
  expect(persona('rest-turbo').pro).toBe(true)
  expect(persona('todo').pro).toBe(true)
})

test('cambiar de persona conserva la sesión, el modo y los avisos vistos, y borra lo demás de la app', () => {
  const reload = vi.fn()
  vi.stubGlobal('location', { ...window.location, pathname: '/', reload })
  const kept = [
    'rappi-proto-user',
    'rappi-proto-token',
    'rappi-proto-demo-mode',
    'rappi-proto-privacy-seen',
    'rappi-proto-guia-vista',
    'rappi-proto-address',
  ]
  for (const key of [...kept, 'rappi-proto-cart', 'rappi-proto-orders', 'otra-app']) localStorage.setItem(key, '1')
  sessionStorage.setItem('rappi-proto-session', '{}')
  sessionStorage.setItem('rappi-proto-mochi-pendiente', '{}')

  switchPersona(snapshot, persona('rest-turbo'))

  expect(Object.keys(localStorage).sort()).toEqual(
    [...kept, 'rappi-proto-offline-api', 'rappi-proto-pro', 'otra-app'].sort(), // su historial y su marca Pro, nuevos
  )
  expect(localStorage.getItem('rappi-proto-pro')).toBe('true')
  expect(Object.keys(sessionStorage)).toEqual([])
  expect(reload).toHaveBeenCalledTimes(1)
})

test('la demo arranca una sola vez con la persona del perfil principal (el mexicano), que sigue entre las personas', () => {
  expect(startingPersona(snapshot)).toMatchObject({ id: 'gusto-mexicano', label: '🌮 Amante de lo mexicano' })
  // Entre las personas de gusto, el principal va primero.
  const tastes = personas(snapshot).filter((p) => p.taste)
  expect(tastes.map((p) => p.id)).toEqual(['gusto-mexicano', 'gusto-asiatico'])

  const first = startingHistory(snapshot, NOW)
  expect(first.orders).toHaveLength(3)
  expect(first.orders.every((o) => o.lines[0].concept_id === 'mexicana' && o.vertical === 'restaurantes')).toBe(true)
  expect(tastesReply(snapshot, { userId: 'proto-test', ...first }).perfiles.map((p) => p.id)).toEqual(['mexicano'])
  expect(localStorage.getItem('rappi-proto-pro')).toBe('true')
  // Ya arrancó en este navegador: "Borrar mis datos" (que borra `rappi-proto-*`) no la vuelve a sembrar.
  expect(startingHistory(snapshot, NOW)).toBeNull()
})

test('sin conexión, la primera sesión trae el historial de la persona principal; una sesión que vuelve, no', () => {
  const call = (body) =>
    route(snapshot, { method: 'POST', path: '/session', query: new URLSearchParams(), body: body ?? {} }, NOW)
  call()
  expect(readState().orders).toHaveLength(3)
  localStorage.removeItem('rappi-proto-offline-api') // "Borrar mis datos"
  call()
  expect(readState().orders).toEqual([])
  localStorage.clear()
  call({ legacy_user_id: 'proto-0123456789abcdef' }) // un id de antes: no se le inventa un historial
  expect(readState().orders).toEqual([])
})

test('sin perfil principal grabado en la muestra, la demo arranca como siempre: sin historial', () => {
  const without = { ...snapshot, tastes: { asiatico: snapshot.tastes.asiatico } }
  expect(startingPersona(without)).toBeNull()
  expect(startingHistory(without, NOW)).toBeNull()
})

test('"Borrar historial" saca los pedidos y los toques, pero no la dieta ni las alergias de la persona', () => {
  const preferences = [{ kind: 'dieta', value: 'vegetariano' }]
  writeState({
    userId: 'proto-1',
    events: [{ type: 'vertical_open', vertical: 'farmacia', ts: 1 }],
    orders: [{ id: 'o-1' }],
    preferences,
    autonomy: { modo: 'pedir' },
  })
  clearHistory()
  const state = readState()
  expect(state).toMatchObject({ userId: 'proto-1', events: [], orders: [], preferences })
  // "Pedir por mí" sí se va: sus tiendas salen de los pedidos que se borraron.
  expect(state.autonomy).toBeUndefined()
})
