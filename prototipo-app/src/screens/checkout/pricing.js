// Cálculo del carro y del checkout, por tienda: un pedido es de una tienda (api/orders.js: basketsOf).
//
// Lo que sale del catálogo (GET /catalog/terms: el envío de los restaurantes y la compra mínima, el envío y la tarifa
// que Rappi guarda en algunas tiendas) es un dato. Todo lo demás es un SUPUESTO de la demo, no un dato ni una política
// de Rappi: cada monto dice de dónde salió (`basis`: 'catalogo' o 'supuesto') y la interfaz rotula "de ejemplo" los
// supuestos. Los créditos y los cupones son de ejemplo.
import { formatPrice } from '../../state/CartContext'

export const TIPS = [0, 500, 1000, 1500]
export const DEFAULT_TIP = 1000

// Supuestos por vertical (código del backend) para lo que el catálogo no trae. El envío de un restaurante es la mediana
// de los que sí lo traen en la base (349 de 3.798 locales, $1.490), aplicada a uno que no lo trae.
export const ASSUMED_DELIVERY = { restaurantes: 1490, turbo: 990 }
export const DEFAULT_DELIVERY = 1990
export const ASSUMED_MIN_ORDER = { supermercado: 8000, licores: 5000, mall: 5000, chocolateria: 5000 }
export const DEFAULT_MIN_ORDER = 3000
const SERVICE_RATE = 0.03
const MIN_SERVICE_FEE = 490

// Rappi Pro. Supuestos: el envío es $0 solo en un pedido sobre `freeDeliveryMin` (la app de Rappi exige un monto,
// "Tu pedido debe superar…", pero no se sabe cuál en Chile) y la tarifa de servicio baja un 20 % (docs/ecosistema-rappi.md
// dice "≥20 %"). El precio del plan sí es el público de Rappi (CLP 4.990 al mes, docs/ecosistema-rappi.md).
export const PRO = { freeDeliveryMin: 10000, serviceDiscount: 0.2, monthlyPrice: 4990 }

// Créditos de ejemplo: los $1.900 del banner de la Home, que vencen con su cuenta regresiva. El saldo (lo gastado y lo
// que suman la ayuda, la garantía de Turbo y las cancelaciones) vive en state/credits.js.
export const CREDITS = { amount: 1900, rule: 'Solo en productos: no en envío, servicio ni propina' }

// Cupones de ejemplo. Uno activo a la vez (otro reemplaza al anterior). SUPER20 es solo de tiendas de Supermercado:
// en un carro sin ellas, "no aplica para esta tienda".
export const COUPONS = [
  {
    code: 'BIENVENIDA',
    title: '$2.000 de descuento',
    detail: 'En los productos de un pedido sobre $10.000',
    amount: 2000,
    minSubtotal: 10000,
  },
  {
    code: 'SUPER20',
    title: '20 % en Supermercado',
    detail: 'Tope $3.000, solo en tiendas de Supermercado',
    percent: 20,
    cap: 3000,
    verticals: ['supermercado'],
  },
]

// Tipo de entrega. Supuestos de la demo (la app de Rappi muestra "Envío prioritario" con recargo y franjas con
// descuento, pero los montos los manda su servidor): "Sin prisa" descuenta del envío y tarda más, "Prioritaria" suma y
// llega antes. `etaShift`: minutos que suma o resta al tiempo estimado. Por pedido (cada tienda es un pedido).
export const DELIVERY_TYPES = [
  { id: 'basica', label: 'Básica', eta: '25–35 min', fee: 0, etaShift: 0 },
  { id: 'sin_prisa', label: 'Sin prisa', eta: '40–55 min', fee: -500, etaShift: 15 },
  { id: 'prioritaria', label: 'Prioritaria', eta: '15–25 min', fee: 990, etaShift: -8 },
]
export const deliveryType = (id) => DELIVERY_TYPES.find((type) => type.id === id) ?? DELIVERY_TYPES[0]

const round10 = (value) => Math.round(value / 10) * 10
const sum = (list, key) => list.reduce((total, item) => total + item[key], 0)

/** El cupón de ejemplo con ese código (sin importar mayúsculas ni espacios), o null. */
export const findCoupon = (code) =>
  COUPONS.find(
    (coupon) =>
      coupon.code ===
      String(code ?? '')
        .trim()
        .toUpperCase(),
  ) ?? null

/**
 * Las condiciones de una canasta: lo que trae el catálogo (`catalog`: `{ deliveryFee, minOrder, servicePct }` de
 * `/catalog/terms`, cada uno null si no lo sabe) y, para lo que falta, el supuesto de su vertical.
 */
export function basketTerms(basket, catalog) {
  const known = catalog ?? {}
  const vertical = basket.vertical
  return {
    delivery:
      known.deliveryFee != null
        ? { value: known.deliveryFee, basis: 'catalogo' }
        : { value: ASSUMED_DELIVERY[vertical] ?? DEFAULT_DELIVERY, basis: 'supuesto' },
    minOrder:
      known.minOrder != null
        ? { value: known.minOrder, basis: 'catalogo' }
        : { value: ASSUMED_MIN_ORDER[vertical] ?? DEFAULT_MIN_ORDER, basis: 'supuesto' },
    service:
      known.servicePct != null
        ? { rate: known.servicePct / 100, min: 0, basis: 'catalogo' }
        : { rate: SERVICE_RATE, min: MIN_SERVICE_FEE, basis: 'supuesto' },
  }
}

