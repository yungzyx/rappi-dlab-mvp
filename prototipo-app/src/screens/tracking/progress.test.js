import { describe, expect, test } from 'vitest'
import {
  FLOWS,
  ROUTE,
  deliveryCode,
  flowFor,
  isDelivered,
  isRiding,
  minutesLeft,
  pointOnRoute,
  rideProgress,
  stepAt,
} from './progress'

const ids = (flow) => flow.steps.map((step) => step.id)
const order = (...verticals) => ({ items: verticals.map((vertical) => ({ name: 'x', vertical })) })

describe('pasos por vertical', () => {
  test('un restaurante prepara, busca un Rappi, va en camino, llega y entrega', () => {
    expect(ids(flowFor(order('restaurants')))).toEqual([
      'confirmed',
      'preparing',
      'searching',
      'on-the-way',
      'arrived',
      'delivered',
    ])
  })

  test('el súper, la farmacia y las demás tiendas pasan por la tienda con su shopper', () => {
    for (const vertical of ['grocery', 'pharmacy', 'liquor', 'express']) {
      expect(flowFor(order(vertical))).toBe(FLOWS.shopper)
    }
    expect(FLOWS.shopper.steps[1].label).toBe('En tienda: tu shopper elige tus productos')
  })

  test('Turbo arma el pedido y dice su promesa de minutos', () => {
    expect(flowFor(order('turbo', 'turbo'))).toBe(FLOWS.turbo)
    expect(FLOWS.turbo.promise).toMatch(/minutos/)
    expect(minutesLeft(0, FLOWS.turbo)).toBeLessThan(minutesLeft(0, FLOWS.restaurants))
  })

  test('un pedido con un plato es de restaurante; uno mixto sin plato, de tienda; uno sin verticales, de restaurante', () => {
    expect(flowFor(order('grocery', 'restaurants'))).toBe(FLOWS.restaurants)
    expect(flowFor(order('turbo', 'grocery'))).toBe(FLOWS.shopper)
    expect(flowFor({ items: [{ name: 'de antes' }] })).toBe(FLOWS.restaurants)
  })
})

describe('línea de tiempo del pedido', () => {
  test('avanza de paso según los segundos, con los pasos de su flujo', () => {
    expect(stepAt(0)).toBe(0)
    expect(stepAt(4)).toBe(1)
    expect(stepAt(7)).toBe(2) // buscando un Rappi
    expect(stepAt(12)).toBe(3)
    expect(stepAt(60)).toBe(5)
    expect(stepAt(4, FLOWS.shopper)).toBe(1)
    expect(stepAt(12, FLOWS.shopper)).toBe(2)
  })

  test('el viaje va de 0 a 1 y los minutos bajan hasta 0 al llegar; se entrega a los 20 s', () => {
    expect(rideProgress(0)).toBe(0)
    expect(rideProgress(13.5)).toBeCloseTo(0.5)
    expect(rideProgress(99)).toBe(1)
    expect(minutesLeft(10)).toBeGreaterThan(minutesLeft(16))
    expect(minutesLeft(18)).toBe(0)
    expect(isRiding(5)).toBe(false)
    expect(isRiding(12)).toBe(true)
    expect(isDelivered(19.9)).toBe(false)
    expect(isDelivered(20)).toBe(true)
    expect(isRiding(20)).toBe(false)
  })

  test('el código de entrega tiene 4 dígitos y es siempre el mismo para un pedido', () => {
    expect(deliveryCode('order-1')).toMatch(/^\d{4}$/)
    expect(deliveryCode('order-1')).toBe(deliveryCode('order-1'))
    expect(deliveryCode('order-1')).not.toBe(deliveryCode('order-2'))
  })
})

describe('pointOnRoute', () => {
  test('parte en el primer punto y termina en el último', () => {
    expect(pointOnRoute(0)).toEqual(ROUTE[0])
    expect(pointOnRoute(1)).toEqual(ROUTE[ROUTE.length - 1])
  })

  test('interpola por largo de tramo', () => {
    const route = [
      [0, 0],
      [10, 0],
      [10, 30],
    ]
    expect(pointOnRoute(0.25, route)).toEqual([10, 0])
    expect(pointOnRoute(0.5, route)).toEqual([10, 10])
  })
})
