import { useEffect, useRef, useState } from 'react'
import BackButton from '../../components/BackButton'
import Sheet from '../../components/Sheet'
import { health, sendOrder } from '../../api/client'
import { basketsOf, buildOrders, cartEventFields, orderVertical, trackOrder } from '../../api/orders'
import { userId } from '../../api/user'
import { useToast } from '../../components/Toast'
import { ChevronRight } from '../../components/Icons'
import { CardIcon, PinIcon } from '../../components/LineIcons'
import { useAddress } from '../../state/AddressContext'
import { sessionId, useEvents } from '../../state/EventsContext'
import { formatPrice, useCart } from '../../state/CartContext'
import { usePro } from '../../state/pro'
import { markCoupon, spendCredits, useWallet } from '../../state/credits'
import CheckoutBasket from './CheckoutBasket'
import CheckoutBenefits from './CheckoutBenefits'
import CheckoutDelivery from './CheckoutDelivery'
import CheckoutSuggestion from './CheckoutSuggestion'
import { useOrders } from '../../state/OrdersContext'
import { useDemo } from '../../state/DemoContext'
import { DEFAULT_TIP, TIPS, checkoutTotals, deliveryType, orderShares, pricedBasket } from './pricing'
import { ageConfirmed, confirmAge, hasAgeRestricted, needsPrescription } from './restrictions'
import { anyClosed, slotsFor } from './schedule'
import { DEFAULT_SUBSTITUTION, SUBSTITUTION_VERTICALS } from '../tracking/liveChanges'
import { slotLabel } from '../tracking/progress'
import { UNDO_MS } from './undo'
import { useStoreTerms } from './useStoreTerms'
import './checkout.css'

const MODES = ['Envío', 'Retiro']

// El producto como se guarda en el pedido: sin de dónde salió esta vez (su lugar y si fue una sugerencia), que en
// "Pídelo de nuevo" es otro.
const reorderable = ({ placement: _placement, fromSuggestion: _from, suggestionOrigin: _origin, ...product }) => product

/**
 * Checkout (funcionalidad agregada), una canasta por tienda: cada tienda es un pedido. El medio de pago es solo un texto
 * de ejemplo: no se ingresan datos. Los montos que no trae el catálogo, los créditos y los cupones son de ejemplo.
 */
