import { useCallback, useEffect, useState } from 'react'
import { envelope } from '../../api/attribution'
import { useOpenDialogs } from '../../hooks/useDialog'
import { useAssistant } from '../../state/AssistantContext'
import { useDemo } from '../../state/DemoContext'
import { sessionId, useEvents } from '../../state/EventsContext'
import { useAgentEnabled } from '../../state/agentEnabled'
import { useAgentHidden } from '../../state/agentHidden'
import {
  canAsk,
  canAskP3,
  clearP3,
  currentJourney,
  endJourney,
  markAsked,
  markAskedP3,
  pendingP3,
  surveyTrigger,
  useP3Pending,
  useSurveyJourney,
  whyOpened,
} from '../../state/survey'
import { today } from '../../utils/today'

// Nunca en el checkout (ahí también se paga) ni en el seguimiento del pedido.
export const NEVER_ON = new Set(['checkout', 'tracking'])
// Al volver, la pregunta espera un momento: la pantalla termina de llegar y, si Mochi va a decir algo, lo dice primero.
export const SETTLE_MS = 1200
export const THANKS_MS = 1800
// Lo que la pregunta espera a que se vaya: un globo o un menú de Mochi (el de la Home, LiveAgent; el flotante,
// AgentPresence), con una oferta o no, y el aviso de privacidad de la primera visita.
const WAIT_FOR = '.live-bubble, .agent-popover, .privacy-notice'

/** Los campos de un evento de la pregunta: su pantalla, la búsqueda que la originó y la pregunta con su motivo. */
const fields = (card, extra = {}) => ({
  ...envelope({ surface: card.screen, requestId: card.requestId }),
  payload: { question: card.question, trigger: card.trigger, mochi: card.mochi, ...extra },
})

/**
 * Cuándo sale la pregunta in-app (docs/diseno-ia.md, "La pregunta de la H3"). Tras un recorrido de búsqueda
 * (state/survey.js), cuando la persona vuelve a donde lo empezó (cerró el buscador, o volvió de lo que abrió) o a la
 * Home: una por sesión y una por día, nunca en el pago ni el seguimiento, ni con el buscador, una hoja o el aviso de
 * privacidad encima. No depende de que Mochi esté a la vista; si Mochi está diciendo algo (una oferta), espera, y si
 * empieza a decir algo con la pregunta abierta, ella se esconde hasta que termine.
 * La p3, solo con Mochi a la vista: sigue a la p1 al responderla si la persona ya abrió un "¿Por qué?" en la sesión, o
 * sale sola cuando se va una oferta cuyo "¿Por qué?" abrió (con las mismas esperas; si toca la p1, va primero). Una
 * por día, aparte de la p1.
 * `screen` y `depth` son la pantalla de arriba de la pila y cuántas hay.
 * Devuelve `{ card, visible, answer, close }`: `card` es `{ question, trigger, requestId, screen, depth, mochi,
 * thanks }` o null.
 */
