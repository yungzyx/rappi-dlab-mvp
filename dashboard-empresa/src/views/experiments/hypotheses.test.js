import { describe, expect, test } from 'vitest'
import { formatSigned, hypothesesMode, monthName, surveyVerdict, verdict } from './hypotheses.js'

const groups = (treated, control) => ({
  variantes: [
    { variante: 'tratamiento', personas: treated },
    { variante: 'control', personas: control },
  ],
})

describe('hypotheses', () => {
  test('groups are compared only when both have people', () => {
    expect(hypothesesMode(groups(3, 2))).toBe('grupos')
    expect(hypothesesMode(groups(3, 0))).toBe('poblacion')
    expect(hypothesesMode(groups(0, 0))).toBe('poblacion')
  })

  test('the verdict: describe without groups, none with simulated data, then the interval decides', () => {
    expect(verdict({ mode: 'poblacion' }).label).toMatch(/^Sin grupo de control/)
    expect(verdict({ mode: 'grupos', source: 'synthetic', conclusive: true, ic95: [1, 2] }).label).toBe(
      'Simulado: sin veredicto',
    )
    expect(verdict({ mode: 'grupos', source: 'prototype', conclusive: false, ic95: [1, 2] }).label).toBe(
      'No es concluyente',
    )
    expect(verdict({ mode: 'grupos', source: 'prototype', conclusive: true, ic95: [1, 2] }).tone).toBe('good')
    expect(verdict({ mode: 'grupos', source: 'prototype', conclusive: true, ic95: [-2, -1] }).tone).toBe('bad')
    expect(verdict({ mode: 'grupos', source: 'prototype', conclusive: true, ic95: [-1, 2] }).tone).toBe('muted')
  })

  test('the survey reads with its one-sided p, without a threshold', () => {
    const survey = (p) => ({ concluyente: true, diferencia: { puntos: 5, ic95: [-1, 11], p_una_cola: p } })
    expect(surveyVerdict({ mode: 'grupos', source: 'prototype', survey: survey(0.01) })).toEqual({
      tone: 'good',
      label: 'Sube en tratamiento (p de una cola 0,010)',
    })
    expect(surveyVerdict({ mode: 'grupos', source: 'prototype', survey: survey(0.2) }).tone).toBe('muted')
    expect(surveyVerdict({ mode: 'grupos', source: 'synthetic', survey: survey(0.01) }).label).toBe(
      'Simulado: sin veredicto',
    )
  })

  test('formats', () => {
    expect(formatSigned(0.25)).toBe('+0,25')
    expect(formatSigned(-1)).toBe('−1,00')
    expect(formatSigned(null)).toBe('—')
    expect(monthName('2026-09')).toBe('septiembre')
    expect(monthName(null)).toBe('—')
  })
})
