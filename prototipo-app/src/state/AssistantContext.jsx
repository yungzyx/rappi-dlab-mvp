import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { useDemo } from './DemoContext'
import { useAgentEnabled } from './agentEnabled'

const AssistantContext = createContext(null)

/**
 * Abre y cierra el asistente. `open({ origin, query, search })`:
 *  - origin: rectángulo (relativo al teléfono) desde donde crece la animación
 *  - query: pregunta que se envía al abrir
 *  - product: un producto del que se pide el complemento ("¿Con qué acompaño…?"); en vez de enviar `query`, se pide la
 *    oferta `carrito` de ese producto
 *  - offer: `{ moment, context }`, una oferta del agente que se muestra al abrir (por ejemplo "¿Qué puedo probar?", el
 *    momento `vertical_por_probar`); `query` es lo que la persona "dijo"
 *  - search: texto con el que arranca el buscador (al volver a una búsqueda que se dejó)
 */
export function AssistantProvider({ children }) {
  const [session, setSession] = useState(null)
  // El buscador con Mochi es del prototipo final: "Rappi hoy" tiene el buscador de siempre. Al pasar a "Rappi hoy" (el
  // interruptor o la tecla D) se cierra, y volver atrás no lo reabre ahí (mostraba el perfil de gusto y lo aprendido).
  // Sin el proveedor del modo (tests de piezas sueltas) cuenta como el prototipo final. En el grupo de control ("Mochi
  // apagado") tampoco se abre: nada de la app lo abre ahí, y si algo lo hiciera, se cierra al tiro.
  const enabled = useAgentEnabled()
  const final = (useDemo()?.isFinal ?? true) && enabled
  const finalRef = useRef(final)
  useEffect(() => {
    finalRef.current = final
  })
  if (!final && session) setSession(null)

  // Volver (o avanzar) a la entrada del historial del asistente lo reabre con la búsqueda que tenía: así, abrir una
  // tienda desde el agente y volver no deja la Home con el panel cerrado y la búsqueda perdida.
  useEffect(() => {
    const onPopState = (event) => {
      if (!event.state?.assistant || !finalRef.current) return
      setSession((prev) => prev ?? { search: event.state.assistantSearch ?? '', openedAt: Date.now() })
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const value = useMemo(
    () => ({
      session,
      isOpen: session !== null,
      // Abrir agrega una entrada al historial: el gesto "volver" de Safari cierra el asistente.
      open: (options = {}) => {
        window.history.pushState({ ...window.history.state, assistant: true }, '')
        setSession({ ...options, openedAt: Date.now() })
      },
      // viaHistory: el cierre ya vino del historial (gesto volver o una pantalla que reemplazó la entrada).
      close: ({ viaHistory = false } = {}) => {
        setSession(null)
        if (!viaHistory && window.history.state?.assistant) window.history.back()
      },
    }),
    [session],
  )

  return <AssistantContext.Provider value={value}>{children}</AssistantContext.Provider>
}

export const useAssistant = () => useContext(AssistantContext)

/** Rectángulo de un elemento relativo al teléfono (el teléfono puede estar escalado con zoom). */
export function rectInPhone(element) {
  const phone = element.closest('.phone')
  const zoom = parseFloat(getComputedStyle(phone).zoom) || 1
  const outer = phone.getBoundingClientRect()
  const inner = element.getBoundingClientRect()
  return {
    top: (inner.top - outer.top) / zoom,
    left: (inner.left - outer.left) / zoom,
    width: inner.width / zoom,
    height: inner.height / zoom,
    phoneWidth: outer.width / zoom,
    phoneHeight: outer.height / zoom,
  }
}
