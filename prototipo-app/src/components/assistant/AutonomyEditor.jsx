import { useEffect, useState } from 'react'
import { AGENT_NAME } from '../../agent/name'
import { autonomy, saveAutonomy, turnOffAutonomy } from '../../api/autonomy'
import { useRovingGroup } from '../../hooks/useRovingGroup'
import { formatPrice } from '../../state/CartContext'

const CAP_STEP = 1000

/**
 * "Pedir por mí", dentro de una hoja: "Revisar antes de pedir" (por defecto) o "Pedir por mí" en las tiendas que elija
 * (de las que ya pidió) y con un tope por pedido. Volver a "Revisar antes de pedir" lo apaga en un toque (`DELETE`);
 * "Guardar" lo enciende o lo cambia (`PUT /profile/{id}/autonomia`). `onTurnedOff` deshace lo que esté en su ventana.
 */
export default function AutonomyEditor({ onSaved, onTurnedOff }) {
  const [status, setStatus] = useState('loading') // loading | ready | saving | error | save-error
  const [setting, setSetting] = useState(null)
  const [mode, setMode] = useState('revisar')
  const [stores, setStores] = useState([])
  const [cap, setCap] = useState(null)

  const show = (reply) => {
    setSetting(reply)
    setMode(reply.mode)
    setStores(reply.stores)
    setCap(reply.cap ?? reply.options.suggested)
    setStatus('ready')
  }

  useEffect(() => {
    let live = true
    autonomy()
      .then((reply) => live && show(reply))
      .catch(() => live && setStatus('error'))
    return () => {
      live = false
    }
  }, [])

  if (status === 'loading') return <p className="agent-prefs-note">Cargando…</p>
  if (status === 'error')
    return <p className="agent-prefs-note">No pude leer cómo pido por ti. Inténtalo en un rato.</p>

  const busy = status === 'saving'
  const { options } = setting
  const run = (call, after) => {
    setStatus('saving')
    call()
      .then((reply) => {
        show(reply)
        after?.(reply)
      })
      .catch(() => setStatus('save-error'))
  }
  // "Revisar antes de pedir" apaga al tiro lo que estaba encendido; si no estaba, solo se elige.
  const review = () => {
    setMode('revisar')
    if (setting.mode === 'pedir') run(turnOffAutonomy, () => onTurnedOff?.())
  }
  const toggle = (id) => setStores((list) => (list.includes(id) ? list.filter((s) => s !== id) : [...list, id]))
  const validCap = Number.isInteger(cap) && cap >= options.min && cap <= options.max
  const chosen = stores.filter((id) => options.stores.some((store) => store.id === id))

  return (
    <div className="agent-prefs agent-autonomy">
      <AutonomyModes
        mode={mode}
        busy={busy}
        noStores={options.stores.length === 0}
        onReview={review}
        onAsk={() => setMode('pedir')}
      />

      {options.stores.length === 0 && (
        <p className="agent-prefs-note">Cuando pidas en una tienda, podrás elegirla aquí para que pida por ti.</p>
      )}

      {mode === 'pedir' && (
        <>
          <h3 className="agent-prefs-title">Tiendas donde pido por ti</h3>
          <div className="agent-prefs-chips">
            {options.stores.map((store) => {
              const on = stores.includes(store.id)
              return (
                <button
                  key={store.id}
                  type="button"
                  className={`assistant-chip agent-prefs-chip${on ? ' is-on' : ''}`}
                  aria-pressed={on}
                  disabled={busy}
                  onClick={() => toggle(store.id)}
                >
                  {store.name}
                </button>
              )
            })}
          </div>
          <label className="agent-autonomy-cap">
            <span>Tope por pedido (productos, envío y tarifa)</span>
            <input
              type="number"
              inputMode="numeric"
              min={options.min}
              max={options.max}
              step={CAP_STEP}
              value={cap ?? ''}
              disabled={busy}
              onChange={(e) => setCap(e.target.value === '' ? null : Math.round(Number(e.target.value)))}
            />
          </label>
          {!validCap && (
            <p className="agent-prefs-note">
              Entre {formatPrice(options.min)} y {formatPrice(options.max)}.
            </p>
          )}
          <p className="agent-prefs-note">
            Solo pido lo de siempre: tu último pedido en esa tienda, con el precio de hoy. Nunca alcohol, +18, farmacia,
            bebé ni salud, nunca sobre tu tope ni en una tienda cerrada, y te doy unos segundos para deshacerlo (si
            cierras el buscador antes, no lo pido). Si algo no calza, te lo dejo para que lo revises. Cuando te toque
            repetir, toca "Pide lo de siempre por mí" en la Home.
          </p>
        </>
      )}

      {status === 'save-error' && <p role="alert">No pude guardar. No cambió nada: inténtalo de nuevo.</p>}
      {mode === 'pedir' && (
        <button
          type="button"
          className="sheet-confirm-primary tap"
          disabled={busy || chosen.length === 0 || !validCap}
          onClick={() => run(() => saveAutonomy({ stores: chosen, cap }), onSaved)}
        >
          Guardar
        </button>
      )}
    </div>
  )
}

/** "Revisar antes de pedir" o "Pedir por mí": un grupo que se recorre con las flechas. */
function AutonomyModes({ mode, busy, noStores, onReview, onAsk }) {
  const choose = [onReview, onAsk]
  const roving = useRovingGroup(
    2,
    mode === 'pedir' ? 1 : 0,
    (i) => choose[i](),
    (i) => busy || (i === 1 && noStores),
  )
  return (
    <div className="agent-autonomy-modes" role="radiogroup" aria-label="Cómo pide por ti" onKeyDown={roving.onKeyDown}>
      <button
        type="button"
        role="radio"
        aria-checked={mode === 'revisar'}
        className={`agent-autonomy-mode tap${mode === 'revisar' ? ' is-on' : ''}`}
        disabled={busy}
        onClick={onReview}
        {...roving.itemProps(0)}
      >
        <strong>Revisar antes de pedir</strong>
        <small>Te muestro el resumen y pagas en el checkout de siempre.</small>
      </button>
      <button
        type="button"
        role="radio"
        aria-checked={mode === 'pedir'}
        className={`agent-autonomy-mode tap${mode === 'pedir' ? ' is-on' : ''}`}
        disabled={busy || noStores}
        onClick={onAsk}
        {...roving.itemProps(1)}
      >
        <strong>Pedir por mí</strong>
        <small>En las tiendas que elijas, pido lo de siempre sin preguntarte, hasta tu tope.</small>
      </button>
    </div>
  )
}
