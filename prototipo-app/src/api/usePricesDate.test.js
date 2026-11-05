import { expect, test } from 'vitest'
import { pricesDate, rangeOf } from './usePricesDate'

const DATES = {
  from: '2026-09-24',
  to: '2026-10-18',
  byVertical: {
    grocery: { from: '2026-10-11', to: '2026-10-18' },
    turbo: { from: '2026-09-28', to: '2026-09-28' },
    restaurants: { from: '2026-09-24', to: '2026-10-05' },
  },
}

test('un solo día se dice "al", un rango "del … al …", con día y mes', () => {
  expect(pricesDate({ from: '2026-09-28', to: '2026-09-28' })).toBe('al 28-09')
  expect(pricesDate({ from: '2026-09-24', to: '2026-10-18' })).toBe('del 24-09 al 18-10')
  expect(pricesDate(null)).toBeNull()
})

test('cada vertical tiene su fecha, y varias se juntan del precio más antiguo al más nuevo', () => {
  expect(pricesDate(rangeOf(DATES, ['turbo']))).toBe('al 28-09')
  expect(pricesDate(rangeOf(DATES, ['grocery', 'turbo']))).toBe('del 28-09 al 18-10')
  expect(pricesDate(rangeOf(DATES, ['turbo', 'restaurants']))).toBe('del 24-09 al 05-10')
})

test('sin verticales, o con ninguna que el catálogo conozca, la fecha es la de todo el catálogo', () => {
  expect(rangeOf(DATES, [])).toBe(DATES)
  expect(rangeOf(DATES, ['pet'])).toBe(DATES)
  expect(rangeOf(null, ['turbo'])).toBeNull()
})
