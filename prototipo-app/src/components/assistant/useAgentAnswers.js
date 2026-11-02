import { useRef } from 'react'
import { AGENT_NAME } from '../../agent/name'
import { envelope } from '../../api/attribution'
import { ask as askAgent, toMessage } from '../../api/client'
import { offer, plans, profileLadder } from '../../api/agent'
import { noteShown } from '../../api/suggestions'
import { userId } from '../../api/user'
import { useDemo } from '../../state/DemoContext'
import { noteShownTopic, sessionId, shownTopics, useEvents } from '../../state/EventsContext'
import { useProfile } from '../../state/ProfileContext'
import { STOPPED } from './useAgentConversation'

const FOR_YOU_WAIT_MS = 3000 // lo que el saludo espera lo que se pide al abrir; después sale con lo que haya de "Para ti"

const GREETING = `¡Hola! Soy ${AGENT_NAME}, tu asistente de compras 🧡 Toca una idea o busca lo que quieras.`
// Con un perfil de gusto, como en el Comité 2: lo que le gusta (`gusto` del perfil) y la escalera justo debajo.
const PROFILE_GREETING = (profile) =>
  `¡Hola de nuevo! 🧡 Veo que te gusta ${profile.gusto} ${profile.emoji} Te armé ideas en otras verticales 👇`
const NOTHING_TO_PAIR = 'No se me ocurre nada para acompañar eso'
export const NOTHING_IN_KIT = 'No pude armar ese kit ahora. Prueba con otra ocasión.'
const NOTHING_FOR_YOU = 'Todavía no tengo algo armado para ti. Cuando pidas un par de veces, te lo traigo aquí ✨'
const PICK_A_KIT = '¿Para qué te armo el kit? 🧺'
const KIT_OPTIONS = 4
// Los textos fijos del resumen y del pedido los pone la app, que sabe lo que la demo hace hoy: con "Pedir por mí"
// Mochi sí pide, y el seguimiento cancela con rescate (los mismos de la copia sin conexión, api/offline/search.js).
const SUMMARY_TEXT =
  'Este es el resumen de tu pedido antes de pagar 🧾. Revísalo y paga en el checkout: si no me diste permiso con ' +
  '"Pedir por mí", el pedido lo haces tú.'
const ORDER_TEXT =
  'Tu pedido lo sigues en "Mis pedidos" 🛵: ahí ves dónde viene, lo cancelas antes de que salga o pides ayuda si ' +
  'algo llegó mal.'

/**
 * El sobre de lo que ofrece una respuesta de Mochi (un servicio, sobre todo): en el buscador, con el origen de la
 * respuesta (su sugerencia, la oferta del momento o `agent-ask`) y su `request_id`.
 */
export const placementOf = (message) =>
  envelope({
    surface: 'agent',
    origin: message?.origin ?? message?.suggestion?.origin ?? 'agent-ask',
    requestId: message?.requestId,
  })

/** Lo que sale de "Para ti" es una sugerencia del agente: agregarlo se cuenta como aceptada y no enseña afinidad. */
const asForYou = (product) => ({ ...product, fromSuggestion: true, suggestionOrigin: 'para-ti' })

/**
 * Lo que Mochi responde, pedido a la API: una pregunta, la oferta de un momento, las ocasiones de un kit, "Algo para ti"
 * y el saludo. Cada función devuelve la respuesta a mostrar (para `ask` de `useAgentConversation`); si la API no
 * contesta, "Sin conexión" con "Reintentar" (`offline`), y si se canceló, lo que llegue no cuenta (ni para la
 * conversación ni como sugerencia mostrada). Guarda el estado de la conversación que devolvió la API: va como
 * `previous` en el próximo mensaje, hasta `forgetTurn`.
 */
