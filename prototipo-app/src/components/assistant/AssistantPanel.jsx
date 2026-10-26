import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { AGENT_NAME } from '../../agent/name'
import { envelope } from '../../api/attribution'
import { AUTONOMY_TITLE, appCheck, autoOrderBody, demoOrder, turnOffAutonomy } from '../../api/autonomy'
import { storeOfProduct, storeTerms } from '../../api/catalog'
import { ask as askAgent, profile as remoteProfile, recommendations, sendOrder, toMessage } from '../../api/client'
import { offer, plans, profileLadder, tasteProfiles } from '../../api/agent'
import { cartEventFields, trackOrder } from '../../api/orders'
import { firstShowing, noteShown } from '../../api/suggestions'
import { userId } from '../../api/user'
import { askAbout } from '../../assistant/agentAsk'
import { looksLikeQuestion } from '../../assistant/question'
import { routeForScreen } from '../../data/verticals'
import { PopularStores, SearchIdeas, SearchResults } from '../search/SearchSections'
import { useSearch } from '../search/useSearch'
import { useDemo } from '../../state/DemoContext'
import { noteShownTopic, sessionId, shownTopics, useEvents } from '../../state/EventsContext'
import { useForgetAll } from '../../state/forgetAll'
import { useAssistant } from '../../state/AssistantContext'
import { useCart } from '../../state/CartContext'
import { useDialog } from '../../hooks/useDialog'
import { useProfile } from '../../state/ProfileContext'
import { useAddress } from '../../state/AddressContext'
import { useOrders } from '../../state/OrdersContext'
import { usePro } from '../../state/pro'
import { UNDO_MS } from '../../screens/checkout/undo'
import { useToast } from '../Toast'
import BackButton from '../BackButton'
import ForgetConfirm, { FORGET_TITLE } from '../ForgetConfirm'
import Sheet from '../Sheet'
import { AutoOrderCard } from './AgentCards'
import AgentMessage from './AgentMessage'
import AskAgentRow from './AskAgentRow'
import AutonomyEditor from './AutonomyEditor'
import DiscoverSection from './DiscoverSection'
import FollowUp from './FollowUp'
import Mascot from './Mascot'
import PreferencesEditor, { PREFERENCES_TITLE } from './PreferencesEditor'
import { SparkleIcon } from './SmartBar'
import { LadderRail, ProfileCard } from './TasteProfile'
import '../search/search.css'
import './assistant.css'

const OPEN_MS = 380
const CLOSE_MS = 280
const MIN_TYPING_MS = 450
const FOR_YOU_WAIT_MS = 3000 // lo que el saludo espera lo que se pide al abrir; después sale con lo que haya de «Para ti»

const DISCOVER_ROWS = 3

const GREETING = `¡Hola! Soy ${AGENT_NAME}, tu asistente de compras 🧡 Toca una idea o busca lo que quieras.`
const OFFLINE = 'Sin conexión'
const NOTHING_TO_PAIR = 'No se me ocurre nada para acompañar eso'
const NOTHING_TO_TRY = 'No se me ocurre nada nuevo para probar'
const NOTHING_TO_REPEAT = 'Todavía no veo algo que pidas seguido. Cuando repitas un pedido, te lo traigo aquí 🔁'
const NOTHING_IN_KIT = 'No pude armar ese kit ahora. Prueba con otra ocasión.'
const NOTHING_FOR_YOU = 'Todavía no tengo algo armado para ti. Cuando pidas un par de veces, te lo traigo aquí ✨'
const PICK_A_KIT = '¿Para qué te armo el kit? 🧺'
const STOPPED = 'Listo, paré aquí.'
const AUTO_OFF = 'Listo: vuelvo a revisar antes de pedir.'
const AUTO_OFF_FAILED = 'No pude apagarlo ahora. Intenta de nuevo.'
const AUTO_NOT_SENT = 'no pude enviarlo ahora'
const AUTO_SENT = (store) => `Listo, pedí lo de siempre en ${store}: está en Mis pedidos.`
const AUTO_UNDONE_ON_CLOSE = (store) => `No pedí lo de siempre en ${store}: cerraste antes de que saliera.`
const KIT_OPTIONS = 4
// Lo que Mochi sabe hacer, al abrir (como el «Puedo ayudarte a:» de la app de Rappi): repetir lo de siempre (la
// recompra), armar un kit (los planes) y algo para ti (el perfil de gusto o, sin él, lo que le recomienda). Nada de
// salud. Solo en la propuesta: «Rappi hoy» no ofrece.
const CAPABILITIES = [
  { id: 'recompra', label: '🔁 Repite lo de siempre' },
  { id: 'plan', label: '🧺 Arma un kit' },
  { id: 'perfil', label: '✨ Algo para ti' },
]
// El último pedido, en los dos modos (la app de Rappi también lo muestra): solo si la demo ya tiene uno.
const LAST_ORDER = { id: 'pedido', label: '📦 Mi último pedido' }
const LAST_ORDER_ANSWER = {
  text: 'Así va tu último pedido 🛵',
  lastOrder: true,
  actions: [{ label: 'Ver mis pedidos', route: ['orders'] }],
}
const withoutEmoji = (label) => label.replace(/^\S+\s/, '')
// Las ideas de siempre, como texto fijo: tocar una le pregunta eso al agente.
const CHIPS = ['🍔 ¿Qué almuerzo hoy?', '🍻 Arma un carrete', '🔥 Ofertas de hoy', '🍫 Algo dulce', '🎁 Un regalo']

