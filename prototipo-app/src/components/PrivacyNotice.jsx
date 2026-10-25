import { useState } from 'react'
import './privacy-notice.css'

// El aviso se muestra una vez por navegador; la clave se borra con «Borrar mis datos» (lleva el prefijo rappi-proto-).
const SEEN_KEY = 'rappi-proto-privacy-seen'

function wasSeen() {
  try {
    return localStorage.getItem(SEEN_KEY) !== null
  } catch {
    return false // sin almacenamiento no se puede recordar: se muestra y se cierra para esta visita
  }
}

function markSeen() {
  try {
    localStorage.setItem(SEEN_KEY, '1')
  } catch {
    // Sin almacenamiento: vale lo que dura la visita.
  }
}

/**
 * Qué se guarda y cómo borrarlo, la primera vez que alguien abre la app. «Entendido» lo cierra; «Ir a Cuenta»
 * (`onOpenAccount`) también, y lleva a «Borrar mis datos».
 */
export default function PrivacyNotice({ onOpenAccount }) {
  const [open, setOpen] = useState(() => !wasSeen())
  if (!open) return null

  const close = () => {
    markSeen()
    setOpen(false)
  }

  return (
    <section className="privacy-notice" role="region" aria-label="Privacidad">
      <p>
        Para recomendarte mejor guardamos tus búsquedas y lo que haces en la app con un identificador anónimo. Puedes
        borrarlo en Cuenta → Borrar mis datos.
      </p>
      <div className="privacy-notice-actions">
        <button
          type="button"
          className="privacy-notice-account tap"
          onClick={() => {
            close()
            onOpenAccount()
          }}
        >
          Ir a Cuenta
        </button>
        <button type="button" className="privacy-notice-ok tap" onClick={close}>
          Entendido
        </button>
      </div>
    </section>
  )
}
