import { describe, expect, test } from 'vitest'
import { DEFAULTS, extraActive, goalValue, HORIZON, parseAmount, paybackMonth } from './goalValue.js'

// Números redondos inventados: no son de Rappi ni de nadie. Margen por pedido = 10 × 10 % = 1.
const INVENTED = {
  ...DEFAULTS,
  usuarios: '100.000',
  retencion: '50',
  pedidos: '2',
  valor: '10',
  margen: '10',
  restaurantes: '100.000',
  turbo: '20',
}

// El cálculo independiente: fórmulas cerradas, sin la simulación mes a mes del módulo.
const r = 0.5
const perMonth = 100000 * 0.02 // retenidos de más cada mes
const monthlyMargin = (people) => people * 2 * 10 * 0.1
const ceilingAt = (k) => k * perMonth
const prudentAt = (k) => (perMonth * (1 - r ** k)) / (1 - r)
const firstYear = (at) => Array.from({ length: 12 }, (_, i) => monthlyMargin(at(i + 1))).reduce((a, b) => a + b, 0)
const firstPayback = (at, investment, cost) => {
  for (let k = 1; k <= HORIZON; k += 1) {
    let total = -investment
    for (let j = 1; j <= k; j += 1) total += monthlyMargin(at(j)) - cost
    if (total >= 0) return k
  }
  return null
}

describe('parseAmount', () => {
  test('reads es-CL: dot for thousands, comma for decimals', () => {
    expect(parseAmount('10.000')).toBe(10000)
    expect(parseAmount('1.234.567')).toBe(1234567)
    expect(parseAmount('2,5')).toBe(2.5)
    expect(parseAmount('1.234,5')).toBe(1234.5)
    expect(parseAmount(' 100 000 ')).toBe(100000)
    expect(parseAmount('100\u00a0000')).toBe(100000)
    expect(parseAmount('2.5')).toBe(2.5)
    expect(parseAmount('0')).toBe(0)
    expect(parseAmount('−3')).toBe(-3)
  })

  test('empty is null and anything else is NaN', () => {
    expect(parseAmount('')).toBeNull()
    expect(parseAmount(undefined)).toBeNull()
    expect(parseAmount('abc')).toBeNaN()
    expect(parseAmount('1,2,3')).toBeNaN()
    expect(parseAmount('10 %')).toBeNaN()
  })
})

