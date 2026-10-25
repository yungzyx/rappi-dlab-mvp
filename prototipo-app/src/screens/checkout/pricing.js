// Cálculo del carro y del checkout, por tienda: un pedido es de una tienda (api/orders.js: basketsOf).
//
// Lo que sale del catálogo (GET /catalog/terms: el envío de los restaurantes y la compra mínima, el envío y la tarifa
// que Rappi guarda en algunas tiendas) es un dato. Todo lo demás es un SUPUESTO de la demo, no un dato ni una política
// de Rappi: cada monto dice de dónde salió (`basis`: 'catalogo' o 'supuesto') y la interfaz rotula «de ejemplo» los
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
// «Tu pedido debe superar…», pero no se sabe cuál en Chile) y la tarifa de servicio baja un 20 % (docs/ecosistema-rappi.md
// dice «≥20 %»). El precio del plan sí es el público de Rappi (CLP 4.990 al mes, docs/ecosistema-rappi.md).
export const PRO = { freeDeliveryMin: 10000, serviceDiscount: 0.2, monthlyPrice: 4990 }

// Créditos de ejemplo: los $1.900 del banner de la Home (data/home.js, CREDITS), que vencen con su cuenta regresiva.
export const CREDITS = { amount: 1900, rule: 'Solo en productos: no en envío, servicio ni propina' }

// Cupones de ejemplo. Uno activo a la vez (otro reemplaza al anterior). SUPER20 es solo de tiendas de Supermercado:
// en un carro sin ellas, «no aplica para esta tienda».
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
export function pricedBasket(basket, catalog, { isPro = false, pickup = false } = {}) {
  const terms = basketTerms(basket, catalog)
  const { subtotal } = basket
  const fullDelivery = pickup ? 0 : terms.delivery.value
  const reachesPro = subtotal >= PRO.freeDeliveryMin
  const fullService = subtotal === 0 ? 0 : Math.max(terms.service.min, round10(subtotal * terms.service.rate))
  const proService = round10(fullService * (1 - PRO.serviceDiscount))
  return {
    ...basket,
    terms,
    missing: Math.max(0, terms.minOrder.value - subtotal),
    fullDelivery,
    delivery: isPro && reachesPro ? 0 : fullDelivery,
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
 * `credits`: si se usan los créditos (ya vigentes). Los créditos van solo en productos, después del cupón.
 */
export function checkoutTotals(priced, { tip = 0, pickup = false, coupon = null, credits = false } = {}) {
  const subtotal = sum(priced, 'subtotal')
  const delivery = sum(priced, 'delivery')
  const service = sum(priced, 'service')
  const appliedTip = pickup ? 0 : tip
  const couponResult = coupon ? couponDiscount(coupon, priced) : null
  const couponAmount = couponResult?.amount ?? 0
  const creditsAmount = credits ? Math.min(CREDITS.amount, subtotal - couponAmount) : 0
  return {
    subtotal,
    delivery,
    service,
    tip: appliedTip,
    coupon: couponResult,
    couponAmount,
    credits: creditsAmount,
    proSaving: sum(priced, 'proSaving'),
    short: priced.filter((b) => b.missing > 0),
    total: subtotal + delivery + service + appliedTip - couponAmount - creditsAmount,
  }
}
