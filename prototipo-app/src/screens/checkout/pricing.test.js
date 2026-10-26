import { describe, expect, test } from 'vitest'
import {
  CREDITS,
  DEFAULT_DELIVERY,
  PRO,
  basketTerms,
  checkoutTotals,
  couponDiscount,
  findCoupon,
  orderAmounts,
  pricedBasket,
} from './pricing'

const basket = (subtotal, vertical = 'restaurantes', key = `${vertical}-${subtotal}`) => ({
  key,
  storeId: 1,
  store: 'Tienda',
  vertical,
  lines: [],
  subtotal,
})
const RESTAURANT = { deliveryFee: 1490, minOrder: null, servicePct: null } // lo que trae /catalog/terms de un local

describe('condiciones de cada tienda', () => {
  test('lo que trae el catálogo es dato; lo que falta, el supuesto de su vertical', () => {
    const terms = basketTerms(basket(5000), RESTAURANT)
    expect(terms.delivery).toEqual({ value: 1490, basis: 'catalogo' })
    expect(terms.minOrder).toEqual({ value: 3000, basis: 'supuesto' })
    expect(terms.service.basis).toBe('supuesto')
    const store = basketTerms(basket(5000, 'supermercado'), { deliveryFee: null, minOrder: 0, servicePct: 5 })
    expect(store.delivery).toEqual({ value: DEFAULT_DELIVERY, basis: 'supuesto' })
    expect(store.minOrder).toEqual({ value: 0, basis: 'catalogo' }) // «sin mínimo» también es un dato
    expect(store.service).toMatchObject({ rate: 0.05, basis: 'catalogo' })
    // Sin respuesta de la API: todo supuesto.
    expect(basketTerms(basket(5000, 'supermercado'), null).minOrder).toEqual({ value: 8000, basis: 'supuesto' })
  })

  test('la tarifa de servicio supuesta es 3 % con mínimo $490; la del catálogo, su porcentaje', () => {
    expect(pricedBasket(basket(20000), RESTAURANT).service).toBe(600)
    expect(pricedBasket(basket(5000), RESTAURANT).service).toBe(490)
    expect(pricedBasket(basket(20000), { servicePct: 5 }).service).toBe(1000)
    expect(pricedBasket(basket(0), RESTAURANT).service).toBe(0)
  })

  test('bajo la compra mínima la canasta dice cuánto falta', () => {
    expect(pricedBasket(basket(1990, 'supermercado'), { minOrder: 8490 }).missing).toBe(6500)
    expect(pricedBasket(basket(9000, 'supermercado'), { minOrder: 8490 }).missing).toBe(0)
    expect(pricedBasket(basket(10, 'supermercado'), { minOrder: 0 }).missing).toBe(0)
  })
})

describe('Rappi Pro', () => {
  test('sin Pro se cobra el envío de la tienda y se dice cuánto ahorraría', () => {
    const priced = pricedBasket(basket(20000), RESTAURANT, { isPro: false })
    expect(priced.delivery).toBe(1490)
    expect(priced.service).toBe(600)
    expect(priced.proSaving).toBe(1490 + 120) // el envío (sobre el mínimo Pro) y el 20 % del servicio
  })

  test('con Pro, envío gratis solo sobre el mínimo, y 20 % menos en servicio', () => {
    const over = pricedBasket(basket(20000), RESTAURANT, { isPro: true })
    expect(over).toMatchObject({ delivery: 0, fullDelivery: 1490, service: 480, proMissing: 0 })
    const under = pricedBasket(basket(6000), RESTAURANT, { isPro: true })
    expect(under.delivery).toBe(1490)
    expect(under.proMissing).toBe(PRO.freeDeliveryMin - 6000)
    expect(under.proSaving).toBe(100) // bajo el mínimo Pro solo ahorra en servicio (490 → 390)
  })

  test('retiro en tienda: sin envío ni «te faltan» para Pro', () => {
    const pickup = pricedBasket(basket(6000), RESTAURANT, { isPro: true, pickup: true })
    expect(pickup).toMatchObject({ delivery: 0, fullDelivery: 0, proMissing: 0 })
  })
})

