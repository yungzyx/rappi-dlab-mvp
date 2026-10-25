import { describe, expect, test } from 'vitest'
import { complementOf, makeOffer, offerableProduct } from './offers'
import { decodeSnapshot } from './snapshot'
import { CONCEPTS, META, product, recordedStep } from '../../test/offlineMeta'

const NOW = Date.UTC(2026, 9, 17, 15)
let n = 0
const order = (vertical, lines = [], mode = 'propuesta') => ({
  order_id: `o-${(n += 1)}`,
  ts: NOW - 60_000,
  vertical,
  mode,
  lines,
})
const line = (p) => ({
  entity_type: p.entity_type,
  entity_id: p.entity_id,
  concept_id: p.concept,
  store_id: p.store_id,
  qty: 1,
})
const DAY_MS = 86_400_000
/** El pedido, hecho hace `days` días. */
const ago = (days, made) => ({ ...made, ts: NOW - days * DAY_MS })
const state = ({ orders = [], events = [] } = {}) => ({ userId: 'proto-test', orders, events })
const ALL = ['restaurantes', 'turbo', 'supermercado', 'conveniencia', 'mall', 'chocolateria']

const coffee = product(1, { name: 'Café molido 250 g' })
const cookies = product(2, { name: 'Galletas de vainilla', concept: 'galletas', vertical: 'conveniencia' })
const turboSnack = product(3, { name: 'Galletas Turbo', concept: 'galletas', vertical: 'turbo' })
const beer = product(4, { name: 'Cerveza lata', concept: 'cerveza', vertical: 'licores', age_restricted: true })

const turboCoffee = product(5, { name: 'Café Turbo', vertical: 'turbo' })
const turboToy = product(6, { name: 'Pelota', concept: 'juguetes', vertical: 'turbo' })
// La misma entidad en dos verticales, cada una con su tienda: el hielo se vende en Licores y en Express, y el café
// también en Express.
const ice = product(7, { name: 'Hielo 2 kg', concept: 'hielo', vertical: 'licores', store_id: 3 })
const expressIce = { ...ice, vertical: 'conveniencia', store_id: 2 }
const expressCoffee = { ...coffee, vertical: 'conveniencia', store_id: 2 }
const pharmacyCookies = product(8, { name: 'Galletas sin azúcar', concept: 'galletas', vertical: 'farmacia' })

function snapshotWith(fields = {}) {
  const pool = [
    coffee,
    cookies,
    turboSnack,
    beer,
    turboCoffee,
    turboToy,
    expressIce,
    ice,
    expressCoffee,
    pharmacyCookies,
  ]
  return {
    meta: META,
    pool,
    // Como decodeSnapshot: la primera copia de cada entidad (la del café, la del súper; la del hielo, la de Express).
    byEntity: new Map([...pool].reverse().map((p) => [`${p.entity_type}:${p.entity_id}`, p])),
    toTry: {
      usual: { ...recordedStep('supermercado', [coffee]), reason: { text: '', basis: [] } },
      turbo: recordedStep('turbo', [turboSnack]),
      supermercado: recordedStep('supermercado', [coffee]),
    },
    complements: {
      cafe: {
        moment: 'carrito',
        text: 'Para acompañar café: galletas, en Express.',
        products: [cookies],
        vertical: 'conveniencia',
        prototype_vertical: 'express',
        reason: { concept: 'galletas', from_concept: 'cafe', text: 'Porque llevas ☕ café.', basis: [] },
        actions: [],
      },
    },
    planOffers: {},
    noResult: {},
    ...fields,
  }
}
const offer = (moment, s, context = {}, snapshot = snapshotWith()) => makeOffer(snapshot, s, NOW, { moment, context })

