import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { offer, plans as fetchPlans } from '../../../api/agent'
import { envelope } from '../../../api/attribution'
import { conceptOf } from '../../../api/orders'
import { EXPIRED, noteDismissal, noteOfferDismissal, noteOfferShown, noteShown } from '../../../api/suggestions'
import { userId } from '../../../api/user'
import DemoDisclaimer from '../../../components/DemoDisclaimer'
import PlainSearchBar from '../../../components/PlainSearchBar'
import { PRIVACY_CLOSED_EVENT, privacyPending } from '../../../components/PrivacyNotice'
import SmartBar from '../../../components/assistant/SmartBar'
import { useToast } from '../../../components/Toast'
import { ChevronDown } from '../../../components/Icons'
import { VERTICAL_NAMES, routeForScreen, screenForBackend } from '../../../data/verticals'
import { useReducedMotion } from '../../../hooks/useReducedMotion'
import { useScrollState } from '../../../hooks/useScrollState'
import { useAddress } from '../../../state/AddressContext'
import { useAssistant } from '../../../state/AssistantContext'
import { useAddToCart } from '../../../hooks/useAddToCart'
import { lineKey } from '../../../state/CartContext'
import { useEvents } from '../../../state/EventsContext'
import { useOrders } from '../../../state/OrdersContext'
import { useProfile } from '../../../state/ProfileContext'
import { useProductSheet } from '../../../state/ProductSheetContext'
import CreditsBanner from '../CreditsBanner'
import { BestRated, FastRestaurants, MainTiles, NearbyStores, Promos, Shortcuts, useHomeCatalog } from '../HomeSections'
import { CREDITS } from '../../../data/home'
import '../home.css'
import { useVerticalOrder } from '../useVerticalOrder'
import LiveAgent from './LiveAgent'
import { PlanBlock, RepeatBlock, kitAddedText, openItem } from './LiveBlocks'
import {
  AGENT_CART_EVENT,
  REPLAY_EVENT,
  forgetAdded,
  markTourSeen,
  rememberMove,
  session,
  tourSeen,
} from '../../../state/liveMemory'
import { isHushed, isQuiet, noteDismissed, noteEngaged } from '../../../state/agentQuiet'
import { isAgentHidden, useAgentHidden } from '../../../state/agentHidden'
import { moveText, moveWhy, useShortcutMove } from './shortcutMoves'
import { today } from '../../../utils/today'
import './live.css'

// Las secciones de la Home de hoy, más "¿Repetimos?" (la recompra) o, si no hay, "¿Volvemos a…?" (lo que dejó de pedir),
// que solo aparecen cuando la API los ofrece.
const ORDER = ['essentials', 'recompra', 'promos', 'turbo', 'plan', 'nearby', 'lower']
const WINBACK_ORIGIN = 'agent-volver'
// El tipo de una invitación a volver (su señal): `volver` si es de un concepto, `vuelta` si es de una vertical. Va en
// `payload.kind` de sus eventos: así la API reconoce cuál se mostró o se descartó.
const winbackKind = (made) => made.reason?.basis?.[0]?.kind
/** Si la invitación a volver de esta sesión es la de una vertical (`¿Volvemos a Turbo?`): su vertical del backend. */
const backVertical = () => {
  const made = session.winback?.offer
  return made && winbackKind(made) === 'vuelta' ? made.backendVertical : null
}
const T = { enter: 900, greet: 3400, greetHold: 6000 }
// Silenciado por hoy (desde el agente flotante) o callado porque lo ignoraron: no habla por su cuenta; si lo tocan, sí.
// Oculto ("Ocultar a Mochi"): no está, así que tampoco habla ni propone nada.
const silent = () => isQuiet(today()) || isHushed() || isAgentHidden()
// El origen de los eventos de "Mochi movió tus accesos".
const MOVE_ORIGIN = 'agent-reorden'
// Los accesos esperan a que Mochi llegue junto a ellos (su paso dura 680 ms en live.css) antes de deslizarse.
const GLIDE_DELAY = 550

// Guía de la primera vez, tras el saludo: el buscador y qué pasa al tocarlo. Se ve una vez ("Repetir escena" la repite).
const TOUR = [
  {
    text: 'Arriba está mi buscador: búscame lo que quieras o toca una de sus ideas 🔎',
    at: 'essentials',
    gesture: 'point',
  },
  { text: 'Y si me tocas, te propongo una vertical nueva para probar ✨', at: 'essentials', gesture: 'hop' },
]

const GREETING = '¡Hola! Ahora vivo en tu Home 👋 Toca una idea o prueba una vertical nueva.'