export default function CheckoutScreen({ back, push }) {
  const cart = useCart()
  const address = useAddress()
  const orders = useOrders()
  const toast = useToast()
  const events = useEvents()
  const demo = useDemo()
  const isPro = usePro()
  const [mode, setMode] = useState(MODES[0])
  const [tip, setTip] = useState(DEFAULT_TIP)
  const [useCredits, setUseCredits] = useState(true)
  const [coupon, setCoupon] = useState(null)
  const [prescription, setPrescription] = useState(false)
  const [asking, setAsking] = useState(null) // la hoja de edad: 'ask' o 'refused'
  const [placing, setPlacing] = useState(false) // la ventana de "Deshacer pedido"
  const [type, setType] = useState('basica') // el tipo de entrega (pricing.js: DELIVERY_TYPES, de ejemplo)
  const [when, setWhen] = useState('now') // 'now' o el inicio de la franja programada (ms)
  const pickup = mode === 'Retiro'

  const baskets = basketsOf(cart.items)
  const termsOf = useStoreTerms(baskets)
  // Con una tienda cerrada según lo publicado, solo se programa; las franjas sirven a todas las tiendas de la compra.
  const storeHours = baskets.map((basket) => termsOf(basket))
  const closed = anyClosed(storeHours)
  const [now] = useState(() => Date.now())
  const slots = slotsFor(storeHours, now)
  // Con la tienda cerrada, "Ahora" no se puede: queda elegida la primera franja (se cambia por otra), en Envío y Retiro.
  const slot =
    when !== 'now' && slots.some((s) => s.from === when) ? when : closed && slots.length ? slots[0].from : null
  const scheduled = slot !== null
  // Programado o retiro: sin tipo de entrega (la franja es la entrega básica). Un retiro también se programa.
  const chosenType = pickup ? null : scheduled ? 'basica' : type
  const priced = baskets.map((basket) =>
    pricedBasket(basket, termsOf(basket), { isPro, pickup, type: chosenType ?? 'basica' }),
  )
  // El saldo de créditos de ejemplo (state/credits.js): los del banner hasta que vencen, más lo que sumaron la ayuda,
  // la garantía de Turbo o una cancelación.
  const wallet = useWallet()
  const minutesLeft = useMinutesLeft(wallet.expiresAt)
  const expiring = minutesLeft > 0 ? wallet.welcome : 0
  const available = expiring + wallet.extra
  const totals = checkoutTotals(priced, { tip, pickup, coupon, credits: useCredits ? available : 0 })
  const stores = baskets.map((basket) => basket.store).filter(Boolean)
  const prescriptionMissing = priced.some(needsPrescription) && !prescription
  const mustSchedule = closed && !scheduled
  const blocked = totals.short.length > 0 || prescriptionMissing || mustSchedule

  // Abrir el checkout es iniciar el pago (quien vuelve atrás sin pagar es el abandono de esa etapa). Uno por carro
  // y vertical, porque el embudo del panel se mide por sesión y vertical; el ref evita contarlo dos veces en StrictMode.
  const started = useRef(new Set())
  const verticals = [...new Set(buildOrders(cart.items, {}).map((order) => order.vertical))].join(',')
  useEffect(() => {
    for (const vertical of verticals ? verticals.split(',') : []) {
      const key = `${cart.id}|${vertical}`
      if (started.current.has(key)) continue
      started.current.add(key)
      events.track('checkout_start', { cart_id: cart.id, vertical, surface: 'checkout' })
    }
  }, [cart.id, verticals, events])

  // Pasada la ventana de "Deshacer pedido": recién ahí sale cada pedido (uno por tienda) y se guardan los de la demo.
  const commit = () => {
    // En el Súper y Turbo cada línea va con qué hacer si se agota (sin elegir, "Si no contesto, elijan por mí").
    const substitutionOf = (line) =>
      SUBSTITUTION_VERTICALS.has(orderVertical(line.product)) ? (line.substitution ?? DEFAULT_SUBSTITUTION) : undefined
    const items = cart.items.map((line) => ({ ...line, substitution: substitutionOf(line) }))
    const pending = buildOrders(items, {
      userId: userId(),
      sessionId: sessionId(),
      cartId: cart.id,
      mode: demo.isFinal ? 'propuesta' : 'actual',
      pro: isPro,
      scheduledFor: slot,
      deliveryType: chosenType,
    })
    // Registro para el panel (si la API está arriba). No bloquea el pedido de la demo. Antes salen los eventos en cola
    // (y se esperan los lotes en camino): el servidor les pone la hora al recibirlos, y checkout_start va primero.
    // Todo el camino cuenta como pedido en vuelo: "Olvidar" lo espera antes de borrar el perfil.
    trackOrder(
      events
        .flush()
        .then(() => events.settled())
        .then(() => health())
        .then((online) => online && Promise.all(pending.map((order) => sendOrder(order).catch(() => {})))),
    )
    // Un pedido por tienda, como los que recibe la API: cada uno con su total (orderShares suma el del checkout) y lo
    // que usó de créditos y cupón, que vuelven si se cancela.
    const shares = orderShares(priced, totals)
    const [id] = orders.placeMany(
      priced.map((basket, i) => ({
        stores: basket.store ? [basket.store] : [],
        storeId: basket.storeId,
        vertical: basket.vertical,
        cartId: cart.id,
        items: basket.lines
          .map((line) => ({ line, substitution: substitutionOf(line) }))
          .map(({ line: { product, qty }, substitution }) => ({
            name: product.name,
            img: product.img,
            price: product.price,
            qty,
            // Con ellos el agente arma el próximo pedido al entregar (oferta `proximo_pedido`).
            entityType: product.entityType,
            entityId: product.entityId,
            // Los pasos del seguimiento dependen de la vertical; "Pídelo de nuevo" vuelve a armar el carro con el producto.
            vertical: product.vertical,
            product: reorderable(product),
            ...(substitution ? { substitution } : {}),
          })),
        total: shares[i].total,
        ...(shares[i].credits > 0 ? { credits: shares[i].credits } : {}),
        ...(i === 0 && totals.tip > 0 ? { tip: totals.tip } : {}),
        ...(shares[i].coupon > 0 ? { coupon: { code: coupon.code, amount: shares[i].coupon } } : {}),
        pickup,
        address: address.selected.line,
        payment: 'Visa •••• 4242',
        ...(slot ? { scheduledFor: slot } : {}),
        ...(chosenType ? { deliveryType: chosenType, etaShift: deliveryType(chosenType).etaShift } : {}),
      })),
    )
    // Lo usado sale del saldo de la demo: los créditos se gastan y el cupón queda usado.
    spendCredits(totals.credits)
    if (totals.couponAmount > 0) markCoupon(coupon.code)
    cart.clear()
    // El seguimiento (del primero) reemplaza al checkout en el historial: "volver" no regresa a un carrito vacío.
    push('tracking', { orderId: id }, { swap: true })
  }

  // "Hacer pedido": con un producto +18 pregunta la edad una vez por sesión; después abre la ventana de deshacer.
  const placeOrder = () => {
    if (blocked) return
    if (hasAgeRestricted(cart.items) && !ageConfirmed()) {
      setAsking('ask')
      return
    }
    setPlacing(true)
  }

  const removeAgeRestricted = () => {
    for (const { product, qty } of cart.items.filter((line) => line.product.ageRestricted)) {
      events.track('cart_remove', cartEventFields(product, cart.id, { qty }))
      for (let n = 0; n < qty; n++) cart.remove(product)
    }
    setAsking(null)
  }

  if (cart.count === 0) {
    return (
      <div className="screen checkout">
        <CheckoutHeader back={back} />
        <p className="checkout-empty">Tu carro está vacío.</p>
        <button type="button" className="checkout-continue tap" onClick={back}>
          Seguir comprando
        </button>
      </div>
    )
  }

  return (
    <>
      <div className="screen checkout">
        <CheckoutHeader back={back} />

        <div className="checkout-modes" role="radiogroup" aria-label="Cómo lo recibes">
          {MODES.map((option) => (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={option === mode}
              className={option === mode ? 'checkout-mode is-active' : 'checkout-mode'}
              onClick={() => setMode(option)}
            >
              {option}
            </button>
          ))}
        </div>

        <button type="button" className="checkout-card tap" onClick={address.openSheet}>
          <PinIcon size={24} />
          <span>
            <strong>{pickup ? 'Retiro en tienda' : address.selected.label}</strong>
            <small>{pickup ? stores.join(', ') : address.selected.line}</small>
          </span>
          <ChevronRight size={18} />
        </button>
        <p className="checkout-eta">
          {scheduled
            ? `${pickup ? 'Retiro programado' : 'Programado'} para ${slotLabel(slot, now)}`
            : closed
              ? 'Programa tu pedido'
              : pickup
                ? 'Listo en 15–20 min'
                : `Llega en ${deliveryType(type).eta}`}
        </p>
        <CheckoutDelivery
          type={type}
          onType={setType}
          when={slot ?? 'now'}
          onWhen={setWhen}
          slots={slots}
          closed={closed}
          baskets={baskets.length}
          pickup={pickup}
          published={storeHours.every((terms) => terms?.spans && (terms.spans.hoy.length || terms.spans.manana.length))}
        />

        <h2 className="checkout-title">Tu pedido</h2>
        {baskets.length > 1 && (
          <p className="checkout-split">
            Tu compra será dividida en {baskets.length} pedidos separados, uno por tienda.
          </p>
        )}
        {priced.map((basket) => (
          <CheckoutBasket
            key={basket.key}
            basket={basket}
            isPro={isPro}
            pickup={pickup}
            prescription={prescription}
            onPrescription={setPrescription}
            substitutionOf={cart.substitutionOf}
            onSubstitution={cart.setSubstitution}
          />
        ))}
        <CheckoutSuggestion />

        {!pickup && (
          <>
            <h2 className="checkout-title">Propina para tu Rappitendero</h2>
            <div className="checkout-tips">
              {TIPS.map((amount) => (
                <button
                  key={amount}
                  type="button"
                  className={amount === tip ? 'checkout-tip is-active' : 'checkout-tip'}
                  aria-pressed={amount === tip}
                  onClick={() => setTip(amount)}
                >
                  {amount === 0 ? 'Sin propina' : formatPrice(amount)}
                </button>
              ))}
            </div>
          </>
        )}

        <h2 className="checkout-title">Medio de pago</h2>
        <button type="button" className="checkout-card tap" onClick={() => toast('Medio de pago de ejemplo')}>
          <CardIcon size={24} />
          <span>
            <strong>Visa •••• 4242</strong>
            <small>Tarjeta de ejemplo</small>
          </span>
          <span className="checkout-change">Cambiar</span>
        </button>

        <CheckoutBenefits
          totals={totals}
          isPro={isPro}
          credits={useCredits}
          onCredits={setUseCredits}
          available={available}
          expiring={expiring}
          minutesLeft={minutesLeft}
          usedCoupons={wallet.coupons}
          coupon={coupon}
          onCoupon={setCoupon}
        />

        <dl className="checkout-summary">
          <SummaryRow label="Subtotal" value={formatPrice(totals.subtotal)} />
          {!pickup && (
            <SummaryRow
              label={baskets.length > 1 ? `Envío (${baskets.length} pedidos)` : 'Envío'}
              value={totals.delivery === 0 ? 'Gratis con Pro' : formatPrice(totals.delivery)}
              accent={totals.delivery === 0}
            />
          )}
          {totals.typeFee !== 0 && (
            <SummaryRow
              label={`Entrega ${deliveryType(chosenType).label.toLowerCase()} (de ejemplo)`}
              value={totals.typeFee > 0 ? formatPrice(totals.typeFee) : `−${formatPrice(-totals.typeFee)}`}
              accent={totals.typeFee < 0}
            />
          )}
          <SummaryRow
            label={isPro ? 'Tarifa de servicio (con Pro)' : 'Tarifa de servicio'}
            value={formatPrice(totals.service)}
          />
          {!pickup && <SummaryRow label="Propina" value={formatPrice(totals.tip)} />}
          {totals.couponAmount > 0 && (
            <SummaryRow label={`Cupón ${coupon.code}`} value={`−${formatPrice(totals.couponAmount)}`} accent />
          )}
          {totals.credits > 0 && <SummaryRow label="Créditos" value={`−${formatPrice(totals.credits)}`} accent />}
          <SummaryRow label="Total" value={formatPrice(totals.total)} total />
        </dl>
        <p className="checkout-note">
          Lo marcado "de ejemplo" son supuestos de la demo (envíos, mínimos y tarifas que el catálogo no trae, tipos de
          entrega, créditos, cupones y el beneficio Pro), no tarifas ni políticas de Rappi.
        </p>
      </div>

      {/* Fuera del contenedor con scroll para que quede fijo abajo */}
      <div className="checkout-footer">
        {blocked && (
          <p className="checkout-blocked" role="status">
            {totals.short.length > 0
              ? `Te faltan ${formatPrice(totals.short[0].missing)} para hacer el pedido en ${totals.short[0].store || 'la tienda'}`
              : prescriptionMissing
                ? 'Marca que tienes la receta médica para seguir'
                : 'La tienda está cerrada: elige una franja para programar tu pedido'}
          </p>
        )}
        <button type="button" className="checkout-place tap" onClick={placeOrder} disabled={blocked}>
          Hacer pedido · {formatPrice(totals.total)}
        </button>
      </div>

      <AgeSheet
        state={asking}
        onYes={() => {
          confirmAge()
          setAsking(null)
          setPlacing(true)
        }}
        onNo={() => setAsking('refused')}
        onRemove={removeAgeRestricted}
        onClose={() => setAsking(null)}
      />
      <UndoSheet
        open={placing}
        orders={baskets.length}
        scheduled={scheduled ? slotLabel(slot, now) : null}
        onDone={commit}
        onUndo={() => setPlacing(false)}
      />
    </>
  )
}