export function useAgentAnswers({ vertical, offline, checkAutoOrder, later }) {
  const demo = useDemo()
  const events = useEvents()
  const profile = useProfile()
  // El estado de la conversación que devolvió la API (`conversation`): va como `previous` en el próximo mensaje.
  const lastTurn = useRef(null)
  const forgetTurn = () => {
    lastTurn.current = null
  }

  const apiContext = (extra = {}) => ({
    vertical,
    user_id: userId(),
    session_id: sessionId(),
    mode: demo.isFinal ? 'propuesta' : 'actual',
    shown_topics: shownTopics(), // preguntas y "Para ti": una sugerencia por tema en la sesión
    ...extra,
  })

  /**
   * Registra la sugerencia cruzada mostrada (para el panel) y no la repite en la sesión. Como las demás, una vez por
   * pestaña (noteShown): AddButton registra la mostrada que falte al aceptarla y no debe contarse dos veces.
   */
  const noteSuggestion = (message) => {
    // Un servicio sin catálogo (RappiTravel, RappiFavor) ofrecido: cada vez que el agente lo ofrece, con su respuesta.
    if (message.service)
      events.track('service_shown', { ...placementOf(message), payload: { servicio: message.service } })
    if (!message.suggestion) return message
    const { concept, vertical, origin = 'agent-ask' } = message.suggestion
    noteShownTopic(concept)
    noteShown(events.track, null, {
      origin,
      concept,
      vertical,
      generation: profile.resets,
      surface: 'agent',
      requestId: message.requestId,
    })
    return message
  }

  /**
   * Respuesta de la API a lo que se le pide. El resumen del pedido y el último pedido los arma el panel con el carro y
   * los pedidos de la demo (`orderSummary`, `lastOrder`).
   */
  const answer = async (text, askVertical, signal) => {
    try {
      const response = await askAgent(
        {
          message: text,
          ...apiContext({ vertical: askVertical ?? vertical }),
          ...(lastTurn.current ? { previous: lastTurn.current } : {}),
        },
        { signal },
      )
      if (signal?.aborted) return { text: STOPPED }
      // Lo que queda para el próximo mensaje: "más barato" o "sin carne" se leen sobre él. Una respuesta que no se
      // sigue (un saludo, un consejo médico) no lo borra.
      if (response.conversation) lastTurn.current = response.conversation
      const message = noteSuggestion(toMessage(response))
      if (message.autoOrder) return await checkAutoOrder(message)
      if (message.kind === 'resumen') return { ...message, text: SUMMARY_TEXT, orderSummary: true }
      if (message.kind === 'pedido') return { ...message, text: ORDER_TEXT, lastOrder: true }
      return message
    } catch {
      if (signal?.aborted) return { text: STOPPED }
      return offline((retrySignal) => answer(text, askVertical, retrySignal))
    }
  }

  /** Una oferta del agente para un momento (`carrito`, `vertical_por_probar`…); `nothing` es lo que dice si no tiene nada. */
  const offered = async (moment, context, nothing, signal) => {
    // Lo que se muestra ya no es esa conversación: "más barato" después no refina algo que no está en pantalla.
    lastTurn.current = null
    try {
      const made = await offer(moment, context, { userId: userId(), surface: 'agent' })
      if (signal?.aborted) return { text: STOPPED }
      if (!made) return { text: nothing }
      noteShown(events.track, made.products, {
        origin: `agent-${moment}`,
        concept: made.reason?.concept,
        reason: made.reason,
        generation: profile.resets,
      })
      // Un servicio sin catálogo ofrecido (el paso de la escalera puede ser RappiFavor o RappiTravel, sin productos).
      const shown = { origin: `agent-${moment}`, requestId: made.requestId }
      for (const action of made.actions)
        if (action.service)
          events.track('service_shown', { ...placementOf(shown), payload: { servicio: action.service } })
      return {
        text: made.text,
        products: made.products,
        actions: made.actions,
        offerReason: made.reason,
        offerOrigin: `agent-${moment}`,
        ...shown,
      }
    } catch {
      if (signal?.aborted) return { text: STOPPED }
      return offline((retrySignal) => offered(moment, context, nothing, retrySignal))
    }
  }

  /** "¿Con qué acompaño…?": la oferta del agente para ese producto (el momento `carrito`). */
  const pairing = (product, signal) =>
    offered(
      'carrito',
      { product: { entity_type: product.entityType, entity_id: product.entityId } },
      NOTHING_TO_PAIR,
      signal,
    )

  /** "Arma un kit": las ocasiones que sabe armar (las que le gustan primero), para elegir una. */
  const kitOptions = async (signal) => {
    lastTurn.current = null
    try {
      const list = await plans()
      if (signal?.aborted) return { text: STOPPED }
      if (!list.length) return { text: NOTHING_IN_KIT }
      const actions = list.slice(0, KIT_OPTIONS).map((plan) => ({
        label: `${plan.emoji} ${plan.name}`,
        offer: { moment: 'plan', context: { occasion: plan.id } },
      }))
      return { text: PICK_A_KIT, actions }
    } catch {
      if (signal?.aborted) return { text: STOPPED }
      return offline((retrySignal) => kitOptions(retrySignal))
    }
  }

  /** "Algo para ti" con un perfil de gusto: su escalera (el momento `perfil`) en una sola fila de productos. */
  const forYou = async (found, signal) => {
    lastTurn.current = null
    try {
      const ladder = await profileLadder(found.profile.id)
      if (signal?.aborted) return { text: STOPPED }
      const products = (ladder?.steps ?? []).flatMap((step) => step.products).slice(0, 6)
      if (!products.length) return { text: NOTHING_FOR_YOU }
      noteShown(events.track, products, { origin: 'agent-perfil', reason: ladder.reason, generation: profile.resets })
      return { text: ladder.text, products, offerReason: ladder.reason, offerOrigin: 'agent-perfil' }
    } catch {
      if (signal?.aborted) return { text: STOPPED }
      return offline((retrySignal) => forYou(found, retrySignal))
    }
  }

  /**
   * El saludo, con "Para ti" de /recommendations (sin él si la API no contesta o no tiene nada que recomendar). Con un
   * perfil de gusto (`taste`, en la propuesta) es "¡Hola de nuevo!" con lo que le gusta, sin "Para ti" (y sin esperarlo):
   * su escalera va justo debajo. Espera también lo aprendido (`learned`): el panel aparece con el saludo (`waiting`), y
   * lo que llegara después lo empujaría. Recibe lo que se pidió al abrir (`useOpenData`).
   */
  const greeting = async ({ rows, taste, learned }) => {
    // Al tope sale con lo que ya llegó, aunque lo demás siga en camino.
    let arrived = []
    let tasteArrived = null
    rows.then((list) => (arrived = list))
    taste.then((found) => (tasteArrived = found))
    const waited = new Promise((resolve) => later(() => resolve([arrived, tasteArrived]), FOR_YOU_WAIT_MS))
    // Una muestra sin conexión grabada antes de `gusto` no lo trae: entonces, el saludo de siempre. Con perfil no
    // se espera "Para ti": no sale en su saludo.
    const withGusto = (found) => demo.isFinal && Boolean(found?.profile.gusto)
    const all = taste.then(async (found) => {
      const [list] = await Promise.allSettled([withGusto(found) ? [] : rows, learned])
      return [list.value ?? [], found]
    })
    const [[row], found] = await Promise.race([all, waited])
    if (withGusto(found)) return { text: PROFILE_GREETING(found.profile) }
    if (!row) return { text: GREETING }
    const shown = {
      origin: 'para-ti',
      concept: row.concept,
      generation: profile.resets,
      kind: row.kind,
      reason: row.reason,
    }
    noteShown(events.track, row.products, shown)
    return { text: GREETING, products: row.products.map(asForYou), reason: row.reason }
  }

  return { answer, offered, pairing, kitOptions, forYou, greeting, forgetTurn }
}
