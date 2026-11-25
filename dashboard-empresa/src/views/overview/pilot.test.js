import { describe, expect, test } from 'vitest'
import { pilotProgress } from './pilot.js'

const groups = (treated, control, key = 'personas') => [
  { variante: 'tratamiento', [key]: treated },
  { variante: 'control', [key]: control },
]
const experiment = (overrides = {}) => ({
  control_pct: 10,
  variantes: groups(900, 100),
  retencion: { variantes: groups(900, 100), minimo: { tratamiento: 7836, control: 871 } },
  rest_a_turbo: { variantes: groups(400, 50), minimo: { tratamiento: 400, control: 40 } },
  encuesta: { variantes: groups(60, 25, 'respondidas'), minimo: 100 },
  ...overrides,
})

describe('pilotProgress', () => {
  test('each hypothesis is as far as its group that is furthest behind', () => {
    const { on, rows } = pilotProgress(experiment())
    expect(on).toBe(true)
    const [h1, h2, h3] = rows
    expect(h1).toMatchObject({ id: 'H1', done: false, have: { tratamiento: 900, control: 100 } })
    expect(h1.share).toBeCloseTo(100 / 871) // el control va más atrás que el tratamiento (900 de 7.836)
    expect(h2).toMatchObject({ id: 'H2', share: 1, done: true })
    expect(h3).toMatchObject({ id: 'H3', share: 0.25, done: false, need: { tratamiento: 100, control: 100 } })
  })

  test('without a minimum yet, a hypothesis has no share', () => {
    const { rows } = pilotProgress(experiment({ retencion: { variantes: groups(900, 100), minimo: null } }))
    expect(rows[0]).toMatchObject({ share: null, need: null, done: false })
  })

  test('with the control group off, or one group empty, there is nothing to measure', () => {
    expect(pilotProgress(experiment({ control_pct: 0 })).on).toBe(false)
    expect(pilotProgress(experiment({ variantes: groups(900, 0) })).on).toBe(false)
  })
})