/** "¿Eres mayor de edad?": una vez por sesión, sin documento. Si dice que no, puede quitar los productos +18. */
function AgeSheet({ state, onYes, onNo, onRemove, onClose }) {
  return (
    <Sheet open={state !== null} onClose={onClose} title="¿Eres mayor de edad?">
      {state === 'refused' ? (
        <div className="checkout-sheet">
          <p>Sin confirmar tu edad no podemos enviar productos para mayores de 18.</p>
          <button type="button" className="checkout-sheet-primary tap" onClick={onRemove}>
            Quitar los productos +18
          </button>
          <button type="button" className="checkout-sheet-secondary" onClick={onClose}>
            Volver
          </button>
        </div>
      ) : (
        <div className="checkout-sheet">
          <p>
            Tu pedido tiene productos para mayores de 18. Te lo preguntamos una vez en esta sesión; no pedimos
            documentos.
          </p>
          <button type="button" className="checkout-sheet-primary tap" onClick={onYes}>
            Sí, soy mayor de edad
          </button>
          <button type="button" className="checkout-sheet-secondary" onClick={onNo}>
            No
          </button>
        </div>
      )}
    </Sheet>
  )
}

/**
 * "Pedido creado" con "Deshacer pedido" unos segundos (`UNDO_MS`). Al cerrarse la ventana sale el pedido (`onDone`);
 * deshacer (o cerrar la hoja) lo anula antes de enviar nada y vuelve al checkout con el carro intacto.
 */
