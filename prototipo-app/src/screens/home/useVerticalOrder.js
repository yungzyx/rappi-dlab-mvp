import { useEffect, useRef, useState } from 'react'
import { homeVerticals } from '../../api/client'
import { userId } from '../../api/user'
import { useApi } from '../../api/useApi'
import { useEvents } from '../../state/EventsContext'
import { useProfile } from '../../state/ProfileContext'

/**
 * El orden de los 6 verticales de la Home del prototipo final, según lo que más usa la persona (`GET /profile/{id}/verticales`).
 * Pide al montar y cada vez que la Home vuelve a estar arriba (`active`: queda montada bajo las pantallas que se abren
 * encima). Al volver, antes de pedir manda los eventos en cola (los toques a los accesos), para que el orden ya los
 * cuente. La respuesta de una petición anterior no pisa a la última, y mientras llega la nueva se mantiene el orden que
 * había. Tras «Olvidar» (cambian las `resets`) queda el orden fijo y no pide: el buscador olvida antes de que el
 * servidor borre, y pedir ahí traía el orden de antes (la Home parpadeaba hasta recargarse). Si el borrado sale bien la
 * app se recarga; si falla, pide al volver de otra pantalla (cerrar el buscador no cuenta: se abre sobre la Home).
 * Sin API (o con error) `order` es null: la Home queda en el orden fijo y sin el texto. En la demo sin conexión pide
 * también cuando el «Panel de la demo» cambia el historial.
 */
export function useVerticalOrder(active = true) {
  const { resets } = useProfile()
  const events = useEvents()
  const [returns, setReturns] = useState(0)
  const wasActive = useRef(active)

  useEffect(() => {
    const back = active && !wasActive.current
    wasActive.current = active
    if (!back) return undefined
    let current = true
    ;(async () => {
      await events.flush()
      await events.settled() // un lote que ya había salido (el envío cada 5 s) también debe llegar antes
      if (current) setReturns((n) => n + 1)
    })()
    return () => {
      current = false
    }
  }, [active, events])

  // Demo sin conexión («Prototipo MVP.html»): con «+1 visita» o «Borrar historial» el «Panel de la demo» cambia el
  // historial sin que la Home deje de estar arriba, y avisa con `rappi-demo-history` (DEMO_HISTORY_EVENT de
  // src/api/offline/personas.js; no se importa para no traer ese código). En los demás builds Vite pliega la condición:
  // el efecto queda vacío y no escucha nada.
  useEffect(() => {
    if (import.meta.env.VITE_OFFLINE_DEMO !== '1') return undefined
    const again = () => setReturns((n) => n + 1)
    window.addEventListener('rappi-demo-history', again)
    return () => window.removeEventListener('rappi-demo-history', again)
  }, [])

  const { data } = useApi(async () => ({ resets, reply: await homeVerticals(userId()) }), [returns], {
    keepPrevious: true,
  })
  if (data?.resets !== resets || !data.reply?.order) return { order: null, personalized: false }
  return { order: data.reply.order.map((entry) => entry.id), personalized: data.reply.personalized === true }
}
