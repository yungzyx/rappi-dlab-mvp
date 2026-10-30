import { useEffect, useState } from 'react'
import { ChevronRight } from '../../components/Icons'
import { formatPrice } from '../../state/CartContext'
import { availableCredits, useWallet, welcomeLeft } from '../../state/credits'

const MINUTE_MS = 60_000
const TICK_MS = 1_000

/** "1 h 56 min" (como en el checkout), o "56 min". */
export function formatRemaining(ms) {
  const totalMinutes = Math.max(0, Math.ceil(ms / MINUTE_MS))
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return hours > 0 ? `${hours} h ${minutes} min` : `${minutes} min`
}

/**
 * Banner de créditos con cuenta regresiva, como en la Home del video. Muestra el saldo de créditos de ejemplo de la
 * demo (state/credits.js): baja al usarlos en el checkout, sube con la ayuda o una cancelación y desaparece en cero. La
 * cuenta regresiva es la de los créditos del banner (una sola fecha, guardada: la misma en los dos modos).
 */
export default function CreditsBanner({ credits, onClick }) {
  const wallet = useWallet()
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), TICK_MS)
    return () => clearInterval(timer)
  }, [])

  const amount = availableCredits(wallet, now)
  if (amount <= 0) return null
  return (
    <button type="button" className="credits-banner tap" onClick={onClick}>
      <img src={credits.logo} alt="" />
      <span className="credits-text">
        <strong>{formatPrice(amount)} en créditos</strong>
        <span>{credits.subtitle}</span>
      </span>
      {welcomeLeft(wallet, now) > 0 && <span className="credits-timer">{formatRemaining(wallet.expiresAt - now)}</span>}
      <ChevronRight size={18} />
    </button>
  )
}
