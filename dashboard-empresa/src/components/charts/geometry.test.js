import { describe, expect, test } from 'vitest'
import { scaleLinear } from './geometry.js'

describe('scaleLinear', () => {
  test('interpola y admite rangos invertidos', () => {
    const y = scaleLinear([0, 100], [200, 0])
    expect(y(0)).toBe(200)
    expect(y(25)).toBe(150)
    expect(scaleLinear([5, 5], [0, 10])(5)).toBe(0)
  })
})
