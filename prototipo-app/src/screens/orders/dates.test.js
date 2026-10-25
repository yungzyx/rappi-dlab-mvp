import { describe, expect, test } from 'vitest'
import { relativeDay } from './dates'

const now = new Date(2026, 9, 12, 15, 30).getTime() // 12 oct 2026, 15:30

describe('relativeDay', () => {
  test('hoy, ayer (aunque sea casi medianoche) y una fecha corta en español', () => {
    expect(relativeDay(new Date(2026, 9, 12, 0, 5).getTime(), now)).toBe('Hoy')
    expect(relativeDay(new Date(2026, 9, 11, 23, 50).getTime(), now)).toBe('Ayer')
    expect(relativeDay(new Date(2026, 9, 3).getTime(), now)).toBe('3 oct')
    expect(relativeDay(new Date(2026, 0, 28).getTime(), now)).toBe('28 ene')
  })
})
