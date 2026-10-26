import { useSyncExternalStore } from 'react'
import { CREDITS } from '../screens/checkout/pricing'
import { loadStored, saveStored } from './storage'

// El saldo de créditos de ejemplo de la persona de la demo, en el navegador (como los pedidos y Pro; «Olvidar» lo
// borra). Empieza con los créditos del banner de la Home (`welcome`, que vencen con su cuenta regresiva, una sola fecha
// para los dos modos); el checkout los gasta, y la ayuda (reembolso en créditos), la garantía de Turbo y la cancelación
// (lo que el pedido había usado) suman a `extra`, que no vence. Los cupones de ejemplo se usan una vez (`coupons`) y
// vuelven si se cancela el pedido donde se usaron. Todo es un SUPUESTO de la demo: no son créditos ni cupones de Rappi.
export const CREDITS_KEY = 'rappi-proto-creditos'
const WELCOME_MINUTES = 116 // la cuenta regresiva del banner del video
const MINUTE_MS = 60_000

const listeners = new Set()
// La última lectura, para devolver el mismo objeto mientras no cambie lo guardado (useSyncExternalStore lo exige).
let cache = { raw: undefined, wallet: null }

const isWallet = (value) =>
  value &&
  typeof value === 'object' &&
  Number.isFinite(value.welcome) &&
  Number.isFinite(value.expiresAt) &&
  Number.isFinite(value.extra) &&
  Array.isArray(value.coupons)

const fresh = () => ({
  welcome: CREDITS.amount,
  expiresAt: Date.now() + WELCOME_MINUTES * MINUTE_MS,
  extra: 0,
  coupons: [],
})

const rawStored = () => {
  try {
    return localStorage.getItem(CREDITS_KEY)
  } catch {
    return null
  }
}

/** El saldo guardado (o uno nuevo, que se guarda: así la fecha de vencimiento es la misma tras recargar). */
export function readWallet() {
  const raw = rawStored()
  if (cache.wallet && raw === cache.raw) return cache.wallet
  const stored = loadStored(CREDITS_KEY, isWallet, null)
  const wallet = stored ?? fresh()
  if (!stored) saveStored(CREDITS_KEY, wallet)
  cache = { raw: rawStored(), wallet }
  return wallet
}

function write(change) {
  const before = readWallet()
  const wallet = { ...before, ...change(before) }
  saveStored(CREDITS_KEY, wallet)
  cache = { raw: rawStored(), wallet }
  listeners.forEach((listener) => listener())
}

/** Lo que vale todavía de los créditos del banner (0 si vencieron). */
export const welcomeLeft = (wallet, now = Date.now()) => (now < wallet.expiresAt ? wallet.welcome : 0)

/** Los créditos que se pueden usar ahora. */
export const availableCredits = (wallet, now = Date.now()) => welcomeLeft(wallet, now) + wallet.extra

/** Gasta `amount`: primero los del banner (vencen antes), después los demás. */
export function spendCredits(amount, now = Date.now()) {
  if (!(amount > 0)) return
  write((wallet) => {
    const fromWelcome = Math.min(amount, welcomeLeft(wallet, now))
    return { welcome: wallet.welcome - fromWelcome, extra: Math.max(0, wallet.extra - (amount - fromWelcome)) }
  })
}

/** Suma `amount` al saldo (ayuda, garantía de Turbo, cancelación). */
export function addCredits(amount) {
  if (!(amount > 0)) return
  write((wallet) => ({ extra: wallet.extra + amount }))
}

/** ¿Ya se usó este cupón de ejemplo? */
export const couponUsed = (wallet, code) => wallet.coupons.includes(code)

/** Marca el cupón como usado (`used = false`: vuelve, al cancelar el pedido donde se usó). */
export function markCoupon(code, used = true) {
  if (!code) return
  write((wallet) => ({
    coupons: used ? [...new Set([...wallet.coupons, code])] : wallet.coupons.filter((c) => c !== code),
  }))
}

const subscribe = (listener) => {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** El saldo de créditos y cupones de la demo: `{ welcome, expiresAt, extra, coupons }`. */
export const useWallet = () => useSyncExternalStore(subscribe, readWallet)
