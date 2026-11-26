import { describe, expect, test } from 'vitest'
import { riskAudiences } from '../views/customers/audiences.js'
import { shareableSnapshot } from './shareable.js'

const atRisk = (source, data) => ({ source, data })
const person = (usuario, estado, concepto_top, consiente_avisos, dias_sin_pedir) => ({
  usuario,
  persona: 'foodie',
  estado,
  ritmo_dias: 7,
  dias_sin_pedir,
  concepto_top,
  consiente_avisos,
  accion: 'Recordatorio en su ritmo con su concepto top + complemento',
})

describe('shareableSnapshot', () => {
  const rows = [
    person('u-5a0b1c2d', 'en_riesgo', '🍕 Pizza', true, 30),
    person('u-77aa88bb', 'perdido', '🍣 Sushi', false, 60),
    person('u-12ab34cd', 'en_riesgo', '🍕 Pizza', false, 25),
  ]
  const snapshot = {
    grabado: { fecha: '2026-11-25', base: 'rappi_staging' },
    respuestas: {
      'at-risk.prototype': atRisk('prototype', rows),
      'at-risk.synthetic': atRisk('synthetic', rows),
      'kpis.prototype': { source: 'prototype', data: { en_riesgo: 2, perdidos: 1 } },
    },
  }

  test('the prototype at-risk list keeps only what the audiences count: no id, profile, pace or days', () => {
    const shared = shareableSnapshot(snapshot)
    const kept = shared.respuestas['at-risk.prototype']

    expect(kept.source).toBe('prototype')
    expect(JSON.stringify(kept)).not.toMatch(/u-5a0b1c2d|u-77aa88bb|u-12ab34cd|foodie|dias_sin_pedir|ritmo_dias/)
    for (const row of kept.data) expect(Object.keys(row).sort()).toEqual(['concepto_top', 'consiente_avisos', 'estado'])
    // Lo que el panel muestra de esa lista (las audiencias por concepto) no cambia.
    expect(riskAudiences(kept.data)).toEqual(riskAudiences(rows))
  })

  test('the order of the rows no longer says who was the most behind', () => {
    const kept = shareableSnapshot(snapshot).respuestas['at-risk.prototype'].data
    expect(kept.map((row) => `${row.estado} ${row.concepto_top} ${row.consiente_avisos}`)).toEqual([
      'en_riesgo 🍕 Pizza false',
      'en_riesgo 🍕 Pizza true',
      'perdido 🍣 Sushi false',
    ])
  })

  test('the simulated people and every other answer stay as they were, and the input is not changed', () => {
    const before = JSON.stringify(snapshot)
    const shared = shareableSnapshot(snapshot)

    expect(shared.respuestas['at-risk.synthetic']).toEqual(snapshot.respuestas['at-risk.synthetic'])
    expect(shared.respuestas['kpis.prototype']).toEqual(snapshot.respuestas['kpis.prototype'])
    expect(shared.grabado).toEqual(snapshot.grabado)
    expect(JSON.stringify(snapshot)).toBe(before)
  })

  test('a photo without the prototype list (or with an empty one) goes as is', () => {
    const empty = { respuestas: { 'at-risk.prototype': atRisk('prototype', []) } }
    expect(shareableSnapshot(empty)).toEqual(empty)
    expect(shareableSnapshot({ respuestas: {} })).toEqual({ respuestas: {} })
  })
})
