import { useEffect, useRef, useState } from 'react'
import { AGENT_NAME } from '../../agent/name'
import { AGENT_DRAG_TYPE, askAbout } from '../../assistant/agentAsk'
import { useAddToCart } from '../../hooks/useAddToCart'
import { useAssistant } from '../../state/AssistantContext'
import { formatPrice, useCart } from '../../state/CartContext'
import { useDemo } from '../../state/DemoContext'
import { useEvents } from '../../state/EventsContext'
import { setAgentHidden, useAgentHidden } from '../../state/agentHidden'
import { openCartSheet } from '../../state/cartSheet'
import { AGENT_CART_EVENT, REPLAY_EVENT } from '../../state/liveMemory'
import { isHushed, isQuiet, noteDismissed, noteEngaged, quietToday, wake } from '../../state/agentQuiet'
import { today } from '../../utils/today'
import { useFloatingInset } from '../floatingInset'
import Mascot from './Mascot'
import { coversControl } from './agentSpot'
import './agent-presence.css'

// Donde el agente no flota: ya está en la pantalla (la Home, el mapa del seguimiento) o estorba (el checkout).
const AGENT_HIDDEN_SCREENS = new Set(['checkout', 'tracking'])
export const SIDE_KEY = 'rappi-proto-mochi-lado'

const SIZE = 68
const JUMP_MS = 900 // al tocarlo salta, como en la Home
const SETTLE_MS = 750 // al hacer scroll se aparta al borde y, un rato después del último, vuelve a mirar si puede salir
const CHECK_MS = 200 // lo que cambia en la pantalla sin scroll se revisa cuando deja de cambiar
const DRAG_THRESHOLD_PX = 8 // menos que esto es un toque, no un arrastre
const CART_BUBBLE_MS = 4000

const readSide = () => {
  try {
    return localStorage.getItem(SIDE_KEY) === 'left' ? 'left' : 'right'
  } catch {
    return 'right'
  }
}

/**
 * El agente flotando a un costado, fuera de la Home (prototipo final). Tocarlo abre un menú corto; arrastrarlo lo deja en
 * el lado más cercano. La posición sale solo del CSS: sobre la barra inferior o la del carrito según las clases.
 */
