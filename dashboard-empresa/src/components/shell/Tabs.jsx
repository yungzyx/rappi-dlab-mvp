import { useRef } from 'react'

const KEY_MOVES = { ArrowRight: 1, ArrowLeft: -1 }

/** Pestañas WAI-ARIA con foco itinerante: ← → recorren, Inicio y Fin saltan a los extremos. */
export function Tabs({ views, active, onSelect }) {
  const buttons = useRef(new Map())

  const onKeyDown = (event) => {
    const index = views.findIndex((view) => view.id === active)
    let next
    if (KEY_MOVES[event.key]) next = (index + KEY_MOVES[event.key] + views.length) % views.length
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = views.length - 1
    else return
    event.preventDefault()
    const { id } = views[next]
    onSelect(id)
    buttons.current.get(id)?.focus()
  }

  return (
    <div role="tablist" aria-label="Vistas del panel" className="tabs" onKeyDown={onKeyDown}>
      {views.map((view) => (
        <button
          key={view.id}
          ref={(element) => {
            if (element) buttons.current.set(view.id, element)
            else buttons.current.delete(view.id)
          }}
          type="button"
          role="tab"
          id={`tab-${view.id}`}
          className="tab"
          aria-selected={view.id === active}
          aria-controls={view.id === active ? `panel-${view.id}` : undefined}
          tabIndex={view.id === active ? 0 : -1}
          onClick={() => onSelect(view.id)}
          aria-label={view.label}
        >
          {/* En angosto, el nombre corto (las tres pestañas caben); el lector de pantalla lee siempre el largo. */}
          <span className="tab-long">{view.label}</span>
          <span className="tab-short">{view.short ?? view.label}</span>
        </button>
      ))}
    </div>
  )
}
