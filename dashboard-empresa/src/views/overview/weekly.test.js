import { describe, expect, test } from 'vitest'
import { isPartialWeek, WEEKLY_SERIES, weeklySeries } from './weekly.js'

const [activeUsers, , cartAbandon] = WEEKLY_SERIES
const rows = [
  { semana: '2026-08-17', usuarios_activos: 100, abandono_carrito_pct: 30 },
  { semana: '2026-08-24', usuarios_activos: 110, abandono_carrito_pct: 29 },
  { semana: '2026-08-31', usuarios_activos: 120, abandono_carrito_pct: 28 },
  { semana: '2026-09-07', usuarios_activos: 130, abandono_carrito_pct: 27 },
  { semana: '2026-09-14', usuarios_activos: 150, abandono_carrito_pct: 25.5 },
  { semana: '2026-09-21', usuarios_activos: 40, abandono_carrito_pct: null },
]
const AS_OF = '2026-09-26T23:58:56-03:00'

describe('isPartialWeek', () => {
  test('la semana del corte es parcial hasta su domingo', () => {
    expect(isPartialWeek('2026-09-21', AS_OF)).toBe(true)
    expect(isPartialWeek('2026-09-21', '2026-09-27T10:00:00-03:00')).toBe(false)
    expect(isPartialWeek('2026-09-14', AS_OF)).toBe(false)
    expect(isPartialWeek('2026-09-21', null)).toBe(false)
  })
})

describe('weeklySeries', () => {
  test('compara la última semana completa con la de 4 semanas antes (conteos en %)', () => {
    const { points, latest, change } = weeklySeries(rows, activeUsers, AS_OF)

    expect(points.at(-1)).toEqual({ date: '2026-09-21', value: 40, partial: true })
    expect(latest.value).toBe(150)
    expect(change).toBe(50)
  })

  test('las tasas se comparan en puntos porcentuales y un null no cuenta como semana', () => {
    const { latest, change, formatChange } = weeklySeries(rows, cartAbandon, AS_OF)

    expect(latest.value).toBe(25.5)
    expect(change).toBeCloseTo(-4.5)
    expect(formatChange(change)).toBe('−4,5 puntos')
  })

  test('sin 5 semanas completas no hay cambio que mostrar', () => {
    const { change } = weeklySeries(rows.slice(-3), activeUsers, AS_OF)

    expect(change).toBeNull()
  })
})

describe('semanas sin dato', () => {
  const gap = [
    { semana: '2026-08-10', abandono_carrito_pct: 31 },
    { semana: '2026-08-17', abandono_carrito_pct: 30 },
    { semana: '2026-08-24', abandono_carrito_pct: null },
    { semana: '2026-08-31', abandono_carrito_pct: 28 },
    { semana: '2026-09-07', abandono_carrito_pct: 27 },
    { semana: '2026-09-14', abandono_carrito_pct: null },
    { semana: '2026-09-21', abandono_carrito_pct: 26 },
  ]

  test('si la última semana completa no tiene dato no se muestra otra como si fuera la última', () => {
    const { latest, change } = weeklySeries(gap, cartAbandon, AS_OF) // 21-09 es parcial; 14-09 sin carros
    expect(latest).toBeNull()
    expect(change).toBeNull()
  })

  test('la comparación es con la semana de 4 semanas antes por fecha, no por posición', () => {
    const complete = gap.slice(0, 5) // termina el 07-09: base = 10-08 (el hueco del 24-08 no corre la base)
    const { latest, change } = weeklySeries(complete, cartAbandon, AS_OF)
    expect(latest.date).toBe('2026-09-07')
    expect(change).toBe(27 - 31)
    const withoutBase = weeklySeries(gap.slice(2, 5), cartAbandon, AS_OF)
    expect(withoutBase.change).toBeNull()
  })
})
