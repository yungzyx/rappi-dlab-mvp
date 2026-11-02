import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { AGENT_NAME } from '../../agent/name'
import { envelope } from '../../api/attribution'
import { AUTONOMY_TITLE } from '../../api/autonomy'
import { storeOfProduct } from '../../api/catalog'
import { askAbout } from '../../assistant/agentAsk'
import { looksLikeQuestion } from '../../assistant/question'
import { routeForScreen } from '../../data/verticals'
import { PopularStores, SearchIdeas, SearchResults } from '../search/SearchSections'
import { useSearch } from '../search/useSearch'
import { useDemo } from '../../state/DemoContext'
import { useEvents } from '../../state/EventsContext'
import { useAssistant } from '../../state/AssistantContext'
import { useCart } from '../../state/CartContext'
import { useDialog } from '../../hooks/useDialog'
import { useProfile } from '../../state/ProfileContext'
import { useOrders } from '../../state/OrdersContext'
import BackButton from '../BackButton'
import ForgetConfirm, { FORGET_TITLE } from '../ForgetConfirm'
import Sheet from '../Sheet'
import { AutoOrderCard, shownOrder } from './AgentCards'
import AgentMessage from './AgentMessage'
import AskAgentRow from './AskAgentRow'
import AutonomyEditor from './AutonomyEditor'
import DiscoverSection from './DiscoverSection'
import FollowUp from './FollowUp'
import Mascot from './Mascot'
import PreferencesEditor, { PREFERENCES_TITLE } from './PreferencesEditor'
import { SparkleIcon } from './SmartBar'
import { LadderRail, ProfileCard } from './TasteProfile'
import { NOTHING_IN_KIT, placementOf, useAgentAnswers } from './useAgentAnswers'
import { useAgentConversation } from './useAgentConversation'
import { useAutoOrders } from './useAutoOrders'
import { useForgetFlow } from './useForgetFlow'
import { useOpenData } from './useOpenData'
import '../search/search.css'
import './assistant.css'

const OPEN_MS = 380
const CLOSE_MS = 280

const NOTHING_TO_TRY = 'No se me ocurre nada nuevo para probar'
const NOTHING_TO_REPEAT = 'Todavía no veo algo que pidas seguido. Cuando repitas un pedido, te lo traigo aquí 🔁'
// Lo que Mochi sabe hacer, al abrir (como el "Puedo ayudarte a:" de la app de Rappi): repetir lo de siempre (la
// recompra), armar un kit (los planes) y algo para ti (el perfil de gusto o, sin él, lo que le recomienda). Nada de
// salud. Solo en la propuesta: "Rappi hoy" no ofrece.
const CAPABILITIES = [
  { id: 'recompra', label: '🔁 Repite lo de siempre' },
  { id: 'plan', label: '🧺 Arma un kit' },
  { id: 'perfil', label: '✨ Algo para ti' },
]
// El último pedido, en los dos modos (la app de Rappi también lo muestra): solo si la demo ya tiene uno.
const LAST_ORDER = { id: 'pedido', label: '📦 Mi último pedido' }
// La tarjeta muestra el pedido en curso más reciente o, sin uno, el último (LastOrderCard): el texto dice cuál.
const lastOrderAnswer = (order) => ({
  text: !order
    ? 'Todavía no tienes pedidos en esta demo.'
    : order.cancelled
      ? 'Tu último pedido se canceló.'
      : 'Así va tu último pedido 🛵',
  lastOrder: true,
  actions: [{ label: 'Ver mis pedidos', route: ['orders'] }],
})
const withoutEmoji = (label) => label.replace(/^\S+\s/, '')
// Las ideas de siempre, como texto fijo: tocar una le pregunta eso al agente.
const CHIPS = ['🍔 ¿Qué almuerzo hoy?', '🍻 Arma un carrete', '🔥 Ofertas de hoy', '🍫 Algo dulce', '🎁 Un regalo']

/** Los atajos de lo que Mochi sabe hacer ("Repite lo de siempre", "Arma un kit"…), como chips. */
function CapabilityChips({ capabilities, disabled, onPick }) {
  return capabilities.map((capability) => (
    <button
      key={capability.id}
      type="button"
      className="assistant-chip agent-capability"
      disabled={disabled}
      onClick={(event) => onPick(capability, event)}
    >
      {capability.label}
    </button>
  ))
}

