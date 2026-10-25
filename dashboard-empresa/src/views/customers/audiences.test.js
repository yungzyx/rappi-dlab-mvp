import { describe, expect, test } from 'vitest'
import { NO_CONCEPT, riskAudiences, withConsent } from './audiences.js'

const person = (concepto_top, estado, consiente_avisos) => ({ concepto_top, estado, consiente_avisos })

describe('riskAudiences', () => {
  test('groups people by what they ordered most, largest first, counting at risk and consent', () => {
    const rows = [
      person('🍕 Pizza', 'en_riesgo', true),
      person('🍔 Hamburguesa', 'en_riesgo', false),
      person('🍕 Pizza', 'perdido', false),
      person('🍕 Pizza', 'en_riesgo', true),
      person('🍔 Hamburguesa', 'perdido', true),
      person('☕ Café', 'en_riesgo', false),
    ]

    expect(riskAudiences(rows)).toEqual([
      { concept: '🍕 Pizza', people: 3, atRisk: 2, withConsent: 2 },
      { concept: '🍔 Hamburguesa', people: 2, atRisk: 1, withConsent: 1 },
      { concept: '☕ Café', people: 1, atRisk: 1, withConsent: 0 },
    ])
    expect(withConsent(rows)).toBe(3)
  })

  test('people without a top concept get their own group', () => {
    expect(riskAudiences([person(null, 'en_riesgo', false)])).toEqual([
      { concept: NO_CONCEPT, people: 1, atRisk: 1, withConsent: 0 },
    ])
  })

  test('no rows, no audiences', () => {
    expect(riskAudiences([])).toEqual([])
  })
})
