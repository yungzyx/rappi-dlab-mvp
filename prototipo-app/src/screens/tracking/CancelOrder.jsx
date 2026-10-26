import { useEffect, useRef, useState } from 'react'
import Sheet from '../../components/Sheet'
import { useToast } from '../../components/Toast'
import { useAddress } from '../../state/AddressContext'
import { formatPrice } from '../../state/CartContext'
import { useEvents } from '../../state/EventsContext'
import { useOrders } from '../../state/OrdersContext'
import { CANCEL_REASONS, PAYMENTS, cancelFee } from './cancel'

/**
 * «Cancelar pedido» (antes de «En camino»): el motivo, y si tiene solución («Aún tiene solución»: cambiar la dirección o
 * el medio de pago) la ofrece antes de «Continuar con la cancelación». Desde que la tienda empezó el pedido, muestra el
 * costo de cancelar (de ejemplo). Mientras la hoja está abierta, el reloj de la demo espera. Cancelar registra
 * `order_cancelled` (el pedido es su carro y su tienda).
 */
export default function CancelOrder({ order, stage }) {
  const orders = useOrders()
  const events = useEvents()
  const address = useAddress()
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState(null)
  const [rescued, setRescued] = useState(false) // ya se mostró la solución: el siguiente paso es cancelar
  // La etapa y el costo quedan fijos al abrir la hoja (el reloj espera mientras se decide).
  const [frozen, setFrozen] = useState(null)
  const fee = frozen ? cancelFee(order, frozen) : 0
  const rescue = CANCEL_REASONS.find((r) => r.id === reason)?.rescue
  // Si la hoja se va (la pantalla se cierra o el paso cambia en el mismo render en que se abrió), el pedido sigue su
  // reloj: soltar sin pausa de «Cancelar» no hace nada, así que no depende de que el efecto haya visto la hoja abierta.
  const release = useRef(orders.release)
  useEffect(() => {
    release.current = orders.release
  })
  useEffect(() => () => release.current(order.id, 'cancelar'), [order.id])

  const start = () => {
    setFrozen(stage)
    setReason(null)
    setRescued(false)
    setOpen(true)
    // Uno programado todavía no corre: no hay reloj que detener (si no, su franja se correría).
    if (stage !== 'programado') orders.hold(order.id, 'cancelar')
  }

  const close = () => {
    setOpen(false)
    orders.release(order.id, 'cancelar')
  }

  const confirm = () => {
    orders.cancel(order.id, { reason, stage: frozen, fee })
    if (order.cartId) {
      events.track('order_cancelled', {
        surface: 'tracking',
        cart_id: order.cartId,
        ...(order.vertical ? { vertical: order.vertical } : {}),
        value: fee || undefined,
        payload: {
          reason,
          stage: frozen,
          ...(Number.isSafeInteger(order.storeId) ? { store_id: order.storeId } : {}),
          // El costo es un supuesto de la demo, no una tarifa de Rappi.
          ...(fee ? { fee, basis: 'supuesto' } : {}),
        },
      })
      events.flush()
    }
    setOpen(false)
    toast(fee ? `Pedido cancelado · costo de ejemplo ${formatPrice(fee)}` : 'Pedido cancelado sin costo')
  }

  const fix = (change, text) => {
    orders.change(order.id, change)
    toast(text)
    close()
  }

  return (
    <>
      <button type="button" className="tracking-cancel tap" onClick={start}>
        Cancelar pedido
      </button>
      <Sheet open={open} onClose={close} title="Cancelar pedido">
        <div className="tracking-sheet-body">
          {reason === null || (rescue && !rescued) ? null : <CostNote fee={fee} stage={frozen} />}
          {reason === null && (
            <>
              <p>¿Por qué quieres cancelar?</p>
              <div className="tracking-options" role="group" aria-label="Motivo">
                {CANCEL_REASONS.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    className="tracking-option tap"
                    onClick={() => setReason(option.id)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </>
          )}
          {reason !== null && rescue && !rescued && (
            <>
              <p className="tracking-rescue-title">
                <strong>Aún tiene solución</strong>
                <small>No hay necesidad de cancelar: lo cambiamos en tu pedido.</small>
              </p>
              <div className="tracking-options">
                {rescue === 'address'
                  ? address.addresses
                      .filter((a) => a.line !== order.address)
                      .map((a) => (
                        <button
                          key={a.id}
                          type="button"
                          className="tracking-option tap"
                          onClick={() => fix({ address: a.line }, `Listo: tu pedido va a ${a.line}`)}
                        >
                          Entregar en {a.label} · {a.line}
                        </button>
                      ))
                  : PAYMENTS.filter((p) => p !== (order.payment ?? PAYMENTS[0])).map((p) => (
                      <button
                        key={p}
                        type="button"
                        className="tracking-option tap"
                        onClick={() => fix({ payment: p }, `Listo: pagas con ${p} (de ejemplo)`)}
                      >
                        Pagar con {p}
                      </button>
                    ))}
              </div>
              <button type="button" className="tracking-sheet-secondary" onClick={() => setRescued(true)}>
                Continuar con la cancelación
              </button>
            </>
          )}
          {reason !== null && (!rescue || rescued) && (
            <>
              <button type="button" className="tracking-sheet-danger tap" onClick={confirm}>
                {fee ? `Cancelar pedido · ${formatPrice(fee)}` : 'Cancelar pedido'}
              </button>
              <button type="button" className="tracking-sheet-secondary" onClick={close}>
                Mantener mi pedido
              </button>
            </>
          )}
        </div>
      </Sheet>
    </>
  )
}

function CostNote({ fee, stage }) {
  if (!fee)
    return (
      <p className="tracking-cost">
        {stage === 'programado'
          ? 'Tu pedido aún no empieza: cancelarlo no tiene costo.'
          : 'Cancelarlo ahora no tiene costo.'}
      </p>
    )
  return (
    <p className="tracking-cost is-fee">
      La tienda ya empezó tu pedido: cancelarlo cuesta {formatPrice(fee)}.
      <small>Costo de ejemplo de la demo (30 % de los productos), no la política de Rappi.</small>
    </p>
  )
}