describe('cupones y créditos de ejemplo', () => {
  test('BIENVENIDA: $2.000 en el pedido más grande sobre $10.000; si no llega, cuánto falta', () => {
    const coupon = findCoupon(' bienvenida ')
    expect(couponDiscount(coupon, [basket(4000, 'turbo'), basket(12000)])).toEqual({
      amount: 2000,
      basketKey: 'restaurantes-12000',
    })
    expect(couponDiscount(coupon, [basket(7000)]).error).toBe('Te faltan $3.000 en un pedido para usar este cupón')
  })

  test('SUPER20: solo en Supermercado (20 % con tope); en otra tienda «no aplica para esta tienda»', () => {
    const coupon = findCoupon('SUPER20')
    expect(couponDiscount(coupon, [basket(12000)])).toEqual({ error: 'Este cupón no aplica para esta tienda' })
    expect(couponDiscount(coupon, [basket(12000, 'supermercado')]).amount).toBe(2400)
    expect(couponDiscount(coupon, [basket(40000, 'supermercado')]).amount).toBe(3000)
    expect(findCoupon('NOEXISTE')).toBeNull()
  })

  test('el total descuenta el cupón y los créditos (solo en productos, nunca bajo cero)', () => {
    const priced = [pricedBasket(basket(12000), RESTAURANT), pricedBasket(basket(4000, 'turbo'), null)]
    const plain = checkoutTotals(priced, { tip: 1000 })
    expect(plain.total).toBe(16000 + 1490 + 990 + 490 + 490 + 1000)
    const discounted = checkoutTotals(priced, { tip: 1000, coupon: findCoupon('BIENVENIDA'), credits: true })
    expect(discounted.couponAmount).toBe(2000)
    expect(discounted.credits).toBe(CREDITS.amount)
    expect(discounted.total).toBe(plain.total - 2000 - CREDITS.amount)
    // Un pedido chico: los créditos no pasan del valor de los productos.
    const small = checkoutTotals([pricedBasket(basket(1000), RESTAURANT)], { credits: true })
    expect(small.credits).toBe(1000)
    // Un cupón que no aplica no descuenta nada y dice por qué.
    const notHere = checkoutTotals(priced, { coupon: findCoupon('SUPER20') })
    expect(notHere.couponAmount).toBe(0)
    expect(notHere.coupon.error).toMatch(/no aplica para esta tienda/)
  })

  test('las canastas bajo su mínimo quedan en `short`; retiro no cobra propina', () => {
    const priced = [pricedBasket(basket(1000), RESTAURANT), pricedBasket(basket(9000), RESTAURANT)]
    const totals = checkoutTotals(priced, { tip: 1500, pickup: true })
    expect(totals.short.map((b) => b.subtotal)).toEqual([1000])
    expect(totals.tip).toBe(0)
  })
})

describe('tipo de entrega y el total de cada pedido', () => {
  test('«Sin prisa» descuenta del envío sin dejarlo bajo $0, «Prioritaria» suma, y el retiro no tiene tipo', () => {
    const terms = { deliveryFee: 300, minOrder: 0, servicePct: null }
    expect(pricedBasket(basket(5000), terms, { type: 'sin_prisa' }).typeFee).toBe(-300)
    expect(pricedBasket(basket(5000), null, { type: 'prioritaria' }).typeFee).toBe(990)
    expect(pricedBasket(basket(5000), null, { type: 'prioritaria', pickup: true }).typeFee).toBe(0)
    const totals = checkoutTotals([pricedBasket(basket(5000), null, { type: 'prioritaria' })])
    expect(totals.typeFee).toBe(990)
  })

  test('los totales de los pedidos suman el del checkout: cupón en su canasta, créditos y propina en el primero', () => {
    const priced = [
      pricedBasket(basket(4000, 'licores', 'a'), null, { type: 'prioritaria' }),
      pricedBasket(basket(12_000, 'supermercado', 'b'), null),
    ]
    const totals = checkoutTotals(priced, { tip: 1000, coupon: findCoupon('SUPER20'), credits: true })
    const amounts = orderAmounts(priced, totals)
    expect(amounts.reduce((a, b) => a + b, 0)).toBe(totals.total)
    expect(amounts[1]).toBe(12_000 + priced[1].delivery + priced[1].service - totals.couponAmount)
  })
})
