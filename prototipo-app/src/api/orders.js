// Pedidos del prototipo → rappi-ia: un pedido por tienda (como en Rappi: dos restaurantes son dos pedidos).
import { parsePrice } from '../state/CartContext'
import { placementFields } from './attribution'

// Los pedidos que van en camino al servidor (`POST /orders` y lo que lo precede): «Olvidar» los espera antes de borrar el
// perfil, porque uno que llegue después lo recrearía.
const inFlight = new Set()

/** Registra un pedido en camino (la promesa de todo su envío) y devuelve la misma promesa; su fallo no afecta a quien espera (queda en la consola). */
export function trackOrder(sending) {
  const tracked = Promise.resolve(sending).then(
    () => {},
    (error) => console.warn('No se pudo enviar el pedido al servidor; el pedido de la demo sigue igual.', error),
  )
  inFlight.add(tracked)
  tracked.then(() => inFlight.delete(tracked))
  return sending
}

/** Termina cuando ya no hay pedidos en camino (también los que se registren mientras espera). */
export async function ordersSettled() {
  while (inFlight.size) await Promise.all([...inFlight])
}

/** Concepto de un producto: el que trae de la API (`concept`); sin él, el evento y el pedido van sin concepto. */
export const conceptOf = (product) => product.concept

/**
 * Campos de un evento de carro (agregar, quitar, vaciar) o de ver un producto para rappi-ia; `qty` = unidades del
 * evento. Con el sobre de dónde salió el producto (`placementFields`: pantalla, lista, posición y respuesta de la API).
 */
export function cartEventFields(item, cartId, { qty } = {}) {
  return {
    ...placementFields(item),
    cart_id: cartId,
    vertical: item.vertical,
    concept_id: conceptOf(item),
    entity_type: item.entityType,
    entity_id: item.entityId,
    value: parsePrice(item.price) || undefined,
    // La tienda: con ella la API fija el precio y la oferta vigentes que se vieron ahí (payload.catalogo).
    payload: {
      ...(item.fromSuggestion ? { from_suggestion: true } : {}),
      ...(qty ? { qty } : {}),
      ...(Number.isSafeInteger(item.storeId) && item.storeId >= 0 ? { store_id: item.storeId } : {}),
    },
  }
}

// Verticales que acepta POST /orders. El pedido va con el código del backend: un producto con
// `backendVertical: 'licores'` y otro con `vertical: 'liquor'` son de la misma vertical.
const BACKEND_VERTICALS = {
  grocery: 'supermercado',
  liquor: 'licores',
  pharmacy: 'farmacia',
  retail: 'mall',
  express: 'conveniencia',
  chocolates: 'chocolateria',
  restaurants: 'restaurantes',
}
const BACKEND_CODES = new Set([...Object.values(BACKEND_VERTICALS), 'turbo'])
/** El código del backend de la vertical de un producto (la de la API manda sobre la de la pantalla), o undefined. */
export const orderVertical = (product) => {
  const vertical = product.backendVertical ?? product.vertical
  return BACKEND_CODES.has(vertical) ? vertical : BACKEND_VERTICALS[vertical]
}

/**
 * La tienda de un producto, que es su canasta y su pedido: su `storeId` (en un plato, el restaurante; los ids de tiendas
 * y restaurantes no se repiten) o, sin él, la vertical y el nombre de la tienda.
 */
export const storeKeyOf = (product) =>
  product.storeId != null ? `id:${product.storeId}` : `name:${orderVertical(product) ?? ''}|${product.store ?? ''}`

/**
 * Las líneas del carro por tienda, en el orden en que se agregaron: `[{ key, storeId, store, vertical, lines,
 * subtotal }]`. `vertical` es el código del backend de la primera línea (una tienda con dos verticales, como un súper
 * que también es express, es un solo pedido).
 */
export function basketsOf(items) {
  const byStore = new Map()
  for (const line of items) {
    const key = storeKeyOf(line.product)
    if (!byStore.has(key))
      byStore.set(key, {
        key,
        storeId: line.product.storeId ?? null,
        store: line.product.store ?? '',
        vertical: orderVertical(line.product) ?? null,
        lines: [],
        subtotal: 0,
      })
    const basket = byStore.get(key)
    basket.lines.push(line)
    basket.subtotal += line.qty * parsePrice(line.product.price)
  }
  return [...byStore.values()]
}

/**
 * Líneas del carrito → un pedido por tienda (`basketsOf`). Todo producto trae su `entityId` real de la API: una línea
 * sin él no existe (nunca se inventa un id) y se descarta con un aviso en desarrollo. Un producto sin vertical del
 * catálogo sigue en el carrito de la demo, pero no se envía: la API rechazaría el pedido completo. En «Rappi hoy»
 * (`mode: 'actual'`) la app no aprende: el pedido va marcado y sin conceptos, como los eventos de ese modo. `pro`: si la
 * persona es Rappi Pro en la app (el backend lo guarda en la persona); sin él, el pedido no lo dice.
 */
export function buildOrders(items, { userId, sessionId, cartId, mode = 'propuesta', pro }) {
  const orders = []
  for (const basket of basketsOf(items)) {
    const lines = basket.lines.flatMap((line) => orderLine(line, mode))
    if (basket.vertical && lines.length)
      orders.push({
        user_id: userId,
        session_id: sessionId,
        cart_id: cartId,
        vertical: basket.vertical,
        mode,
        ...(pro == null ? {} : { pro }),
        lines,
      })
  }
  return orders
}

/** Una línea del carro → `[línea de POST /orders]`, o `[]` si no se puede enviar (sin vertical del catálogo o sin id). */
function orderLine({ product, qty, fromSuggestion }, mode) {
  if (!orderVertical(product)) return []
  if (product.entityId == null) {
    if (import.meta.env.DEV) console.warn(`Línea sin entityId descartada del pedido: ${product.name ?? product.id}`)
    return []
  }
  return [
    {
      entity_type: product.entityType === 'menu_item' ? 'menu_item' : 'catalog_item',
      entity_id: product.entityId,
      ...(mode === 'propuesta' ? { concept_id: conceptOf(product) } : {}),
      // La tienda de donde se agregó: el precio cambia entre tiendas y el backend toma el de esa.
      ...(product.storeId != null ? { store_id: product.storeId } : {}),
      qty,
      unit_price: parsePrice(product.price) || undefined,
      from_suggestion: Boolean(fromSuggestion ?? product.fromSuggestion),
    },
  ]
}
