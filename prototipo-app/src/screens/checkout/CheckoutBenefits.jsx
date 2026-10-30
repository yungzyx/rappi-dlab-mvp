import { useState } from 'react'
import { formatPrice } from '../../state/CartContext'
import { COUPONS, CREDITS, PRO, findCoupon } from './pricing'

/**
 * Beneficios del checkout, todos de ejemplo: el saldo de créditos de la demo (solo en productos; los del banner de la
 * Home vencen, `expiring`, y lo que sumaron la ayuda o una cancelación no), un cupón activo a la vez (cada uno se usa
 * una vez, `usedCoupons`) y lo que ahorra (o ahorraría) Rappi Pro. `totals` es lo que da `checkoutTotals`.
 */
export default function CheckoutBenefits({
  totals,
  isPro,
  credits,
  onCredits,
  available,
  expiring,
  coupon,
  onCoupon,
  minutesLeft,
  usedCoupons = [],
}) {
  return (
    <>
      <h2 className="checkout-title">Beneficios</h2>
      <div className="checkout-benefits">
        <label className="checkout-benefit">
          <span>
            <strong>
              {available > 0 ? `${formatPrice(available)} en créditos de ejemplo` : 'Créditos de ejemplo'}
            </strong>
            <small>
              {available === 0
                ? 'Ya los usaste o vencieron: no te quedan créditos'
                : `${CREDITS.rule}.${expiring > 0 ? ` ${formatPrice(expiring)} vencen en ${formatMinutes(minutesLeft)}.` : ''}`}
            </small>
          </span>
          <input
            type="checkbox"
            role="switch"
            aria-label="Usar créditos"
            checked={credits && available > 0}
            disabled={available === 0}
            onChange={(e) => onCredits(e.target.checked)}
          />
        </label>
        <CouponField coupon={coupon} result={totals.coupon} onCoupon={onCoupon} usedCoupons={usedCoupons} />
      </div>
      <ProRow isPro={isPro} saving={totals.proSaving} />
    </>
  )
}

const formatMinutes = (minutes) => {
  const hours = Math.floor(minutes / 60)
  return hours > 0 ? `${hours} h ${minutes % 60} min` : `${minutes} min`
}

/** "Ingresar cupón": un cupón de ejemplo a la vez (otro reemplaza al anterior), con su motivo si no aplica. */
function CouponField({ coupon, result, onCoupon, usedCoupons }) {
  const [code, setCode] = useState('')
  const [error, setError] = useState(null)
  const [replaced, setReplaced] = useState(null)

  const apply = (value) => {
    const found = findCoupon(value)
    if (!found) {
      setError('Ese cupón no existe en la demo')
      return
    }
    if (usedCoupons.includes(found.code)) {
      setError('Ya usaste este cupón de ejemplo: se usa una vez')
      return
    }
    setError(null)
    setReplaced(coupon && coupon.code !== found.code ? coupon.code : null)
    setCode('')
    onCoupon(found)
  }

  return (
    <div className="checkout-coupon">
      {coupon ? (
        <div className="checkout-coupon-active">
          <span>
            <strong>
              {coupon.code} · {coupon.title}
            </strong>
            <small>{result?.error ?? `${coupon.detail}. Cupón de ejemplo.`}</small>
            {replaced && <small>Reemplazó a {replaced}: se usa un cupón a la vez.</small>}
          </span>
          <button type="button" className="checkout-change" onClick={() => onCoupon(null)}>
            Quitar
          </button>
        </div>
      ) : null}
      <form
        className="checkout-coupon-form"
        onSubmit={(e) => {
          e.preventDefault()
          apply(code)
        }}
      >
        <input
          type="text"
          aria-label="Código del cupón"
          placeholder="Ingresar cupón"
          autoCapitalize="characters"
          value={code}
          onChange={(e) => setCode(e.target.value)}
        />
        <button type="submit" disabled={!code.trim()}>
          Aplicar
        </button>
      </form>
      {error && <p className="checkout-coupon-error">{error}</p>}
      <p className="checkout-coupon-examples">
        Cupones de ejemplo:{' '}
        {COUPONS.map((example) => (
          <button key={example.code} type="button" className="checkout-coupon-chip" onClick={() => apply(example.code)}>
            {example.code}
          </button>
        ))}
      </p>
    </div>
  )
}

/** Pro: lo que ahorra en este pedido, o lo que ahorraría quien no es Pro. Montos con supuestos rotulados. */
function ProRow({ isPro, saving }) {
  if (saving <= 0) return null
  return (
    <p className={isPro ? 'checkout-pro is-member' : 'checkout-pro'}>
      <strong>{isPro ? `Con Pro ahorras ${formatPrice(saving)}` : `Ahorra ${formatPrice(saving)} con Pro`}</strong>
      <small>
        Envío gratis en pedidos sobre {formatPrice(PRO.freeDeliveryMin)} y {Math.round(PRO.serviceDiscount * 100)} %
        menos en la tarifa de servicio (montos de ejemplo).
        {!isPro && ` Plan desde ${formatPrice(PRO.monthlyPrice)} al mes.`}
      </small>
    </p>
  )
}