describe('guardias (offers/guards.py)', () => {
  test('nunca +18, Farmacia, Licores, conceptos que no se ofrecen ni nombres que dicen alcohol o bebé', () => {
    expect(offerableProduct(coffee, CONCEPTS)).toBe(true)
    expect(offerableProduct({ ...coffee, age_restricted: true }, CONCEPTS)).toBe(false)
    expect(offerableProduct({ ...coffee, vertical: 'farmacia' }, CONCEPTS)).toBe(false)
    expect(offerableProduct({ ...coffee, vertical: 'licores' }, CONCEPTS)).toBe(false)
    expect(offerableProduct({ ...coffee, concept: 'analgesicos' }, CONCEPTS)).toBe(false)
    expect(offerableProduct({ ...coffee, concept: 'panales' }, CONCEPTS)).toBe(false)
    expect(offerableProduct({ ...coffee, name: 'Soju uva verde' }, CONCEPTS)).toBe(false)
    expect(offerableProduct({ ...coffee, name: 'Galletas de Vino' }, CONCEPTS)).toBe(false)
    // Los cócteles que un menú nombra sin decir alcohol (#130), aunque su concepto sea otro.
    expect(offerableProduct({ ...coffee, name: 'Tom Collins' }, CONCEPTS)).toBe(false)
    expect(offerableProduct({ ...coffee, name: 'Clavo oxidado de la casa' }, CONCEPTS)).toBe(false)
    expect(offerableProduct({ ...coffee, name: 'Juguete para Bebés', concept: 'juguetes' }, CONCEPTS)).toBe(false)
    // Palabra entera: «ron» no está en «ronda», ni «gin» en «ginger».
    expect(offerableProduct({ ...coffee, name: 'Galletas Ronda ginger' }, CONCEPTS)).toBe(true)
  })

  test('un plato sin concepto o con uno de bebida no se ofrece: el backend lee su descripción y la muestra no la tiene', () => {
    const dish = { ...coffee, entity_type: 'menu_item', vertical: 'restaurantes', concept: 'galletas' }
    expect(offerableProduct(dish, CONCEPTS)).toBe(true)
    expect(offerableProduct({ ...dish, concept: null }, CONCEPTS)).toBe(false)
    expect(offerableProduct({ ...dish, concept: 'cafe' }, CONCEPTS)).toBe(false)
    expect(offerableProduct({ ...dish, concept: 'concepto-que-ya-no-existe' }, CONCEPTS)).toBe(false)
    expect(offerableProduct({ ...coffee, concept: null }, CONCEPTS)).toBe(true) // un producto del catálogo, sí
    expect(offerableProduct({ ...dish, name: 'Absolute Blue' }, CONCEPTS)).toBe(false)
    expect(offerableProduct({ ...coffee, name: 'Absolute New York delineador' }, CONCEPTS)).toBe(true)
  })

  test('una oferta grabada pierde los productos que no pasan las guardias; sin ninguno, no se ofrece nada', () => {
    const snapshot = snapshotWith({ toTry: { turbo: recordedStep('turbo', [beer, turboSnack]) } })
    const made = offer('vertical_por_probar', state({ orders: [order('restaurantes')] }), {}, snapshot)
    expect(made.products).toEqual([turboSnack])
    const empty = snapshotWith({ toTry: { turbo: recordedStep('turbo', [beer]) } })
    expect(offer('vertical_por_probar', state({ orders: [order('restaurantes')] }), {}, empty)).toBeNull()
  })
})

describe('vertical_por_probar', () => {
  test('sin pedidos: la de siempre (el súper), con «Aún no pides en…» y su basis', () => {
    const made = offer('vertical_por_probar', state())
    expect(made).toMatchObject({
      vertical: 'supermercado',
      text: 'Aún no pides en el súper: mira estas ofertas.',
      reason: {
        text: 'Porque aún no pides en el súper.',
        basis: [{ kind: 'sin_pedidos', id: 'supermercado', source: 'contexto' }],
      },
    })
  })

  test('la oferta grabada del paso lleva primero la combinación de esta persona', () => {
    const made = offer('vertical_por_probar', state({ orders: [order('restaurantes')] }))
    expect(made.vertical).toBe('turbo')
    expect(made.reason.basis).toEqual([
      { kind: 'combinacion', id: 'restaurantes→restaurantes+turbo', source: 'rappi' },
      { kind: 'lo_mas_pedido', id: 'turbo', source: 'poblacion:synthetic' },
    ])
  })

  test('con todo el catálogo: «¿Conoces RappiFavor?», sin productos y con una acción que lo abre', () => {
    const made = offer('vertical_por_probar', state({ orders: ALL.map((v) => order(v)) }))
    expect(made).toMatchObject({
      text: '¿Conoces RappiFavor? Un Rappitendero lleva lo que necesites.',
      products: [],
      vertical: null,
      reason: { text: 'Porque ya pides en 6 verticales: RappiFavor te ayuda con lo que no está en la app.' },
      actions: [{ label: 'Abrir RappiFavor', route: ['favor'], service: 'rappifavor' }],
    })
    expect(made.reason.basis[0]).toMatchObject({ kind: 'combinacion', source: 'rappi+supuesto' })
    expect(made.reason.basis[0].id).not.toMatch(/farmacia|licores/)
  })
})

