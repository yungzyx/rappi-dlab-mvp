import { describe, expect, test } from 'vitest'
import { notableChanges } from './changes.js'

// Seis semanas completas al 14-06 (domingo): la última, la del 08-06, se compara con la del 11-05.
const WEEKS = ['2026-05-04', '2026-05-11', '2026-05-18', '2026-05-25', '2026-06-01', '2026-06-08']
const AS_OF = '2026-06-14T23:59:00-04:00'
const weekly = (overrides = {}) =>
  WEEKS.map((semana, index) => ({
    semana,
    usuarios_activos: 100,
    pedidos: 200,
    abandono_carrito_pct: 30,
    sin_resultado_pct: 20,
    ...(index === WEEKS.length - 1 ? overrides : {}),
  }))
const changes = (input) => notableChanges({ weekly: weekly(), asOf: AS_OF, trends: [], opportunities: [], ...input })

describe('notableChanges', () => {
  test('nothing moved enough: nothing to show', () => {
    expect(changes({ weekly: weekly({ usuarios_activos: 104, abandono_carrito_pct: 30.9 }) })).toEqual([])
  })

  test('what gets worse goes first, then what improves, each with its figure and how much it moved', () => {
    const items = changes({ weekly: weekly({ usuarios_activos: 120, pedidos: 180, abandono_carrito_pct: 33 }) })
    expect(items.map((item) => [item.key, item.tone, item.figure, item.change])).toEqual([
      ['pedidos', 'bad', '180', '−10%'],
      ['abandono_carrito_pct', 'bad', '33,0%', '+3,0 puntos'],
      ['usuarios_activos', 'good', '120', '+20%'],
    ])
    expect(items[0].detail).toBe('frente a hace 4 semanas')
    expect(items.every((item) => item.target === null)).toBe(true) // los tres ya están en el Resumen
  })

  test('searches with no result link to their detail in the other view', () => {
    const [item] = changes({ weekly: weekly({ sin_resultado_pct: 25 }) })
    expect(item).toMatchObject({ key: 'sin_resultado_pct', tone: 'bad', target: ['mochi', 'busquedas'] })
  })

  test('growing demand goes last and without judgment; the same concept is not repeated', () => {
    const opportunities = [
      { concept_id: 'peruana', que: 'Comida peruana', usuarios: 700, crecimiento_pct: 31 },
      { concept_id: 'thai', que: 'Comida thai', usuarios: 900, crecimiento_pct: 5 }, // no crece lo suficiente
    ]
    const trends = [
      { concept_id: 'peruana', concepto: 'Comida peruana', recientes: 90, anteriores: 40, crecimiento_pct: 125 },
      { concept_id: 'asiatica', concepto: 'Despensa asiática', recientes: 62, anteriores: 37, crecimiento_pct: 68 },
    ]
    const items = changes({ weekly: weekly({ pedidos: 150 }), opportunities, trends })
    expect(items.map((item) => [item.key, item.tone])).toEqual([
      ['pedidos', 'bad'],
      ['sube-asiatica', 'muted'],
      ['falta-peruana', 'muted'],
    ])
    expect(items[2]).toMatchObject({ figure: '700 personas', change: '+31%', target: ['mochi', 'busquedas'] })
  })

  test('at most `limit` changes', () => {
    const moved = weekly({ usuarios_activos: 50, pedidos: 100, abandono_carrito_pct: 40, sin_resultado_pct: 30 })
    const trends = [{ concept_id: 'a', concepto: 'A', recientes: 9, anteriores: 3, crecimiento_pct: 200 }]
    expect(changes({ weekly: moved, trends })).toHaveLength(4)
    expect(changes({ weekly: moved, trends, limit: 2 })).toHaveLength(2)
  })
})
