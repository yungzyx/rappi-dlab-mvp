import { describe, expect, test } from 'vitest'
import { splitTrends } from './trends.js'
import saved from '../../fixtures/trends.synthetic.json'

const row = (concept_id, crecimiento_pct) => ({ concept_id, concepto: concept_id, crecimiento_pct })

describe('splitTrends', () => {
  test('separa y ordena del cambio más fuerte al más débil', () => {
    const { rising, falling, max } = splitTrends([row('a', 10), row('b', -40), row('c', 35), row('d', -5)])

    expect(rising.map((r) => r.concept_id)).toEqual(['c', 'a'])
    expect(falling.map((r) => r.concept_id)).toEqual(['b', 'd'])
    expect(max).toBe(40)
  })

  test('descarta cambios nulos o cero', () => {
    const { rising, falling } = splitTrends([row('a', null), row('b', 0)])

    expect(rising).toEqual([])
    expect(falling).toEqual([])
  })

  test('con los datos guardados: el que más sube va primero entre los que suben y el que más cae primero entre los que bajan', () => {
    const { rising, falling } = splitTrends(saved.data)
    const lowest = saved.data.reduce((min, row) => (row.crecimiento_pct < min.crecimiento_pct ? row : min))

    const highest = saved.data.reduce((max, row) => (row.crecimiento_pct > max.crecimiento_pct ? row : max))

    expect(rising[0].concept_id).toBe(highest.concept_id) // la simulación cambia con cada `make synth`: se lee del fixture
    expect(rising.some((row) => row.concept_id === 'peruana')).toBe(true) // el antojo sin oferta sigue subiendo
    expect(falling[0].concept_id).toBe(lowest.concept_id)
    expect(rising.length + falling.length).toBe(saved.data.length)
  })
})
