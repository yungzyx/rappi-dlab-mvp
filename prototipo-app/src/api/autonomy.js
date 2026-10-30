// "Pedir por mí" (rappi-ia offers/autonomy.py, migración 049): cuánta autonomía le da la persona a Mochi para pedir.
// Por defecto, "Revisar antes de pedir". Con "Pedir por mí", en las tiendas que eligió (de las que ya pidió) y hasta su
// tope, Mochi pide solo "lo de siempre" (su último pedido ahí, con el precio de hoy): nunca alcohol, +18, farmacia,
// bebé ni salud, ni en una tienda cerrada o bajo la compra mínima. La app suma lo que la API no sabe (el envío y la
// tarifa de ejemplo) antes de abrir la ventana de "Deshacer pedido"; el pedido sale recién al cerrarse la ventana, y la
// API vuelve a revisar cada límite (un 409 con el motivo lo deja para revisar antes).
import { request } from './client'
import { basketsOf, buildOrders, orderVertical } from './orders'
import { userId } from './user'
import { formatPrice } from '../state/CartContext'
import { checkoutTotals, pricedBasket } from '../screens/checkout/pricing'

export { AUTO_ORDER_ORIGIN, toAutoOrder } from './client'
export const AUTONOMY_TITLE = 'Pedir por mí'
const TIMEOUT_MS = 5_000

const path = () => `/profile/${encodeURIComponent(userId())}/autonomia`

/** La respuesta de `/profile/{id}/autonomia` → `{ mode, stores, cap, options: { stores, min, max, suggested } }`. */
export function toSetting(reply) {
  return {
    mode: reply.modo,
    stores: reply.tiendas,
    cap: reply.tope,
    options: {
      stores: reply.opciones.tiendas,
      min: reply.opciones.tope_min,
      max: reply.opciones.tope_max,
      suggested: reply.opciones.tope_sugerido,
    },
  }
}

/** El ajuste de la persona: "revisar" (por defecto) o "pedir", con sus tiendas y su tope. */
export const autonomy = () => request(path(), { timeout: TIMEOUT_MS }).then(toSetting)

/** Enciende o cambia "Pedir por mí" (`stores`: ids de tiendas de las que ya pidió; `cap`: tope por pedido en pesos). */
export const saveAutonomy = ({ stores, cap }) =>
  request(path(), { method: 'PUT', body: { tiendas: stores, tope: cap }, timeout: TIMEOUT_MS }).then(toSetting)

/** Lo apaga en un toque: vuelve a "Revisar antes de pedir". */
export const turnOffAutonomy = () => request(path(), { method: 'DELETE', timeout: TIMEOUT_MS }).then(toSetting)

/**
 * Lo que la app revisa antes de abrir la ventana: el total con envío y tarifa (los del catálogo o los de ejemplo, como
 * en el checkout; sin propina, que se elige al recibirlo) frente al tope, y la compra mínima de ejemplo. `terms`: las
 * condiciones de la tienda (`storeTerms`). Devuelve `{ total, reason }`: `reason` es null si Mochi puede pedirlo.
 */
export function appCheck(order, terms, { isPro = false } = {}) {
  const [basket] = basketsOf(order.lines)
  const priced = pricedBasket(basket, terms, { isPro })
  const { total } = checkoutTotals([priced], { tip: 0 })
  if (priced.missing > 0)
    return {
      total,
      reason: `no llega a la compra mínima de ${order.store.name} (${formatPrice(priced.terms.minOrder.value)}, de ejemplo)`,
    }
  if (order.cap != null && total > order.cap)
    return { total, reason: `con envío y tarifa son ${formatPrice(total)}: pasa tu tope de ${formatPrice(order.cap)}` }
  return { total, reason: null }
}

/** El `POST /orders` del autopedido: el pedido de su tienda, marcado `autopedido` con la respuesta que lo armó. */
export function autoOrderBody(order, { sessionId, cartId, pro }) {
  const [body] = buildOrders(order.lines, { userId: userId(), sessionId, cartId, mode: 'propuesta', pro })
  return body && { ...body, autopedido: order.requestId ? { request_id: order.requestId } : {} }
}

// El producto como se guarda en el pedido de la demo: sin de dónde salió esta vez (como en el checkout).
const stored = ({ placement: _placement, fromSuggestion: _from, suggestionOrigin: _origin, ...product }) => product

/** El pedido de la demo (OrdersContext) de un autopedido ya aceptado por la API, como el del checkout. */
export function demoOrder(order, { cartId, total, address }) {
  return {
    stores: [order.store.name],
    // Como los del checkout: con su tienda y su vertical (los cambios en vivo del Súper, y el pedido que se califica o
    // se cancela se encuentra por carro y tienda).
    storeId: order.store.id,
    vertical: orderVertical(order.lines[0]?.product) ?? null,
    cartId,
    items: order.lines.map(({ product, qty }) => ({
      name: product.name,
      img: product.img,
      price: product.price,
      qty,
      entityType: product.entityType,
      entityId: product.entityId,
      vertical: product.vertical,
      product: stored(product),
    })),
    total,
    pickup: false,
    address,
    byAgent: true,
  }
}
