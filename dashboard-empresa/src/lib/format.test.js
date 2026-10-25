import { describe, expect, test } from 'vitest'
import { formatDate, formatNumber, formatPct, formatPoints, formatShortDate, formatSignedPct } from './format.js'

describe('formatNumber', () => {
  test('agrupa miles con punto desde 4 cifras', () => {
    expect(formatNumber(1234)).toBe('1.234')
    expect(formatNumber(12345678)).toBe('12.345.678')
    expect(formatNumber(999)).toBe('999')
  })

  test('usa coma decimal', () => {
    expect(formatNumber(2.99, 2)).toBe('2,99')
    expect(formatNumber(6, 1)).toBe('6,0')
  })

  test('usa el signo menos tipográfico', () => {
    expect(formatNumber(-1234)).toBe('−1.234')
  })

  test('muestra una raya cuando no hay dato', () => {
    expect(formatNumber(null)).toBe('—')
    expect(formatNumber(undefined)).toBe('—')
    expect(formatNumber(Number.NaN)).toBe('—')
  })
})

describe('porcentajes', () => {
  test('formatPct sin espacio antes del signo', () => {
    expect(formatPct(28.6)).toBe('28,6%')
    expect(formatPct(100)).toBe('100,0%')
    expect(formatPct(73, 0)).toBe('73%')
    expect(formatPct(null)).toBe('—')
  })

  test('formatSignedPct marca el sentido del cambio', () => {
    expect(formatSignedPct(43)).toBe('+43%')
    expect(formatSignedPct(-4)).toBe('−4%')
    expect(formatSignedPct(0)).toBe('0%')
  })

  test('formatPoints usa puntos porcentuales', () => {
    expect(formatPoints(10.94)).toBe('+10,9 puntos')
    expect(formatPoints(-2.5)).toBe('−2,5 puntos')
    expect(formatPoints(35.2, 0)).toBe('+35 puntos')
  })
})

describe('fechas', () => {
  test('formatDate usa día-mes-año y no depende de la zona horaria', () => {
    expect(formatDate('2026-09-26T23:58:56.939166-03:00')).toBe('26-09-2026')
    expect(formatDate('2026-05-01')).toBe('01-05-2026')
    expect(formatDate(null)).toBe('—')
  })

  test('formatShortDate abrevia el mes en español', () => {
    expect(formatShortDate('2026-05-11')).toBe('11 may')
    expect(formatShortDate('2026-08-03')).toBe('3 ago')
  })
})
