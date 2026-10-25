import { useEffect, useRef, useState } from 'react'
import AddButton from '../AddButton'
import HScroll from '../HScroll'
import Img from '../Img'
import OfferWhy from './OfferWhy'
import { useReducedMotion } from '../../hooks/useReducedMotion'
import { useProductSheet } from '../../state/ProductSheetContext'
import { typedEnd } from '../../utils/typed'

const CHARS_PER_SECOND = 70
const TICK_MS = 30

/**
 * Texto que aparece letra por letra, como si el asistente lo estuviera escribiendo (entero con «reducir movimiento»).
 * Lo que falta va invisible detrás (`data-rest`, que pinta el CSS): la burbuja mide desde el principio lo que medirá al
 * terminar y las palabras no saltan de línea, así que lo de abajo no se mueve. No es texto de la página: el lector de
 * pantalla oye la respuesta entera en el anunciador del panel.
 */
function StreamText({ text, animate, onDone }) {
  const reduce = useReducedMotion()
  const [typed, setCount] = useState(animate ? 0 : text.length)
  const count = reduce ? text.length : typed
  const finished = useRef(!animate)
  const startedAt = useRef(null)
  // En una ref para que un render del padre no reinicie el temporizador.
  const onDoneRef = useRef(onDone)
  useEffect(() => {
    onDoneRef.current = onDone
  }, [onDone])

  useEffect(() => {
    if (finished.current) return undefined
    if (count >= text.length) {
      finished.current = true
      onDoneRef.current?.()
      return undefined
    }
    // El avance sale del tiempo transcurrido: si el navegador atrasa los ticks, el texto no se hace más lento.
    startedAt.current ??= performance.now()
    const timer = setTimeout(() => {
      const elapsed = performance.now() - startedAt.current
      setCount(Math.max(count + 1, Math.floor((elapsed / 1000) * CHARS_PER_SECOND)))
    }, TICK_MS)
    return () => clearTimeout(timer)
  }, [count, text])

  const end = typedEnd(text, count)
  return (
    <>
      {text.slice(0, end)}
      {end < text.length && <span className="agent-msg-rest" data-rest={text.slice(end)} />}
    </>
  )
}

function ProductCards({ products, onOpenProduct, delay = 0 }) {
  const sheet = useProductSheet()
  return (
    <HScroll className="agent-msg-products">
      {products.map((product, i) => (
        <div key={product.id} className="agent-msg-product" style={{ animationDelay: `${delay + i * 60}ms` }}>
          <button
            type="button"
            className="agent-msg-product-main tap"
            onClick={() => sheet.open(product, { onOpenStore: () => onOpenProduct(product) })}
          >
            <span className="agent-msg-product-media">
              <Img src={product.img} draggable="false" />
              {product.ageRestricted && (
                <span className="agent-msg-product-age" aria-label="Solo mayores de 18">
                  +18
                </span>
              )}
            </span>
            <span className="agent-msg-product-name">{product.name}</span>
            <span className="agent-msg-product-price">
              <b>{product.price}</b>
              {product.discount && <span>{product.discount}</span>}
            </span>
            <span className="agent-msg-product-store">{product.store}</span>
          </button>
          <AddButton product={product} className="add-button--agent" />
        </div>
      ))}
    </HScroll>
  )
}

/** Logo de la tienda; si no hay (o no carga), su inicial. */
function StoreLogo({ store }) {
  const [broken, setBroken] = useState(false)
  if (!store.logo || broken) return <span className="agent-msg-also-initial">{store.name.trim().charAt(0)}</span>
  return <Img src={store.logo} onError={() => setBroken(true)} />
}

