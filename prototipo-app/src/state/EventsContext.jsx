import { createContext, useCallback, useContext, useEffect, useMemo, useRef } from 'react'
import { version } from '../../package.json'
import { beaconEvents, health, sendEvents } from '../api/client'
import { randomId, randomUuid, userId } from '../api/user'
import { useDemo } from './DemoContext'
import { tabStore } from './storage'
import { observeEvent } from './survey'

// Eventos de uso para el panel de la empresa (búsquedas, carrito, sugerencias, pedidos). Se envían en lotes a
// rappi-ia; sin API esperan en la cola (con tope) hasta que contesta, y un lote que falla en el camino vuelve a la cola:
// cada evento lleva su id (`client_event_id`), así la API no guarda dos veces uno que sí había llegado. Cada evento
// lleva también su hora (`client_ts`) y su orden en la sesión (`seq`), y cada lote lo que la app cuenta de su sesión
// (`app_sessions`). En "Rappi hoy" se envían sin concepto y con `payload.mode = 'actual'`: ni el agente ni el motor
// aprenden de ellos. Desde dónde se hizo cada cosa (pantalla, lista, posición, respuesta de la API) lo arma
// api/attribution.js.
const SESSION_KEY = 'rappi-proto-session'
const SESSION_IDLE_MS = 30 * 60 * 1000 // una sesión termina tras 30 min sin actividad
const FLUSH_MS = 5000
const MAX_QUEUE = 200
// Largo máximo de los textos en rappi-ia (EventIn): uno más largo haría rechazar (422) el lote completo.
const FIELD_LIMITS = { query: 500, entity_id: 64, cart_id: 64, session_id: 64 }
const PLATFORM = 'web'

/**
 * ¿Se abrió la página con un enlace (una ruta o parámetros en la dirección) o directamente? Al recargar, la pantalla
 * vuelve de `history.state`: eso no es un enlace. Se lee al cargar el módulo, antes de que la navegación escriba su hash.
 */
function pageEntry() {
  if (typeof window === 'undefined') return 'directa'
  const { hash, search } = window.location
  return !window.history.state?.nav && (hash.length > 1 || search.length > 1) ? 'enlace' : 'directa'
}
// La entrada vale para la sesión que empieza al cargar la página; las siguientes de la misma pestaña son directas.
let nextEntry = pageEntry()

/** ¿Vale la pena reintentar el lote? Sin red, sin respuesta a tiempo, la API ocupada o con un error suyo, sí; un lote
 * que la API rechazó (400, 403, 422) volvería a rechazarse. */
const retryable = (error) =>
  error?.kind === 'offline' || error?.kind === 'timeout' || error?.status === 429 || error?.status >= 500

function withinLimits(event) {
  const clipped = { ...event }
  for (const [field, max] of Object.entries(FIELD_LIMITS)) {
    if (typeof clipped[field] === 'string') clipped[field] = clipped[field].slice(0, max)
  }
  return clipped
}

/**
 * Sesión vigente (se renueva tras 30 min sin actividad), con `change` aplicado a lo que vive con ella. Si el navegador
 * bloquea sessionStorage, vive en memoria durante la pestaña (`tabStore`), con el mismo id y la misma expiración.
 */
function touchSession(now, change = (session) => session) {
  let stored
  try {
    stored = JSON.parse(tabStore.get(SESSION_KEY))
  } catch {
    stored = null
  }
  let session = stored && now - stored.lastAt < SESSION_IDLE_MS ? stored : null
  if (!session) {
    session = { id: randomId('s'), lastAt: now, entry: nextEntry }
    nextEntry = 'directa'
  }
  const next = change({ ...session, lastAt: now })
  tabStore.set(SESSION_KEY, JSON.stringify(next))
  return next
}

/** Sesión actual; se renueva tras 30 min sin actividad. */
export function sessionId(now = Date.now()) {
  return touchSession(now).id
}

/** El siguiente evento de la sesión: su id y su número (`seq`, 0 el primero), con la sesión al día. */
function nextInSession(now) {
  const session = touchSession(now, (current) => ({ ...current, seq: (current.seq ?? -1) + 1 }))
  return { session_id: session.id, seq: session.seq }
}

/**
 * Lo que la app cuenta de su sesión (`app_sessions`): versión, plataforma, modo y cómo se abrió. Solo lee la sesión
 * guardada (enviar un lote no es actividad: no la alarga).
 */
function sessionInfo(proposal) {
  let stored = null
  try {
    stored = JSON.parse(tabStore.get(SESSION_KEY))
  } catch {
    // Guardado corrupto: la entrada queda como directa.
  }
  return {
    app_version: version,
    platform: PLATFORM,
    mode: proposal ? 'propuesta' : 'actual',
    entry: stored?.entry ?? 'directa',
  }
}

/**
 * Temas que el agente ya sugirió en la sesión (preguntas y "Para ti"): una sugerencia por tema por sesión. Viven con la
 * sesión, así que recargar la página no los olvida y una sesión nueva empieza sin ellos.
 */