function UndoSheet({ open, orders, scheduled, onDone, onUndo }) {
  const done = useRef(onDone)
  useEffect(() => {
    done.current = onDone
  })
  useEffect(() => {
    if (!open) return undefined
    const timer = setTimeout(() => done.current(), UNDO_MS)
    return () => clearTimeout(timer)
  }, [open])
  return (
    <Sheet open={open} onClose={onUndo} title="¡Pedido creado!">
      <div className="checkout-sheet">
        <p>
          {orders > 1 ? `Estamos enviando tus ${orders} pedidos.` : 'Estamos enviando tu pedido.'}
          {scheduled && ` Programado para ${scheduled}.`} ¿Quieres modificar algo? Tienes unos segundos.
        </p>
        <span className="checkout-undo-bar" style={{ animationDuration: `${UNDO_MS}ms` }} />
        <button type="button" className="checkout-sheet-secondary is-strong" onClick={onUndo}>
          Deshacer pedido
        </button>
      </div>
    </Sheet>
  )
}

/** Los minutos que faltan para `deadline` (los créditos del banner), al minuto. */
function useMinutesLeft(deadline) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(timer)
  }, [])
  return Math.max(0, Math.ceil((deadline - now) / 60_000))
}

function CheckoutHeader({ back }) {
  return (
    <header className="checkout-header">
      <BackButton className="round-button" onClick={back} />
      <h1>Tu pedido</h1>
    </header>
  )
}

function SummaryRow({ label, value, accent = false, total = false }) {
  return (
    <div className={total ? 'checkout-row is-total' : 'checkout-row'}>
      <dt>{label}</dt>
      <dd className={accent ? 'is-accent' : undefined}>{value}</dd>
    </div>
  )
}
