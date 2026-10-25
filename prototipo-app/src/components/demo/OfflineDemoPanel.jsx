import { useEffect, useState } from 'react'
import {
  addVisit,
  clearHistory,
  DEMO_HISTORY_EVENT,
  ladderReadout,
  personas,
  switchPersona,
} from '../../api/offline/personas'
import { loadSnapshot } from '../../api/offline/snapshot'
import { OFFLINE_STATE_EVENT } from '../../api/offline/state'
import './offline-demo-panel.css'

// Los 6 accesos chicos que ordena la Home (motor/home.py), con su nombre en la fila de accesos.
const VISITS = [
  ['supermercado', 'Súper'],
  ['farmacia', 'Farmacia'],
  ['mall', 'Rappi Mall'],
  ['licores', 'Licores'],
  ['conveniencia', 'Express'],
  ['chocolateria', 'Chocolates'],
]

/**
 * «Panel de la demo» de «Prototipo MVP.html» (solo el build sin conexión): elegir una persona con su historial, sumar
 * visitas a los accesos para ver cómo se reordena la Home, y leer en qué paso de la escalera está la persona.
 */
export default function OfflineDemoPanel() {
  const [open, setOpen] = useState(false)
  const [snapshot, setSnapshot] = useState(null)
  const [readout, setReadout] = useState('')

  useEffect(() => {
    loadSnapshot().then(setSnapshot)
  }, [])

  useEffect(() => {
    if (!snapshot || !open) return undefined
    const update = () => setReadout(ladderReadout(snapshot))
    update()
    // Cambia con el panel y también con lo que se hace en la app (un pedido, abrir RappiFavor…).
    window.addEventListener(DEMO_HISTORY_EVENT, update)
    window.addEventListener(OFFLINE_STATE_EVENT, update)
    return () => {
      window.removeEventListener(DEMO_HISTORY_EVENT, update)
      window.removeEventListener(OFFLINE_STATE_EVENT, update)
    }
  }, [snapshot, open])

  return (
    <div className="offline-demo">
      <button
        type="button"
        className="offline-demo-toggle"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        🎛️ Panel de la demo
      </button>
      {open && snapshot && (
        <section className="offline-demo-panel" aria-label="Panel de la demo">
          <p className="offline-demo-readout" role="status">
            {readout}
          </p>

          <h2>Persona</h2>
          <p className="offline-demo-help">Borra lo de ahora, siembra su historial y vuelve a la Home.</p>
          <div className="offline-demo-buttons">
            {personas(snapshot).map((persona) => (
              <button key={persona.id} type="button" onClick={() => switchPersona(snapshot, persona)}>
                {persona.label}
              </button>
            ))}
          </div>

          <h2>Mover la Home</h2>
          <p className="offline-demo-help">Cada toque es una visita al acceso en el prototipo (no en «Rappi hoy»).</p>
          <div className="offline-demo-buttons">
            {VISITS.map(([vertical, label]) => (
              <button key={vertical} type="button" onClick={() => addVisit(vertical)}>
                +1 visita a {label}
              </button>
            ))}
            <button type="button" className="is-danger" onClick={clearHistory}>
              Borrar historial
            </button>
          </div>
        </section>
      )}
    </div>
  )
}
