import { describe, expect, test } from 'vitest'
import { responsesAfter, TOUR } from './tour.js'

const recorded = {
  'offers.prototype': {
    source: 'prototype',
    data: {
      personas: 25,
      momentos: [
        { momento: 'plan', mostradas: 9, aceptadas: 0, aceptacion_pct: null },
        { momento: 'pregunta', mostradas: 26, aceptadas: 2, aceptacion_pct: 7.7 },
      ],
    },
  },
  'kpis.prototype': {
    source: 'prototype',
    data: { usuarios_activos: 45, pedidos_30d: 18, frecuencia: 0.4, en_riesgo: 0 },
  },
  'unmet.prototype': {
    source: 'prototype',
    data: { personas: 26, busquedas: 59, sin_resultado: 0, por_vertical: [] },
  },
  'combos.prototype': { source: 'prototype', data: { rappi: {} } },
}

describe('Ver cómo funciona', () => {
  test('the offer step adds a shown «Plan» offer, a person and an active user', () => {
    const after = responsesAfter(recorded, 1)

    expect(after['offers.prototype'].data.momentos[0]).toEqual({
      momento: 'plan',
      mostradas: 10,
      aceptadas: 0,
      aceptacion_pct: 0, // con 10 mostradas aparece la tasa
    })
    expect(after['offers.prototype'].data.personas).toBe(26)
    expect(after['kpis.prototype'].data).toMatchObject({ usuarios_activos: 46, pedidos_30d: 18, frecuencia: 0.39 })
  })

  test('accepting, paying and searching build on each other', () => {
    const after = responsesAfter(recorded, TOUR.length)

    expect(after['offers.prototype'].data.momentos[0]).toMatchObject({
      mostradas: 10,
      aceptadas: 1,
      aceptacion_pct: 10,
    })
    expect(after['kpis.prototype'].data).toMatchObject({ usuarios_activos: 46, pedidos_30d: 19, frecuencia: 0.41 })
    expect(after['unmet.prototype'].data).toEqual({
      personas: 27,
      busquedas: 60,
      sin_resultado: 1,
      por_vertical: [{ vertical: 'restaurantes', concepto: null, sin_resultado: 1 }],
    })
  })

  test('the recorded answers never change, and what the tour does not touch stays the same object', () => {
    const copy = structuredClone(recorded)

    const after = responsesAfter(recorded, TOUR.length)

    expect(recorded).toEqual(copy)
    expect(after['combos.prototype']).toBe(recorded['combos.prototype'])
    expect(responsesAfter(recorded, 0)).toBe(recorded)
  })

  test('a moment the recording does not have is added', () => {
    const withoutPlan = {
      ...recorded,
      'offers.prototype': { source: 'prototype', data: { personas: 0, momentos: [] } },
    }

    expect(responsesAfter(withoutPlan, 2)['offers.prototype'].data.momentos).toEqual([
      { momento: 'plan', mostradas: 1, aceptadas: 1, aceptacion_pct: null },
    ])
  })

  test('every step says where to look', () => {
    for (const step of TOUR) {
      expect(['resumen', 'clientes', 'mochi']).toContain(step.view)
      expect(step.section).toMatch(/^[a-z-]+$/)
      expect(step.title && step.text).toBeTruthy()
    }
  })
})
