import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, test } from 'vitest'
import { CONTRACT_METRICS, PANEL_METRICS } from './metrics.js'

// Las dos listas de rappi-ia/tests/integration/test_contract.py: las que escribe `make contract` (PANEL_METRICS) y las
// que guarda `npm run fixtures` (PANEL_SHAPE).
const contractTest = readFileSync(
  resolve(import.meta.dirname, '../../../rappi-ia/tests/integration/test_contract.py'),
  'utf8',
)
const pythonTuple = (name) => {
  const match = new RegExp(`^${name} = \\(([^)]*)\\)`, 'm').exec(contractTest)
  return [...match[1].matchAll(/"([\w-]+)"/g)].map(([, metric]) => metric)
}

describe('CONTRACT_METRICS', () => {
  test('are the ones `make contract` writes: npm run fixtures never overwrites them', () => {
    expect([...CONTRACT_METRICS].sort()).toEqual(pythonTuple('PANEL_METRICS').sort())
  })

  test('with the ones npm run fixtures saves, they are every metric of the panel', () => {
    const saved = PANEL_METRICS.filter((name) => !CONTRACT_METRICS.includes(name))
    expect(saved.sort()).toEqual(pythonTuple('PANEL_SHAPE').sort())
  })
})
