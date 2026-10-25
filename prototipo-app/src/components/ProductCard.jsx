import { useEffect, useState } from 'react'
import { AGENT_NAME } from '../agent/name'
import { EtaIcon } from './StoreMeta'
import { AGENT_DRAG_TYPE, askAbout } from '../assistant/agentAsk'
import { useLongPress } from '../hooks/useLongPress'
import { useAssistant } from '../state/AssistantContext'
import { useDemo } from '../state/DemoContext'
import AddButton from './AddButton'
import Img from './Img'
import { useProductSheet } from '../state/ProductSheetContext'
import './product-card.css'

const ASK_VISIBLE_MS = 3000

// En escritorio (mouse) la tarjeta también se puede arrastrar hasta el agente; en el celular, arrastrar es scroll.
const canDrag = () => typeof window !== 'undefined' && window.matchMedia?.('(pointer: fine)').matches === true

/** Producto de supermercado/farmacia/botillería (Meat & Seafood, beers, Baby care…). Tocarlo abre su hoja; el "+" va aparte. */
export function ProductCard({ product, onOpenStore }) {
  const sheet = useProductSheet()
  const final = useDemo()?.isFinal === true
  const assistant = useAssistant()
  const [asking, setAsking] = useState(false)
  const press = useLongPress(() => setAsking(true))

  // «Preguntarle al agente» se va solo, o al tocar fuera.
  useEffect(() => {
    if (!asking) return undefined
    const timer = setTimeout(() => setAsking(false), ASK_VISIBLE_MS)
    const onPointer = (event) => {
      if (!event.target.closest?.('.product-ask')) setAsking(false)
    }
    document.addEventListener('pointerdown', onPointer)
    return () => {
      clearTimeout(timer)
      document.removeEventListener('pointerdown', onPointer)
    }
  }, [asking])

  // En el prototipo final, mantener presionado (o arrastrar hasta el agente, en escritorio) es preguntarle por él.
  const askProps = final
    ? {
        ...press.handlers,
        draggable: canDrag(),
        onDragStart: (event) => event.dataTransfer.setData(AGENT_DRAG_TYPE, JSON.stringify(product)),
      }
    : {}
  const openSheet = () => {
    if (final && press.fired()) return // fue un toque largo
    sheet.open(product, { onOpenStore })
  }

  return (
    <div className="product-card">
      {asking && (
        <button
          type="button"
          className="product-ask tap"
          onClick={() => {
            setAsking(false)
            assistant?.open({ query: askAbout(product), product })
          }}
        >
          Preguntarle a {AGENT_NAME}
        </button>
      )}
      <button
        type="button"
        className={final ? 'product-card-main tap is-askable' : 'product-card-main tap'}
        onClick={openSheet}
        {...askProps}
      >
        <span className={product.partial ? 'product-media is-partial' : 'product-media'}>
          <Img src={product.img} draggable="false" />
          {product.ageRestricted && (
            <span className="product-age" aria-label="Solo mayores de 18">
              +18
            </span>
          )}
        </span>
        <span className="product-price-row">
          <span className={product.discount ? 'product-price' : 'product-price is-plain'}>{product.price}</span>
          {product.before && <s>{product.before}</s>}
        </span>
        {product.discount && <span className="product-pct">{product.discount}</span>}
        <span className="product-name">{product.name}</span>
        <span className="product-size">{product.size}</span>
        <span className="product-unit">{product.unit}</span>
        <StoreLine item={product} />
      </button>
      <AddButton product={product} className="add-button--grocery" />
    </div>
  )
}

/** Logo de la tienda: imagen recortada o, si no hay, un círculo con la inicial (`storeBadge`; sin nombre, vacío). */
export function StoreLogo({ item }) {
  if (item.storeLogo) return <Img src={item.storeLogo} />
  return (
    <span className="store-badge" style={{ background: item.storeBadge ?? '#8b8b8b' }}>
      {item.store?.charAt(0)}
    </span>
  )
}

function StoreLine({ item }) {
  return (
    <span className="store-line">
      <StoreLogo item={item} />
      <span>
        <strong>{item.store}</strong>
        {item.eta && (
          <span className="store-line-eta">
            <EtaIcon kind={item.etaIcon} size={15} />
            {item.eta}
          </span>
        )}
      </span>
    </span>
  )
}