describe('recompra', () => {
  test('con ritmo (tres días de compra o más): «¿Repetimos…? Pides cada N días» cuando le toca', () => {
    const weekly = [21, 14, 7].map((days) => ago(days, order('supermercado', [line(coffee)])))
    expect(offer('recompra', state({ orders: weekly }))).toMatchObject({
      moment: 'recompra',
      text: '¿Repetimos café? Pides cada 7 días.',
      products: [coffee],
      reason: {
        concept: 'cafe',
        text: 'Porque pides café cada 7 días y tu último pedido fue hace 7 días.',
        basis: [{ kind: 'recompra', id: 'cafe', source: 'pedidos' }],
      },
    })
    // Le toca en 5 días: todavía no (se ofrece desde 2 días antes).
    const early = [16, 9, 2].map((days) => ago(days, order('supermercado', [line(coffee)])))
    expect(offer('recompra', state({ orders: early }))).toBeNull()
  })

  test('atrasado más de un intervalo ya no es recompra; tampoco lo pedido dos veces hace semanas', () => {
    const stopped = [45, 38, 31, 24].map((days) => ago(days, order('supermercado', [line(coffee)])))
    expect(offer('recompra', state({ orders: stopped }))).toBeNull()
    const twice = [21, 20].map((days) => ago(days, order('supermercado', [line(coffee)])))
    expect(offer('recompra', state({ orders: twice }))).toBeNull()
    // Dos pedidos, pero solo uno en las últimas dos semanas.
    const apart = [60, 2].map((days) => ago(days, order('supermercado', [line(coffee)])))
    expect(offer('recompra', state({ orders: apart }))).toBeNull()
  })

  test('el producto es la copia de la vertical donde lo pidió, con su tienda', () => {
    const made = offer('recompra', state({ orders: [1, 0].map((d) => ago(d, order('conveniencia', [line(coffee)]))) }))
    expect(made).toMatchObject({
      products: [expressCoffee],
      vertical: 'conveniencia',
      actions: [{ route: ['express'], store_id: 2 }],
    })
  })

  test('nunca en Licores ni Farmacia, aunque el producto se ofrezca en otra vertical', () => {
    for (const vertical of ['licores', 'farmacia']) {
      const p = vertical === 'licores' ? ice : pharmacyCookies
      const demo = [1, 0].map((d) => ago(d, order(vertical, [line(p)])))
      const weekly = [21, 14, 7].map((d) => ago(d, order(vertical, [line(p)])))
      expect(offer('recompra', state({ orders: demo }))).toBeNull()
      expect(offer('recompra', state({ orders: weekly }))).toBeNull()
    }
    // En Express, el mismo hielo sí.
    const express = [1, 0].map((d) => ago(d, order('conveniencia', [line(ice)])))
    expect(offer('recompra', state({ orders: express })).products).toEqual([expressIce])
  })

  test('un concepto en dos pedidos: «¿Repetimos…?» con el último producto comprado', () => {
    const s = state({ orders: [order('supermercado', [line(coffee)]), order('supermercado', [line(coffee)])] })
    const made = offer('recompra', s)
    expect(made).toMatchObject({
      moment: 'recompra',
      text: '¿Repetimos café? Lo pediste 2 veces.',
      products: [coffee],
      reason: { concept: 'cafe', basis: [{ kind: 'recompra', id: 'cafe', source: 'pedidos' }] },
      actions: [{ label: 'Ver producto', route: ['grocery'], store_id: 1 }],
    })
  })

  test('un pedido no basta; el alcohol y los pedidos de «Rappi hoy» nunca se repiten', () => {
    expect(offer('recompra', state({ orders: [order('supermercado', [line(coffee)])] }))).toBeNull()
    const beers = [order('licores', [line(beer)]), order('licores', [line(beer)])]
    expect(offer('recompra', state({ orders: beers }))).toBeNull()
    const today = [order('supermercado', [line(coffee)], 'actual'), order('supermercado', [line(coffee)], 'actual')]
    expect(offer('recompra', state({ orders: today }))).toBeNull()
  })
})