export default function AgentPresence({ screen, homeTab, raised }) {
  const demo = useDemo()
  const assistant = useAssistant()
  const cart = useCart()
  const { remove } = useAddToCart()
  const [added, setAdded] = useState(null) // lo último agregado, mientras dura su globo
  const [menu, setMenu] = useState(false)
  const [side, setSide] = useState(readSide)
  const [jumping, setJumping] = useState(false)
  const [tucked, setTucked] = useState(false) // apartado al borde: ver agentSpot.js
  const [quiet, setQuiet] = useState(() => isQuiet(today()))
  const [dragging, setDragging] = useState(false) // se arrastra un producto: el agente lo espera
  const [confirmHide, setConfirmHide] = useState(false) // "Ocultar a Mochi" pide confirmar en el mismo globo
  const agentHidden = useAgentHidden()
  const events = useEvents()
  const host = useRef(null)
  const body = useRef(null)
  const drag = useRef(null)
  const timers = useRef({})
  const scrolling = useRef(false)
  const hasCart = cart.count > 0
  // Lo que cuenta para el relleno de las pantallas es Mochi (o su pestañita), no sus globos pasajeros.
  useFloatingInset(() => host.current?.querySelector('.agent-presence-body, .agent-quiet-tab'))

  const hidden =
    !demo.isFinal ||
    agentHidden ||
    assistant.isOpen ||
    AGENT_HIDDEN_SCREENS.has(screen) ||
    (screen === 'home' && homeTab === 'home')

  const later = (key, fn, ms) => {
    clearTimeout(timers.current[key])
    timers.current[key] = setTimeout(fn, ms)
  }
  useEffect(() => () => Object.values(timers.current).forEach(clearTimeout), [])

  // Al hacer scroll en el teléfono se aparta al borde para no tapar lo que se está mirando. Al parar vuelve, salvo que
  // quede sobre un control (un "+", "Ver más", un chip): ahí sigue apartado hasta que deje de estar encima. También mira
  // al cambiar de lugar (carro, barra inferior, lado) y cuando la pantalla cambia sin scroll (llega la lista).
  useEffect(() => {
    const phone = host.current?.closest('.phone')
    if (!phone) return undefined
    const check = () => {
      if (!scrolling.current) setTucked(coversControl(body.current))
    }
    const onScroll = () => {
      scrolling.current = true
      setTucked(true)
      later(
        'settle',
        () => {
          scrolling.current = false
          check()
        },
        SETTLE_MS,
      )
    }
    const observer = new MutationObserver(() => later('check', check, CHECK_MS))
    observer.observe(phone, { childList: true, subtree: true })
    later('check', check, CHECK_MS)
    phone.addEventListener('scroll', onScroll, true)
    return () => {
      observer.disconnect()
      phone.removeEventListener('scroll', onScroll, true)
    }
  }, [hidden, screen, hasCart, raised, side])

  // Al agregar al carro, una confirmación corta con "Deshacer". No sugiere nada: eso queda para la Home al volver.
  // En silencio (por hoy o porque lo ignoraron) no dice nada.
  useEffect(() => {
    if (hidden) return undefined
    const onAdded = (event) => {
      if (isQuiet(today()) || isHushed()) return
      setMenu(false)
      setAdded(event.detail.product)
      setJumping(true)
      later('jump', () => setJumping(false), JUMP_MS)
      later('added', () => setAdded(null), CART_BUBBLE_MS)
    }
    window.addEventListener(AGENT_CART_EVENT, onAdded)
    return () => window.removeEventListener(AGENT_CART_EVENT, onAdded)
  }, [hidden])

  // "Repetir escena": como una persona que llega por primera vez (resetLive ya borró el silencio guardado).
  useEffect(() => {
    const replay = () => {
      setQuiet(false)
      setMenu(false)
      setAdded(null)
    }
    window.addEventListener(REPLAY_EVENT, replay)
    return () => window.removeEventListener(REPLAY_EVENT, replay)
  }, [])

  // Mientras se arrastra un producto (escritorio), el agente avisa que se lo pueden soltar encima.
  useEffect(() => {
    if (hidden) return undefined
    const onStart = (event) => {
      if (event.dataTransfer?.types?.includes(AGENT_DRAG_TYPE)) setDragging(true)
    }
    const onEnd = () => setDragging(false)
    document.addEventListener('dragstart', onStart)
    document.addEventListener('dragend', onEnd)
    return () => {
      document.removeEventListener('dragstart', onStart)
      document.removeEventListener('dragend', onEnd)
    }
  }, [hidden])

  // Escape o tocar fuera cierran el menú (y su confirmación); con Escape el foco vuelve al agente.
  useEffect(() => {
    if (!menu) return undefined
    const close = () => {
      setMenu(false)
      setConfirmHide(false)
    }
    const onPointer = (event) => {
      if (!host.current?.contains(event.target)) close()
    }
    const onKey = (event) => {
      if (event.key !== 'Escape') return
      close()
      body.current?.focus()
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [menu])

  if (hidden) return null

  const moveTo = (next) => {
    setSide(next)
    try {
      localStorage.setItem(SIDE_KEY, next)
    } catch {
      // Sin almacenamiento (ventana privada): el lado dura lo que dura la pestaña.
    }
  }

  const actions = [
    { id: 'search', label: `Buscar con ${AGENT_NAME}` },
    cart.count > 0
      ? { id: 'cart', label: `Revisar mi carrito · ${formatPrice(cart.total)}` }
      : { id: 'try', label: '¿Qué puedo probar?' },
    { id: 'move', label: side === 'right' ? 'Mover a la izquierda' : 'Mover a la derecha' },
    { id: 'quiet', label: 'Silenciar por hoy' },
    { id: 'hide', label: `Ocultar a ${AGENT_NAME}` },
  ]
  const run = (id) => {
    // Ocultar para siempre se confirma antes, en el mismo globo.
    if (id === 'hide') return setConfirmHide(true)
    setMenu(false)
    noteEngaged()
    if (id === 'search') assistant.open()
    // La vertical por probar la elige el servidor, según los pedidos de la persona.
    if (id === 'try')
      assistant.open({
        query: 'Muéstrame algo nuevo para probar',
        offer: { moment: 'vertical_por_probar', context: {} },
      })
    if (id === 'cart') openCartSheet()
    if (id === 'move') moveTo(side === 'right' ? 'left' : 'right')
    if (id === 'quiet') {
      quietToday(today())
      setQuiet(true)
    }
  }

  // La misma posición en silencio y despierto: sobre la barra del carrito y la inferior, nunca encima.
  const classes = ['agent-presence']
  if (side === 'left') classes.push('is-left')
  if (hasCart) classes.push('has-cart')
  if (raised) classes.push('is-raised')

  // Silenciado por hoy: solo una pestañita en el borde, sin globos; tocarla lo despierta.
  if (quiet)
    return (
      <div ref={host} className={[...classes, 'is-quiet'].join(' ')}>
        <button
          type="button"
          className="agent-quiet-tab"
          aria-label={`${AGENT_NAME} está en silencio: tocar para despertarlo`}
          onClick={() => {
            wake()
            setQuiet(false)
          }}
        >
          <Mascot size={40} badge />
        </button>
      </div>
    )

  const down = (event) => {
    setJumping(true)
    later('jump', () => setJumping(false), JUMP_MS)
    drag.current = { x: event.clientX, moved: false }
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }
  const move = (event) => {
    const current = drag.current
    if (!current || current.moved || Math.abs(event.clientX - current.x) < DRAG_THRESHOLD_PX) return
    current.moved = true
    setMenu(false)
  }
  const up = (event) => {
    const current = drag.current
    if (!current?.moved) return
    const phone = host.current?.closest('.phone')?.getBoundingClientRect()
    if (phone) moveTo(event.clientX < phone.left + phone.width / 2 ? 'left' : 'right')
  }
  const toggle = () => {
    // Un arrastre no abre el menú.
    if (drag.current?.moved) {
      drag.current = null
      return
    }
    drag.current = null
    setConfirmHide(false)
    setMenu((open) => !open)
  }

  // Con el menú abierto o un producto arrastrándose hacia él, sale entero.
  if (tucked && !menu && !dragging) classes.push('is-tucked')

  return (
    <div ref={host} className={classes.join(' ')}>
      {dragging && (
        <div className="agent-popover" role="status">
          <p>Acércamelo y lo vemos juntos.</p>
        </div>
      )}
      {added && !menu && !dragging && (
        <div className="agent-popover agent-bubble" role="status">
          <button
            type="button"
            className="agent-bubble-close"
            aria-label="Cerrar"
            onClick={() => {
              noteDismissed()
              setAdded(null)
            }}
          >
            ×
          </button>
          <p>¡Listo! {added.name} está en tu carrito.</p>
          <button
            type="button"
            className="agent-action tap"
            onClick={() => {
              noteEngaged()
              remove(added)
              setAdded(null)
            }}
          >
            Deshacer
          </button>
        </div>
      )}
      {menu && confirmHide && (
        <div className="agent-popover" role="group" aria-label={`Ocultar a ${AGENT_NAME}`}>
          <p>{AGENT_NAME} no volverá a aparecer. Puedes traerlo de vuelta en Cuenta.</p>
          <div className="agent-actions">
            <button
              type="button"
              className="agent-action is-primary tap"
              onClick={() => {
                setMenu(false)
                setConfirmHide(false)
                events.track('agent_visibility', {
                  surface: 'agent',
                  origin: 'menu-mochi',
                  payload: { visible: false },
                })
                setAgentHidden(true)
              }}
            >
              Ocultar
            </button>
            <button type="button" className="agent-action tap" onClick={() => setConfirmHide(false)}>
              Cancelar
            </button>
          </div>
        </div>
      )}
      {menu && !confirmHide && (
        <div className="agent-popover" role="group" aria-label={`Opciones de ${AGENT_NAME}`}>
          <p>¿Qué hacemos juntos?</p>
          <div className="agent-actions">
            {actions.map((action) => (
              <button key={action.id} type="button" className="agent-action tap" onClick={() => run(action.id)}>
                {action.label}
              </button>
            ))}
          </div>
          <small>También puedes arrastrarme al otro lado.</small>
        </div>
      )}
      <button
        ref={body}
        type="button"
        className="agent-presence-body"
        aria-label={`${AGENT_NAME}: ayuda y opciones`}
        aria-expanded={menu}
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={() => (drag.current = null)}
        onClick={toggle}
        onDragOver={(event) => {
          if (event.dataTransfer?.types?.includes(AGENT_DRAG_TYPE)) event.preventDefault()
        }}
        onDrop={(event) => {
          const data = event.dataTransfer?.getData(AGENT_DRAG_TYPE)
          if (!data) return
          event.preventDefault()
          setDragging(false)
          noteEngaged()
          const product = JSON.parse(data)
          assistant.open({ query: askAbout(product), product })
        }}
      >
        <Mascot size={SIZE} mood={jumping ? 'jump' : menu ? 'listen' : 'idle'} />
      </button>
    </div>
  )
}
