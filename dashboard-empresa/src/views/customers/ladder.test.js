import { describe, expect, test } from 'vitest'
import combos from '../../fixtures/combos.synthetic.json'
import { biggestStep, ladderSteps, retentionDomain } from './ladder.js'

const rappi = combos.data.rappi.filas

describe('ladderSteps', () => {
  test('each starting combination goes to the one with one more group that retains the most', () => {
    const steps = ladderSteps(rappi).map((step) => [step.from.combo, step.to.combo, step.added, Math.round(step.gain)])

    expect(steps).toEqual([
      ['rest', 'rest+turbo', 'turbo', 35],
      ['turbo', 'rest+turbo', 'rest', 32],
      ['rest+turbo', 'rest+turbo+retail', 'retail', 11],
      ['retail', 'turbo+retail', 'turbo', 39],
      ['rest+retail', 'rest+turbo+retail', 'turbo', 17],
      ['turbo+retail', 'rest+turbo+retail', 'rest', 13],
    ])
  })

  test('the biggest step is where most users are: only restaurants, plus Turbo', () => {
    const step = biggestStep(rappi)

    expect(step.from.pct_usuarios).toBe(62.6)
    expect(step.fromPct).toBe(47)
    expect(step.toPct).toBe(82)
  })

  test('a combination without retention or without a next one is left out', () => {
    const rows = [
      { combo: 'rest', pct_usuarios: 50, retencion_m1: 0.4 },
      { combo: 'turbo', pct_usuarios: 20, retencion_m1: null },
      { combo: 'rest+turbo', pct_usuarios: 10, retencion_m1: null },
      { combo: 'favor', pct_usuarios: 5, retencion_m1: 0.3 },
    ]

    expect(ladderSteps(rows)).toEqual([])
    expect(biggestStep(rows)).toBeNull()
  })

  test('the axis starts at the tens below the lowest value and ends at 100%', () => {
    expect(retentionDomain(ladderSteps(rappi))).toEqual([30, 100])
    expect(retentionDomain([{ fromPct: 3, toPct: 10 }])).toEqual([0, 100])
    // Un paso que baja también cabe en el eje.
    expect(retentionDomain([{ fromPct: 60, toPct: 42 }])).toEqual([30, 100])
  })
})
