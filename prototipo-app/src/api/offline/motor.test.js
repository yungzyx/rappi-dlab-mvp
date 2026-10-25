import { describe, expect, test } from 'vitest'
import { currentFine, fineExpectation, homeVerticals, stepSignal, targetStep } from './motor'
import { COMBOS, LABELS } from '../../test/offlineMeta'

const NOW = Date.UTC(2026, 9, 17, 15)
const MIN = 60_000
let n = 0
const order = (vertical, { mode = 'propuesta', ago = 0 } = {}) => ({
  order_id: `o-${(n += 1)}`,
  ts: NOW - ago,
  vertical,
  mode,
  lines: [],
})
const open = (vertical, { mode, ago = MIN } = {}) => ({
  type: 'vertical_open',
  ts: NOW - ago,
  vertical,
  payload: mode ? { mode } : {},
})
const serviceOpened = (servicio) => ({ type: 'service_opened', ts: NOW - MIN, vertical: null, payload: { servicio } })
const state = ({ orders = [], events = [] } = {}) => ({ userId: 'proto-test', orders, events })
const home = (s) => homeVerticals(s, NOW, LABELS)
const ids = (reply) => reply.order.map((entry) => entry.id)
const step = (s) => targetStep(COMBOS, s, NOW)

describe('orden de la Home (motor/home.py)', () => {
  test('sin historial queda el orden fijo, sin porqué y sin personalizar', () => {
    const reply = home(state())
    expect(reply.fixed).toEqual(['restaurantes', 'turbo'])
    expect(ids(reply)).toEqual(['supermercado', 'farmacia', 'mall', 'licores', 'conveniencia', 'chocolateria'])
    expect(reply.personalized).toBe(false)
    expect(reply.order.every((entry) => entry.reason === null)).toBe(true)
  })

  test('los toques a Farmacia la suben primera entre los accesos chicos, con «Porque entras seguido a…»', () => {
    const reply = home(state({ events: [open('farmacia'), open('farmacia'), open('mall')] }))
    expect(ids(reply)).toEqual(['farmacia', 'mall', 'supermercado', 'licores', 'conveniencia', 'chocolateria'])
    expect(reply.personalized).toBe(true)
    expect(reply.order[0].reason).toEqual({
      text: 'Porque entras seguido a farmacia.',
      basis: [{ kind: 'afinidad_vertical', id: 'farmacia', source: 'eventos' }],
    })
    expect(reply.order[1].reason).toBeNull()
  })

  test('los pedidos dicen «Porque pides seguido en…» y contraen el artículo', () => {
    const reply = home(state({ orders: [order('supermercado')] }))
    expect(reply.order[0]).toMatchObject({ id: 'supermercado', reason: { text: 'Porque pides seguido en el súper.' } })
    const visits = home(state({ events: [open('supermercado')] }))
    expect(visits.order[0].reason.text).toBe('Porque entras seguido al súper.')
  })

  test('Restaurantes y Turbo quedan fijos: usarlos no mueve los accesos chicos', () => {
    const reply = home(state({ orders: [order('restaurantes'), order('turbo')], events: [open('turbo')] }))
    expect(reply.fixed).toEqual(['restaurantes', 'turbo'])
    expect(ids(reply)).toEqual(['supermercado', 'farmacia', 'mall', 'licores', 'conveniencia', 'chocolateria'])
    expect(reply.personalized).toBe(false)
  })

  test('los toques y pedidos de «Rappi hoy» no enseñan', () => {
    const reply = home(
      state({
        orders: [order('chocolateria', { mode: 'actual' })],
        events: [open('chocolateria', { mode: 'actual' })],
      }),
    )
    expect(reply.personalized).toBe(false)
    expect(ids(reply)[0]).toBe('supermercado')
  })

  test('las señales de hace más de 180 días no cuentan', () => {
    const reply = home(state({ events: [open('mall', { ago: 181 * 86_400_000 })] }))
    expect(reply.personalized).toBe(false)
  })
})