describe('complementos', () => {
  const entity = (p) => ({ entity_type: p.entity_type, entity_id: p.entity_id })

  test('carrito: el complemento grabado del concepto del producto', () => {
    const made = offer('carrito', state(), { product: entity(coffee) })
    expect(made).toMatchObject({ moment: 'carrito', products: [cookies], reason: { concept: 'galletas' } })
  })

  test('checkout y proximo_pedido cambian el texto; lo que ya está en el carro no se ofrece', () => {
    const checkout = offer('checkout', state(), { cart: [entity(coffee)] })
    expect(checkout.text).toBe('Para completar lo que llevas: galletas, en Express.')
    const next = offer('proximo_pedido', state(), { items: [entity(coffee)] })
    expect(next).toMatchObject({
      text: 'Para tu próximo pedido: galletas, en Express.',
      reason: { text: 'Porque pediste ☕ café.', basis: [{ kind: 'pedido', id: 'cafe', source: 'contexto' }] },
    })
    expect(offer('checkout', state(), { cart: [entity(coffee), entity(cookies)] })).toBeNull()
  })
})

describe('volver («¿Volvemos a…?»)', () => {
  const stoppedCoffee = [45, 38, 31, 24].map((days) => ago(days, order('supermercado', [line(coffee)])))
  // Tres conceptos distintos en Turbo: con uno solo, lo que dejó sería ese concepto (va antes que la vertical).
  const stoppedTurbo = [
    ...[turboSnack, turboCoffee, turboToy].map((p, i) => ago(60 - i * 10, order('turbo', [line(p)]))),
    ago(2, order('supermercado', [line(coffee)])),
  ]
  const event = (type, concept, vertical, kind, days = 1) => ({
    type,
    ts: NOW - days * DAY_MS,
    vertical,
    concept_id: concept,
    payload: { origen: 'agent-volver', kind },
  })

  test('un concepto que pedía con ritmo y dejó: el último producto que compró, con su señal `volver`', () => {
    expect(offer('volver', state({ orders: stoppedCoffee }))).toMatchObject({
      moment: 'volver',
      text: '¿Volvemos a café? La última vez que pediste café fue hace 24 días.',
      products: [coffee],
      vertical: 'supermercado',
      prototype_vertical: 'grocery',
      reason: {
        concept: 'cafe',
        text: 'Porque pedías café cada 7 días y la última vez fue hace 24 días.',
        basis: [{ kind: 'volver', id: 'cafe', source: 'pedidos' }],
      },
      actions: [{ label: 'Ver producto', route: ['grocery'], store_id: 1 }],
    })
  })

  test('una vertical que dejó hace más de 30 días mientras pide en otra: su señal `vuelta`', () => {
    const made = offer('volver', state({ orders: stoppedTurbo }))
    expect(made).toMatchObject({
      text: '¿Volvemos a Turbo? Tu último pedido ahí fue hace 40 días.',
      products: [turboToy],
      reason: {
        text: 'Porque pediste 3 veces en Turbo y tu último pedido ahí fue hace 40 días.',
        basis: [{ kind: 'vuelta', id: 'turbo', source: 'pedidos' }],
      },
    })
    expect(made.reason.concept).toBeUndefined()
    // Sin pedidos recientes en otra vertical no la dejó: dejó de pedir.
    expect(offer('volver', state({ orders: stoppedTurbo.slice(0, 3) }))).toBeNull()
  })

  test('nunca Licores ni Farmacia, ni lo de hace más de 90 días', () => {
    const recent = ago(2, order('supermercado', [line(coffee)]))
    for (const [vertical, p] of [
      ['licores', ice],
      ['farmacia', pharmacyCookies],
    ]) {
      // Un concepto que pedía con ritmo ahí y una vertical que dejó: ninguna de las dos.
      const weekly = [45, 38, 31, 24].map((days) => ago(days, order(vertical, [line(p)])))
      expect(offer('volver', state({ orders: [...weekly, recent] }))).toBeNull()
    }
    const old = [120, 113, 106, 99].map((days) => ago(days, order('supermercado', [line(coffee)])))
    expect(offer('volver', state({ orders: old }))).toBeNull()
  })

  test('pausa de 7 días por persona: solo vuelve la misma; dos «Después» la dejan', () => {
    const both = [...stoppedCoffee, ...stoppedTurbo.slice(0, 3), ago(2, order('restaurantes'))]
    expect(offer('volver', state({ orders: both })).reason.basis[0].kind).toBe('volver')
    // Mostrada la de Turbo hace 3 días, sigue esa aunque la del café va primero.
    const shownTurbo = [event('suggestion_shown', 'juguetes', 'turbo', 'vuelta', 3)]
    expect(offer('volver', state({ orders: both, events: shownTurbo })).vertical).toBe('turbo')
    // Descartada dos veces, no vuelve, y en la pausa tampoco sale la otra.
    const dismissed = [
      ...shownTurbo,
      ...[2, 1].map((d) => event('suggestion_dismissed', 'juguetes', 'turbo', 'vuelta', d)),
    ]
    expect(offer('volver', state({ orders: both, events: dismissed }))).toBeNull()
    // Pasada la semana, la del café.
    const later = dismissed.map((e) => ({ ...e, ts: e.ts - 8 * DAY_MS }))
    expect(offer('volver', state({ orders: both, events: later })).reason.concept).toBe('cafe')
  })
})

