import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from 'react'
import { AGENT_NAME } from '../../../agent/name'
import Mascot from '../../../components/assistant/Mascot'
import OfferWhy from '../../../components/assistant/OfferWhy'
import { rectInPhone } from '../../../state/AssistantContext'
import { typedEnd } from '../../../utils/typed'

const SIZE = 84 // ancho de la mascota de cuerpo entero (alto = 1,2 × ancho)
const HEIGHT = SIZE * 1.2
const EDGE = 14 // margen derecho
const TOP_LIMIT = 118 // bajo la dirección: nunca tapa la barra de estado
const BOTTOM_RESERVE = 104 // sobre la barra inferior (y la del carrito)
const TYPE_MS = 16 // ms por letra al «hablar»
// Mientras nadie le habla, el agente no se queda quieto: cada tanto mira, baila, saluda o se estira (en este orden).
const FIDGETS = ['look', 'dance', 'wave', 'stretch', 'hop']
const FIDGET_MS = 6000
const TUCK_MS = 700 // tras el último scroll, vuelve a asomarse
const JUMP_MS = 900 // al tocarlo salta; vive aquí porque cada frase nueva vuelve a montar la mascota

/** Texto que aparece letra por letra mientras el agente habla (sin animación si se pidió reducir movimiento). */
function useTypewriter(text, reduceMotion) {
  // El avance se guarda junto a su texto: un texto nuevo parte de cero sin reiniciar nada a mano.
  const [progress, setProgress] = useState({ text: null, count: 0 })
  useEffect(() => {
    if (!text || reduceMotion) return undefined
    const timer = setInterval(
      () =>
        setProgress((prev) => {
          if (prev.text !== text) return { text, count: 1 }
          // Ya escrita: el mismo estado, así no vuelve a pintar el globo cada 16 ms mientras sigue a la vista.
          return prev.count >= text.length ? prev : { text, count: prev.count + 1 }
        }),
      TYPE_MS,
    )
    return () => clearInterval(timer)
  }, [text, reduceMotion])
  if (!text) return { shown: '', done: true }
  if (reduceMotion) return { shown: text, done: true }
  const count = progress.text === text ? progress.count : 0
  return { shown: text.slice(0, typedEnd(text, count)), done: count >= text.length }
}

/**
 * El agente de cuerpo entero viviendo en la Home: se para sobre el bloque del que habla (`target`, que `getBlock`
 * convierte en su elemento) o descansa sobre la barra inferior. Habla con un globo y, a veces, ofrece botones. Tocarlo dispara `onPoke`.
 */
