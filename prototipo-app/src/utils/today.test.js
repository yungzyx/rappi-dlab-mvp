import { describe, expect, test } from 'vitest'
import { today } from './today'

describe('today', () => {
  test('usa la fecha local, no UTC', () => {
    // Las pruebas corren con la hora de Chile (vite.config.js): las 23:30 locales ya son el día siguiente en UTC.
    expect(new Date(2026, 9, 8, 23, 30).toISOString().slice(0, 10)).toBe('2026-10-09')
    expect(today(new Date(2026, 9, 8, 23, 30))).toBe('2026-10-08')
    expect(today(new Date(2026, 0, 1, 0, 5))).toBe('2026-01-01')
  })
})
