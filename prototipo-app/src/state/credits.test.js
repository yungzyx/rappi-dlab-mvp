import { afterEach, describe, expect, test, vi } from 'vitest'
import { CREDITS } from '../screens/checkout/pricing'
import { addCredits, availableCredits, markCoupon, readWallet, spendCredits, welcomeLeft } from './credits'

afterEach(() => {
  vi.useRealTimers()
  localStorage.clear()
})

describe('saldo de créditos de ejemplo', () => {
  test('empieza con los del banner, guardados con su vencimiento (el mismo tras recargar)', () => {
    const first = readWallet()
    expect(first).toMatchObject({ welcome: CREDITS.amount, extra: 0, coupons: [] })
    expect(JSON.parse(localStorage.getItem('rappi-proto-creditos')).expiresAt).toBe(first.expiresAt)
    expect(readWallet()).toBe(first)
  })

  test('se gastan primero los del banner y después los demás; lo sumado no vence', () => {
    vi.useFakeTimers({ now: new Date(2026, 9, 26, 12) })
    addCredits(1_000)
    spendCredits(2_400)
    expect(readWallet()).toMatchObject({ welcome: 0, extra: 500 })
    addCredits(300)
    vi.setSystemTime(new Date(2026, 9, 27, 12))
    expect(availableCredits(readWallet())).toBe(800)
  })

  test('vencidos los del banner, no se gastan ni cuentan', () => {
    vi.useFakeTimers({ now: new Date(2026, 9, 26, 12) })
    readWallet()
    vi.setSystemTime(new Date(2026, 9, 26, 15))
    expect(welcomeLeft(readWallet())).toBe(0)
    addCredits(700)
    spendCredits(700)
    expect(readWallet()).toMatchObject({ welcome: CREDITS.amount, extra: 0 })
  })

  test('un cupón queda usado y vuelve si se cancela su pedido', () => {
    markCoupon('BIENVENIDA')
    markCoupon('BIENVENIDA')
    expect(readWallet().coupons).toEqual(['BIENVENIDA'])
    markCoupon('BIENVENIDA', false)
    expect(readWallet().coupons).toEqual([])
  })
})