/**
 * Una canasta con sus montos (`basket` de `basketsOf`). `missing`: lo que falta para su compra mínima (bloquea el
 * pedido); `proMissing`: lo que falta para el envío gratis con Pro; `full*`: el monto sin Pro; `proSaving`: lo que Pro
 * ahorra en esta canasta (envío sobre el mínimo y descuento en servicio). Retiro en tienda: sin envío.
 */
export function pricedBasket(basket, catalog, { isPro = false, pickup = false, type = 'basica' } = {}) {
  const terms = basketTerms(basket, catalog)
  const { subtotal } = basket
  const fullDelivery = pickup ? 0 : terms.delivery.value
  const reachesPro = subtotal >= PRO.freeDeliveryMin
  const fullService = subtotal === 0 ? 0 : Math.max(terms.service.min, round10(subtotal * terms.service.rate))
  const proService = round10(fullService * (1 - PRO.serviceDiscount))
  const delivery = isPro && reachesPro ? 0 : fullDelivery
  // "Sin prisa" no deja el envío bajo $0; con retiro en tienda no hay tipo de entrega.
  const typeFee = pickup ? 0 : Math.max(-delivery, deliveryType(type).fee)
  return {
    ...basket,
    terms,
    missing: Math.max(0, terms.minOrder.value - subtotal),
    fullDelivery,
    delivery,
    typeFee,
    proMissing: pickup || reachesPro ? 0 : PRO.freeDeliveryMin - subtotal,
    fullService,
    service: isPro ? proService : fullService,
    proSaving: (reachesPro ? fullDelivery : 0) + fullService - proService,
  }
}

/**
 * Lo que descuenta un cupón en las canastas: `{ amount, basketKey }` (va en la canasta más grande donde aplica) o
 * `{ error }` con el motivo para mostrar.
 */
export function couponDiscount(coupon, baskets) {
  const fits = baskets.filter((b) => !coupon.verticals || coupon.verticals.includes(b.vertical))
  if (fits.length === 0) return { error: 'Este cupón no aplica para esta tienda' }
  const best = fits.reduce((a, b) => (b.subtotal > a.subtotal ? b : a))
  if (coupon.minSubtotal && best.subtotal < coupon.minSubtotal)
    return { error: `Te faltan ${formatPrice(coupon.minSubtotal - best.subtotal)} en un pedido para usar este cupón` }
  const amount = coupon.amount ?? Math.min(coupon.cap ?? Infinity, round10((best.subtotal * coupon.percent) / 100))
  return { amount: Math.min(amount, best.subtotal), basketKey: best.key }
}

/**
 * Los totales del checkout a partir de las canastas con sus montos (`pricedBasket`). `coupon`: el cupón activo o null;
 * `credits`: los créditos que se pueden usar (el saldo vigente, 0 si no se usan). Van solo en productos, después del
 * cupón.
 */
export function checkoutTotals(priced, { tip = 0, pickup = false, coupon = null, credits = 0 } = {}) {
  const subtotal = sum(priced, 'subtotal')
  const delivery = sum(priced, 'delivery')
  const typeFee = sum(priced, 'typeFee')
  const service = sum(priced, 'service')
  const appliedTip = pickup ? 0 : tip
  const couponResult = coupon ? couponDiscount(coupon, priced) : null
  const couponAmount = couponResult?.amount ?? 0
  const creditsAmount = Math.max(0, Math.min(credits, subtotal - couponAmount))
  return {
    subtotal,
    delivery,
    typeFee,
    service,
    tip: appliedTip,
    coupon: couponResult,
    couponAmount,
    credits: creditsAmount,
    proSaving: sum(priced, 'proSaving'),
    short: priced.filter((b) => b.missing > 0),
    total: subtotal + delivery + typeFee + service + appliedTip - couponAmount - creditsAmount,
  }
}

/**
 * El total de cada pedido (una canasta, en el orden de `priced`), que suman el total del checkout: sus productos, envío,
 * tipo de entrega y servicio; el cupón en la canasta donde aplica; los créditos (solo en productos) de la primera
 * canasta en adelante; y la propina, en el primer pedido.
 */
export function orderAmounts(priced, totals) {
  return orderShares(priced, totals).map((share) => share.total)
}

/**
 * Lo de cada pedido (`orderAmounts`) con lo que usó de los descuentos: `{ total, credits, coupon }`. Si se cancela ese
 * pedido, sus créditos vuelven al saldo y su cupón se puede volver a usar (state/credits.js).
 */
export function orderShares(priced, totals) {
  let credits = totals.credits
  return priced.map((basket, i) => {
    const coupon = totals.coupon?.basketKey === basket.key ? totals.couponAmount : 0
    const used = Math.min(credits, basket.subtotal - coupon)
    credits -= used
    return {
      total:
        basket.subtotal +
        basket.delivery +
        basket.typeFee +
        basket.service -
        coupon -
        used +
        (i === 0 ? totals.tip : 0),
      credits: used,
      coupon,
    }
  })
}
