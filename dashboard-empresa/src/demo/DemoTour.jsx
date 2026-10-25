import { AGENT_NAME } from '../lib/agentName.js'
import { useEffect, useRef, useState } from 'react'
import snapshot from 'virtual:panel-snapshot'
import { Icon } from '../components/Icon.jsx'
import { setDemoResponses } from '../lib/api.js'
import { responsesAfter, TOUR } from './tour.js'
import './demo.css'

const INTRO = {
  title: 'Así reacciona el panel al uso de la app',
  text: `Sigue a una persona nueva en el prototipo: ${AGENT_NAME} le ofrece un kit, lo acepta, paga y busca algo que no hay. Cada paso suma un evento de ejemplo a lo grabado y te lleva a donde cambia.`,
  view: 'mochi',
  section: 'ofertas',
}
const OUTRO = {
  title: 'Así funciona con la API',
  text: 'La app manda cada evento, la API los cuenta y el panel los muestra al tocar «Actualizar». Al cerrar, las cifras vuelven a la foto grabada.',
}
const HIGHLIGHT_MS = 1800

/**
 * «Ver cómo funciona» (solo en el panel en un solo HTML): un recorrido corto que aplica eventos de ejemplo a las
 * respuestas grabadas de la fuente del prototipo y lleva a la sección que cambia. La tarjeta dice siempre que es una
 * demostración; al cerrarla, el panel vuelve a la foto. `onShow(destino)` cambia de vista (o, sin destino, solo vuelve a
 * pintar los datos).
 */
export default function DemoTour({ onShow }) {
  const [step, setStep] = useState(null) // null: cerrada · 0: inicio · 1…N: pasos · N + 1: final
  const launch = useRef(null)
  const advance = useRef(null)
  const open = useRef(false)
  const stop = step === null ? null : step === 0 ? INTRO : (TOUR[step - 1] ?? OUTRO)

  const go = (next) => {
    setDemoResponses(next ? responsesAfter(snapshot.respuestas, Math.min(next, TOUR.length)) : {})
    setStep(next)
    const target = next === null ? null : next === 0 ? INTRO : TOUR[next - 1]
    onShow(target ? { view: target.view, section: target.section } : null)
  }

  // Al abrir, el foco va al botón que avanza (el que abrió desaparece); al cerrar, vuelve a «Ver cómo funciona».
  useEffect(() => {
    if (step === null) {
      if (open.current) launch.current?.focus()
      open.current = false
    } else if (!open.current) {
      open.current = true
      advance.current?.focus()
    }
  }, [step])

  // Escape cierra la demostración desde cualquier parte de la página.
  useEffect(() => {
    if (step === null) return undefined
    const close = (event) => {
      if (event.key === 'Escape') go(null)
    }
    document.addEventListener('keydown', close)
    return () => document.removeEventListener('keydown', close)
  })

  // Marca un momento la sección que cambió.
  useEffect(() => {
    const section = stop?.section && document.getElementById(stop.section)?.closest('section')
    if (!section) return undefined
    section.classList.add('demo-highlight')
    const timer = setTimeout(() => section.classList.remove('demo-highlight'), HIGHLIGHT_MS)
    return () => {
      clearTimeout(timer)
      section.classList.remove('demo-highlight')
    }
  }, [stop])

  if (step === null) {
    return (
      <button type="button" className="demo-launch" ref={launch} onClick={() => go(0)}>
        <Icon name="chart" />
        Ver cómo funciona
      </button>
    )
  }

  const last = step === TOUR.length + 1
  return (
    <aside className="demo-tour" aria-label="Ver cómo funciona">
      <header className="demo-tour-head">
        <span className="badge badge--simulated">
          <Icon name="flask" />
          Demostración
        </span>
        {step > 0 && !last && (
          <span className="demo-tour-count">
            Paso {step} de {TOUR.length}
          </span>
        )}
      </header>
      <div aria-live="polite">
        <h2>{stop.title}</h2>
        <p>{stop.text}</p>
      </div>
      <p className="demo-tour-note">Eventos de ejemplo sobre la foto grabada: no son datos reales.</p>
      <div className="demo-tour-actions">
        <button type="button" className="link-button" onClick={() => go(null)}>
          Cerrar
        </button>
        {/* Un solo botón que avanza: así el foco no se pierde al pasar de un paso a otro ni al final. */}
        <button type="button" className="demo-next" ref={advance} onClick={() => go(last ? 0 : step + 1)}>
          {last ? 'Repetir' : step === 0 ? 'Empezar' : step === TOUR.length ? 'Terminar' : 'Siguiente'}
        </button>
      </div>
    </aside>
  )
}
