import { useEffect, useRef } from 'react'
import { Icon } from './Icon.jsx'

/**
 * Ayuda a demanda: un botón (ícono ⓘ, o texto con `text`) que abre una definición. Es un <details>: accesible sin
 * JavaScript y con el teclado; además se cierra con Escape (el foco vuelve al botón) o al tocar fuera.
 */
export function Help({ label, text, children }) {
  const ref = useRef(null)

  useEffect(() => {
    const details = ref.current
    const onKeyDown = (event) => {
      if (event.key !== 'Escape' || !details.open) return
      details.open = false
      details.querySelector('summary').focus()
    }
    const onPointerDown = (event) => {
      if (details.open && !details.contains(event.target)) details.open = false
    }
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('pointerdown', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('pointerdown', onPointerDown)
    }
  }, [])

  return (
    <details ref={ref} className={text ? 'help help--text' : 'help'}>
      <summary className="help-button" aria-label={text ? undefined : `Ayuda: ${label}`}>
        {text ?? <Icon name="help" />}
      </summary>
      <div className="help-panel">{children}</div>
    </details>
  )
}
