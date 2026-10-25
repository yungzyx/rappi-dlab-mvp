import { useState } from 'react'
import { useToast } from '../../components/Toast'
import BackButton from '../../components/BackButton'
import { useAddress } from '../../state/AddressContext'
import './favor.css'

const USES = [
  {
    id: 'envio',
    emoji: '📦',
    title: 'Envíos de un punto a otro',
    text: 'Unas llaves olvidadas, un documento, un almuerzo o un paquete chico, dentro de la ciudad.',
  },
  {
    id: 'compra',
    emoji: '🛍️',
    title: 'Compras en cualquier tienda',
    text: 'Aunque no esté en Rappi: te manda fotos, revisa la talla y el precio, y te lo lleva.',
  },
  {
    id: 'tramite',
    emoji: '📝',
    title: 'Trámites rápidos',
    text: 'Retirar un paquete en una sucursal de correos o algo ya pagado en un comercio.',
  },
]

/** RappiFavor: un Rappitendero hace un favor de corta distancia. En Rappi hoy aparece no disponible; aquí, simulado. */
export default function FavorScreen({ back }) {
  const toast = useToast()
  const address = useAddress()
  const [useId, setUseId] = useState(null)
  const [task, setTask] = useState('')
  const [pickup, setPickup] = useState('')
  const [missing, setMissing] = useState(false)
  const chosen = USES.find((use) => use.id === useId)

  const submit = (e) => {
    e.preventDefault()
    if (!task.trim()) return setMissing(true)
    setMissing(false)
    toast('Un Rappitendero va en camino 🛵')
  }

  return (
    <div className="screen favor">
      <header className="favor-header">
        <BackButton className="favor-back" onClick={back} />
        <h1>RappiFavor</h1>
      </header>

      <h2 className="favor-title">¿Qué necesitas? 🛵</h2>
      <p className="favor-text">Un Rappitendero lo hace por ti, de un punto a otro de la ciudad.</p>

      <ul className="favor-uses">
        {USES.map((use) => (
          <li key={use.id}>
            <button
              type="button"
              className={use.id === useId ? 'favor-use is-active tap' : 'favor-use tap'}
              aria-pressed={use.id === useId}
              onClick={() => setUseId(use.id)}
            >
              <span className="favor-use-emoji" aria-hidden="true">
                {use.emoji}
              </span>
              <span>
                <strong>{use.title}</strong>
                <small>{use.text}</small>
              </span>
            </button>
          </li>
        ))}
      </ul>

      {chosen && (
        <form className="favor-form" onSubmit={submit}>
          <label>
            <span>Qué hay que hacer</span>
            <textarea value={task} onChange={(e) => setTask(e.target.value)} rows={3} placeholder={chosen.text} />
          </label>
          {missing && <p className="favor-error">Cuéntanos qué hay que hacer</p>}
          <label>
            <span>Retiro en</span>
            <input value={pickup} onChange={(e) => setPickup(e.target.value)} placeholder="Dirección o tienda" />
          </label>
          <p className="favor-dropoff">
            Entrega en <strong>{address.selected.line}</strong>
          </p>
          <button type="submit" className="favor-submit tap">
            Pedir RappiFavor
          </button>
        </form>
      )}
    </div>
  )
}