const LiveAgent = forwardRef(function LiveAgent(
  { say, target, getBlock, entering, away, reduceMotion, onPoke, onWhyToggle },
  ref,
) {
  const layerRef = useRef(null)
  const [spot, setSpot] = useState(null)
  const [hopKey, setHopKey] = useState(0)
  const lastY = useRef(null)
  const { shown, done } = useTypewriter(say?.text, reduceMotion)
  const [fidget, setFidget] = useState(null)
  const fidgets = useRef(0)
  const [tucked, setTucked] = useState(false)
  const tuckTimer = useRef(null)
  const [jumping, setJumping] = useState(false)
  const jumpTimer = useRef(null)
  const frame = useRef(0)
  // Tamaño del teléfono: no cambia al hacer scroll (solo al cambiar la ventana), así que se mide una vez.
  const phoneSize = useRef(null)
  useEffect(
    () => () => {
      clearTimeout(tuckTimer.current)
      clearTimeout(jumpTimer.current)
      cancelAnimationFrame(frame.current)
    },
    [],
  )

  const place = useCallback(() => {
    const layer = layerRef.current
    if (!layer) return
    if (!phoneSize.current) {
      const phone = rectInPhone(layer)
      phoneSize.current = { height: phone.phoneHeight, width: phone.phoneWidth }
    }
    const { height, width } = phoneSize.current
    let y = height - BOTTOM_RESERVE - HEIGHT
    const block = target ? getBlock(target) : null
    if (block) {
      const box = rectInPhone(block)
      const visible = box.top + box.height > TOP_LIMIT && box.top < height - BOTTOM_RESERVE
      // Parado sobre el borde superior del bloque (los zapatos lo pisan), dentro de la pantalla.
      if (visible) y = Math.min(Math.max(box.top - HEIGHT + 16, TOP_LIMIT), height - BOTTOM_RESERVE - HEIGHT)
    }
    const x = width - SIZE - EDGE
    // En la mitad de abajo el globo crece hacia arriba (no tapa la barra inferior).
    const low = y > height / 2
    setSpot((prev) => (prev && Math.abs(prev.x - x) < 1 && Math.abs(prev.y - y) < 1 ? prev : { x, y, low }))
  }, [target, getBlock])

  useLayoutEffect(() => {
    place()
  }, [place, say])

  // Cada vez que cambia de bloque da un salto.
  useEffect(() => {
    if (!spot) return
    if (lastY.current !== null && Math.abs(lastY.current - spot.y) > 30) setHopKey((n) => n + 1)
    lastY.current = spot.y
  }, [spot])

  useEffect(() => {
    const onResize = () => {
      phoneSize.current = null
      place()
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [place])

  // Al hacer scroll se esconde tras el borde (no tapa lo que se está mirando) y vuelve a asomarse al parar.
  // La posición se recalcula a lo más una vez por cuadro (mide el bloque con getBoundingClientRect).
  const scrolled = useCallback(() => {
    if (!frame.current)
      frame.current = requestAnimationFrame(() => {
        frame.current = 0
        place()
      })
    setTucked(true)
    clearTimeout(tuckTimer.current)
    tuckTimer.current = setTimeout(() => setTucked(false), TUCK_MS)
  }, [place])

  useImperativeHandle(ref, () => ({ reposition: place, scrolled }), [place, scrolled])

  useEffect(() => {
    if (say || away || reduceMotion) return undefined
    const timer = setInterval(() => {
      setFidget({ name: FIDGETS[fidgets.current % FIDGETS.length], key: fidgets.current })
      fidgets.current += 1
    }, FIDGET_MS)
    return () => clearInterval(timer)
  }, [say, away, reduceMotion])

  const mood = say ? (done ? (say.mood ?? 'idle') : 'talk') : 'idle'
  const style = spot ? { transform: `translate3d(${spot.x}px, ${spot.y}px, 0)` } : { opacity: 0 }
  // Cada frase trae su gesto (saludar, saltar, apuntar, girar); sin frase, el último gesto de espera. La llave nueva
  // vuelve a montar el envoltorio y la animación corre otra vez.
  const gesture = say ? say.gesture : fidget?.name
  const gestureKey = say ? `say-${say.text}` : `fidget-${fidget?.key ?? 'none'}`
  // Sin nada que decir, se asoma desde el borde derecho en vez de tapar tarjetas y botones.
  const resting = !say && !entering && !away
  const classes = ['live-agent']
  if (entering) classes.push('is-entering')
  if (away) classes.push('is-away')
  if (spot?.low) classes.push('is-low')
  if (resting) classes.push(tucked ? 'is-resting is-tucked' : 'is-resting')

  return (
    <div ref={layerRef} className="live-layer">
      {/* Para lectores de pantalla, la frase entera una vez (el globo la escribe letra por letra). */}
      <p className="sr-only" role="status">
        {away ? '' : (say?.text ?? '')}
      </p>
      <div className={classes.join(' ')} style={style} data-at={target ?? undefined}>
        {say && !away && (
          <div className="live-bubble">
            {/* Lo que falta va invisible detrás (`data-rest`, que pinta el CSS): el globo mide desde la primera letra lo
                que medirá al terminar, y su borde no se corre con cada letra. */}
            <p aria-hidden="true">
              {shown}
              {!done && <span className="live-bubble-rest" data-rest={say.text.slice(shown.length)} />}
            </p>
            {/* «¿Por qué?» y los botones también ocupan su lugar desde el principio (el globo no crece al terminar),
                pero no se ven ni se tocan hasta que termina de escribir. */}
            {(say.why || say.actions?.length > 0) && (
              <div
                className={done ? 'live-bubble-more' : 'live-bubble-more is-pending'}
                aria-hidden={!done || undefined}
              >
                {say.why && <OfferWhy reason={say.why} onToggle={onWhyToggle} />}
                {say.actions?.length > 0 && (
                  <div className="live-bubble-actions">
                    {say.actions.map((action, i) => (
                      <button
                        key={action.label}
                        type="button"
                        className={i === 0 ? 'live-chip is-primary tap' : 'live-chip tap'}
                        onClick={action.onClick}
                      >
                        {action.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
        <button
          type="button"
          className="live-agent-body"
          aria-label={`${AGENT_NAME}: muéstrame algo nuevo para probar`}
          title={AGENT_NAME}
          hidden={away}
          onPointerDown={() => {
            setJumping(true)
            clearTimeout(jumpTimer.current)
            jumpTimer.current = setTimeout(() => setJumping(false), JUMP_MS)
          }}
          onClick={onPoke}
        >
          <span key={hopKey} className={hopKey ? 'live-hop' : undefined}>
            <span key={gestureKey} className={gesture ? `live-gesture live-gesture--${gesture}` : 'live-gesture'}>
              <Mascot size={SIZE} mood={jumping ? 'jump' : mood} />
            </span>
          </span>
        </button>
      </div>
    </div>
  )
})

export default LiveAgent
