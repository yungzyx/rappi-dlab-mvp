import { expect, test } from 'vitest'
import { homeVerticals, targetStep } from './motor'
import { makeOffer } from './offers'
import { ladderReadout, personaHistory, personas } from './personas'
import { profileOffer, tastesReply } from './tastes'
import { COMBOS, LABELS, META, product } from '../../test/offlineMeta'

const NOW = Date.UTC(2026, 9, 17, 15)
const VERTICALS = ['restaurantes', 'turbo', 'supermercado', 'conveniencia', 'mall', 'chocolateria', 'farmacia']
const sushi = product(9, {
  name: 'Roll de salmón',
  concept: 'sushi',
  vertical: 'restaurantes',
  entity_type: 'menu_item',
})
const snapshot = {
  meta: {
    ...META,
    concepts: { ...META.concepts, sushi: { name: 'Sushi', emoji: '🍣', group: 'comida', offerable: true } },
    profiles: { asiatico: { name: 'Amante de lo asiático', emoji: '🥢', main: true, concepts: ['sushi', 'asiatica'] } },
  },
  pool: VERTICALS.map((vertical, i) => product(i + 1, { vertical })),
  tastes: {
    asiatico: {
      gustos: { id: 'asiatico', nombre: 'Amante de lo asiático', emoji: '🥢', nivel: 'medio', principal: true },
      ladder: { moment: 'perfil', escalera: [] },
      seed: [sushi, sushi, sushi],
    },
  },
}
const persona = (id) => personas(snapshot).find((p) => p.id === id)
const stateOf = (id) => ({ userId: 'proto-test', ...personaHistory(snapshot, persona(id), NOW) })

test('las personas de la escalera están donde dice su nombre, y la línea del panel lo muestra', () => {
  expect(targetStep(COMBOS, stateOf('restaurantes'), NOW).vertical).toBe('turbo')
  expect(targetStep(COMBOS, stateOf('rest-turbo'), NOW).vertical).toBe('supermercado')
  expect(targetStep(COMBOS, stateOf('todo'), NOW).vertical).toBe('favor')
  expect(ladderReadout(snapshot, stateOf('rest-turbo'), NOW)).toBe('Hoy: restaurantes+turbo → siguiente: supermercado')
  expect(ladderReadout(snapshot, stateOf('todo'), NOW)).toMatch(/→ siguiente: RappiFavor$/)
  expect(ladderReadout(snapshot, stateOf('nueva'), NOW)).toMatch(/^Hoy: sin pedidos/)
})

test('«Usa mucho Farmacia» la sube primera en la Home y Mochi igual nunca la ofrece', () => {
  const state = stateOf('farmacia')
  expect(homeVerticals(state, NOW, LABELS).order[0].id).toBe('farmacia')
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

test('una persona de la escalera pide un concepto distinto en cada vertical (sin «¿Repetimos?» por accidente)', () => {
  // El primer producto de Rappi Mall es del mismo concepto que el de Restaurantes: se elige el siguiente.
  const pool = VERTICALS.map((vertical, i) => product(i + 1, { vertical, concept: `c${i}` }))
  const clash = product(20, { vertical: 'mall', concept: 'c0' })
  const withClash = { ...snapshot, pool: [clash, ...pool] }
  const all = personas(withClash).find((p) => p.id === 'todo')
  const concepts = personaHistory(withClash, all, NOW).orders.map((o) => o.lines[0].concept_id)
  expect(concepts).toEqual(['c0', 'c1', 'c2', 'c3', 'c4', 'c5'])
})

test('«Dejó de pedir su plato de siempre» y «Dejó Turbo hace 40 días» reciben «¿Volvemos a…?» y no «¿Repetimos?»', () => {
  const dishes = [
    product(30, { name: 'Roll de salmón', concept: 'sushi', vertical: 'restaurantes', entity_type: 'menu_item' }),
    product(31, { name: 'Pizza napolitana', concept: 'pizza', vertical: 'restaurantes', entity_type: 'menu_item' }),
  ]
  const turbo = ['cafe', 'galletas', 'juguetes'].map((concept, i) => product(32 + i, { concept, vertical: 'turbo' }))
  const pool = [...dishes, ...turbo, product(40, { concept: 'galletas' })]
  const habits = { ...snapshot, pool, byEntity: new Map(pool.map((p) => [`${p.entity_type}:${p.entity_id}`, p])) }
  const offerFor = (id, moment) => {
    const history = personaHistory(
      habits,
      personas(habits).find((p) => p.id === id),
      NOW,
    )
    return makeOffer(habits, { userId: 'proto-test', ...history }, NOW, { moment })
  }
  expect(offerFor('volver-plato', 'volver')).toMatchObject({
    text: '¿Volvemos a sushi? La última vez que pediste sushi fue hace 24 días.',
    products: [dishes[0]],
  })
  expect(offerFor('volver-turbo', 'volver')).toMatchObject({
    text: '¿Volvemos a Turbo? Tu último pedido ahí fue hace 40 días.',
    products: [turbo[2]],
  })
  expect(offerFor('volver-plato', 'recompra')).toBeNull()
  expect(offerFor('volver-turbo', 'recompra')).toBeNull()
})

test('el plato de siempre es de un concepto de hábito y de un restaurante que está en la muestra', () => {
  const dish = (id, concept, store) =>
    product(id, { concept, vertical: 'restaurantes', entity_type: 'menu_item', store_id: store })
  const pool = [dish(50, 'pizza', 7), dish(51, 'hamburguesa', 8), dish(52, 'sushi', 8)]
  const withMenus = { ...snapshot, pool, catalog: { menus: { 8: {} }, stores: {} } }
  const persona = personas(withMenus).find((p) => p.id === 'volver-plato')
  const concepts = personaHistory(withMenus, persona, NOW).orders.map((o) => o.lines[0].concept_id)
  // La pizza no tiene su restaurante en la muestra; la hamburguesa va antes en ella, pero el sushi, en los hábitos.
  expect(concepts.slice(0, 4)).toEqual(['sushi', 'sushi', 'sushi', 'sushi'])
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