describe('la escalera fina (motor/combos.py, predict.py)', () => {
  test('restaurantes → turbo', () => {
    const s = state({ orders: [order('restaurantes')] })
    expect(step(s)).toMatchObject({ vertical: 'turbo', current: 'restaurantes', target: 'restaurantes+turbo' })
    expect(stepSignal(COMBOS, step(s))).toEqual({
      kind: 'combinacion',
      id: 'restaurantes→restaurantes+turbo',
      source: 'rappi',
    })
  })

  test('turbo → restaurantes', () => {
    expect(step(state({ orders: [order('turbo')] })).vertical).toBe('restaurantes')
  })

  test('restaurantes + turbo → supermercado (la primera de retail, por el orden que desempata)', () => {
    const s = state({ orders: [order('restaurantes'), order('turbo')] })
    expect(step(s)).toMatchObject({ vertical: 'supermercado', target: 'restaurantes+turbo+supermercado' })
  })

  test('el uso propio de la persona desempata dentro de retail', () => {
    const s = state({ orders: [order('restaurantes'), order('turbo')], events: [open('chocolateria')] })
    expect(step(s).vertical).toBe('chocolateria')
  })

  test('dentro de un grupo se aplica el supuesto del rendimiento decreciente y la basis lo dice', () => {
    const s = state({ orders: [order('restaurantes'), order('turbo'), order('supermercado')] })
    const next = step(s)
    expect(next.vertical).toBe('mall') // sin afinidad, el orden de siempre desempata (mall antes que Express)
    expect(stepSignal(COMBOS, next).source).toBe('rappi+supuesto')
  })

  test('todo el catálogo → RappiFavor → RappiTravel, y después nada', () => {
    const all = ['restaurantes', 'turbo', 'supermercado', 'conveniencia', 'mall', 'chocolateria'].map((v) => order(v))
    expect(step(state({ orders: all })).vertical).toBe('favor')
    expect(step(state({ orders: all, events: [serviceOpened('rappifavor')] })).vertical).toBe('travel')
    expect(step(state({ orders: all, events: [serviceOpened('rappifavor'), serviceOpened('rappitravel')] }))).toBeNull()
  })

  test('nunca Farmacia ni Licores, aunque sean las más usadas', () => {
    const events = Array.from({ length: 20 }, () => [open('farmacia'), open('licores')]).flat()
    const s = state({ orders: [order('restaurantes'), order('turbo')], events })
    expect(step(s).vertical).toBe('supermercado')
    const all = ['restaurantes', 'turbo', 'supermercado', 'conveniencia', 'mall', 'chocolateria'].map((v) => order(v))
    expect(step(state({ orders: all, events })).vertical).toBe('favor')
  })

  test('la basis nunca nombra Farmacia ni Licores, aunque cuenten en la combinación', () => {
    const s = state({ orders: [order('restaurantes'), order('farmacia'), order('licores')] })
    expect(currentFine(COMBOS, s, NOW)).toBe('restaurantes+farmacia+licores')
    expect(stepSignal(COMBOS, step(s)).id).toBe('restaurantes→restaurantes+turbo')
  })

  test('sin pedidos no hay paso; los pedidos de «Rappi hoy» y los servicios abiertos ahí no cuentan', () => {
    expect(step(state())).toBeNull()
    expect(step(state({ orders: [order('restaurantes', { mode: 'actual' })] }))).toBeNull()
    const all = ['restaurantes', 'turbo', 'supermercado', 'conveniencia', 'mall', 'chocolateria'].map((v) => order(v))
    const opened = { ...serviceOpened('rappifavor'), payload: { servicio: 'rappifavor', mode: 'actual' } }
    expect(step(state({ orders: all, events: [opened] })).vertical).toBe('favor')
  })

  test('los pedidos de hace más de 30 días cuentan solo si no hay en 30 (ventana de 90)', () => {
    const DAY = 86_400_000
    const s = state({ orders: [order('turbo', { ago: 45 * DAY })] })
    expect(currentFine(COMBOS, s, NOW)).toBe('turbo')
    expect(currentFine(COMBOS, state({ orders: [order('turbo', { ago: 120 * DAY })] }), NOW)).toBe('ninguna')
  })

  test('la retención esperada calza con la tabla de Rappi y nunca llega a 1', () => {
    expect(fineExpectation(COMBOS, 'restaurantes+turbo')).toEqual([0.82, false])
    const [value, used] = fineExpectation(COMBOS, 'restaurantes+turbo+supermercado+conveniencia+favor')
    expect(value).toBeCloseTo(1 - 0.07 * 0.9 * 0.95, 10)
    expect(used).toBe(true)
    expect(fineExpectation(COMBOS, 'travel')).toEqual([null, false])
  })
})