export function shownTopics(now = Date.now()) {
  return touchSession(now).topics ?? []
}

export function noteShownTopic(concept, now = Date.now()) {
  touchSession(now, (session) => ({ ...session, topics: [...new Set([...(session.topics ?? []), concept])] }))
}

export function clearShownTopics(now = Date.now()) {
  touchSession(now, (session) => ({ ...session, topics: [] }))
}

/**
 * Conceptos de ofertas que la persona rechazó en la sesión ("Ahora no", "Después"; no las que se fueron solas): Mochi no
 * los vuelve a proponer en la misma sesión (api/suggestions.js: `wasRefused`). Viven con la sesión, como los temas.
 */
export function refusedConcepts(now = Date.now()) {
  return touchSession(now).refused ?? []
}

export function noteRefused(concept, now = Date.now()) {
  touchSession(now, (session) => ({ ...session, refused: [...new Set([...(session.refused ?? []), concept])] }))
}

/** "Repetir escena": como una persona que llega por primera vez, sin nada rechazado. */
export function clearRefused(now = Date.now()) {
  touchSession(now, (session) => ({ ...session, refused: [] }))
}

const EventsContext = createContext(null)

export function EventsProvider({ children }) {
  const demo = useDemo()
  const queue = useRef([])
  // Sube con "Olvidar" (clear): un lote que falla después no vuelve a una cola que ya se vació.
  const generation = useRef(0)
  const opened = useRef(false)
  // Lotes que ya salieron: "Olvidar" los espera para que no recreen en el servidor lo que se borra.
  const inFlight = useRef(Promise.resolve())
  const proposal = useRef(demo.isFinal)
  useEffect(() => {
    proposal.current = demo.isFinal
  }, [demo.isFinal])

  const flush = useCallback(async () => {
    if (queue.current.length === 0) return
    const sending = (async () => {
      // Sin API (arrancando, o reiniciándose) el lote espera en la cola; la cola ya tiene su tope (MAX_QUEUE).
      if (!(await health())) return
      const batch = queue.current.splice(0, MAX_QUEUE)
      if (batch.length === 0) return // "Olvidar" vació la cola mientras se revisaba la API
      const sentIn = generation.current
      try {
        await sendEvents(userId(), batch, sessionInfo(proposal.current))
      } catch (error) {
        // Falló en el camino: vuelve al frente de la cola para el próximo envío (con su id, no se duplica si sí había
        // llegado). La cola mantiene su tope: si no cabe todo, se pierde lo más antiguo.
        if (retryable(error) && sentIn === generation.current)
          queue.current = [...batch, ...queue.current].slice(-MAX_QUEUE)
      }
    })()
    inFlight.current = Promise.all([inFlight.current, sending])
    await sending
  }, [])

  const track = useCallback((type, fields = {}) => {
    const now = Date.now()
    const event = withinLimits({
      type,
      ...nextInSession(now),
      client_event_id: randomUuid(),
      client_ts: new Date(now).toISOString(),
      ...fields,
    })
    // En "Rappi hoy" el evento va sin concepto y marcado `payload.mode = 'actual'`: el motor y los segmentos lo saltan.
    if (!proposal.current) {
      delete event.concept_id
      // Los elementos de un `list_view` (api/impressions.js) también van sin concepto.
      if (event.items) event.items = event.items.map(({ concept_id: _concept, ...item }) => item)
      event.payload = { ...event.payload, mode: 'actual' }
    }
    queue.current.push(event)
    if (queue.current.length > MAX_QUEUE) queue.current.shift()
    observeEvent(event, now) // la pregunta in-app sigue las búsquedas y sus toques (state/survey.js)
  }, [])

  useEffect(() => {
    if (!opened.current) track('app_open') // StrictMode monta dos veces en desarrollo
    opened.current = true
    const timer = setInterval(flush, FLUSH_MS)
    const onHide = () => {
      if (beaconEvents(userId(), queue.current, sessionInfo(proposal.current))) queue.current = []
    }
    window.addEventListener('pagehide', onHide)
    return () => {
      clearInterval(timer)
      window.removeEventListener('pagehide', onHide)
    }
  }, [flush, track])

  /** Descarta lo que aún no se envía (p. ej. al "Olvidar": si no, volvería a aparecer en el servidor). */
  const clear = useCallback(() => {
    queue.current = []
    generation.current += 1
  }, [])

  /** Se cumple cuando terminan los lotes ya enviados. */
  const settled = useCallback(() => inFlight.current, [])

  const value = useMemo(() => ({ track, flush, clear, settled }), [track, flush, clear, settled])
  return <EventsContext.Provider value={value}>{children}</EventsContext.Provider>
}

const NOOP = { track: () => {}, flush: async () => {}, clear: () => {}, settled: async () => {} }
/** Fuera del proveedor (tests de componentes sueltos) no registra nada. */
export const useEvents = () => useContext(EventsContext) ?? NOOP
