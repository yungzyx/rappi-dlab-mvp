import { afterEach, describe, expect, test, vi } from 'vitest'
import { toPrototypeProduct } from './client'
import { parsePrice } from '../state/CartContext'
import { basketsOf, buildOrders, conceptOf, ordersSettled, trackOrder } from './orders'
import { fixture } from '../test/api'

const ctx = { userId: 'proto-1', sessionId: 's-1', cartId: 'c-1' }
// Verticales que acepta POST /orders (códigos del backend).
const ACCEPTED = [
  'supermercado',
  'licores',
  'farmacia',
  'mall',
  'conveniencia',
  'turbo',
  'chocolateria',
  'restaurantes',
]
// Una cerveza de la API (licores), tal como la devuelve /search.
const beer = () => toPrototypeProduct(fixture('search-grouped').groups[0].products[0])

afterEach(() => vi.restoreAllMocks())

describe('pedidos para el panel', () => {
  test('un pedido por tienda; los productos de la API conservan sus ids', () => {
    const orders = buildOrders(
      [
        {
          product: {
            id: 'cat-200',
            entityType: 'catalog_item',
            entityId: '200',
            concept: 'cerveza',
            vertical: 'licores',
            price: '$1.290',
          },
          qty: 2,
        },
        {
          product: {
            id: 'cat-100',
            entityType: 'catalog_item',
            entityId: '100',
            concept: 'snacks-salados',
            vertical: 'supermercado',
            price: '$1.990',
            fromSuggestion: true,
          },
          qty: 1,
        },
      ],
      ctx,
    )
    expect(orders.map((o) => o.vertical)).toEqual(['licores', 'supermercado'])
    expect(orders[0].lines[0]).toEqual({
      entity_type: 'catalog_item',
      entity_id: '200',
      concept_id: 'cerveza',
      qty: 2,
      unit_price: 1290,
      from_suggestion: false,
    })
    expect(orders[1].lines[0].from_suggestion).toBe(true)
  })

  test('el pedido manda la vertical del backend y el entity_id real', () => {
    const item = toPrototypeProduct(fixture('catalog-product'))
    const dish = toPrototypeProduct(fixture('catalog-menu').sections[0].items[0])
    const orders = buildOrders(
      [
        { product: item, qty: 2 },
        { product: dish, qty: 1 },
      ],
      ctx,
    )
    expect(orders.map((o) => o.vertical)).toEqual(['supermercado', 'restaurantes'])
    expect(orders[0].lines[0]).toMatchObject({
      entity_type: 'catalog_item',
      entity_id: '91001',
      qty: 2,
      unit_price: 1990,
    })
    expect(orders[1].lines[0]).toMatchObject({ entity_type: 'menu_item', entity_id: '98002', unit_price: 8990 })

    // Cada vertical de la API vuelve a ella tal cual, pase por la pantalla que pase.
    ACCEPTED.forEach((vertical) => {
      const [order] = buildOrders(
        [{ product: toPrototypeProduct({ ...fixture('catalog-product'), vertical }), qty: 1 }],
        ctx,
      )
      expect(order.vertical).toBe(vertical)
    })
    // Si la vertical del backend y la de la pantalla no coinciden, manda la del backend.
    const [turbo] = buildOrders([{ product: { ...item, vertical: 'express', backendVertical: 'turbo' }, qty: 1 }], ctx)
    expect(turbo.vertical).toBe('turbo')
  })

  test('el concepto de un producto es el que trae de la API; sin él, no se inventa uno', () => {
    expect(conceptOf(beer())).toBe('cerveza')
    expect(conceptOf({ name: 'Cerveza sin concepto' })).toBeUndefined()
    const [order] = buildOrders([{ product: beer(), qty: 1 }], ctx)
    expect(order.lines[0]).toMatchObject({ entity_id: '94001', concept_id: 'cerveza' })
  })

  test('una línea sin entityId no viaja: nunca se inventa un id local', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const loose = { id: 'p-heineken', name: 'Heineken', price: '$6.690', store: 'Líquidos', vertical: 'liquor' }
    const orders = buildOrders(
      [
        { product: loose, qty: 1 },
        { product: beer(), qty: 1 },
      ],
      ctx,
    )
    expect(orders).toHaveLength(1)
    expect(orders[0].lines.map((line) => line.entity_id)).toEqual(['94001'])
    orders[0].lines.forEach((line) => expect(line.entity_id).toMatch(/^\d+$/)) // ids reales de la API
    expect(warn).toHaveBeenCalledTimes(1)
    expect(buildOrders([{ product: loose, qty: 1 }], ctx)).toEqual([])
  })

  test('todo producto de las respuestas de ejemplo llega con una vertical que la API acepta', () => {
    const products = [
      ...fixture('search-grouped').groups.flatMap((group) => group.products),
      ...fixture('catalog-store').products,
      ...fixture('agent-offer-plan').products,
    ].map(toPrototypeProduct)
    const orders = buildOrders(
      products.map((product) => ({ product, qty: 1 })),
      ctx,
    )
    expect(orders.flatMap((order) => order.lines)).toHaveLength(products.length)
    orders.forEach((order) => expect(ACCEPTED).toContain(order.vertical))
  })

  test('sin vertical del catálogo la línea no se envía; el resto sí, y la misma tienda es un solo pedido', () => {
    const orders = buildOrders(
      [
        { product: { id: 'pet-1', name: 'Snack para perro', vertical: 'pet', price: '$2.000', entityId: '1' }, qty: 1 },
        { product: { id: 'sin-tienda', name: 'Algo', price: '$1.000', entityId: '2' }, qty: 1 },
        { product: beer(), qty: 1 },
        { product: { ...beer(), id: 'cat-200', entityId: '200' }, qty: 1 },
      ],
      ctx,
    )
    expect(orders).toHaveLength(1)
    expect(orders[0].vertical).toBe('licores')
    expect(orders[0].lines.map((line) => line.entity_id)).toEqual(['94001', '200'])
  })

  test('un pedido por tienda: dos restaurantes son dos pedidos aunque sean de la misma vertical', () => {
    const dish = toPrototypeProduct(fixture('catalog-menu').sections[0].items[0])
    const other = { ...dish, id: 'menu-1', entityId: '1', storeId: dish.storeId + 1, store: 'Otro restaurante' }
    const orders = buildOrders(
      [
        { product: dish, qty: 1 },
        { product: other, qty: 2 },
        { product: { ...dish, id: 'menu-2', entityId: '2' }, qty: 1 },
      ],
      ctx,
    )
    expect(orders.map((o) => o.vertical)).toEqual(['restaurantes', 'restaurantes'])
    expect(orders.map((o) => o.lines.map((line) => line.entity_id))).toEqual([['98002', '2'], ['1']])
    orders.forEach((order) => expect(new Set(order.lines.map((line) => line.store_id)).size).toBe(1))
    // Sin `storeId`, la tienda es su nombre (y su vertical).
    const loose = (store) => ({ id: `x-${store}`, entityId: '9', vertical: 'licores', store, price: '$1.000' })
    const byName = buildOrders(
      [
        { product: loose('A'), qty: 1 },
        { product: loose('B'), qty: 1 },
        { product: { ...loose('A'), id: 'y' }, qty: 1 },
      ],
      ctx,
    )
    expect(byName.map((o) => o.lines.length)).toEqual([2, 1])
  })

  test('basketsOf: una canasta por tienda con su subtotal; el pedido dice si la persona es Pro', () => {
    const dish = toPrototypeProduct(fixture('catalog-menu').sections[0].items[0])
    const baskets = basketsOf([
      { product: dish, qty: 2 },
      { product: beer(), qty: 1 },
    ])
    expect(baskets.map((b) => [b.storeId, b.vertical, b.subtotal])).toEqual([
      [dish.storeId, 'restaurantes', 2 * 8990],
      [beer().storeId, 'licores', parsePrice(beer().price)],
    ])
    expect(buildOrders([{ product: dish, qty: 1 }], { ...ctx, pro: true })[0].pro).toBe(true)
    expect(buildOrders([{ product: dish, qty: 1 }], ctx)[0]).not.toHaveProperty('pro')
  })

  test("buildOrders en modo actual lleva mode 'actual' y ningún concept_id", () => {
    // En "Rappi hoy" la app no aprende: el pedido lo dice y no nombra conceptos (el backend tampoco lo lleva al perfil).
    const items = [
      { product: beer(), qty: 1 },
      { product: toPrototypeProduct(fixture('catalog-product')), qty: 2 },
    ]
    const orders = buildOrders(items, { ...ctx, mode: 'actual' })
    expect(orders).toHaveLength(2)
    orders.forEach((order) => {
      expect(order.mode).toBe('actual')
      order.lines.forEach((line) => expect(line).not.toHaveProperty('concept_id'))
    })
    const [proposal] = buildOrders([{ product: beer(), qty: 1 }], ctx)
    expect(proposal.mode).toBe('propuesta')
    expect(proposal.lines[0].concept_id).toBe('cerveza')
  })

  test('cada línea lleva la tienda de donde se agregó: el backend toma el precio de esa tienda', () => {
    const item = toPrototypeProduct(fixture('catalog-product'))
    const dish = toPrototypeProduct(fixture('catalog-menu').sections[0].items[0])
    const [grocery, restaurant] = buildOrders(
      [
        { product: { ...item, storeId: 9102 }, qty: 1 },
        { product: dish, qty: 1 },
      ],
      ctx,
    )
    expect(grocery.lines[0].store_id).toBe(9102)
    expect(restaurant.lines[0].store_id).toBe(dish.storeId)
    expect(dish.storeId).toEqual(expect.any(Number))
    // Sin tienda (un producto sin oferta abierta), la línea va sin ella y el backend usa la oferta más barata.
    const [loose] = buildOrders([{ product: { ...item, storeId: undefined }, qty: 1 }], ctx)
    expect(loose.lines[0]).not.toHaveProperty('store_id')
  })

  test('from_suggestion sale de la línea del carrito', () => {
    const [order] = buildOrders([{ product: beer(), qty: 1, fromSuggestion: true }], ctx)
    expect(order.lines[0].from_suggestion).toBe(true)
  })
})

describe('pedidos en vuelo', () => {
  test('ordersSettled waits for every tracked order, failed or not', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    await ordersSettled() // sin pedidos, termina al tiro

    let finish
    let fail
    trackOrder(new Promise((resolve) => (finish = resolve)))
    trackOrder(new Promise((_, reject) => (fail = reject)))
    let settled = false
    const waiting = ordersSettled().then(() => (settled = true))

    fail(new Error('sin red'))
    await Promise.resolve()
    await Promise.resolve()
    expect(settled).toBe(false) // falta el otro pedido

    finish()
    await waiting
    expect(settled).toBe(true)
    expect(warn).toHaveBeenCalledTimes(1) // el pedido que falló no se traga en silencio
    expect(warn.mock.calls[0][0]).toMatch(/^No se pudo enviar el pedido/)
  })

  test('a failed order does not break the caller: trackOrder hands the promise back', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const failed = Promise.reject(new Error('sin red'))
    expect(trackOrder(failed)).toBe(failed)
    await expect(failed).rejects.toThrow('sin red')
    await ordersSettled()
  })
})
