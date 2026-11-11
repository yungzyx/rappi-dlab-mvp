import { useEffect, useRef, useState } from 'react'
import { AGENT_NAME } from '../../agent/name'
import { useEvents } from '../../state/EventsContext'
import { setAgentHidden } from '../../state/agentHidden'
import './agent-presence.css'

/**
 * El menú de Mochi: "¿Qué hacemos juntos?" con las opciones de quien lo abre (`actions`: `{ id, label }`, que van a
 * `onRun(id)`) y, al final, "Ocultar a Mochi", que pide confirmar en el mismo globo. Confirmado, Mochi queda oculto
 * (`agent_visibility` con origen `menu-mochi`) y el menú se cierra (`onClose`). Lo usan Mochi flotante (AgentPresence)
 * y Mochi en la Home (LiveAgent); `className` es el globo de cada uno y `children` va debajo de las opciones.
 */
export default function AgentMenu({ className, actions, onRun, onClose, surface = 'agent', children }) {
  const events = useEvents()
  const [confirmHide, setConfirmHide] = useState(false)

  if (confirmHide)
    return (
      <div className={className} role="group" aria-label={`Ocultar a ${AGENT_NAME}`}>
        <p>{AGENT_NAME} no volverá a aparecer. Puedes traerlo de vuelta en Cuenta.</p>
        <div className="agent-actions">
          <button
            type="button"
            className="agent-action is-primary tap"
            onClick={() => {
              // Primero se oculta: lo que cierra el menú ya lo ve oculto (en la Home no muestra lo pendiente).
              events.track('agent_visibility', { surface, origin: 'menu-mochi', payload: { visible: false } })
              setAgentHidden(true)
              onClose()
            }}
          >
            Ocultar
          </button>
          <button type="button" className="agent-action tap" onClick={() => setConfirmHide(false)}>
            Cancelar
          </button>
        </div>
      </div>
    )

  return (
    <div className={className} role="group" aria-label={`Opciones de ${AGENT_NAME}`}>
      <p>¿Qué hacemos juntos?</p>
      <div className="agent-actions">
        {actions.map((action) => (
          <button key={action.id} type="button" className="agent-action tap" onClick={() => onRun(action.id)}>
            {action.label}
          </button>
        ))}
        <button type="button" className="agent-action tap" onClick={() => setConfirmHide(true)}>
          Ocultar a {AGENT_NAME}
        </button>
      </div>
      {children}
    </div>
  )
}

/**
 * Con el menú abierto, Escape o tocar fuera de `host` (el menú y Mochi: tocar a Mochi lo abre y lo cierra) lo cierran:
 * `onClose(event)`, con el evento del teclado si fue Escape.
 */
export function useMenuDismiss(open, host, onClose) {
  const close = useRef(onClose)
  useEffect(() => {
    close.current = onClose
  })
  useEffect(() => {
    if (!open) return undefined
    const onPointer = (event) => {
      if (!host.current?.contains(event.target)) close.current()
    }
    const onKey = (event) => {
      if (event.key === 'Escape') close.current(event)
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, host])
}
