import { useSyncExternalStore } from 'react'
import { localStore, tabStore } from './storage'

// La pregunta in-app de la H3 (docs/diseno-ia.md, "La pregunta de la H3"): "¿Encontraste lo que buscabas?" (p1) para
// todos, con Mochi o sin él, y "¿Confías en las sugerencias de Mochi?" (p3) solo si la persona ve a Mochi y abrió un
// "¿Por qué?" en la sesión. Aquí viven sus topes y el recorrido de búsqueda que la hace aparecer; la tarjeta es
// components/survey/FoundItCard.jsx.
//
// Topes: una vez por sesión de los eventos (la de EventsContext: 30 min sin actividad la terminan; se guarda su id en
// sessionStorage) y una vez por día por persona (la fecha, en localStorage, como el silencio de agentQuiet.js). Llevan
// el prefijo `rappi-proto-`: "Borrar mis datos" los borra con lo demás. Sin almacenamiento viven en memoria (storage.js):
// la pregunta sigue saliendo una vez en la pestaña y la app no se cae.

export const SURVEY_SESSION_KEY = 'rappi-proto-encuesta-sesion'
export const SURVEY_DAY_KEY = 'rappi-proto-encuesta-dia'
const WHY_KEY = 'rappi-proto-encuesta-porque' // la sesión en que la persona abrió un "¿Por qué?"

/** Las preguntas y sus respuestas, con los códigos que acepta la API (events/store.py: SURVEY_ANSWERS). */
export const P1_ANSWERS = [
  { id: 'si', label: 'Sí' },
  { id: 'en_parte', label: 'En parte' },
  { id: 'no', label: 'No' },
]
export const P3_ANSWERS = [1, 2, 3, 4, 5]

// Los toques que salen de una lista de resultados (los mismos que cuenta el panel: analytics/queries.py, SEARCH_CLICKS).
const SEARCH_CLICKS = new Set(['view_store', 'view_item', 'recommendation_click', 'cart_add', 'suggestion_accepted'])
// Un recorrido más viejo que esto no se pregunta: la sesión de los eventos ya terminó (EventsContext: SESSION_IDLE_MS).
const JOURNEY_MAX_MS = 30 * 60 * 1000

// El recorrido de búsqueda en curso, desde la primera búsqueda que todavía no se preguntó: las búsquedas que hizo
// (`requestIds`, los `request_id` de sus respuestas), si tocó algún resultado y si agregó algo al carro. Vive en la
// memoria de la pestaña: recargar en medio de una búsqueda no la pregunta.
let journey = null
const listeners = new Set()
const notify = () => listeners.forEach((listener) => listener())

/**
 * Mira cada evento que registra la app (EventsContext: `track`) y arma el recorrido: una búsqueda lo empieza o lo
 * sigue, un toque en sus resultados (mismo `request_id`) lo marca como tocado y un `cart_add` de sus resultados, o
 * después de tocar uno, como con carro. Abrir un "¿Por qué?" queda anotado para la p3.
 */
export function observeEvent(event, now = Date.now()) {
  const { type, request_id: requestId } = event
  if (type === 'offer_why_open') {
    tabStore.set(WHY_KEY, event.session_id ?? '')
    return
  }
  if (type === 'search') {
    const current = journey && now - journey.at < JOURNEY_MAX_MS ? journey : null
    journey = {
      requestIds: [...(current?.requestIds ?? []), ...(requestId ? [requestId] : [])],
      requestId: current?.touched ? current.requestId : (requestId ?? current?.requestId ?? null),
      touched: current?.touched ?? false,
      carted: current?.carted ?? false,
      at: now,
    }
    notify()
    return
  }
  if (!journey || !SEARCH_CLICKS.has(type)) return
  const fromResults = Boolean(requestId) && journey.requestIds.includes(requestId)
  if (!fromResults && !(type === 'cart_add' && journey.touched)) return
  journey = {
    ...journey,
    ...(fromResults ? { touched: true, requestId } : {}),
    carted: journey.carted || type === 'cart_add',
    at: now,
  }
  notify()
}

/** Lo que hizo aparecer la pregunta: algo al carro, un resultado tocado o una búsqueda sin toques (abandono). */
export const surveyTrigger = (path) => (path.carted ? 'carro' : path.touched ? 'busqueda' : 'abandono')

/** El recorrido en curso (o null), si no es de una sesión que ya terminó. */
export function currentJourney(now = Date.now()) {
  return journey && now - journey.at < JOURNEY_MAX_MS ? journey : null
}

/** La pregunta salió: el recorrido termina (otra búsqueda empieza uno nuevo). */
export function endJourney() {
  journey = null
  notify()
}

function subscribe(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** El recorrido en curso; se actualiza con cada búsqueda y cada toque. */
export function useSurveyJourney() {
  return useSyncExternalStore(subscribe, () => journey)
}

/** ¿Se puede preguntar en la sesión `session` del día `day` (AAAA-MM-DD)? Una por sesión y una por día. */
export function canAsk(session, day) {
  return tabStore.get(SURVEY_SESSION_KEY) !== session && localStore.get(SURVEY_DAY_KEY) !== day
}

/** La pregunta se mostró: no vuelve en esta sesión ni en este día. */
export function markAsked(session, day) {
  tabStore.set(SURVEY_SESSION_KEY, session)
  localStore.set(SURVEY_DAY_KEY, day)
}

/** ¿Abrió un "¿Por qué?" en la sesión `session`? */
export const whyOpened = (session) => tabStore.get(WHY_KEY) === session

/** Para los tests: como una pestaña nueva. */
export function resetSurvey() {
  journey = null
  for (const key of [SURVEY_SESSION_KEY, WHY_KEY]) tabStore.remove(key)
  localStore.remove(SURVEY_DAY_KEY)
  notify()
}
