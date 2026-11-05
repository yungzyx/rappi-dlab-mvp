import { describe, expect, test } from 'vitest'
import { motorRows } from './motor.js'

const evaluation = {
  proximo_vertical: { combinado: { hit1: 0.9663, personas: 505 }, orden_fijo: { hit1: 0.8396 } },
  compra_cruzada: {
    personas: 505,
    mezcla: { precision3: 0.1294, personas_con_prediccion: 480 },
    lo_mas_pedido: { precision3: 0.1294 },
  },
  paso: { escalera: 0.5811, mas_sumada: 0.5946, personas: 74 },
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

  test('each row says how many people it is measured on, and the step gap without McNemar and under 100 is noise', () => {
    const rows = motorRows(evaluation)

    expect(rows.map((row) => [row.key, row.n, row.noise])).toEqual([
      ['proximo', 505, false],
      ['cruzada', 480, false],
      ['paso', 74, true],
    ])
    // Una corrida vieja sin personas_con_prediccion en la mezcla: las personas de la compra cruzada.
    const old = { ...evaluation, compra_cruzada: { ...evaluation.compra_cruzada, mezcla: { precision3: 0.1294 } } }
    expect(motorRows(old)[1].n).toBe(505)
  })

  test('with McNemar the step gap is noise only when p >= 0.05', () => {
    const step = (paso) => motorRows({ ...evaluation, paso: { ...evaluation.paso, ...paso } })[2]

    expect(step({ p_mcnemar: 0.01, personas: 200 }).noise).toBe(false)
    expect(step({ p_mcnemar: 0.42, personas: 200 }).noise).toBe(true)
    expect(step({ p_mcnemar: 0.42 }).p).toBe(0.42)
  })

  test('runs before the fine ladder have no step row', () => {
    expect(motorRows({ ...evaluation, paso: undefined }).map((row) => row.key)).toEqual(['proximo', 'cruzada'])
  })
})
