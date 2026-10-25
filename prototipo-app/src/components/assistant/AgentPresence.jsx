import { useEffect, useRef, useState } from 'react'
import { AGENT_NAME } from '../../agent/name'
import { AGENT_DRAG_TYPE, askAbout } from '../../assistant/agentAsk'
import { useAddToCart } from '../../hooks/useAddToCart'
import { useAssistant } from '../../state/AssistantContext'
import { formatPrice, useCart } from '../../state/CartContext'
import { useDemo } from '../../state/DemoContext'
import { AGENT_CART_EVENT, REPLAY_EVENT } from '../../state/liveMemory'
import { isHushed, isQuiet, noteDismissed, noteEngaged, quietToday, wake } from '../../state/agentQuiet'
import { today } from '../../utils/today'
import Mascot from './Mascot'
import './agent-presence.css'

// Donde el agente no flota: ya está en la pantalla (la Home, el mapa del seguimiento) o estorba (el checkout).
const AGENT_HIDDEN_SCREENS = new Set(['checkout', 'tracking'])
export const SIDE_KEY = 'rappi-proto-mochi-lado'

const SIZE = 68
const JUMP_MS = 900 // al tocarlo salta, como en la Home
const SMALL_AFTER_SCROLL_MS = 750 // al hacer scroll se achica y vuelve un rato después
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
  const [small, setSmall] = useState(false)
  const [quiet, setQuiet] = useState(() => isQuiet(today()))
  const [dragging, setDragging] = useState(false) // se arrastra un producto: el agente lo espera
  const host = useRef(null)
  const body = useRef(null)
  const drag = useRef(null)
  const timers = useRef({})

  const hidden =
    !demo.isFinal || assistant.isOpen || AGENT_HIDDEN_SCREENS.has(screen) || (screen === 'home' && homeTab === 'home')

  const later = (key, fn, ms) => {
    clearTimeout(timers.current[key])
    timers.current[key] = setTimeout(fn, ms)
  }
  useEffect(() => () => Object.values(timers.current).forEach(clearTimeout), [])

  // Al hacer scroll en el teléfono se achica para no tapar lo que se está mirando.
  useEffect(() => {
    const phone = host.current?.closest('.phone')
    if (!phone) return undefined
    const onScroll = () => {
      setSmall(true)
      later('small', () => setSmall(false), SMALL_AFTER_SCROLL_MS)
    }
    phone.addEventListener('scroll', onScroll, true)
    return () => phone.removeEventListener('scroll', onScroll, true)
  }, [hidden])

  // Al agregar al carro, una confirmación corta con «Deshacer». No sugiere nada: eso queda para la Home al volver.
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

  // «Repetir escena»: como una persona que llega por primera vez (resetLive ya borró el silencio guardado).
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

  // Escape o tocar fuera cierran el menú; con Escape el foco vuelve al agente.
  useEffect(() => {
    if (!menu) return undefined
    const onPointer = (event) => {
      if (!host.current?.contains(event.target)) setMenu(false)
    }
    const onKey = (event) => {
      if (event.key !== 'Escape') return
      setMenu(false)
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
  ]
  const run = (id) => {
    setMenu(false)
    noteEngaged()
    if (id === 'search') assistant.open()
    // La vertical por probar la elige el servidor, según los pedidos de la persona.
    if (id === 'try')
      assistant.open({
        query: 'Muéstrame algo nuevo para probar',
        offer: { moment: 'vertical_por_probar', context: {} },
      })
    if (id === 'cart') host.current?.closest('.phone')?.querySelector('.cart-bar')?.click()
    if (id === 'move') moveTo(side === 'right' ? 'left' : 'right')
    if (id === 'quiet') {
      quietToday(today())
      setQuiet(true)
    }
  }

  // La misma posición en silencio y despierto: sobre la barra del carrito y la inferior, nunca encima.
  const classes = ['agent-presence']
  if (side === 'left') classes.push('is-left')
  if (cart.count > 0) classes.push('has-cart')
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
    setMenu((open) => !open)
  }

  if (small && !menu) classes.push('is-small')

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
      {menu && (
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
