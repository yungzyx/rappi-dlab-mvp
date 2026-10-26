// Las reglas de los flujos del seguimiento (fase 8): la línea de tiempo con espera, atraso y programado; cuándo y cuánto
// cuesta cancelar (de ejemplo); el cambio en vivo y el plazo de la ayuda.
import { describe, expect, test } from 'vitest'
import { CANCEL_FEE, cancelFee, cancelStage } from './cancel'
import { DELAY, delayCompensation } from './delay'
import { HELP_WINDOW_HOURS, helpDeadline } from './help'
import { hasLiveChanges, resolveChange, soldOutIndex } from './liveChanges'
import { FLOWS, deliveredAt, etaMinutes, isAhead, secondsSince, slotLabel, statusOf } from './progress'

const T0 = new Date(2026, 9, 21, 12).getTime()
const pizza = { name: 'Pizza', price: '$10.000', qty: 1, vertical: 'restaurants' }
const order = (extra = {}) => ({ placedAt: T0, items: [pizza], total: 12_000, stores: ['Pizzería'], ...extra })
const at = (seconds) => T0 + seconds * 1000

describe('línea de tiempo', () => {
  test('mientras la persona decide, el reloj espera, y sigue donde quedó', () => {
    expect(secondsSince(order({ heldAt: at(4) }), at(60))).toBe(4)
    expect(secondsSince(order({ pausedMs: 10_000 }), at(14))).toBe(4)
  })

  test('un atraso deja el pedido en su paso `delay.seconds` y después sigue', () => {
    const late = order({ delay: { ...DELAY, from: 5 } })
    expect(secondsSince(late, at(3))).toBe(3)
    expect(secondsSince(late, at(5 + DELAY.seconds / 2))).toBe(5)
    expect(secondsSince(late, at(5 + DELAY.seconds + 2))).toBe(7)
    expect(deliveredAt(late)).toBe(at(20 + DELAY.seconds))
  })

  test('el tiempo estimado suma el atraso y el tipo de entrega, y llega a 0 al llegar', () => {
    const plain = etaMinutes(order(), 1)
    expect(etaMinutes(order({ etaShift: 15 }), 1)).toBe(plain + 15)
    expect(etaMinutes(order({ etaShift: -8 }), 1)).toBe(plain - 8)
    expect(etaMinutes(order({ delay: { ...DELAY, from: 0 } }), 1)).toBe(plain + DELAY.minutes)
    expect(etaMinutes(order({ delay: { ...DELAY, from: 0 } }), 18)).toBe(0)
  })

  test('programado: espera su franja con su rótulo y empieza a la hora', () => {
    const slot = new Date(2026, 9, 21, 15).getTime()
    const scheduled = order({ scheduledFor: slot })
    expect(isAhead(scheduled, at(10))).toBe(true)
    expect(statusOf(scheduled, at(10))).toMatchObject({ kind: 'scheduled', short: 'Programado · hoy 15:00–16:00' })
    expect(statusOf(scheduled, slot + 1000).kind).toBe('active')
    expect(slotLabel(new Date(2026, 9, 22, 10).getTime(), T0)).toBe('mañana 10:00–11:00')
  })

  test('cancelado y atrasado en las listas', () => {
    expect(statusOf(order({ cancelled: { reason: 'ya_no' } }), at(30))).toMatchObject({ kind: 'cancelled', done: true })
    expect(statusOf(order({ delay: { ...DELAY, from: 4 } }), at(5)).short).toBe('Preparando · atrasado')
    expect(statusOf(order(), at(25)).kind).toBe('delivered')
  })
})

describe('cancelar', () => {
  test('gratis antes de que la tienda empiece, con costo después y nunca en camino', () => {
    expect(cancelStage(order(), at(1))).toBe('antes_de_tienda')
    expect(cancelStage(order(), at(4))).toBe('en_tienda')
    expect(cancelStage(order(), at(10))).toBeNull()
    expect(cancelStage(order({ scheduledFor: at(3600) }), at(10))).toBe('programado')
    expect(cancelStage(order({ cancelled: {} }), at(1))).toBeNull()
  })

  test('el costo de ejemplo es un porcentaje de los productos, con un mínimo', () => {
    expect(cancelFee(order(), 'antes_de_tienda')).toBe(0)
    expect(cancelFee(order(), 'en_tienda')).toBe(10_000 * CANCEL_FEE.rate)
    expect(cancelFee(order({ items: [{ ...pizza, price: '$1.000' }] }), 'en_tienda')).toBe(CANCEL_FEE.min)
  })
})

describe('atraso y ayuda', () => {
  test('solo Turbo compensa (con el total del pedido en Créditos de ejemplo)', () => {
    expect(delayCompensation(FLOWS.turbo, order())).toBe(12_000)
    expect(delayCompensation(FLOWS.restaurants, order())).toBe(0)
  })

  test('el plazo para pedir ayuda cuenta desde la entrega', () => {
    expect(helpDeadline(T0)).toBe(T0 + HELP_WINDOW_HOURS * 3_600_000)
  })
})

describe('cambios en vivo', () => {
  const pasta = {
    name: 'Tallarines',
    price: '$1.290',
    qty: 2,
    entityType: 'catalog_item',
    entityId: '1',
    product: { storeId: 9 },
  }
  test('solo en el Súper, y se agota el primer producto del catálogo con su tienda', () => {
    expect(hasLiveChanges({ vertical: 'supermercado', items: [] })).toBe(true)
    expect(hasLiveChanges({ vertical: 'turbo', items: [] })).toBe(false)
    expect(soldOutIndex({ items: [pizza, pasta] })).toBe(1)
  })

  test('el ajuste en el total: sustituto menos agotado por sus unidades, o el reembolso', () => {
    expect(resolveChange(pasta, 1, 'sustituto', { name: 'Fideos', price: '$1.490' }).delta).toBe(400)
    expect(resolveChange(pasta, 1, 'reembolso', null)).toMatchObject({ choice: 'reembolso', delta: -2580 })
    // «Elijan por mí» sin un sustituto en la tienda termina en reembolso.
    expect(resolveChange(pasta, 1, 'elijan', undefined).choice).toBe('reembolso')
  })
})