const HOME_PLANS = 5 // la Home muestra solo los primeros planes del servidor (once, carrete, asado, panorama, regalo)

const ACTIONS_HOLD = 12000 // un globo con botones se va solo después de esto (no queda tapando la Home)
// Un globo con una oferta (el comentario del carro, la vertical por probar) da más tiempo para leerla y decidir; si se
// va solo, queda anotado que se fue sola (no es un rechazo).
const OFFER_HOLD = 30000

/** Un toque de vibración en los momentos clave (solo donde el navegador lo permite, como Android). */
const buzz = () => navigator.vibrate?.(12)

/**
 * Home del prototipo final: la barra abre el buscador con el agente. El agente de cuerpo entero vive en
 * la Home: saluda, acompaña el plan del día, al tocarlo invita a una vertical nueva y, cuando el motor cambia el orden
 * de los accesos, los mueve y dice por qué. Oculto ("Ocultar a Mochi"), la Home queda sin él y con el buscador de siempre.
 */
export default function LiveHomeFeed({ push, active = true }) {
  const toast = useToast()
  const address = useAddress()
  const catalog = useHomeCatalog()
  const { add: addToCart } = useAddToCart()
  const profile = useProfile()
  const events = useEvents()
  const verticalOrder = useVerticalOrder(active)
  const hidden = useAgentHidden()
  // La fila que se ve: el último orden que vio la persona hasta que la Home está a la vista (arriba y sin el buscador
  // encima); ahí, si cambió, se mueve. Un cambio con el buscador abierto se ve al cerrarlo.
  const searching = useAssistant()?.isOpen === true
  // El buscador de Mochi y la hoja de direcciones se abren encima de la Home (sin cambiar `active`) y la tapan.
  const overlay = searching || address.sheetOpen === true
  const shortcuts = useShortcutMove(verticalOrder, { active: active && !searching, resets: profile.resets })
  // Cambia con cada pedido y con cada calificación (una mala pausa lo de ese pedido): "¿Volvemos a…?" se vuelve a pedir.
  const orders = useOrders().orders
  const lastOrder = `${orders[0]?.id ?? ''}|${orders.filter((order) => order.rating).length}`
  const reduceMotion = useReducedMotion()
  const [replays, setReplays] = useState(0)
  const [privacyClosed, setPrivacyClosed] = useState(0) // sube al cerrarse el aviso de privacidad: recién ahí saluda

  const [plans, setPlans] = useState([]) // las ocasiones que el agente sabe armar (GET /agent/plans)
  const [plan, setPlan] = useState(() => session.plan?.id ?? null) // la ocasión elegida
  const [kit, setKit] = useState(() => session.plan?.kit ?? null) // sus productos (la oferta `plan`); null mientras llega
  const [kitReason, setKitReason] = useState(() => session.plan?.reason ?? null) // por qué ese kit (`reason` de la oferta)
  const [kitStores, setKitStores] = useState(() => session.plan?.stores ?? []) // sus tiendas y sus mínimos (`stores`)
  const [kitAdded, setKitAdded] = useState(null) // plan cuyo kit ya está en el carro
  const [say, setSay] = useState(null)
  const [target, setTarget] = useState(null) // id del bloque donde se para el agente
  const [present, setPresent] = useState(() => session.played) // aún no entra a escena
  const [repeat, setRepeat] = useState(null) // "¿Repetimos?" (`recompra`) o, si no hay, "¿Volvemos a…?" (`volver`)
  const [entering, setEntering] = useState(false)

  const screenRef = useRef(null)
  const agentRef = useRef(null)
  const blockRefs = useRef(new Map())
  const timers = useRef([])
  const hideTimer = useRef(null)
  const run = useRef(0) // cambia al repetir la escena o al salir: lo que estaba esperando ya no sigue
  const planRun = useRef(0) // cambia en cada ocasión elegida: el kit de una anterior ya no vale
  const poking = useRef(false) // ya se pidió la vertical por probar: otro toque no pide otra
  const [{ scrolled }, onScroll] = useScrollState()

  const later = useCallback((ms, fn) => timers.current.push(setTimeout(fn, ms)), [])
  const clearTimers = useCallback(() => {
    timers.current.forEach(clearTimeout)
    timers.current = []
  }, [])
  useEffect(
    () => () => {
      run.current += 1
      clearTimers()
      clearTimeout(hideTimer.current)
    },
    [clearTimers],
  )

  // El globo a la vista y si es de la guía de la primera vez (se leen en timers y efectos, no en el render).
  const said = useRef(null)
  const touring = useRef(false)
  const holdFor = useRef(0) // cuánto dura el globo actual (0: se queda hasta que algo lo reemplace)
  const paused = useRef(new Set()) // lo que detiene su cuenta: "¿Por qué?" abierto, puntero o teclado encima

  // Lo de este render que leen los timers, las respuestas de la API y los globos: si la Home está tapada y `drain`.
  const live = useRef({ covered: true, drain: () => {} })
  const spoken = useRef(0) // cuenta los globos dichos: lo pedido no reemplaza a uno que apareció mientras llegaba

  /** Esconde el globo en `ms`; si trae `onExpire` (una oferta), lo llama al irse solo. */
  const armHide = useCallback((ms) => {
    hideTimer.current = setTimeout(() => {
      const gone = said.current
      said.current = null
      setSay(null)
      setTarget(null)
      gone?.onExpire?.()
      live.current.drain()
    }, ms)
  }, [])

  /** El agente dice algo (o se calla con `null`); con `holdMs` el globo se va solo. Cada frase reemplaza a la anterior. */
  const speak = useCallback(
    (next, at = null, holdMs = 0) => {
      // Cualquier otro globo que reemplace a la guía la termina: queda vista y no vuelve.
      if (touring.current && !next?.tour) {
        touring.current = false
        markTourSeen()
      }
      if (next?.tour) touring.current = true
      if (next) spoken.current += 1
      said.current = next
      holdFor.current = next && holdMs ? holdMs : 0
      paused.current.clear()
      clearTimeout(hideTimer.current)
      setSay(next)
      setTarget(at)
      if (holdFor.current) armHide(holdFor.current)
      // Al cerrarse un globo, lo que esperaba puede ir.
      if (!next) live.current.drain()
    },
    [armHide],
  )

  /**
   * Mientras se lee el "¿Por qué?" del globo (`why`), o el puntero (`pointer`) o el foco del teclado (`focus`) están
   * sobre él, no se va solo; cuando ya nada lo detiene, vuelve a contar desde cero.
   */
  const holdBubble = useCallback(
    (reason, on) => {
      clearTimeout(hideTimer.current)
      if (on) paused.current.add(reason)
      else paused.current.delete(reason)
      if (!paused.current.size && said.current && holdFor.current) armHide(holdFor.current)
    },
    [armHide],
  )

  const getBlock = useCallback((id) => blockRefs.current.get(id) ?? null, [])
  const setRef = (id) => (element) => {
    if (element) blockRefs.current.set(id, element)
    else blockRefs.current.delete(id)
  }

  const visit = useCallback((vertical, route) => push(...(route ?? routeForScreen(vertical))), [push])
  /** Abrir la vertical de una oferta de Mochi ("Ver …", "Abrir …") cuenta como abrirla, con el origen de la oferta. */
  const openOffer = (made) => {
    if (made.backendVertical)
      events.track('vertical_open', {
        vertical: made.backendVertical,
        ...envelope({ surface: 'home', origin: `agent-${made.moment}`, requestId: made.requestId }),
      })
  }

  // La oferta del carro en camino: la escena en que se pidió (al salir de la Home, `run` cambia y deja de valer).
  const waiting = useRef(null)
  /**
   * Mochi se para sobre el bloque de los accesos, los señala y dice cuál movió y por qué (cuenta como explicación vista).
   * Si la persona bajó y la fila no se ve, espera a que vuelva a verla (no la lleva arriba).
   */
  const explainMove = () => {
    const move = session.pendingMove
    if (move.resets !== profile.resets) {
      rememberMove(null) // de antes de "Olvidar"
      return
    }
    const screenEl = screenRef.current
    const row = blockRefs.current.get('essentials')
    // Arriba del todo la fila siempre se ve (es el primer bloque).
    const below = screenEl?.scrollTop > 0 && row && screenEl.scrollTop > row.offsetTop + row.offsetHeight - 160
    if (below) return
    rememberMove(null)
    speak(
      {
        reorder: true,
        text: moveText(move),
        why: moveWhy(move.reason),
        mood: 'wave',
        gesture: 'point',
        actions: [{ label: 'Entendido', onClick: () => speak(null) }],
      },
      // Parado sobre el bloque de los accesos: el globo queda sobre Restaurantes y Turbo, y la fila que se movió, a la
      // vista debajo.
      'essentials',
      ACTIONS_HOLD,
    )
    events.track('vertical_reorder_shown', {
      vertical: move.vertical,
      ...envelope({ surface: 'home', origin: MOVE_ORIGIN, position: move.to, requestId: move.requestId }),
      payload: { antes: move.from },
    })
  }

  // La guía: cada paso espera a que la persona siga; "Saltar" o "Listo" la terminan para siempre (speak la marca
  // vista) y entonces el agente muestra lo que quedó pendiente de "al volver".
  const endTour = () => speak(null)
  const showTour = (step) => {
    const last = step === TOUR.length - 1
    speak(
      {
        tour: true,
        text: TOUR[step].text,
        mood: 'wave',
        gesture: TOUR[step].gesture,
        actions: last
          ? [{ label: 'Listo', onClick: endTour }]
          : [
              { label: 'Siguiente', onClick: () => showTour(step + 1) },
              { label: 'Saltar', onClick: endTour },
            ],
      },
      TOUR[step].at,
    )
  }

  const openFromBlock = (product) => openItem(product, push)

  // Primera vez en la Home: entra y saluda. No sugiere nada ni mueve la Home. Con el aviso de privacidad abierto (la
  // primera visita), espera a que se cierre: el aviso tapaba el saludo y la guía.
  useEffect(() => {
    if (session.played) return undefined
    clearTimers()
    if (privacyPending()) {
      const start = () => setPrivacyClosed((n) => n + 1)
      window.addEventListener(PRIVACY_CLOSED_EVENT, start, { once: true })
      return () => window.removeEventListener(PRIVACY_CLOSED_EVENT, start)
    }
    later(reduceMotion ? 0 : T.enter, () => {
      setPresent(true)
      setEntering(true)
      if (!silent()) speak({ text: GREETING, mood: 'wave', gesture: 'greet' }, null, T.greetHold)
    })
    later((reduceMotion ? 0 : T.enter) + T.greet, () => {
      setEntering(false)
      session.played = true
    })
    // Cuando el saludo termina, la primera vez: la guía (en silencio, no; ni encima de algo que la persona pidió). Lo
    // que llegó mientras saludaba (un cambio de orden) va cuando se cierra el saludo, o al terminar la guía.
    later((reduceMotion ? 0 : T.enter) + T.greetHold, () => {
      const free = !said.current || said.current.text === GREETING
      if (free && !silent() && !tourSeen()) showTour(0)
    })
    return clearTimers
    // Solo al montar (o al repetir la escena, o al cerrarse el aviso de privacidad).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [replays, privacyClosed])

  // Lo último que se agregó al carro fuera de la Home lo comenta la oferta `carrito` de la API, con sus productos para
  // agregar ahí mismo. Lo agregado se olvida recién cuando la oferta se muestra o la API dice que no hay (204); si falla,
  // o si al llegar la Home está tapada o ya hay otro globo, queda para el próximo `drain`.
  async function commentOn(added) {
    const mine = run.current
    waiting.current = mine
    let made = null
    let failed = false
    if (added.entityId != null) {
      try {
        made = await offer(
          'carrito',
          { product: { entity_type: added.entityType, entity_id: added.entityId } },
          { userId: userId(), surface: 'home' },
        )
      } catch {
        failed = true
      }
    }
    if (mine !== run.current) return // se fue de la Home o repitió la escena
    waiting.current = null
    // Lo que sigue lee la Home de ahora (`live`), no la de cuando se pidió.
    if (failed) return live.current.drain({ cart: false })
    const same = session.lastAdded && lineKey(session.lastAdded) === lineKey(added)
    if (!made) {
      if (same) forgetAdded()
      return live.current.drain()
    }
    if (live.current.covered || said.current || touring.current || silent()) return
    if (same) forgetAdded()
    noteOfferShown(events.track, made, { generation: profile.resets })
    const see = made.actions.find((action) => action.route)
    const expired = () => noteOfferDismissal(events.track, made, { generation: profile.resets, kind: EXPIRED })
    speak(
      {
        cart: true,
        added, // lo que comenta: si después se agrega otra cosa, esta oferta se reemplaza
        expired,
        text: made.text,
        why: made.reason,
        whyOrigin: `agent-${made.moment}`,
        mood: 'wave',
        // Sus productos van en el globo con su "+": agregarlos es aceptar la oferta (llevan `fromSuggestion`).
        products: made.products,
        onExpire: expired,
        actions: [
          ...(see
            ? [
                {
                  label: see.label,
                  // "Ver …" busca lo ofrecido en su vertical.
                  onClick: () => {
                    noteEngaged()
                    openOffer(made)
                    if (see.query) push('search', { query: see.query, vertical: made.vertical })
                    else visit(made.vertical, see.route)
                  },
                },
              ]
            : []),
          {
            label: 'Ahora no',
            onClick: () => {
              noteDismissed()
              noteOfferDismissal(events.track, made, { generation: profile.resets })
              speak(null)
            },
          },
        ],
      },
      null,
      OFFER_HOLD,
    )
  }

  /**
   * Lo que Mochi tiene pendiente, cuando la Home queda libre (arriba, sin nada encima, ya saludó, sin guía, sin globo
   * y sin una oferta en camino): primero la oferta del carro de lo agregado fuera de la Home y después el cambio de
   * orden de los accesos. Corre al volver a la Home, al destaparla, al terminar la guía y al cerrarse cualquier globo.
   * Con `cart: false` (la oferta acaba de fallar) solo el cambio de orden. En silencio, lo pendiente se olvida.
   */
  const drain = ({ cart = true } = {}) => {
    const covered = !active || overlay
    if (covered || !session.played) return
    if (silent()) {
      forgetAdded()
      rememberMove(null)
      return
    }
    if (touring.current || said.current || waiting.current === run.current) return
    if (cart && session.lastAdded) commentOn(session.lastAdded)
    else if (session.pendingMove) explainMove()
  }
  useLayoutEffect(() => {
    live.current = { covered: !active || overlay, drain }
  })

  // Lo que se agrega con la Home a la vista (un kit, un "+" de sus bloques o del globo) no es "lo agregado fuera": no se
  // comenta. Agregar un producto del globo de la oferta la acepta (useAddToCart lo anota) y Mochi lo confirma.
  useEffect(() => {
    const onAdded = ({ detail }) => {
      if (live.current.covered) return
      forgetAdded()
      const shown = said.current
      if (!shown?.cart || !shown.products.some((product) => product.id === detail.product.id)) return
      noteEngaged()
      speak({ text: kitAddedText([detail.product]), mood: 'wave', gesture: 'spin' }, null, 3500)
    }
    window.addEventListener(AGENT_CART_EVENT, onAdded)
    return () => window.removeEventListener(AGENT_CART_EVENT, onAdded)
  }, [speak])

  // Mirar un producto del globo (su hoja encima) también detiene su cuenta.
  const sheetOpen = useProductSheet().isOpen === true
  useEffect(() => {
    if (said.current?.cart) holdBubble('sheet', sheetOpen)
  }, [sheetOpen, holdBubble])

  /**
   * Al volver a la Home o al destaparla. Si el globo del carro sigue a la vista (pausado mientras estaba tapada) y
   * después se agregó otra cosa, esa oferta se va (como ida sola) y se pide la de lo nuevo; otra unidad del mismo
   * producto no es otra cosa.
   */
  const back = () => {
    const shown = said.current
    if (shown?.cart && session.lastAdded) {
      if (lineKey(session.lastAdded) !== lineKey(shown.added)) {
        shown.expired()
        speak(null) // y drain pide la nueva
        return
      }
      forgetAdded()
    }
    drain()
  }

  // Con otra pantalla encima, lo que Mochi esperaba (una oferta, un kit) ya no corresponde: se calla y no habla después.
  // La guía no: sigue donde quedó cuando la Home vuelve a estar arriba.
  useEffect(() => {
    if (active) return
    run.current += 1
    if (!touring.current) speak(null)
  }, [active, speak])

  useEffect(() => {
    if (active) back()
    // Solo al volver a estar arriba (y al montar).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active])

  // Con el buscador de Mochi o la hoja de direcciones encima, el globo no se va solo (no se vería irse); al cerrarlos,
  // como al volver.
  const wasCovered = useRef(overlay)
  useEffect(() => {
    if (said.current) holdBubble('cover', overlay)
    const uncovered = wasCovered.current && !overlay
    wasCovered.current = overlay
    if (uncovered && active) back()
    // Solo al abrirse o cerrarse lo que tapa la Home.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlay])

  // Cambió el orden con la Home arriba (el "Panel de la demo", o al volver de otra pantalla, o al abrir): la fila ya se
  // desliza (Shortcuts), y Mochi lo explica cuando la Home queda libre (`drain`). Oculto o en silencio, el orden cambia
  // sin explicación.
  const moveKey = shortcuts.move?.key
  useEffect(() => {
    if (!moveKey || silent()) return
    rememberMove({ ...shortcuts.move, resets: profile.resets })
    drain()
    // Solo con cada cambio nuevo.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moveKey])

  // La generación del perfil vigente, para lo que llega después de pedirlo.
  const generationNow = useRef(profile.resets)
  useEffect(() => {
    generationNow.current = profile.resets
  }, [profile.resets])

  // "¿Repetimos?" se pide cada vez que la Home vuelve a estar arriba (un pedido nuevo cambia lo que le toca). Si no hay
  // (204), "¿Volvemos a…?", una vez por pestaña y por pedido: la API mantiene la misma invitación una semana, así que se
  // guarda para que no cambie ni desaparezca al volver a la Home; un pedido nuevo (o "Olvidar") la vuelve a pedir, para
  // no invitar a volver a lo que se acaba de comprar. La recompra siempre gana. Sin ninguna, sin red o con una API que no
  // conoce el momento, no hay bloque; en silencio, o si ya dijeron "Después", no se pide.
  // Tras "Olvidar" no pide (como useVerticalOrder): el buscador olvida antes de que el servidor borre, y pedir ahí traía
  // la misma oferta y otra `suggestion_shown`; lo que venía en camino tampoco se muestra ni se cuenta. Si el borrado sale
  // bien la app se recarga; si falla, pide al volver a la Home.
  useEffect(() => {
    if (!active || silent() || session.repeatLater) return undefined
    let current = true
    const generation = generationNow.current
    const key = `${generation}|${lastOrder}`
    const winback = () => {
      if (session.winback?.key === key) return session.winback.offer
      const keep = (made) => {
        session.winback = { key, offer: made?.products.length ? made : null }
        return session.winback.offer
      }
      return offer('volver', {}, { userId: userId(), surface: 'home' }).then(keep, () => keep(null))
    }
    // Una recompra retenida al grupo de control no pide "¿Volvemos a…?": en tratamiento se habría mostrado la recompra.
    let withheld = false
    const onWithheld = () => {
      withheld = true
    }
    offer('recompra', {}, { userId: userId(), surface: 'home', onWithheld })
      .then((made) => (made?.products.length || withheld ? made : winback()))
      .then(
        (made) => {
          if (!current || generation !== generationNow.current) return
          const shown = made?.products.length ? made : null
          if (shown)
            noteOfferShown(events.track, shown, {
              generation,
              kind: shown.moment === 'volver' ? winbackKind(shown) : undefined,
            })
          setRepeat(shown)
        },
        () => {},
      )
    return () => {
      current = false
    }
  }, [active, events.track, lastOrder])

  // "Después" deja el bloque para otra vez y registra el descarte. En "¿Volvemos a…?" lleva su tipo, como la mostrada:
  // con dos, la API deja de ofrecer esa invitación. El de la recompra lleva su propio origen y no cuenta ahí.
  const repeatLater = () => {
    noteDismissed()
    if (repeat?.moment === 'volver') {
      const [product] = repeat.products
      events.track('suggestion_dismissed', {
        concept_id: repeat.reason?.concept ?? conceptOf(product),
        vertical: product.vertical,
        ...envelope({ surface: 'home', origin: WINBACK_ORIGIN, requestId: repeat.requestId }),
        payload: { kind: winbackKind(repeat) },
      })
    } else if (repeat) noteOfferDismissal(events.track, repeat, { generation: generationNow.current })
    session.repeatLater = true
    setRepeat(null)
  }

  // Las ocasiones del plan del día salen de la API; sin ellas el bloque no ofrece nada (no hay kits locales).
  useEffect(() => {
    let current = true
    fetchPlans().then(
      (list) => current && setPlans(list.slice(0, HOME_PLANS)),
      () => {},
    )
    return () => {
      current = false
    }
  }, [])

  // Cuando el plan del día entra en pantalla, el agente camina hasta él (una vez por sesión).
  const hasPlans = plans.length > 0
  useEffect(() => {
    const element = blockRefs.current.get('plan')
    if (!hasPlans || !element || typeof IntersectionObserver === 'undefined') return undefined
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting || session.planPrompted || !session.played || silent() || touring.current) return
        // Tampoco con la Home tapada ni encima de la oferta del carro (en camino o a la vista).
        if (live.current.covered || waiting.current === run.current || said.current?.cart) return
        session.planPrompted = true
        speak(
          {
            text: '¿Qué plan tienes hoy? Elige uno y armo todo, de las tiendas que hagan falta 👇',
            mood: 'wave',
            gesture: 'point',
          },
          'plan',
          5000,
        )
      },
      { threshold: 0.6 },
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [speak, hasPlans])

  // "Repetir la escena" desde fuera del teléfono.
  useEffect(() => {
    const replay = () => {
      run.current += 1
      clearTimers()
      planRun.current += 1
      setPlan(null)
      setKit(null)
      setKitReason(null)
      setKitStores([])
      setKitAdded(null)
      setPresent(false)
      speak(null)
      screenRef.current?.scrollTo({ top: 0 })
      setReplays((n) => n + 1)
    }
    window.addEventListener(REPLAY_EVENT, replay)
    return () => window.removeEventListener(REPLAY_EVENT, replay)
  }, [clearTimers, speak])

  // Tocar una ocasión pide su kit a la API. Sin kit (204 o sin red) la ocasión no queda elegida y el agente no dice nada.
  const pickPlan = async (id) => {
    const chosen = plans.find((option) => option.id === id)
    const mine = (planRun.current += 1)
    session.plan = null
    setPlan(id)
    setKit(null)
    setKitReason(null)
    setKitStores([])
    setKitAdded(null)
    const seen = spoken.current
    let made = null
    try {
      made = await offer('plan', { occasion: id }, { userId: userId(), surface: 'home' })
    } catch {
      // Sin respuesta: queda como estaba.
    }
    if (mine !== planRun.current) return // eligió otra ocasión (o repitió la escena) mientras llegaba
    if (!made?.products.length) {
      setPlan(null)
      return
    }
    // Cada producto del kit es una sugerencia mostrada, con su propio concepto.
    for (const product of made.products)
      noteShown(events.track, [product], {
        origin: `agent-${made.moment}`,
        reason: made.reason,
        generation: profile.resets,
      })
    session.plan = { id, kit: made.products, reason: made.reason, stores: made.stores } // la Home vuelve a montarse al cambiar de pestaña: el kit sigue ahí
    setKit(made.products)
    setKitReason(made.reason)
    setKitStores(made.stores)
    // El globo no sale con la Home tapada ni reemplaza a uno que apareció mientras llegaba el kit (el bloque sí lo muestra).
    if (!live.current.covered && spoken.current === seen)
      speak({ text: `${chosen.emoji} ${made.text}`, mood: 'wave', gesture: 'hop' }, 'plan', 4500)
  }

  // Igual que el "+" de cada producto: al carro, al perfil y a los eventos del panel (una aceptación por producto).
  const addKit = () => {
    for (const product of kit) addToCart(product)
    setKitAdded(plan)
    buzz()
    toast(`Agregaste ${kit.length} productos del kit`)
    speak({ text: kitAddedText(kit), mood: 'wave', gesture: 'spin' }, 'plan', 3500)
  }

  // Tocar al agente: la API propone la vertical que la persona aún no prueba (según sus pedidos), con sus ofertas.
  const poke = async () => {
    // Mientras saluda, tocarlo no cambia de tema.
    if (!session.played || poking.current) return
    poking.current = true
    const mine = run.current
    const seen = spoken.current
    let made = null
    try {
      made = await offer('vertical_por_probar', {}, { userId: userId(), surface: 'home' })
    } catch {
      // Sin respuesta, el agente no dice nada.
    } finally {
      poking.current = false
    }
    // Sin nada que proponer (204) el agente no dice nada. Tampoco repite con "Vuelve a…" la vertical a la que la Home ya
    // invitó a volver en esta sesión ("¿Volvemos a…?"): una sola invitación por vertical.
    if (mine !== run.current || !made) return
    // Con la Home tapada, o si apareció otro globo mientras llegaba, lo pedido se descarta (ni se muestra ni se cuenta).
    if (live.current.covered || spoken.current !== seen) return
    if (made.reason?.basis?.some((signal) => signal.kind === 'vuelta' && signal.id === backVertical())) return
    noteShown(events.track, made.products, {
      origin: `agent-${made.moment}`,
      reason: made.reason,
      generation: profile.resets,
    })
    const open = made.actions.find((action) => action.route)
    // Si el paso es un servicio sin catálogo (RappiFavor, RappiTravel), se anota ofrecido y, al abrirlo, abierto: así
    // la escalera sigue.
    const offered = envelope({ surface: 'home', origin: `agent-${made.moment}`, requestId: made.requestId })
    if (open?.service) events.track('service_shown', { ...offered, payload: { servicio: open.service } })
    // La burbuja no lleva productos: no promete "mira estas ofertas" (eso lo dice el texto de la API, que sí los muestra).
    const name = VERTICAL_NAMES[screenForBackend(made.backendVertical)]
    speak(
      {
        text: name ? `¿Y si pruebas algo de ${name}?` : made.text,
        why: made.reason,
        whyOrigin: `agent-${made.moment}`,
        mood: 'wave',
        gesture: 'hop',
        onExpire: () =>
          noteDismissal(events.track, made.products, {
            origin: `agent-${made.moment}`,
            generation: profile.resets,
            kind: EXPIRED,
          }),
        actions: [
          ...(open
            ? [
                {
                  label: open.label,
                  onClick: () => {
                    if (open.service)
                      events.track('service_opened', { ...offered, payload: { servicio: open.service } })
                    else openOffer(made)
                    visit(made.vertical, open.route)
                  },
                },
              ]
            : []),
          {
            label: 'Después',
            onClick: () => {
              noteDismissed()
              noteDismissal(events.track, made.products, { origin: `agent-${made.moment}`, generation: profile.resets })
              speak(null)
            },
          },
        ],
      },
      null,
      OFFER_HOLD,
    )
  }

  /**
   * Cada toque a un vertical de la Home le enseña al motor qué abre la persona. El sobre dice qué acceso era, en qué
   * lugar estaba y, en la fila que ordena el motor, la respuesta que la ordenó.
   */
  const openVertical = (vertical, where) =>
    events.track('vertical_open', {
      vertical,
      ...envelope({
        surface: 'home',
        ...where,
        requestId: where?.origin === 'accesos' ? verticalOrder.requestId : undefined,
      }),
    })
  /** Abrir RappiFavor o RappiTravel desde la Home cuenta como usarlo, igual que desde la oferta de Mochi. */
  const openService = (servicio, where) =>
    events.track('service_opened', {
      ...envelope({ surface: 'home', ...where, requestId: verticalOrder.requestId }),
      payload: { servicio, desde: 'home' },
    })

  const blocks = {
    essentials: (
      <>
        <MainTiles push={push} onOpen={openVertical} />
        <Shortcuts
          push={push}
          proposal
          order={shortcuts.order}
          glide={shortcuts.move && { ...shortcuts.move, highlight: !hidden, delay: hidden ? 0 : GLIDE_DELAY }}
          requestId={verticalOrder.requestId}
          caption={verticalOrder.personalized ? 'Ordenadas según lo que más usas' : null}
          onOpen={openVertical}
          onService={openService}
        />
      </>
    ),
    recompra: !hidden && repeat && <RepeatBlock offer={repeat} onLater={repeatLater} onOpen={openFromBlock} />,
    promos: <Promos push={push} />,
    turbo: <FastRestaurants stores={catalog.fastRestaurants} push={push} />,
    // El plan del día lo arma Mochi: oculto, no está.
    plan: !hidden && (
      <PlanBlock
        plans={plans}
        plan={plan}
        kit={kit}
        kitReason={kitReason}
        kitStores={kitStores}
        added={kitAdded === plan}
        onPick={pickPlan}
        onOpen={openFromBlock}
        onAddKit={addKit}
        onCheckout={() => push('checkout')}
      />
    ),
    nearby: <NearbyStores stores={catalog.nearbyStores} push={push} />,
    lower: <BestRated stores={catalog.bestRated} push={push} />,
  }

  return (
    <>
      <div
        ref={screenRef}
        className="screen home home--live"
        onScroll={(event) => {
          onScroll(event)
          agentRef.current?.scrolled()
          // Un cambio de orden que esperaba a que la fila volviera a verse.
          if (session.pendingMove) drain({ cart: false })
        }}
        data-top={scrolled ? 'scrolled' : 'top'}
      >
        <section className="home-top">
          <button type="button" className="home-address tap" onClick={address.openSheet}>
            <span className="home-address-line">{address.selected.line}</span>
            <span className="home-address-label">
              {address.selected.label}
              <span className="chevron-chip">
                <ChevronDown size={16} />
              </span>
            </span>
          </button>
          {/* Sin Mochi, el buscador de siempre (el de "Rappi hoy"). */}
          {hidden ? <PlainSearchBar onClick={() => push('search')} /> : <SmartBar />}
          <CreditsBanner credits={CREDITS} onClick={() => push('vertical', { id: 'pharmacy' })} />
        </section>
        <DemoDisclaimer dates={catalog.dates} />

        <div className="live-blocks">
          {ORDER.filter((id) => blocks[id]).map((id) => (
            <div key={id} ref={setRef(id)} className={`live-block live-block--${id}`}>
              {blocks[id]}
            </div>
          ))}
        </div>
      </div>

      {!hidden && (
        <LiveAgent
          ref={agentRef}
          say={say}
          target={target}
          getBlock={getBlock}
          entering={entering}
          away={!present || !active}
          reduceMotion={reduceMotion}
          onPoke={poke}
          onHold={holdBubble}
          onOpenProduct={openFromBlock}
        />
      )}
    </>
  )
}
