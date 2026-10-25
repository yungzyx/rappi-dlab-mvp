import { describe, expect, test } from 'vitest'
import { ROUTE, minutesLeft, pointOnRoute, rideProgress, stepAt } from './progress'

describe('línea de tiempo del pedido', () => {
  test('avanza de paso según los segundos', () => {
    expect(stepAt(0)).toBe(0)
    expect(stepAt(5)).toBe(1)
    expect(stepAt(12)).toBe(2)
    expect(stepAt(60)).toBe(3)
  })

  test('el viaje va de 0 a 1 y los minutos bajan hasta 0', () => {
    expect(rideProgress(0)).toBe(0)
    expect(rideProgress(14.5)).toBeCloseTo(0.5)
    expect(rideProgress(99)).toBe(1)
    expect(minutesLeft(10)).toBeGreaterThan(minutesLeft(18))
    expect(minutesLeft(20)).toBe(0)
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
