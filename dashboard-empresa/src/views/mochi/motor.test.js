import { describe, expect, test } from 'vitest'
import { motorRows } from './motor.js'

const evaluation = {
  proximo_vertical: { combinado: { hit1: 0.9663, personas: 505 }, orden_fijo: { hit1: 0.8396 } },
  compra_cruzada: { mezcla: { precision3: 0.1294 }, lo_mas_pedido: { precision3: 0.1294 } },
  paso: { escalera: 0.5811, mas_sumada: 0.5946 },
}

describe('motorRows', () => {
  test('each decision against its simple rule, in percent, with the gap in points', () => {
    const rows = motorRows(evaluation)

    expect(rows.map((row) => row.key)).toEqual(['proximo', 'cruzada', 'paso'])
    expect(rows[0].motor).toBeCloseTo(96.63)
    expect(rows[0].gap).toBe(12.6) // de las cifras que se muestran: 96,6 − 84,0
    expect(rows[1].gap).toBe(0)
    expect(rows[2].gap).toBe(-1.4) // 58,1 − 59,5
    expect(rows[2].baseLabel).toBe('La que más se suma')
  })

  test('runs before the fine ladder have no step row', () => {
    expect(motorRows({ ...evaluation, paso: undefined }).map((row) => row.key)).toEqual(['proximo', 'cruzada'])
  })
})