/**
 * Lo pedido y sus refinamientos para la respuesta `index`: los mensajes de la persona desde el que la empezó (la
 * respuesta que no siguió a otra), en orden. "Pediste 'asado de 6' · 'más barato'".
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

/**
 * Buscador con el agente: el buscador de siempre (la única entrada de texto), con lo que el agente sabe de la persona en
 * bloques que se tocan y una invitación a descubrir otras verticales. Mochi responde con tarjetas, no con un chat: se
 * ve su última respuesta, que se refina con chips, y las acciones (preferencias, "Pedir por mí", "Olvidar", atajos y
 * el último pedido) son botones. Siempre montado (para no perder lo que el agente respondió); se muestra al abrirlo.
 * La conversación, lo que se pide a la API, "Pedir por mí", lo que se carga al abrir y "Olvidar" viven en sus hooks
 * (`useAgentConversation`, `useAgentAnswers`, `useAutoOrders`, `useOpenData`, `useForgetFlow`); aquí quedan la
 * apertura y el cierre, la navegación y lo que se pinta.
 */
export default function AssistantPanel({ push, vertical, depth = 1 }) {
  const assistant = useAssistant()
  const profile = useProfile()
  const demo = useDemo()
  const events = useEvents()
  const cart = useCart()
  const orders = useOrders()
  const [phase, setPhase] = useState('closed')
  const rootRef = useRef(null)
  const inputRef = useRef(null)
  const bodyRef = useRef(null)
  const askHintId = useId()
  const conversation = useAgentConversation()
  const { messages, later, ask, addMessage } = conversation
  const autoOrders = useAutoOrders({ messages, shownAnswer: conversation.shownAnswer })
  const answers = useAgentAnswers({ vertical, offline: conversation.offline, checkAutoOrder: autoOrders.check, later })
  const openData = useOpenData()
  const { taste } = openData
  const forget = useForgetFlow({
    prepare: () => {
      autoOrders.undoAll() // lo que Mochi iba a pedir solo no sale
      answers.forgetTurn()
      profile.reset()
      openData.forget()
    },
    settle: () => Promise.allSettled([conversation.queued()]),
  })
  const { forgetting } = forget
  // "Mis preferencias": la hoja y su editor (una clave nueva cada vez que se abre: vuelve a leer lo guardado).
  const [preferencesOpen, setPreferencesOpen] = useState(0)
  const [editing, setEditing] = useState(false)
  // "Pedir por mí": la hoja del ajuste (lo que Mochi pide solo lo lleva useAutoOrders).
  const [autonomyOpen, setAutonomyOpen] = useState(0)
  const [tuning, setTuning] = useState(false)
  const search = useSearch({ vertical })
  // El cierre en curso: reabrir antes de que termine lo cancela (si no, cerraba el panel recién abierto).
  const closing = useRef(null)

  /** `vertical_open` desde el buscador con Mochi: qué vertical, desde qué bloque y en qué lugar. */
  const noteVerticalOpen = ({ vertical, origin, position, requestId }) => {
    if (vertical)
      events.track('vertical_open', { vertical, ...envelope({ surface: 'agent', origin, position, requestId }) })
  }

  const onAction = (action) => {
    if (action.ask) return send(action.ask.text, action.ask.vertical)
    if (action.capability) return runCapability(action.capability, action.label)
    if (action.offer) return askOffer(action.offer, withoutEmoji(action.label), NOTHING_IN_KIT)
    if (action.panel === 'preferencias') return openPreferences()
    if (action.panel === 'autonomia') return openAutonomy()
    const shownAnswer = conversation.shownAnswer.current
    // Abrir una vertical desde una respuesta ("También en") deja su lugar, como un acceso de la Home.
    if (action.opens) noteVerticalOpen({ ...action.opens, requestId: shownAnswer?.requestId })
    // Abrir un servicio cuenta con la respuesta de donde salió (la que está en pantalla, o el lugar que trae la acción).
    if (action.service)
      events.track('service_opened', {
        ...(action.placement ? envelope(action.placement) : placementOf(shownAnswer)),
        payload: { servicio: action.service },
      })
    go(...action.route)
  }

  const openAutonomy = () => {
    setAutonomyOpen((n) => n + 1)
    setTuning(true)
  }

  const openPreferences = () => {
    setPreferencesOpen((n) => n + 1)
    setEditing(true)
  }

  /** "Revisar y pagar" un autopedido: lo de siempre al carro y al checkout de siempre. */
  const reviewAuto = (order) => {
    autoOrders.review(order)
    go('checkout')
  }

  const askPairing = (product) => {
    if (forgetting) return
    addMessage({ from: 'user', text: askAbout(product) })
    ask((signal) => answers.pairing(product, signal))
  }

  /**
   * "¿Qué puedo probar?" y similares: la oferta que pidió quien abrió el buscador (`{ moment, context }`), o un kit
   * elegido en "Arma un kit". `nothing` es lo que dice si no tiene nada.
   */
  const askOffer = ({ moment, context }, text, nothing = NOTHING_TO_TRY) => {
    if (forgetting) return
    addMessage({ from: 'user', text })
    ask((signal) => answers.offered(moment, context, nothing, signal))
  }

  /**
   * Un atajo de lo que Mochi sabe hacer: "Repite lo de siempre" (la recompra), "Arma un kit" (elegir una ocasión),
   * "Algo para ti" (su perfil de gusto; sin perfil, lo que le recomienda, como "¿qué me recomiendas?") o "Mi último
   * pedido" (su estado y su seguimiento, que arma el panel con los pedidos de la demo, sin pasar por la API).
   */
  const runCapability = (id, label) => {
    if (forgetting) return
    addMessage({ from: 'user', text: withoutEmoji(label) })
    if (id === 'pedido') {
      answers.forgetTurn() // otra tarjeta en pantalla: "más barato" ya no refina la respuesta de antes
      ask(() => lastOrderAnswer(shownOrder(orders?.orders ?? [])), { cancellable: false })
    } else if (id === 'recompra') ask((signal) => answers.offered('recompra', {}, NOTHING_TO_REPEAT, signal))
    else if (id === 'plan') ask((signal) => answers.kitOptions(signal))
    else if (taste) ask((signal) => answers.forYou(taste, signal))
    else ask((signal) => answers.answer('qué me recomiendas', undefined, signal))
  }

  // En orden: la pregunta N+1 sale cuando la respuesta N ya está en pantalla, así sus shown_topics incluyen
  // lo que N sugirió.
  const send = (text, askVertical, { typed = false } = {}) => {
    const clean = text.trim()
    if (!clean || forgetting) return
    addMessage({ from: 'user', text: clean, typed })
    ask((signal) => answers.answer(clean, askVertical, signal))
  }

  // Mientras askTyped suelta el campo: ese blur no termina una búsqueda (el onBlur todavía ve el texto).
  const askingTyped = useRef(false)

  /** Lo escrito en el buscador, como pedido a Mochi: el campo se vacía y vuelve su tarjeta, arriba, con la respuesta. */
  const askTyped = () => {
    const text = search.query.trim()
    if (!text || forgetting) return
    search.setQuery('')
    send(text, undefined, { typed: true })
    bodyRef.current?.scrollTo({ top: 0 })
    askingTyped.current = true
    inputRef.current?.blur() // en el celular el teclado tapaba la respuesta
    askingTyped.current = false
  }

  // Abrir, paso 1: el buscador se pinta fuera de la pantalla, a la derecha (como el de "Rappi hoy").
  useLayoutEffect(() => {
    const session = assistant.session
    if (!session) return
    clearTimeout(closing.current)
    closing.current = null
    // Paso 1 de la animación: hay que pintar la posición inicial antes de deslizar, así que el render extra es buscado.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPhase('entering')
    search.setQuery(session.search ?? '')
    conversation.setMood('wave')
    later(() => conversation.setMood('idle'), OPEN_MS + 1400)

    const loads = openData.load()
    if (messages.length === 0) ask(() => answers.greeting(loads), { cancellable: false })
    if (session.product) later(() => askPairing(session.product), OPEN_MS)
    else if (session.offer) later(() => askOffer(session.offer, session.query), OPEN_MS)
    else if (session.query) later(() => send(session.query), OPEN_MS)
    conversation.nextChipRound()
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
    autoOrders.undoWaitingOnClose()
    // Lo que no es de una visita al panel no sigue en la próxima (horas después, "más barato" no refina nada).
    answers.forgetTurn()
    setPhase('closing')
    clearTimeout(closing.current)
    closing.current = later(() => {
      closing.current = null
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
  // Si lo cierra otro (al pasar a "Rappi hoy", AssistantContext), el panel también se va, con su animación.
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

  if (phase === 'closed' && !assistant.isOpen) return null

  // Cada respuesta se anuncia completa y una vez: la burbuja la escribe letra por letra, el lector de pantalla no.
  const lastAnswer = messages.findLast((m) => m.from === 'bot' && !m.typing)
  const announcement = lastAnswer?.text ?? ''

  // Hasta la primera respuesta (el saludo, que espera lo que se pide al abrir), solo se ven el encabezado de Mochi y su
  // "escribiendo…": el saludo mide más, y lo aprendido, el perfil y "Para ti" llegan de a uno; cada cosa empujaba lo de
  // abajo. El resto aparece con el saludo, ya en su lugar (a lo más tras FOR_YOU_WAIT_MS). Los resultados de una
  // búsqueda no esperan.
  const waiting = !search.hasQuery && !messages.some((m) => m.from === 'bot' && !m.typing)
  const style = { transitionDuration: `${phase === 'closing' ? CLOSE_MS : OPEN_MS}ms` }
  // Lo aprendido viene de rappi-ia (conceptos, sin sensibles); sin perfil del servidor no se muestra.
  // En "Rappi hoy" Mochi no aprende: no muestra lo aprendido.
  const learned = demo.isFinal ? (openData.learnedRemote ?? []) : []

  // Lo que el agente muestra es su última respuesta (no un historial), con lo dicho en esa conversación.
  const current = messages.findLast((m) => m.from === 'bot')
  // Un autopedido en su ventana (o saliendo) queda fijo arriba aunque llegue otra respuesta: su "Deshacer pedido" no se
  // pierde con un chip, una idea u otra búsqueda.
  const pinnedAuto = messages.findLast(
    (m) => m.autoOrder && m !== current && ['waiting', 'sending'].includes(autoOrders.status[m.autoOrder.key]?.state),
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
  // Con perfil de gusto (en la propuesta), arriba van el perfil, el saludo y la escalera, como en el Comité 2; lo demás
  // (el autopedido fijo, los atajos con "Mis preferencias" y "Pedir por mí", las ideas y el aviso de IA), debajo.
  const withProfile = Boolean(taste && demo.isFinal)
  // Con perfil, la respuesta sale arriba de la escalera: tocar un chip de abajo sube a verla.
  const showAnswer = (event) => {
    if (withProfile) event.currentTarget.closest('.agent-search-body')?.scrollTo?.({ top: 0, behavior: 'smooth' })
  }
  const aiNotice = (
    <p className="agent-ai-notice">
      {demo.isFinal
        ? `${AGENT_NAME} usa IA: recuerda tus gustos por tema y las preferencias que marques, y los borras cuando quieras.`
        : `${AGENT_NAME} usa IA. En "Rappi hoy" no aprende de lo que buscas.`}
    </p>
  )
  const pinnedCard = pinnedAuto && (
    <AutoOrderCard
      order={pinnedAuto.autoOrder}
      status={autoOrders.status[pinnedAuto.autoOrder.key]}
      revealed
      onShown={autoOrders.arm}
      onUndo={autoOrders.undo}
      onReview={reviewAuto}
      onTurnOff={autoOrders.turnOff}
      onTrack={(orderId) => go('tracking', { orderId })}
    />
  )
  const pickCapability = (capability, event) => {
    runCapability(capability.id, capability.label)
    showAnswer(event)
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
            // Pasar con Tab a "Pídele a Mochi" o pedírsela con Enter no es terminar una búsqueda
            onBlur={(e) =>
              askingTyped.current ||
              e.relatedTarget?.classList.contains('agent-ask-row') ||
              search.logSearch(search.query)
            }
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
                  <Mascot size={44} badge mood={conversation.mood} />
                </span>
                <span>
                  <strong>{AGENT_NAME}</strong>
                  <small>
                    <i className="assistant-online" /> Tu asistente Rappi
                  </small>
                </span>
              </header>

              {withProfile ? (
                // Con perfil, "Olvidar" va en su tarjeta; lo aprendido lo dice su "por qué".
                <ProfileCard profile={taste.profile} onForget={forget.open} forgetting={forgetting} />
              ) : (
                <>
                  {/* "Olvidar" siempre a mano: aunque no haya intereses que mostrar, hay búsquedas y eventos que borrar. */}
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
                    <button type="button" onClick={forget.open}>
                      Olvidar
                    </button>
                  </div>
                  {aiNotice}
                  {pinnedCard}
                </>
              )}

              {showAsked && (
                <p className="agent-asked">
                  {trail[0].typed ? 'Pediste' : 'Elegiste'} {trail.map((m) => `"${m.text}"`).join(' · ')}
                </p>
              )}
              {current && (
                <AgentMessage
                  key={current.id}
                  // Sin carro no hay nada que pagar: el resumen dice que está vacío y no lleva al checkout.
                  message={current.orderSummary && cart.count === 0 ? { ...current, actions: [] } : current}
                  onStreamDone={() => conversation.markStreamed(current.id)}
                  onOpenProduct={openProduct}
                  onAction={onAction}
                  onCancel={conversation.cancelAnswer}
                  onTrack={(orderId) => go('tracking', { orderId })}
                  autoOrder={
                    current.autoOrder && {
                      status: autoOrders.status[current.autoOrder.key],
                      onShown: autoOrders.arm,
                      onUndo: autoOrders.undo,
                      onReview: reviewAuto,
                      onTurnOff: autoOrders.turnOff,
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

              {withProfile ? (
                <>
                  <LadderRail
                    ladder={taste.ladder}
                    onOpenVertical={(screen, where) => {
                      noteVerticalOpen({ ...where, origin: 'agent-perfil', requestId: taste.ladder.requestId })
                      go(...routeForScreen(screen))
                    }}
                    onOpenTravel={() =>
                      onAction({
                        route: taste.ladder.trip?.route ?? ['travel'],
                        service: 'rappitravel',
                        placement: { surface: 'agent', origin: 'agent-perfil', requestId: taste.ladder.requestId },
                      })
                    }
                    onOpenProduct={openProduct}
                  />
                  {pinnedCard}
                  {/* Lo demás que Mochi sabe hacer, en una sola fila: los atajos y sus ajustes. */}
                  <div className="assistant-chips agent-capabilities agent-more">
                    {!current?.health && (
                      <CapabilityChips capabilities={capabilities} disabled={forgetting} onPick={pickCapability} />
                    )}
                    <button
                      type="button"
                      className="assistant-chip agent-capability"
                      disabled={forgetting}
                      onClick={openPreferences}
                    >
                      {PREFERENCES_TITLE}
                    </button>
                    <button
                      type="button"
                      className="assistant-chip agent-capability"
                      disabled={forgetting}
                      onClick={openAutonomy}
                    >
                      {AUTONOMY_TITLE}
                    </button>
                  </div>
                </>
              ) : (
                capabilities.length > 0 &&
                !current?.health && (
                  <>
                    <p className="agent-picks-label">Puedo ayudarte a:</p>
                    <div className="assistant-chips agent-capabilities">
                      <CapabilityChips capabilities={capabilities} disabled={forgetting} onPick={pickCapability} />
                    </div>
                  </>
                )
              )}

              {/* Bajo una respuesta de salud no van las ideas de siempre ("Arma un carrete") */}
              {!current?.health && <p className="agent-picks-label">Toca y te armo algo 👇</p>}
              {/* Clave con prefijo: un número solo podría coincidir con la del mensaje de arriba (su id) y React lo duplicaría. */}
              {!current?.health && (
                <div key={`chips-${conversation.chipRound}`} className="assistant-chips agent-picks">
                  {CHIPS.map((chip, i) => (
                    <button
                      key={chip}
                      type="button"
                      className="assistant-chip"
                      disabled={forgetting}
                      style={{ animationDelay: `${120 + i * 55}ms` }}
                      onClick={(event) => {
                        send(chip.replace(/^\S+\s/, ''))
                        showAnswer(event)
                      }}
                    >
                      {chip}
                    </button>
                  ))}
                </div>
              )}
              {withProfile && aiNotice}
            </section>

            <section className="agent-block">
              <SearchIdeas onPick={search.pick} />
            </section>

            {openData.discoverRows.length > 0 && (
              <div className="agent-block">
                <DiscoverSection
                  rows={openData.discoverRows}
                  onOpen={(screen, { row, position }) => {
                    noteVerticalOpen({
                      vertical: row.vertical,
                      origin: 'descubre',
                      position,
                      requestId: row.products[0]?.placement?.requestId,
                    })
                    go(...routeForScreen(screen))
                  }}
                />
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
        <AutonomyEditor key={autonomyOpen} onSaved={() => setTuning(false)} onTurnedOff={autoOrders.undoAll} />
      </Sheet>

      {/* "Olvidar" borra lo mismo que Cuenta → "Borrar mis datos": pide la misma confirmación. */}
      <Sheet open={forget.confirming} onClose={forget.cancel} title={FORGET_TITLE} overPhone>
        <ForgetConfirm
          forgetting={forgetting}
          failed={forget.failed}
          onConfirm={forget.confirm}
          onCancel={forget.cancel}
        />
      </Sheet>
    </div>
  )
}
