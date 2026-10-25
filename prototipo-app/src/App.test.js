import { describe, expect, test } from 'vitest'
import { screenVertical } from './App'

describe('vertical de la pantalla para Mochi', () => {
  test('Turbo va con su código del backend (no "express", que la API lee como conveniencia)', () => {
    expect(screenVertical({ name: 'turbo' })).toBe('turbo')
    expect(screenVertical({ name: 'restaurants' })).toBe('restaurants')
    expect(screenVertical({ name: 'vertical', params: { id: 'liquor' } })).toBe('liquor')
    expect(screenVertical({ name: 'home' })).toBeUndefined()
  })
})
