import { describe, expect, test } from 'vitest'
import { nearestIndex, niceMax, scaleLinear } from './geometry.js'

describe('scaleLinear', () => {
  test('interpola y admite rangos invertidos', () => {
    const y = scaleLinear([0, 100], [200, 0])
    expect(y(0)).toBe(200)
    expect(y(25)).toBe(150)
    expect(scaleLinear([5, 5], [0, 10])(5)).toBe(0)
  })
})

describe('niceMax', () => {
  test('el menor tope redondo (1; 1,5; 2; 2,5; 3; 4; 5; 6 u 8 por una potencia de 10) que alcanza el valor', () => {
    expect(niceMax(561)).toBe(600)
    expect(niceMax(448)).toBe(500)
    expect(niceMax(28)).toBe(30)
    expect(niceMax(1.5)).toBe(1.5)
    expect(niceMax(81)).toBe(100)
    expect(niceMax(250)).toBe(250)
    expect(niceMax(0)).toBe(1)
  })
})

describe('nearestIndex', () => {
  test('el punto más cercano, dentro de los límites', () => {
    expect(nearestIndex(0, 27, 0, 260)).toBe(0)
    expect(nearestIndex(14, 27, 0, 260)).toBe(1)
    expect(nearestIndex(260, 27, 0, 260)).toBe(26)
    expect(nearestIndex(-40, 27, 0, 260)).toBe(0)
    expect(nearestIndex(900, 27, 0, 260)).toBe(26)
    expect(nearestIndex(50, 1, 0, 260)).toBe(0)
  })
})
