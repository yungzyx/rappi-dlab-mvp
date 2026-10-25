import { useEffect, useState } from 'react'
import { ChevronRight } from '../../components/Icons'

const MINUTE_MS = 60_000
const TICK_MS = 1_000

// Fecha límite fija al cargar la página, para que el contador no se reinicie al cambiar de pantalla.
const deadlines = new Map()

function getDeadline(key, minutes) {
  if (!deadlines.has(key)) deadlines.set(key, Date.now() + minutes * MINUTE_MS)
  return deadlines.get(key)
}

function formatRemaining(ms) {
  const totalMinutes = Math.max(0, Math.ceil(ms / MINUTE_MS))
  const hours = String(Math.floor(totalMinutes / 60)).padStart(2, '0')
  const minutes = String(totalMinutes % 60).padStart(2, '0')
  return `${hours}h: ${minutes}m`
}

/** Banner de créditos con cuenta regresiva ("01h: 56m"), como en la Home del video. */
export default function CreditsBanner({ credits, onClick }) {
  const deadline = getDeadline(credits.title, credits.expiresInMinutes)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), TICK_MS)
    return () => clearInterval(timer)
  }, [])

  return (
    <button type="button" className="credits-banner tap" onClick={onClick}>
      <img src={credits.logo} alt="" />
      <span className="credits-text">
        <strong>{credits.title}</strong>
        <span>{credits.subtitle}</span>
      </span>
      <span className="credits-timer">{formatRemaining(deadline - now)}</span>
      <ChevronRight size={18} />
    </button>
  )
}
