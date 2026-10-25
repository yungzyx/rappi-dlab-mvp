import { describe, expect, test } from 'vitest'
import { priceBreakdown } from './pricing'

describe('priceBreakdown', () => {
  test('con Pro el envío es gratis y la tarifa de servicio es 3% (mínimo $490)', () => {
    expect(priceBreakdown({ subtotal: 20000, tip: 1000, pickup: false })).toEqual({
      subtotal: 20000,
      delivery: 0,
      service: 600,
      tip: 1000,
      total: 21600,
    })
    expect(priceBreakdown({ subtotal: 5000, tip: 0, pickup: false }).service).toBe(490)
  })

  test('sin Pro se cobra el envío', () => {
    expect(priceBreakdown({ subtotal: 20000, tip: 0, pickup: false, isPro: false }).delivery).toBe(1990)
  })

  test('retiro en tienda no cobra envío ni propina', () => {
    const pickup = priceBreakdown({ subtotal: 20000, tip: 1500, pickup: true, isPro: false })
    expect(pickup.delivery).toBe(0)
    expect(pickup.tip).toBe(0)
    expect(pickup.total).toBe(20600)
  })

  test('carrito vacío no cobra servicio', () => {
    expect(priceBreakdown({ subtotal: 0, tip: 0, pickup: false }).total).toBe(0)
  })
})