let nextId = 1

/**
 * Lo pedido y sus refinamientos para la respuesta `index`: los mensajes de la persona desde el que la empezó (la
 * respuesta que no siguió a otra), en orden. «Pediste «asado de 6» · «más barato»».
 */
function conversationTrail(messages, index) {
  const trail = []
  for (let i = index; i >= 0; i--) {
    const answer = messages[i]
    if (answer.from !== 'bot' || answer.typing) continue
    const asked = messages.slice(0, i).findLast((m) => m.from === 'user')
    if (!asked || trail.includes(asked)) break
    trail.unshift(asked)
    if (!answer.followUp) break
  }
  return trail
}

/** Lo que sale de «Para ti» es una sugerencia del agente: agregarlo se cuenta como aceptada y no enseña afinidad. */
const asForYou = (product) => ({ ...product, fromSuggestion: true, suggestionOrigin: 'para-ti' })

/**
 * Buscador con el agente: el buscador de siempre (la única entrada de texto), con lo que el agente sabe de la persona en
 * bloques que se tocan y una invitación a descubrir otras verticales. Mochi responde con tarjetas, no con un chat: se
 * ve su última respuesta, que se refina con chips, y las acciones (preferencias, «Pedir por mí», «Olvidar», atajos y
 * el último pedido) son botones. Siempre montado (para no perder lo que el agente respondió); se muestra al abrirlo.
 */