/** "También en": otras verticales con oferta de lo pedido y sus tiendas reales. Cada una abre su vertical. */
function AlsoIn({ alsoIn, onAction }) {
  return (
    <div className="agent-msg-also">
      <p className="agent-msg-reason">
        <span className="agent-msg-suggestion-tag">También en</span> {alsoIn.label} en otras verticales:
      </p>
      <div className="agent-msg-stores">
        {alsoIn.verticals.map((vertical, i) => (
          <button
            key={vertical.label}
            type="button"
            className="agent-msg-store agent-msg-also-vertical tap"
            style={{ animationDelay: `${240 + i * 60}ms` }}
            onClick={() => vertical.route && onAction({ route: vertical.route })}
          >
            <span className="agent-msg-also-logos">
              {vertical.stores.map((store) => (
                <StoreLogo key={store.name} store={store} />
              ))}
            </span>
            <span>
              <strong>{vertical.label}</strong>
              <small>
                {vertical.stores.map((store) => store.name).join(' · ')} · {vertical.items.toLocaleString('es-CL')}{' '}
                productos
              </small>
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

/** Una respuesta del agente con tarjetas (lo elegido se muestra aparte, sin burbuja). */
export default function AgentMessage({ message, onStreamDone, onOpenProduct, onOpenStore, onAction, onRetry }) {
  const [revealed, setRevealed] = useState(!message.animate)

  if (message.typing) {
    return (
      <div className="agent-msg-row">
        <div className="agent-msg-bubble agent-msg-typing" aria-label="Escribiendo">
          <span />
          <span />
          <span />
        </div>
      </div>
    )
  }

  const done = () => {
    setRevealed(true)
    onStreamDone?.()
  }

  return (
    <div className="agent-msg-row">
      <div className="agent-msg-bot">
        <div className="agent-msg-bubble">
          <StreamText text={message.text} animate={message.animate} onDone={done} />
        </div>
        {/* Lo de abajo ocupa su lugar desde el principio (al aparecer no empuja el panel), pero no se ve ni se toca
            hasta que termina el texto. */}
        <div className={`agent-msg-extras${revealed ? '' : ' is-pending'}`} inert={!revealed}>
          {message.reason && <p className="agent-msg-reason">{message.reason}</p>}
          {message.products?.length > 0 && <ProductCards products={message.products} onOpenProduct={onOpenProduct} />}
          {message.offerReason && <OfferWhy reason={message.offerReason} />}
          {message.suggestion?.products?.length > 0 && (
            <div className="agent-msg-suggestion">
              <p className="agent-msg-reason">
                <span className="agent-msg-suggestion-tag">
                  {message.suggestion.verticalLabel ? `De ${message.suggestion.verticalLabel}` : 'De otra tienda'}
                </span>{' '}
                {message.suggestion.question} {message.suggestion.reason}
              </p>
              <ProductCards products={message.suggestion.products} onOpenProduct={onOpenProduct} delay={180} />
              {message.suggestion.route && message.suggestion.verticalLabel && (
                <button
                  type="button"
                  className="agent-msg-action tap"
                  onClick={() => onAction({ route: message.suggestion.route })}
                >
                  Ver más en {message.suggestion.verticalLabel} →
                </button>
              )}
            </div>
          )}
          {message.alsoIn?.verticals?.length > 0 && <AlsoIn alsoIn={message.alsoIn} onAction={onAction} />}
          {message.stores?.length > 0 && (
            <div className="agent-msg-stores">
              {message.stores.map((store, i) => (
                <button
                  key={store.name}
                  type="button"
                  className="agent-msg-store tap"
                  style={{ animationDelay: `${120 + i * 60}ms` }}
                  onClick={() => onOpenStore(store)}
                >
                  <Img src={store.img} className={store.logo ? 'is-logo' : undefined} />
                  <span>
                    <strong>{store.name}</strong>
                    {store.eta && <small>{store.eta}</small>}
                  </span>
                </button>
              ))}
            </div>
          )}
          {message.retry && (
            <button type="button" className="agent-msg-action tap" onClick={onRetry}>
              Reintentar
            </button>
          )}
          {message.actions?.map((action) => (
            <button key={action.label} type="button" className="agent-msg-action tap" onClick={() => onAction(action)}>
              {action.label} →
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