describe('goalValue', () => {
  test('starts empty: nothing to show and nothing wrong', () => {
    const result = goalValue(DEFAULTS)
    expect(result.errors).toEqual({})
    expect(result.costs).toBe(false)
    expect(result.h1.missing).toEqual(['usuarios', 'retencion', 'pedidos', 'valor', 'margen'])
    expect(result.h2.missing).toEqual(['restaurantes', 'turbo', 'valor', 'margen'])
  })

  test('H1 per month and in its two readings, checked against the closed forms', () => {
    const { h1 } = goalValue(INVENTED)
    expect(h1.retained).toBeCloseTo(2000)
    expect(h1.orders).toBeCloseTo(4000)
    expect(h1.margin).toBeCloseTo(4000)
    expect(h1.techo.retainedAtYear).toBeCloseTo(ceilingAt(12)) // 24.000
    expect(h1.prudente.retainedAtYear).toBeCloseTo(prudentAt(12))
    expect(h1.techo.marginYear).toBeCloseTo(firstYear(ceilingAt)) // 78 × 4.000 = 312.000
    expect(h1.techo.marginYear).toBeCloseTo(312000)
    expect(h1.prudente.marginYear).toBeCloseTo(firstYear(prudentAt)) // 8.000 × (11 + 0,5^12)
    expect(h1.prudente.marginYear).toBeCloseTo(88001.953125)
    expect(h1.techo.payback).toBeNull() // sin costos no hay "recupera"
  })

  test('H2: extra Turbo clients with one order a month each', () => {
    const { h2 } = goalValue(INVENTED)
    expect(h2.clients).toBeCloseTo(100000 * 0.2 * 0.1) // 2.000
    expect(h2.margin).toBeCloseTo(2000)
    expect(h2.marginYear).toBeCloseTo(24000)
  })

  test('payback in each reading, or null when 36 months are not enough', () => {
    const { costs, h1, h2 } = goalValue({ ...INVENTED, inversion: '50.000', operacion: '1.000' })
    expect(costs).toBe(true)
    expect(h1.techo.payback).toBe(firstPayback(ceilingAt, 50000, 1000))
    expect(h1.techo.payback).toBe(5)
    expect(h1.prudente.payback).toBe(firstPayback(prudentAt, 50000, 1000))
    expect(h1.prudente.payback).toBe(9)
    expect(h2.payback).toBeNull() // 1.000 netos al mes: harían falta 50 meses
  })

  test('only a monthly cost also counts as costs', () => {
    const { costs, h2 } = goalValue({ ...INVENTED, operacion: '3.000' })
    expect(costs).toBe(true)
    expect(h2.payback).toBeNull() // 2.000 de margen contra 3.000 de costo
    expect(goalValue({ ...INVENTED, operacion: '1.000' }).h2.payback).toBe(1)
  })

  test('partial coverage scales both hypotheses', () => {
    const { h1, h2 } = goalValue({ ...INVENTED, cobertura: '25' })
    expect(h1.people).toBeCloseTo(25000)
    expect(h1.retained).toBeCloseTo(500)
    expect(h1.techo.marginYear).toBeCloseTo(312000 / 4)
    expect(h2.clients).toBeCloseTo(500)
  })

  test('empty coverage means everyone', () => {
    expect(goalValue({ ...INVENTED, cobertura: '' }).h1.retained).toBeCloseTo(2000)
  })

  test('zero is a value, not a gap', () => {
    const { h1, h2, errors } = goalValue({ ...INVENTED, usuarios: '0', turbo: '0' })
    expect(errors).toEqual({})
    expect(h1.margin).toBe(0)
    expect(h1.techo.marginYear).toBe(0)
    expect(h2.clients).toBe(0)
  })

  test('100 % base retention: no room for +2 points, but the prudent reading stops decaying', () => {
    const full = goalValue({ ...INVENTED, retencion: '100' })
    expect(full.errors.puntos).toMatch(/pasa de 100/)
    expect(full.h1.missing).toEqual(['puntos'])
    const { h1 } = goalValue({ ...INVENTED, retencion: '98' })
    expect(h1.retained).toBeCloseTo(2000)
    const flat = goalValue({ ...INVENTED, retencion: '100', puntos: '0' }).h1
    expect(flat.margin).toBe(0)
    // Con r = 1 la lectura prudente es la del techo: nadie se va.
    expect(extraActive(10, 1)).toEqual(Array.from({ length: HORIZON }, (_, i) => 10 * (i + 1)))
  })

  test('Turbo rate times the goal cannot pass 100 %', () => {
    const { errors, h2 } = goalValue({ ...INVENTED, turbo: '95' })
    expect(errors.relativo).toMatch(/pasa de 100/)
    expect(h2.missing).toEqual(['relativo'])
  })

  test('bad input: not a number, negative, a percentage over 100', () => {
    const { errors, h1, h2 } = goalValue({ ...INVENTED, valor: 'diez', pedidos: '-1', margen: '120', cobertura: '150' })
    expect(errors.valor).toMatch(/No es un número/)
    expect(errors.pedidos).toMatch(/negativo/)
    expect(errors.margen).toMatch(/100/)
    expect(errors.cobertura).toMatch(/100/)
    expect(h1.missing).toEqual(['pedidos', 'valor', 'margen', 'cobertura'])
    expect(h2.missing).toEqual(['valor', 'margen', 'cobertura'])
  })

  test('paybackMonth: already paid in month 1, never, and exactly at zero', () => {
    expect(paybackMonth([5, 5], 0, 1)).toBe(1)
    expect(paybackMonth([1, 1, 1], 10, 0)).toBeNull()
    expect(paybackMonth([5, 5], 10, 0)).toBe(2)
  })
})
