import { useEffect, useRef, useState } from 'react'
import Sheet from '../../components/Sheet'
import { formatPrice, parsePrice } from '../../state/CartContext'
import { useOrders } from '../../state/OrdersContext'
import { HELP_REASONS, HELP_WINDOW_HOURS, REFUND_METHODS, clockAndDay, helpDeadline } from './help'
import { deliveredItems } from './liveChanges'

/**
 * "Ayuda con este pedido", de demostración y sin dinero real: "Problemas con productos" (cuáles y qué pasó), "¿Dónde
 * reembolsamos tu dinero?" (Créditos o el medio de pago, con su plazo) y el plazo para pedir ayuda. El plazo y los días
 * del reembolso son de ejemplo. Queda en el pedido (`help`). `now`: la hora con que se compara el plazo.
 */
export default function HelpOrder({ order, deliveredAt, now, className = 'tracking-help-button tap' }) {
  const orders = useOrders()
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState('products')
  const [chosen, setChosen] = useState([])
  const [reason, setReason] = useState(null)
  const [method, setMethod] = useState(null)
  const deadline = helpDeadline(deliveredAt)
  const late = now != null && now > deadline
  // Lo que llegó (con el sustituto en vez del agotado, sin lo reembolsado): se reembolsa lo que se cobró.
  const items = deliveredItems(order)
  const amount = chosen.reduce((sum, i) => sum + parsePrice(items[i].price) * (items[i].qty ?? 1), 0)

  // Al cambiar de paso, el foco va al primer control del paso nuevo (o al aviso de "Recibimos tu solicitud").
  const body = useRef(null)
  const shownStep = useRef(step)
  useEffect(() => {
    if (shownStep.current === step) return
    shownStep.current = step
    body.current?.querySelector('[role="status"], button:not([disabled])')?.focus({ preventScroll: true })
  }, [step])

  const start = () => {
    setStep('products')
    setChosen([])
    setReason(null)
    setMethod(null)
    setOpen(true)
  }

  const send = () => {
    orders.addHelp(order.id, { items: chosen, reason, method, amount })
    setStep('done')
  }

  return (
    <>
      <button type="button" className={className} onClick={start}>
        Ayuda con este pedido
      </button>
      <Sheet open={open} onClose={() => setOpen(false)} title="Ayuda con este pedido">
        <div ref={body} className="tracking-sheet-body">
          <p className="tracking-help-window">
            {late
              ? `El plazo para pedir ayuda con este pedido terminó el ${clockAndDay(deadline)}.`
              : `Tienes hasta el ${clockAndDay(deadline)} para pedir ayuda (plazo de ejemplo: ${HELP_WINDOW_HOURS} horas desde la entrega).`}
          </p>
          {!late && step === 'products' && (
            <>
              <p>
                <strong>Problemas con productos</strong> · ¿Cuáles?
              </p>
              <div className="tracking-options" role="group" aria-label="Productos con problemas">
                {items.map((item, i) => {
                  const on = chosen.includes(i)
                  return (
                    <button
                      key={`${i}-${item.name}`}
                      type="button"
                      aria-pressed={on}
                      className={on ? 'tracking-option is-on tap' : 'tracking-option tap'}
                      onClick={() => setChosen(on ? chosen.filter((c) => c !== i) : [...chosen, i])}
                    >
                      {item.qty} × {item.name}
                    </button>
                  )
                })}
              </div>
              <p>¿Qué pasó?</p>
              <div className="tracking-reason-chips">
                {HELP_REASONS.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    aria-pressed={reason === option.id}
                    className={reason === option.id ? 'tracking-reason is-on tap' : 'tracking-reason tap'}
                    onClick={() => setReason(option.id)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <button
                type="button"
                className="tracking-reason-send tap"
                disabled={chosen.length === 0 || !reason}
                onClick={() => setStep('refund')}
              >
                Siguiente
              </button>
            </>
          )}
          {!late && step === 'refund' && (
            <>
              <p>
                <strong>¿Dónde reembolsamos tu dinero?</strong> · {formatPrice(amount)}
              </p>
              <div className="tracking-options" role="radiogroup" aria-label="Dónde va el reembolso">
                {REFUND_METHODS.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    role="radio"
                    aria-checked={method === option.id}
                    className={method === option.id ? 'tracking-option is-on tap' : 'tracking-option tap'}
                    onClick={() => setMethod(option.id)}
                  >
                    <strong>{option.label}</strong>
                    <small>{option.when} (plazo de ejemplo)</small>
                  </button>
                ))}
              </div>
              <button type="button" className="tracking-reason-send tap" disabled={!method} onClick={send}>
                Enviar solicitud
              </button>
            </>
          )}
          {step === 'done' && (
            <p className="tracking-help-done" role="status" tabIndex={-1}>
              Recibimos tu solicitud: {formatPrice(amount)} en{' '}
              {REFUND_METHODS.find((m) => m.id === method)?.label.toLowerCase()},{' '}
              {REFUND_METHODS.find((m) => m.id === method)?.when.toLowerCase()}.
            </p>
          )}
          <small className="tracking-demo-note">Demostración: no se mueve dinero ni se revisa con fotos.</small>
        </div>
      </Sheet>
    </>
  )
}
