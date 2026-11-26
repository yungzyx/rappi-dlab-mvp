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

  test('with the assignment pace, the weeks left count against the people already assigned', () => {
    const paced = (pace, variantes = groups(900, 100)) =>
      pilotProgress(experiment({ ritmo: { por_semana: pace }, variantes })).rows
    const [h1, h2, h3] = paced({ tratamiento: 500, control: 50 })
    // H1: al tratamiento le falta asignar 6.936 a 500 por semana (13,9) y al control 771 a 50 (15,4): manda el control.
    expect(h1.weeks).toBe(16)
    expect(h2.weeks).toBeNull() // ya llegó
    expect(h3.weeks).toBeNull() // avanza con respuestas, no con asignaciones: sin su ritmo, no se estima
    // Ya están asignadas las que pide el mínimo, aunque todavía no cumplen su plazo: no falta asignar a nadie.
    expect(paced({ tratamiento: 500, control: 50 }, groups(9000, 1000))[0]).toMatchObject({ weeks: 0, done: false })
    // A un grupo al que le falta no le entra nadie, o no hay ritmo: no se puede estimar.
    expect(paced({ tratamiento: 500, control: 0 })[0].weeks).toBeNull()
    expect(paced(null)[0].weeks).toBeNull()
    expect(pilotProgress(experiment()).rows[0].weeks).toBeNull() // una respuesta sin `ritmo`
  })

  test('the H3 counts its weeks with the pace of answers, against the answers it already has', () => {
    const answers = (pace) => pilotProgress(experiment({ ritmo_encuesta: { por_semana: pace } })).rows[2]
    // Al tratamiento le faltan 40 respuestas a 20 por semana (2) y al control 75 a 10 (7,5): manda el control.
    expect(answers({ tratamiento: 20, control: 10 })).toMatchObject({ id: 'H3', weeks: 8, done: false })
    expect(answers({ tratamiento: 20, control: 0 }).weeks).toBeNull() // al control no le llega ninguna
    expect(answers(null).weeks).toBeNull()
    // Ya con las respuestas que pide, no hay nada que estimar.
    const done = pilotProgress(
      experiment({
        encuesta: { variantes: groups(120, 100, 'respondidas'), minimo: 100 },
        ritmo_encuesta: { por_semana: { tratamiento: 20, control: 10 } },
      }),
    ).rows[2]
    expect(done).toMatchObject({ done: true, weeks: null })
  })

  test('with one group empty there is nothing to measure, whether the control group is on or off', () => {
    expect(pilotProgress(experiment({ variantes: groups(900, 0) }))).toMatchObject({ on: false, assigning: true })
    expect(pilotProgress(experiment({ control_pct: 0, variantes: groups(0, 0) }))).toMatchObject({
      on: false,
      assigning: false,
    })
  })

  test('with the control group off but groups already there, it still measures them: no new assignments', () => {
    const pace = { ritmo: { por_semana: { tratamiento: 500, control: 50 } } }
    const { on, assigning, rows } = pilotProgress(experiment({ control_pct: 0, ...pace }))
    expect(on).toBe(true)
    expect(assigning).toBe(false)
    const [h1, h2] = rows
    expect(h1.share).toBeCloseTo(100 / 871)
    expect(h1.weeks).toBeNull() // nadie entra: el ritmo de antes no dice cuándo llega
    expect(h2).toMatchObject({ done: true, weeks: null })
    // Ya asignadas las que pide el mínimo: solo falta su plazo, también sin asignaciones nuevas.
    const assigned = pilotProgress(experiment({ control_pct: 0, ...pace, variantes: groups(9000, 1000) }))
    expect(assigned.rows[0]).toMatchObject({ weeks: 0, done: false })
  })
})