describe('complemento alternado (agent/tools.py: _takes_second)', () => {
  const second = { moment: 'carrito', products: [turboSnack], reason: { concept: 'galletas' } }
  const snapshot = snapshotWith({ complementsAlt: { cafe: second } })

  test('a la mitad de las personas les toca el segundo, siempre el mismo para la misma persona', () => {
    const people = Array.from({ length: 40 }, (_, i) => `proto-${i}`)
    const got = people.map((id) => complementOf(snapshot, 'cafe', id))
    expect(got).toContain(second)
    expect(got).toContain(snapshot.complements.cafe)
    expect(people.map((id) => complementOf(snapshot, 'cafe', id))).toEqual(got)
    // Sin persona, o sin un segundo grabado, el de siempre.
    expect(complementOf(snapshot, 'cafe', null)).toBe(snapshot.complements.cafe)
    const usual = snapshotWith()
    expect(complementOf(usual, 'cafe', people[0])).toBe(usual.complements.cafe)
  })

  test('el carrito de una persona a la que le toca el segundo trae ese', () => {
    const id = Array.from({ length: 40 }, (_, i) => `proto-${i}`).find(
      (p) => complementOf(snapshot, 'cafe', p) === second,
    )
    const made = makeOffer(snapshot, { ...state(), userId: id }, NOW, {
      moment: 'carrito',
      context: { product: { entity_type: coffee.entity_type, entity_id: coffee.entity_id } },
    })
    expect(made.products).toEqual([turboSnack])
  })
})

test('con las fotos del armado, cada una va como data URI; la que no se bajó, sin foto (el cuadro gris)', () => {
  const raw = {
    productFields: ['entity_type', 'entity_id', 'name', 'img'],
    imgPrefix: 'https://images.rappi.cl/products/',
    products: [
      ['catalog_item', '7', 'Café', '~a.png'],
      ['catalog_item', '8', 'Té', '~b.png'],
      ['catalog_item', '9', 'Mate', 'https://otro.cdn.invalid/c.png'],
    ],
    catalog: { stores: [{ logo: 'https://images.rappi.cl/marketplace/t.png', name: 'Tienda' }] },
    search: { cafe: { groups: [{ products: [{ $p: 0 }] }] } },
  }
  const photos = {
    prefix: 'https://images.rappi.cl/',
    photos: { 'products/a.png': 'data:image/webp;base64,AAA', 'marketplace/t.png': 'data:image/webp;base64,BBB' },
  }
  const snapshot = decodeSnapshot(raw, photos)
  expect(snapshot.pool.map((p) => p.img)).toEqual(['data:image/webp;base64,AAA', null, null])
  expect(snapshot.catalog.stores[0]).toEqual({ logo: 'data:image/webp;base64,BBB', name: 'Tienda' })
  expect(snapshot.search.cafe.groups[0].products[0].img).toBe('data:image/webp;base64,AAA')
  // Sin las fotos del armado, los enlaces de siempre.
  expect(decodeSnapshot(raw).catalog.stores[0].logo).toBe('https://images.rappi.cl/marketplace/t.png')
})

test('decodeSnapshot arma los productos desde sus filas y los vuelve a poner en las respuestas', () => {
  const raw = {
    productFields: ['entity_type', 'entity_id', 'name', 'img'],
    imgPrefix: 'https://images.rappi.cl/products/',
    products: [['catalog_item', '7', 'Café', '~a.png']],
    search: { cafe: { groups: [{ products: [{ $p: 0 }] }] } },
  }
  const snapshot = decodeSnapshot(raw)
  expect(snapshot.search.cafe.groups[0].products[0]).toEqual({
    id: 'cat-7',
    entity_type: 'catalog_item',
    entity_id: '7',
    name: 'Café',
    img: 'https://images.rappi.cl/products/a.png',
  })
  expect(snapshot.byEntity.get('catalog_item:7').name).toBe('Café')
})
