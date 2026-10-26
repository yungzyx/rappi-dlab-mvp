import { describe, expect, test } from 'vitest'
import { anyClosed, slotsFor } from './schedule'

const NOW = new Date(2026, 9, 21, 12, 20).getTime() // miércoles 12:20
const hours = (slots, day) => slots.filter((s) => s.day === day).map((s) => new Date(s.from).getHours())

describe('franjas para programar', () => {
  test('sin horario publicado: la ventana de ejemplo, desde una hora después de ahora, hoy y mañana', () => {
    const slots = slotsFor([null], NOW)
    expect(hours(slots, 'hoy')).toEqual([14, 15, 16, 17, 18, 19, 20, 21])
    expect(hours(slots, 'manana')[0]).toBe(10)
    expect(hours(slots, 'manana').at(-1)).toBe(21)
    expect(slots.every((s) => s.to - s.from === 3_600_000)).toBe(true)
  })

  test('un restaurante: solo franjas que caben en su horario de hoy y de mañana', () => {
    const spans = {
      hoy: [
        ['12:00', '16:00'],
        ['19:00', '24:00'],
      ],
      manana: [['12:00', '15:00']],
    }
    const slots = slotsFor([{ spans }], NOW)
    expect(hours(slots, 'hoy')).toEqual([14, 15, 19, 20, 21, 22, 23])
    expect(hours(slots, 'manana')).toEqual([12, 13, 14])
  })

  test('una tienda cerrada en la descarga: hoy desde que abría (si se publicó) y si no, mañana', () => {
    expect(hours(slotsFor([{ hours: { open: false, opens_at: '17:00' } }], NOW), 'hoy')).toEqual([17, 18, 19, 20, 21])
    expect(hours(slotsFor([{ hours: { open: false } }], NOW), 'hoy')).toEqual([])
    expect(anyClosed([{ hours: { open: true } }, { hours: { open: false } }])).toBe(true)
    expect(anyClosed([null, { hours: { open: null } }])).toBe(false)
  })

  test('dos tiendas: las franjas que sirven a las dos', () => {
    const spans = { hoy: [['18:00', '22:00']], manana: [] }
    expect(hours(slotsFor([null, { spans }], NOW), 'hoy')).toEqual([18, 19, 20, 21])
  })
})
