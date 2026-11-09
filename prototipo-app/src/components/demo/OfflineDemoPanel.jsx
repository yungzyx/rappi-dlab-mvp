import { useEffect, useState } from 'react'
import { AGENT_NAME } from '../../agent/name'
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
import { DEMO_DELAY_EVENT } from '../../screens/tracking/delay'
import { setAgentHidden, useAgentHidden } from '../../state/agentHidden'
import { useDemo } from '../../state/DemoContext'
import { useEvents } from '../../state/EventsContext'
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
 * "Panel de la demo" de "Prototipo MVP.html" (solo el build sin conexión): elegir una persona con su historial, sumar
 * visitas a los accesos para ver cómo se reordena la Home, leer en qué paso de la escalera está la persona, atrasar el
 * pedido en curso (el mensaje proactivo y, en Turbo, la garantía de ejemplo con Créditos) y, en el prototipo final,
 * ocultar a Mochi o traerlo de vuelta (como su menú y Cuenta, pero sin confirmar).
 */
export default function OfflineDemoPanel() {
  const [open, setOpen] = useState(false)
  const [snapshot, setSnapshot] = useState(null)
  const [readout, setReadout] = useState('')
  const { isFinal } = useDemo()
  const agentHidden = useAgentHidden()
  const events = useEvents()

  // El mismo cambio y el mismo evento que el menú de Mochi y Cuenta (`agent_visibility`), con su propio origen.
  const toggleAgent = () => {
    events.track('agent_visibility', { origin: 'panel-demo', payload: { visible: agentHidden } })
    setAgentHidden(!agentHidden)
  }

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
          <p className="offline-demo-help">
            Cada toque es una visita de otro día al acceso en el prototipo (no en "Rappi hoy").
          </p>
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

          <h2>Pedido en curso</h2>
          <p className="offline-demo-help">
            Atrasa el pedido en curso: sube el tiempo, llega un mensaje y, en Turbo, la garantía de ejemplo se paga en
            Créditos de ejemplo.
          </p>
          <div className="offline-demo-buttons">
            <button type="button" onClick={() => window.dispatchEvent(new Event(DEMO_DELAY_EVENT))}>
              Atrasar el pedido en curso
            </button>
          </div>

          {isFinal && (
            <>
              <h2>{AGENT_NAME}</h2>
              <p className="offline-demo-help">
                Lo oculta o lo trae de vuelta como su menú y Cuenta (aquí sin confirmar), y queda anotado igual.
              </p>
              <div className="offline-demo-buttons">
                <button type="button" onClick={toggleAgent}>
                  {agentHidden ? `Mostrar a ${AGENT_NAME}` : `Ocultar a ${AGENT_NAME}`}
                </button>
              </div>
            </>
          )}
        </section>
      )}
    </div>
  )
}