export function useFoundItSurvey({ screen, depth }) {
  const events = useEvents()
  const demo = useDemo()
  const assistant = useAssistant()
  const agentHidden = useAgentHidden()
  const agentEnabled = useAgentEnabled()
  const dialogs = useOpenDialogs()
  const journey = useSurveyJourney()
  const whyLeft = useP3Pending()
  const [card, setCard] = useState(null)
  const [origin, setOrigin] = useState(null) // la profundidad de la pila desde la que se buscó
  const [waiting, setWaiting] = useState(false) // Mochi dice algo o está el aviso de privacidad
  const searching = assistant?.isOpen === true || screen === 'search'
  // Mochi a la vista: el prototipo final, no oculto y no apagado (el grupo de control). En silencio sigue a la vista,
  // como una pestañita.
  const mochi = demo?.isFinal !== false && !agentHidden && agentEnabled

  // Desde dónde se buscó: la pantalla bajo el buscador (el de Mochi se abre encima; el plano es una pantalla más).
  if (journey && origin === null) setOrigin(screen === 'search' ? depth - 1 : depth)
  if (!journey && !card && origin !== null) setOrigin(null)
  // Se fue a otra pantalla o volvió a buscar con la pregunta abierta: siguió con lo suyo, la pregunta se va sin evento.
  if (card && (searching || screen !== card.screen || depth !== card.depth)) setCard(null)

  // Mientras haya un recorrido, una p3 pendiente o una pregunta, mira si Mochi está diciendo algo (o si está el aviso de
  // privacidad).
  const watching = Boolean(journey || card || whyLeft !== null)
  useEffect(() => {
    if (!watching) return undefined
    const root = document.querySelector('.phone') ?? document.body
    const check = () => setWaiting(Boolean(root.querySelector(WAIT_FOR)))
    check()
    const observer = new MutationObserver(check)
    observer.observe(root, { childList: true, subtree: true })
    return () => observer.disconnect()
  }, [watching])

  const free = !searching && !NEVER_ON.has(screen) && dialogs === 0 && !waiting
  const due = !card && Boolean(journey) && origin !== null && depth <= origin && free
  // La p3 sola, tras una oferta que se fue con su "¿Por qué?" abierto; si a la vez toca la p1, espera a que pase.
  const dueP3 = !card && !due && whyLeft !== null && mochi && free
  useEffect(() => {
    if (!due) return undefined
    const timer = setTimeout(() => {
      const path = currentJourney()
      endJourney()
      const session = sessionId()
      if (!path || !canAsk(session, today())) return
      markAsked(session, today())
      const next = { question: 'p1', trigger: surveyTrigger(path), requestId: path.requestId, screen, depth, mochi }
      setCard(next)
      events.track('survey_shown', fields(next))
    }, SETTLE_MS)
    return () => clearTimeout(timer)
  }, [due, screen, depth, mochi, events])

  useEffect(() => {
    if (!dueP3) return undefined
    const timer = setTimeout(() => {
      const fresh = pendingP3()
      clearP3()
      if (!fresh || !canAskP3(today())) return
      markAskedP3(today())
      const next = { question: 'p3', trigger: 'porque', requestId: null, screen, depth, mochi: true }
      setCard(next)
      events.track('survey_shown', fields(next))
    }, SETTLE_MS)
    return () => clearTimeout(timer)
  }, [dueP3, screen, depth, events])

  // "¡Gracias!" se va solo.
  const thanks = card?.thanks === true
  useEffect(() => {
    if (!thanks) return undefined
    const timer = setTimeout(() => setCard(null), THANKS_MS)
    return () => clearTimeout(timer)
  }, [thanks])

  const answer = useCallback(
    (value) => {
      if (!card || card.thanks) return
      events.track('survey_answer', fields(card, { answer: value }))
      // La p3 sigue a la p1 en la misma tarjeta: solo con Mochi a la vista, un "¿Por qué?" abierto en la sesión y si la
      // p3 no salió hoy. Así ya no sale sola por la misma oferta.
      if (card.question === 'p1' && mochi && whyOpened(sessionId()) && canAskP3(today())) {
        markAskedP3(today())
        clearP3()
        const next = { ...card, question: 'p3', trigger: 'porque', mochi }
        setCard(next)
        events.track('survey_shown', fields(next))
      } else setCard({ ...card, thanks: true })
    },
    [card, events, mochi],
  )

  const close = useCallback(() => {
    if (!card) return
    if (!card.thanks) events.track('survey_dismissed', fields(card))
    // Cerrar la p1 cuando la iba a seguir la p3 también la deja: no sale sola justo después.
    if (card.question === 'p1' && !card.thanks && mochi && whyOpened(sessionId())) clearP3()
    setCard(null)
  }, [card, events, mochi])

  return { card, visible: Boolean(card) && !waiting && dialogs === 0, answer, close }
}
