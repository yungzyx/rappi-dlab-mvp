import { useEffect, useState } from 'react'
import { placeList } from '../../api/attribution'
import { productStores } from '../../api/catalog'
import Img from '../../components/Img'
import { formatPrice } from '../../state/CartContext'
import { useOrders } from '../../state/OrdersContext'
import { SUBSTITUTIONS, resolveChange, soldOutIndex } from './liveChanges'

const MAX_SUBSTITUTES = 4

/**
 * "Tus productos te necesitan" (Súper, en "En tienda"): un producto del pedido se agota (simulado, rotulado como
 * demostración) y la persona elige un sustituto del mismo concepto en la misma tienda (del catálogo), "Si no contesto,
 * elijan por mí" o el reembolso. Mientras decide, el reloj de la demo espera (el shopper espera su respuesta). Lo que
 * eligió en el checkout va marcado.
 */
export function LiveChangeAlert({ order }) {
  const orders = useOrders()
  const index = soldOutIndex(order)
  const item = order.items[index]
  const [substitutes, setSubstitutes] = useState(null)
  const [picking, setPicking] = useState(false)

  useEffect(() => {
    if (!item) return undefined
    orders.hold(order.id, 'cambio')
    let current = true
    productStores(item.entityId, item.product.storeId, { substitutes: true }).then(
      (reply) =>
        current &&
        setSubstitutes(
          placeList(reply.similar.slice(0, MAX_SUBSTITUTES), { surface: 'tracking', origin: 'sustitutos' }),
        ),
      () => current && setSubstitutes([]),
    )
    return () => {
      current = false
    }
    // Una vez por pedido: el aviso aparece al entrar a "En tienda".
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [order.id])

  if (!item) return null
  const resolve = (choice, substitute) => {
    orders.resolveLiveChange(order.id, resolveChange(item, index, choice, substitute))
    orders.release(order.id, 'cambio')
  }
  const preferred = item.substitution
  const options = SUBSTITUTIONS.map((option) => ({ ...option, preferred: option.id === preferred }))
  return (
    <section className="tracking-live" aria-label="Tus productos te necesitan">
      <h2>Tus productos te necesitan</h2>
      <div className="tracking-live-item">
        <Img src={item.img} />
        <span>
          <strong>{item.name}</strong>
          <small>
            Se agotó en la tienda · {item.qty} × {item.price}
          </small>
        </span>
      </div>
      {picking ? (
        <SubstitutePicker
          substitutes={substitutes}
          onPick={(substitute) => resolve('sustituto', substitute)}
          onBack={() => setPicking(false)}
        />
      ) : (
        <div className="tracking-options">
          {options.map((option) => (
            <button
              key={option.id}
              type="button"
              className={option.preferred ? 'tracking-option is-preferred tap' : 'tracking-option tap'}
              disabled={option.id !== 'reembolso' && substitutes === null}
              onClick={() =>
                option.id === 'sustituto'
                  ? setPicking(true)
                  : // "Elijan por mí": el shopper toma el sustituto más barato de la misma tienda; sin uno, reembolsa.
                    resolve(option.id, option.id === 'elijan' ? substitutes?.[0] : null)
              }
            >
              <strong>{option.label}</strong>
              <small>
                {option.detail}
                {option.preferred && ' · lo elegiste en el checkout'}
              </small>
            </button>
          ))}
        </div>
      )}
      <small className="tracking-demo-note">
        Demostración: el agotado es simulado; los sustitutos salen del catálogo de esta tienda.
      </small>
    </section>
  )
}

function SubstitutePicker({ substitutes, onPick, onBack }) {
  return (
    <div className="tracking-substitutes">
      {substitutes?.length ? (
        <ul aria-label="Sustitutos">
          {substitutes.map((product) => (
            <li key={product.id}>
              <button type="button" className="tracking-substitute tap" onClick={() => onPick(product)}>
                <Img src={product.img} />
                <span>
                  <strong>{product.name}</strong>
                  <small>{product.price}</small>
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p>Esta tienda no tiene un producto parecido. Puedes pedir el reembolso.</p>
      )}
      <button type="button" className="tracking-sheet-secondary" onClick={onBack}>
        Volver
      </button>
    </div>
  )
}

/** Lo que cambió en vivo y el "Ajuste en el total". */
export function LiveChangeResult({ order }) {
  const change = order.liveChange
  if (!change) return null
  const item = order.items[change.index]
  const label =
    change.choice === 'reembolso'
      ? `${item?.name ?? 'Un producto'}: se agotó y te lo reembolsamos`
      : `${item?.name ?? 'Un producto'} → ${change.product.name}${change.choice === 'elijan' ? ' (lo eligió tu shopper)' : ''}`
  return (
    <div className="tracking-live-result" role="status">
      <p>{label}</p>
      <p>
        Ajuste en el total:{' '}
        <strong>
          {change.delta > 0 ? '+' : change.delta < 0 ? '−' : ''}
          {formatPrice(Math.abs(change.delta))}
        </strong>
      </p>
      <small className="tracking-demo-note">Demostración: el agotado es simulado.</small>
    </div>
  )
}