export default function AssistantPanel({ push, vertical, depth = 1 }) {
  const assistant = useAssistant()
  const profile = useProfile()
  const forgetEverything = useForgetAll()
  const demo = useDemo()
  const events = useEvents()
  const cart = useCart()
  const orders = useOrders()
  const address = useAddress()
  const toast = useToast()
  const isPro = usePro()
  const [phase, setPhase] = useState('closed')
  const [messages, setMessages] = useState([])
  const [mood, setMood] = useState('idle')
  const [chipRound, setChipRound] = useState(0)
  const rootRef = useRef(null)
  const inputRef = useRef(null)
  const bodyRef = useRef(null)
  const askHintId = useId()
  const timers = useRef([])
  // Preguntas en fila: la siguiente sale cuando la respuesta anterior ya está en pantalla.
  const askQueue = useRef(Promise.resolve())
  // El estado de la conversación que devolvió la API (`conversation`): va como `previous` en el próximo mensaje.
  const lastTurn = useRef(null)
  const profileGeneration = useRef(0) // sube al "Olvidar": un perfil remoto pedido antes ya no vale
  const [learnedRemote, setLearnedRemote] = useState(null)
  const [forgetting, setForgetting] = useState(false)
  const [confirmingForget, setConfirmingForget] = useState(false)
  const [forgetFailed, setForgetFailed] = useState(false)
  const [discoverRows, setDiscoverRows] = useState([])
  // El perfil de gusto de la persona y su escalera (`{ profile, ladder }`); sin perfil, null y el panel de siempre.
  const [taste, setTaste] = useState(null)
  // «Mis preferencias»: la hoja y su editor (una clave nueva cada vez que se abre: vuelve a leer lo guardado).
  const [preferencesOpen, setPreferencesOpen] = useState(0)
  const [editing, setEditing] = useState(false)
  // «Pedir por mí»: la hoja del ajuste, y el estado de cada «lo de siempre» que Mochi pide solo (clave → { state,
  // reason, orderId }) con su ventana de «Deshacer pedido» (clave → temporizador). La ventana la lleva el panel, que
  // siempre está montado: sigue aunque la respuesta cambie.
  const [autonomyOpen, setAutonomyOpen] = useState(0)
  const [tuning, setTuning] = useState(false)
  const [autoStatus, setAutoStatus] = useState({})
  const autoTimers = useRef(new Map())
  // La respuesta en pantalla: un autopedido que sale cuando ya no se ve avisa con un toast.
  const shownAnswer = useRef(null)
  // La respuesta en curso, para «Cancelar» (su AbortController).
  const pending = useRef(null)
  const search = useSearch({ vertical })

  const later = (fn, ms) => timers.current.push(setTimeout(fn, ms))
  useEffect(
    () => () => {
      timers.current.forEach(clearTimeout)
      autoTimers.current.forEach(clearTimeout)
    },
    [],
  )

  const addMessage = (message) => setMessages((prev) => [...prev, { id: nextId++, ...message }])

  /**
   * Muestra "escribiendo…" hasta que llega la respuesta de la API, con un mínimo para que se note.
   * Devuelve una promesa que se cumple cuando la respuesta ya está en pantalla.
   */
  const botSays = useCallback((responseOrPromise, { cancellable = false } = {}) => {
    const typingId = nextId++
    const startedAt = Date.now()
    setMood('think')
    setMessages((prev) => [...prev, { id: typingId, from: 'bot', typing: true, cancellable }])
    return Promise.resolve(responseOrPromise).then(
      (response) =>
        new Promise((shown) => {
          const wait = Math.max(0, MIN_TYPING_MS - (Date.now() - startedAt))
          later(() => {
            setMood('talk')
            // Id nuevo: si reutilizara el del indicador, React conservaría su estado y mostraría las tarjetas antes del texto.
            setMessages((prev) => [
              ...prev.filter((m) => m.id !== typingId),
              { id: nextId++, from: 'bot', animate: true, ...response },
            ])
            setChipRound((r) => r + 1)
            shown()
          }, wait)
        }),
    )
  }, [])

  const apiContext = (extra = {}) => ({
    vertical,
    user_id: userId(),
    session_id: sessionId(),
    mode: demo.isFinal ? 'propuesta' : 'actual',
    shown_topics: shownTopics(), // preguntas y «Para ti»: una sugerencia por tema en la sesión
    ...extra,
  })

  /**
   * Registra la sugerencia cruzada mostrada (para el panel) y no la repite en la sesión. Como las demás, una vez por
   * pestaña (firstShowing): AddButton registra la mostrada que falte al aceptarla y no debe contarse dos veces.
   */
  const noteSuggestion = (message) => {
    // Un servicio sin catálogo (RappiTravel, RappiFavor) ofrecido: cada vez que el agente lo ofrece.
    if (message.service) events.track('service_shown', { payload: { servicio: message.service } })
    if (!message.suggestion) return message
    const { concept, vertical, origin = 'agent-ask' } = message.suggestion
    noteShownTopic(concept)
    if (firstShowing({ concept, vertical, origin, generation: profile.resets }))
      events.track('suggestion_shown', {
        concept_id: concept,
        vertical,
        ...envelope({ surface: 'agent', origin, requestId: message.requestId }),
      })
    return message
  }

  const onAction = (action) => {
    if (action.ask) return send(action.ask.text, action.ask.vertical)
    if (action.capability) return runCapability(action.capability, action.label)
    if (action.offer) return askOffer(action.offer, withoutEmoji(action.label), NOTHING_IN_KIT)
    if (action.panel === 'preferencias') return openPreferences()
    if (action.panel === 'autonomia') return openAutonomy()
    if (action.service) events.track('service_opened', { payload: { servicio: action.service } })
    go(...action.route)
  }

  /**
   * Pone una respuesta en la fila: la siguiente sale cuando esta ya está en pantalla. `run(signal)` la pide; mientras
   * espera, «Cancelar» corta la petición y Mochi dice que paró (lo que llegue después se descarta). El saludo no se
   * cancela (`cancellable: false`).
   */
  const ask = (run, { cancellable = true } = {}) => {
    askQueue.current = askQueue.current.then(() => {
      if (!cancellable) return botSays(run())
      const controller = new AbortController()
      pending.current = controller
      const stopped = new Promise((resolve) =>
        controller.signal.addEventListener('abort', () => resolve({ text: STOPPED }), { once: true }),
      )
      return botSays(Promise.race([run(controller.signal), stopped]), { cancellable: true }).finally(() => {
        if (pending.current === controller) pending.current = null
      })
    })
  }
  const cancelAnswer = () => pending.current?.abort()

  /**
   * Cuando la API no contesta: «Sin conexión» y un botón que vuelve a pedir lo mismo, una sola vez (dos toques no
   * encolan dos respuestas; si vuelve a fallar, el nuevo «Sin conexión» trae su propio botón).
   */
  const offline = (run) => {
    let used = false
    return {
      text: OFFLINE,
      retry: () => {
        if (used) return
        used = true
        ask(run)
      },
    }
  }

  /**
   * Respuesta de la API; si no contesta, «Sin conexión» con «Reintentar» (no hay respuesta local). Si se canceló, lo
   * que llegue no cuenta (ni para la conversación ni como sugerencia mostrada). El resumen del pedido y el último pedido
   * los arma el panel con el carro y los pedidos de la demo (`orderSummary`, `lastOrder`).
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
      // Lo que queda para el próximo mensaje: «más barato» o «sin carne» se leen sobre él. Una respuesta que no se
      // sigue (un saludo, un consejo médico) no lo borra.
      if (response.conversation) lastTurn.current = response.conversation
      const message = noteSuggestion(toMessage(response))
      if (message.autoOrder) return await checkAutoOrder(message)
      if (message.kind === 'resumen') return { ...message, orderSummary: true }
      if (message.kind === 'pedido') return { ...message, lastOrder: true }
      return message
    } catch {
      if (signal?.aborted) return { text: STOPPED }
      return offline((retrySignal) => answer(text, askVertical, retrySignal))
    }
  }

  /**
   * «Pide lo de siempre»: con «Pedir por mí», antes de abrir la ventana se suma lo que la API no sabe (el envío y la
   * tarifa, de ejemplo si el catálogo no los trae, como en el checkout) y se compara con el tope y la compra mínima; si
   * no cumple, se revisa antes y Mochi dice por qué. Cada uno lleva su clave (`key`) para su estado y su ventana.
   */
  const checkAutoOrder = async (message) => {
    const order = { ...message.autoOrder, key: `auto-${nextId++}` }
    if (order.mode !== 'pedir') return { ...message, autoOrder: order }
    const terms = await storeTerms([order.store.id]).catch(() => new Map())
    const { total, reason } = appCheck(order, terms.get(order.store.id) ?? null, { isPro })
    if (!reason) return { ...message, autoOrder: { ...order, total } }
    return {
      ...message,
      text: `Te armé lo de siempre en ${order.store.name}. Esta vez lo revisas tú: ${reason}.`,
      autoOrder: { ...order, total, mode: 'revisar', code: 'app', reason },
    }
  }

  const setAuto = (key, status) => setAutoStatus((prev) => ({ ...prev, [key]: status }))

  /** Abre la ventana de «Deshacer pedido» (una vez por pedido): al cerrarse, sale el pedido (`commitAuto`). */
  const armAuto = (order) => {
    if (order.mode !== 'pedir' || autoTimers.current.has(order.key)) return
    setAuto(order.key, { state: 'waiting' })
    autoTimers.current.set(
      order.key,
      setTimeout(() => commitAuto(order), UNDO_MS),
    )
  }

  /** Deshacer: el pedido no sale (nunca llegó a la API). */
  const undoAuto = (order) => {
    clearTimeout(autoTimers.current.get(order.key))
    setAuto(order.key, { state: 'undone' })
  }

  const undoAllAuto = () => {
    for (const [key, timer] of autoTimers.current) {
      clearTimeout(timer)
      setAutoStatus((prev) => (prev[key]?.state === 'waiting' ? { ...prev, [key]: { state: 'undone' } } : prev))
    }
  }

  /**
   * Lo que Mochi iba a pedir solo y todavía está en su ventana: con el buscador cerrado ya no se ve su «Deshacer
   * pedido», así que no sale (nada se pide sin que la ventana esté a la vista) y un toast lo dice.
   */
  const undoWaitingOnClose = () => {
    const waiting = messages.filter((m) => m.autoOrder && autoStatus[m.autoOrder.key]?.state === 'waiting')
    if (!waiting.length) return
    undoAllAuto()
    toast?.(AUTO_UNDONE_ON_CLOSE(waiting.at(-1).autoOrder.store.name))
  }

  /**
   * Cerrada la ventana: el pedido va a la API marcado `autopedido`, que vuelve a revisar cada límite. Si lo toma, queda
   * en los pedidos de la demo con su seguimiento; si no (un 409 con el motivo, o sin conexión), se revisa antes.
   */
  const commitAuto = async (order) => {
    setAuto(order.key, { state: 'sending' })
    const cartId = `c-auto-${Date.now().toString(36)}`
    const body = autoOrderBody(order, { sessionId: sessionId(), cartId, pro: isPro })
    try {
      // Antes salen los eventos en cola (como en el checkout); todo el camino cuenta como pedido en vuelo para «Olvidar».
      await trackOrder(
        Promise.resolve(events.flush?.())
          .then(() => events.settled?.())
          .then(() => sendOrder(body)),
      )
      const orderId = orders?.place(demoOrder(order, { cartId, total: order.total, address: address?.selected.line }))
      setAuto(order.key, { state: 'sent', orderId })
      if (shownAnswer.current?.autoOrder?.key !== order.key) toast?.(AUTO_SENT(order.store.name))
    } catch (error) {
      setAuto(order.key, { state: 'review', reason: error?.detail?.motivo ?? AUTO_NOT_SENT })
    }
  }

  /** «Revisar y pagar»: lo de siempre al carro (con lo que ya tenía) y al checkout de siempre. */
  const reviewAuto = (order) => {
    for (const { product, qty } of order.lines) {
      for (let n = 0; n < qty; n += 1) cart.add(product)
      events.track('cart_add', cartEventFields(product, cart.id, { qty }))
    }
    go('checkout')
  }

  /** «Apagar «Pedir por mí»» en un toque: también deshace lo que esté en su ventana. */
  const turnOffAuto = () => {
    undoAllAuto()
    turnOffAutonomy().then(
      () => toast?.(AUTO_OFF),
      () => toast?.(AUTO_OFF_FAILED),
    )
  }

  const openAutonomy = () => {
    setAutonomyOpen((n) => n + 1)
    setTuning(true)
  }

  /** Una oferta del agente para un momento (`carrito`, `vertical_por_probar`…); `nothing` es lo que dice si no tiene nada. */
  const offered = async (moment, context, nothing, signal) => {
    try {
      const made = await offer(moment, context, { userId: userId(), surface: 'agent' })
      if (signal?.aborted) return { text: STOPPED }
      if (!made) return { text: nothing }
      noteShown(events.track, made.products, {
        origin: `agent-${moment}`,
        concept: made.reason?.concept,
        generation: profile.resets,
      })
      // Un servicio sin catálogo ofrecido (el paso de la escalera puede ser RappiFavor o RappiTravel, sin productos).
      for (const action of made.actions)
        if (action.service) events.track('service_shown', { payload: { servicio: action.service } })
      return { text: made.text, products: made.products, actions: made.actions, offerReason: made.reason }
    } catch {
      if (signal?.aborted) return { text: STOPPED }
      return offline((retrySignal) => offered(moment, context, nothing, retrySignal))
    }
  }

  /** «¿Con qué acompaño…?»: la oferta del agente para ese producto (el momento `carrito`). */
  const pairing = (product, signal) =>
    offered(
      'carrito',
      { product: { entity_type: product.entityType, entity_id: product.entityId } },
      NOTHING_TO_PAIR,
      signal,
    )

  const askPairing = (product) => {
    if (forgetting) return
    addMessage({ from: 'user', text: askAbout(product) })
    ask((signal) => pairing(product, signal))
  }

  /**
   * «¿Qué puedo probar?» y similares: la oferta que pidió quien abrió el buscador (`{ moment, context }`), o un kit
   * elegido en «Arma un kit». `nothing` es lo que dice si no tiene nada.
   */
  const askOffer = ({ moment, context }, text, nothing = NOTHING_TO_TRY) => {
    if (forgetting) return
    addMessage({ from: 'user', text })
    ask((signal) => offered(moment, context, nothing, signal))
  }

  /** «Arma un kit»: las ocasiones que sabe armar (las que le gustan primero), para elegir una. */
  const kitOptions = async (signal) => {
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

  /** «Algo para ti» con un perfil de gusto: su escalera (el momento `perfil`) en una sola fila de productos. */
  const forYou = async (found, signal) => {
    try {
      const ladder = await profileLadder(found.profile.id)
      if (signal?.aborted) return { text: STOPPED }
      const products = (ladder?.steps ?? []).flatMap((step) => step.products).slice(0, 6)
      if (!products.length) return { text: NOTHING_FOR_YOU }
      noteShown(events.track, products, { origin: 'agent-perfil', generation: profile.resets })
      return { text: ladder.text, products, offerReason: ladder.reason }
    } catch {
      if (signal?.aborted) return { text: STOPPED }
      return offline((retrySignal) => forYou(found, retrySignal))
    }
  }

  /**
   * Un atajo de lo que Mochi sabe hacer: «Repite lo de siempre» (la recompra), «Arma un kit» (elegir una ocasión),
   * «Algo para ti» (su perfil de gusto; sin perfil, lo que le recomienda, como «¿qué me recomiendas?») o «Mi último
   * pedido» (su estado y su seguimiento, que arma el panel con los pedidos de la demo, sin pasar por la API).
   */
  const runCapability = (id, label) => {
    if (forgetting) return
    addMessage({ from: 'user', text: withoutEmoji(label) })
    if (id === 'pedido') ask(() => LAST_ORDER_ANSWER, { cancellable: false })
    else if (id === 'recompra') ask((signal) => offered('recompra', {}, NOTHING_TO_REPEAT, signal))
    else if (id === 'plan') ask((signal) => kitOptions(signal))
    else if (taste) ask((signal) => forYou(taste, signal))
    else ask((signal) => answer('qué me recomiendas', undefined, signal))
  }

  const openPreferences = () => {
    setPreferencesOpen((n) => n + 1)
    setEditing(true)
  }

  /**
   * El saludo, con «Para ti» de /recommendations (sin él si la API no contesta o no tiene nada que recomendar). Espera
   * también lo demás que se pide al abrir (`others`: lo aprendido y el perfil de gusto): el panel aparece con el saludo
   * (`waiting`), y lo que llegara después lo empujaría.
   */
  const greet = (rows, others) => {
    ask(
      async () => {
        // Al tope sale con «Para ti» si ya llegó, aunque lo demás siga en camino.
        let arrived = []
        rows.then((list) => (arrived = list))
        const waited = new Promise((resolve) => later(() => resolve(arrived), FOR_YOU_WAIT_MS))
        const all = Promise.allSettled([rows, ...others]).then(([list]) => list.value ?? [])
        const [row] = await Promise.race([all, waited])
        if (!row) return { text: GREETING }
        const shown = { origin: 'para-ti', concept: row.concept, generation: profile.resets, kind: row.kind }
        noteShown(events.track, row.products, shown)
        return { text: GREETING, products: row.products.map(asForYou), reason: row.reason }
      },
      { cancellable: false },
    )
  }

  // En orden: la pregunta N+1 sale cuando la respuesta N ya está en pantalla, así sus shown_topics incluyen
  // lo que N sugirió.
  const send = (text, askVertical, { typed = false } = {}) => {
    const clean = text.trim()
    if (!clean || forgetting) return
    addMessage({ from: 'user', text: clean, typed })
    ask((signal) => answer(clean, askVertical, signal))
  }

  /** Lo escrito en el buscador, como pedido a Mochi: el campo se vacía y vuelve su tarjeta, arriba, con la respuesta. */
  const askTyped = () => {
    const text = search.query.trim()
    if (!text || forgetting) return
    search.setQuery('')
    send(text, undefined, { typed: true })
    bodyRef.current?.scrollTo({ top: 0 })
    inputRef.current?.blur() // en el celular el teclado tapaba la respuesta
  }

  /**
   * El perfil de gusto principal de la persona (`GET /profile/{id}/gustos`) con su escalera (el momento `perfil`), o
   * null si no tiene, si no hay escalera o si la API no contesta: entonces el panel queda como siempre.
   */
  const loadTaste = async () => {
    try {
      const [main] = await tasteProfiles()
      const ladder = main ? await profileLadder(main.id) : null
      return ladder?.steps.length ? { profile: main, ladder } : null
    } catch {
      return null
    }
  }

  /**
   * Muestra el perfil y cuenta sus productos como sugerencias mostradas (una vez por pestaña, como las demás). Cuentan
   * todos los peldaños: la escalera se pinta entera (una fila horizontal, como «Para ti»), aunque no quepa en pantalla.
   */
  const showTaste = (found) => {
    setTaste(found)
    for (const step of found?.ladder.steps ?? [])
      noteShown(events.track, step.products, { origin: 'agent-perfil', generation: profile.resets })
  }

  // Abrir, paso 1: el buscador se pinta fuera de la pantalla, a la derecha (como el de «Rappi hoy»).
  useLayoutEffect(() => {
    const session = assistant.session
    if (!session) return
    // Paso 1 de la animación: hay que pintar la posición inicial antes de deslizar, así que el render extra es buscado.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPhase('entering')
    search.setQuery(session.search ?? '')
    setMood('wave')
    later(() => setMood('idle'), OPEN_MS + 1400)

    // Si mientras tanto se tocó "Olvidar", la respuesta es de antes de borrar: se ignora.
    const generation = profileGeneration.current
    const fresh = () => generation === profileGeneration.current
    const learned = remoteProfile(userId())
      .then((data) => fresh() && setLearnedRemote(data.interests.slice(0, 3)))
      .catch(() => fresh() && setLearnedRemote(null))
    // Una sola petición sirve a «Para ti» y a «Descubre con el agente».
    const rows = recommendations(userId())
      .then((data) => data.rows.filter((row) => row.products.length > 0))
      .catch(() => [])
    rows.then((list) => fresh() && setDiscoverRows(list.slice(0, DISCOVER_ROWS)))
    // Solo si sigue siendo la misma persona («Olvidar» mientras llegaba): ni se muestra ni se cuenta.
    const taste = loadTaste()
    taste.then((found) => fresh() && showTaste(found))

    if (messages.length === 0) greet(rows, [learned, taste])
    if (session.product) later(() => askPairing(session.product), OPEN_MS)
    else if (session.offer) later(() => askOffer(session.offer, session.query), OPEN_MS)
    else if (session.query) later(() => send(session.query), OPEN_MS)
    setChipRound((r) => r + 1)
    // Solo al abrir una sesión nueva; el resto del estado se lee en ese momento.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assistant.session?.openedAt])

  // Paso 2: el navegador ya registró la posición inicial; al pasar a 'open' la transición desliza desde ahí.
  // (Sin requestAnimationFrame: en pestañas ocultas no corre y el panel quedaría afuera.)
  useLayoutEffect(() => {
    if (phase !== 'entering') return
    rootRef.current?.getBoundingClientRect()
    // eslint-disable-next-line react-hooks/set-state-in-effect -- paso 2: depende de haber medido el DOM
    setPhase('open')
  }, [phase])

  const close = ({ viaHistory = false } = {}) => {
    undoWaitingOnClose()
    setPhase('closing')
    later(() => {
      setPhase('closed')
      assistant.close({ viaHistory })
    }, CLOSE_MS)
  }

  // La pantalla que se abre desde el agente se apila sobre su entrada del historial, que guarda la búsqueda: al volver,
  // el panel se reabre con ella (AssistantContext).
  const leave = () => {
    if (window.history.state?.assistant)
      window.history.replaceState({ ...window.history.state, assistantSearch: search.query }, '')
  }
  const go = (name, params) => {
    leave()
    push(name, params)
    close({ viaHistory: true })
  }

  // Si otra cosa apila una pantalla con el panel abierto (la barra del carrito abre el checkout), el panel se cierra
  // igual que con `go`, para no quedar encima de esa pantalla.
  const depthRef = useRef(depth)
  useEffect(() => {
    const grew = depth > depthRef.current
    depthRef.current = depth
    if (grew && assistant.isOpen && phase === 'open') {
      leave()
      close({ viaHistory: true })
    }
    // Solo reacciona al cambio de profundidad.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [depth])

  // Gesto "volver" (o botón atrás) con el asistente abierto: se cierra con su animación.
  const closeRef = useRef(close)
  useEffect(() => {
    closeRef.current = close
  })
  // Si lo cierra otro (al pasar a «Rappi hoy», AssistantContext), el panel también se va, con su animación.
  useEffect(() => {
    if (!assistant.isOpen && phase === 'open') closeRef.current({ viaHistory: true })
    // Solo cuando cambia si está abierto.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assistant.isOpen])
  useEffect(() => {
    if (!assistant.isOpen) return undefined
    const onPopState = (event) => {
      if (!event.state?.assistant) closeRef.current({ viaHistory: true })
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [assistant.isOpen])

  // Teclado y VoiceOver: foco adentro al abrir, Escape cierra, Tab no sale, el foco vuelve al cerrar.
  useDialog(rootRef, assistant.isOpen, () => closeRef.current())

  useEffect(() => {
    shownAnswer.current = messages.findLast((m) => m.from === 'bot')
  }, [messages])

  const markStreamed = useCallback((id) => {
    setMood((m) => (m === 'talk' ? 'idle' : m))
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, animate: false } : m)))
  }, [])

  if (phase === 'closed' && !assistant.isOpen) return null

  // Cada respuesta se anuncia completa y una vez: la burbuja la escribe letra por letra, el lector de pantalla no.
  const lastAnswer = messages.findLast((m) => m.from === 'bot' && !m.typing)
  const announcement = lastAnswer?.text ?? ''

  // Hasta la primera respuesta (el saludo, que espera lo que se pide al abrir), solo se ven el encabezado de Mochi y su
  // «escribiendo…»: el saludo mide más, y lo aprendido, el perfil y «Para ti» llegan de a uno; cada cosa empujaba lo de
  // abajo. El resto aparece con el saludo, ya en su lugar (a lo más tras FOR_YOU_WAIT_MS). Los resultados de una
  // búsqueda no esperan.
  const waiting = !search.hasQuery && !messages.some((m) => m.from === 'bot' && !m.typing)
  const style = { transitionDuration: `${phase === 'closing' ? CLOSE_MS : OPEN_MS}ms` }
  // Lo aprendido viene de rappi-ia (conceptos, sin sensibles); sin perfil del servidor no se muestra.
  // En «Rappi hoy» Mochi no aprende: no muestra lo aprendido.
  const learned = demo.isFinal ? (learnedRemote ?? []) : []
  const forgetAll = async () => {
    setForgetting(true) // mientras tanto no se envía nada: una pregunta nueva recrearía lo borrado
    setForgetFailed(false)
    undoAllAuto() // lo que Mochi iba a pedir solo no sale
    profileGeneration.current++
    lastTurn.current = null
    profile.reset()
    setLearnedRemote(null)
    setDiscoverRows([])
    setTaste(null)
    try {
      // Lo que ya salió (preguntas pendientes, un lote de eventos, un pedido) podría recrear lo olvidado en el
      // servidor: forgetAll lo espera antes del DELETE, descarta lo que haya dejado en cola, y deja el navegador en
      // cero.
      await forgetEverything({ settle: () => Promise.allSettled([askQueue.current]) }) // si salió bien, la app se recarga
      setConfirmingForget(false)
    } catch {
      setForgetFailed(true) // el servidor sigue con sus datos: la hoja lo dice y se puede reintentar
    } finally {
      setForgetting(false)
    }
  }

  const closeForget = () => {
    if (forgetting) return
    setConfirmingForget(false)
    setForgetFailed(false)
  }

  // Lo que el agente muestra es su última respuesta (no un historial), con lo dicho en esa conversación.
  const current = messages.findLast((m) => m.from === 'bot')
  // Un autopedido en su ventana (o saliendo) queda fijo arriba aunque llegue otra respuesta: su «Deshacer pedido» no se
  // pierde con un chip, una idea u otra búsqueda.
  const pinnedAuto = messages.findLast(
    (m) => m.autoOrder && m !== current && ['waiting', 'sending'].includes(autoStatus[m.autoOrder.key]?.state),
  )
  const asked = messages.findLast((m) => m.from === 'user')
  const showAsked = asked && current && messages.indexOf(asked) < messages.indexOf(current)
  // Mientras Mochi escribe no se sabe si la pregunta sigue la conversación: solo ella.
  const trail = showAsked && !current.typing ? conversationTrail(messages, messages.indexOf(current)) : []
  if (showAsked && !trail.length) trail.push(asked)
  const openStore = (store) => go('store', { store })
  // Los atajos: los de la propuesta y, en los dos modos, el último pedido si la demo tiene uno.
  const capabilities = [...(demo.isFinal ? CAPABILITIES : []), ...(orders?.orders.length ? [LAST_ORDER] : [])]
  // Un producto o plato de la API abre su tienda por id (otras pueden tener el mismo nombre); sin `storeId` no hay
  // tienda que abrir.
  const openProduct = (product) => {
    if (product.storeId == null) return
    go('store', { store: storeOfProduct(product), item: product })
  }

  return (
    <div
      ref={rootRef}
      className={`assistant agent-search is-${phase}${waiting ? ' is-waiting' : ''}${cart.count > 0 ? ' has-cart' : ''}`}
      style={style}
      role="dialog"
      aria-modal="true"
      aria-label={`Buscador con ${AGENT_NAME}`}
    >
      <p className="sr-only" aria-live="polite" data-testid="assistant-announcer">
        {announcement}
      </p>

      <header className="search-header agent-search-header">
        <BackButton className="search-back" onClick={() => close()} />
        <label className="search-field agent-search-field smart-border">
          <SparkleIcon size={20} />
          <input
            ref={inputRef}
            type="search"
            aria-label="Buscar en Rappi"
            placeholder={`Busca o pídele algo a ${AGENT_NAME}`}
            value={search.query}
            maxLength={500}
            onChange={(e) => search.setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== 'Enter') return
              if (looksLikeQuestion(search.query)) askTyped()
              else search.logSearch(search.query)
            }}
            aria-describedby={search.hasQuery && looksLikeQuestion(search.query) ? askHintId : undefined}
            // Pasar con Tab a «Pídele a Mochi» no es terminar una búsqueda
            onBlur={(e) => e.relatedTarget?.classList.contains('agent-ask-row') || search.logSearch(search.query)}
          />
          {search.hasQuery && (
            <button type="button" className="search-clear" aria-label="Borrar" onClick={() => search.setQuery('')}>
              ×
            </button>
          )}
        </label>
      </header>

      <div ref={bodyRef} className="agent-search-body">
        {search.hasQuery ? (
          <div className="agent-block">
            <AskAgentRow
              query={search.query.trim()}
              question={looksLikeQuestion(search.query)}
              hintId={askHintId}
              onAsk={askTyped}
            />
            <SearchResults
              query={search.query}
              data={search.data}
              loading={search.loading}
              error={search.error}
              onRetry={search.retry}
              onOpenProduct={openProduct}
              onOpenStore={openStore}
              onSearchExact={search.searchExact}
              onOpenFavor={(text) => go('favor', { text })}
              onOpenVertical={(vertical) => go(...routeForScreen(vertical))}
              onTryAnother={() => {
                search.setQuery('')
                inputRef.current?.focus()
              }}
            />
          </div>
        ) : (
          <>
            <section className="agent-card" aria-label={`Recomendaciones de ${AGENT_NAME}`}>
              <header className="agent-card-head">
                <span className="agent-card-mascot">
                  <Mascot size={44} badge mood={mood} />
                </span>
                <span>
                  <strong>{AGENT_NAME}</strong>
                  <small>
                    <i className="assistant-online" /> Tu asistente de compras
                  </small>
                </span>
              </header>

              {/* «Olvidar» siempre a mano: aunque no haya intereses que mostrar, hay búsquedas y eventos que borrar. */}
              <div className="assistant-learning">
                {learned.length > 0 && (
                  <>
                    <span>Aprendiendo de ti:</span>
                    {learned.map((item) => (
                      <b key={item.concept}>{item.label}</b>
                    ))}
                  </>
                )}
                {demo.isFinal && (
                  <button type="button" onClick={openPreferences}>
                    {PREFERENCES_TITLE}
                  </button>
                )}
                {demo.isFinal && (
                  <button type="button" onClick={openAutonomy}>
                    {AUTONOMY_TITLE}
                  </button>
                )}
                <button type="button" onClick={() => setConfirmingForget(true)}>
                  Olvidar
                </button>
              </div>
              <p className="agent-ai-notice">
                {demo.isFinal
                  ? `${AGENT_NAME} usa IA: recuerda tus gustos por tema y las preferencias que marques, y los borras cuando quieras.`
                  : `${AGENT_NAME} usa IA. En «Rappi hoy» no aprende de lo que buscas.`}
              </p>

              {taste && demo.isFinal && <ProfileCard profile={taste.profile} />}

              {pinnedAuto && (
                <AutoOrderCard
                  order={pinnedAuto.autoOrder}
                  status={autoStatus[pinnedAuto.autoOrder.key]}
                  revealed
                  onShown={armAuto}
                  onUndo={undoAuto}
                  onReview={reviewAuto}
                  onTurnOff={turnOffAuto}
                  onTrack={(orderId) => go('tracking', { orderId })}
                />
              )}

              {showAsked && (
                <p className="agent-asked">
                  {trail[0].typed ? 'Pediste' : 'Elegiste'} {trail.map((m) => `«${m.text}»`).join(' · ')}
                </p>
              )}
              {current && (
                <AgentMessage
                  key={current.id}
                  // Sin carro no hay nada que pagar: el resumen dice que está vacío y no lleva al checkout.
                  message={current.orderSummary && cart.count === 0 ? { ...current, actions: [] } : current}
                  onStreamDone={() => markStreamed(current.id)}
                  onOpenProduct={openProduct}
                  onOpenStore={openStore}
                  onAction={onAction}
                  onCancel={cancelAnswer}
                  onTrack={(orderId) => go('tracking', { orderId })}
                  autoOrder={
                    current.autoOrder && {
                      status: autoStatus[current.autoOrder.key],
                      onShown: armAuto,
                      onUndo: undoAuto,
                      onReview: reviewAuto,
                      onTurnOff: turnOffAuto,
                    }
                  }
                  onRetry={() => !forgetting && current.retry()}
                  followUp={
                    // Refinar la respuesta, debajo de los productos: chips de un toque (sin salud), sin campo para escribir
                    showAsked && !current.retry ? (
                      <FollowUp message={current} disabled={forgetting} onRefine={(chip) => send(chip.message)} />
                    ) : null
                  }
                />
              )}

              {capabilities.length > 0 && !current?.health && (
                <>
                  <p className="agent-picks-label">Puedo ayudarte a:</p>
                  <div className="assistant-chips agent-capabilities">
                    {capabilities.map((capability) => (
                      <button
                        key={capability.id}
                        type="button"
                        className="assistant-chip agent-capability"
                        disabled={forgetting}
                        onClick={() => runCapability(capability.id, capability.label)}
                      >
                        {capability.label}
                      </button>
                    ))}
                  </div>
                </>
              )}

              {/* Bajo una respuesta de salud no van las ideas de siempre («Arma un carrete») */}
              {!current?.health && <p className="agent-picks-label">Toca y te armo algo 👇</p>}
              {/* Clave con prefijo: un número solo podría coincidir con la del mensaje de arriba (su id) y React lo duplicaría. */}
              {!current?.health && (
                <div key={`chips-${chipRound}`} className="assistant-chips agent-picks">
                  {CHIPS.map((chip, i) => (
                    <button
                      key={chip}
                      type="button"
                      className="assistant-chip"
                      disabled={forgetting}
                      style={{ animationDelay: `${120 + i * 55}ms` }}
                      onClick={() => send(chip.replace(/^\S+\s/, ''))}
                    >
                      {chip}
                    </button>
                  ))}
                </div>
              )}
            </section>

            {taste && demo.isFinal && (
              <LadderRail
                ladder={taste.ladder}
                onOpenVertical={(screen) => go(...routeForScreen(screen))}
                onOpenTravel={() => onAction({ route: taste.ladder.trip?.route ?? ['travel'], service: 'rappitravel' })}
                onOpenProduct={openProduct}
              />
            )}

            <section className="agent-block">
              <SearchIdeas onPick={search.pick} />
            </section>

            {discoverRows.length > 0 && (
              <div className="agent-block">
                <DiscoverSection rows={discoverRows} onOpen={(vertical) => go(...routeForScreen(vertical))} />
              </div>
            )}

            <section className="agent-block">
              <PopularStores onOpen={openStore} />
            </section>
          </>
        )}
      </div>

      <Sheet open={editing} onClose={() => setEditing(false)} title={PREFERENCES_TITLE} overPhone>
        <PreferencesEditor key={preferencesOpen} onSaved={() => setEditing(false)} />
      </Sheet>

      <Sheet open={tuning} onClose={() => setTuning(false)} title={AUTONOMY_TITLE} overPhone>
        <AutonomyEditor key={autonomyOpen} onSaved={() => setTuning(false)} onTurnedOff={undoAllAuto} />
      </Sheet>

      {/* «Olvidar» borra lo mismo que Cuenta → «Borrar mis datos»: pide la misma confirmación. */}
      <Sheet open={confirmingForget} onClose={closeForget} title={FORGET_TITLE} overPhone>
        <ForgetConfirm forgetting={forgetting} failed={forgetFailed} onConfirm={forgetAll} onCancel={closeForget} />
      </Sheet>
    </div>
  )
}
