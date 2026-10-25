import { resetLive } from '../state/liveMemory'
import { MODE_LABELS, useDemo } from '../state/DemoContext'
import './demo-toggle.css'

/** Interruptor de los dos modos fuera del marco del teléfono (solo en notebook). En el prototipo final, repetir la escena. */
export default function DemoToggle() {
  const demo = useDemo()
  // El interruptor es de la presentación: el sitio desplegado lo muestra solo con VITE_DEMO=1 en el build.
  if (!(import.meta.env.DEV || import.meta.env.VITE_DEMO === '1')) return null

  return (
    <div className="demo-toggle">
      <div className="demo-toggle-modes" role="radiogroup" aria-label="Modo de la demo">
        {Object.entries(MODE_LABELS).map(([mode, label]) => (
          <button
            key={mode}
            type="button"
            role="radio"
            aria-checked={demo.mode === mode}
            className={demo.mode === mode ? 'is-active' : undefined}
            onClick={() => demo.setMode(mode)}
          >
            {label}
          </button>
        ))}
      </div>
      {demo.isFinal && (
        <button type="button" className="demo-toggle-replay" onClick={resetLive}>
          ↺ Repetir escena
        </button>
      )}
      <span className="demo-toggle-hint">Tecla D</span>
    </div>
  )
}
