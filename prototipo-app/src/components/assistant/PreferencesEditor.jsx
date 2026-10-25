import { useEffect, useState } from 'react'
import { AGENT_NAME } from '../../agent/name'
import { preferences, savePreferences } from '../../api/agent'

export const PREFERENCES_TITLE = 'Mis preferencias'

const same = (a) => (b) => a.tipo === b.tipo && a.valor === b.valor

/**
 * «Mis preferencias», dentro de una hoja: la dieta, las alergias y las cocinas que se marcan, y las tiendas favoritas
 * que se dijeron por chat (aquí solo se quitan). Se monta al abrir la hoja (lee lo guardado) y guarda con «Guardar»
 * (`PUT /profile/{id}/preferencias`). `onSaved` recibe la lista que quedó.
 */
export default function PreferencesEditor({ onSaved }) {
  const [status, setStatus] = useState('loading') // loading | ready | saving | error | save-error
  const [options, setOptions] = useState([])
  const [chosen, setChosen] = useState([])

  useEffect(() => {
    let live = true
    preferences()
      .then((reply) => {
        if (!live) return
        setOptions(reply.opciones)
        setChosen(reply.preferencias)
        setStatus('ready')
      })
      .catch(() => live && setStatus('error'))
    return () => {
      live = false
    }
  }, [])

  const save = (list) => {
    setStatus('saving')
    savePreferences(list)
      .then((reply) => {
        setChosen(reply.preferencias)
        setStatus('ready')
        onSaved?.(reply.preferencias)
      })
      .catch(() => setStatus('save-error'))
  }

  if (status === 'loading') return <p className="agent-prefs-note">Cargando…</p>
  if (status === 'error')
    return <p className="agent-prefs-note">No pude leer tus preferencias. Inténtalo de nuevo en un rato.</p>

  const toggle = (option) =>
    setChosen((list) => (list.some(same(option)) ? list.filter((p) => !same(option)(p)) : [...list, option]))
  const filters = options.filter((o) => o.tipo === 'dieta' || o.tipo === 'alergia')
  const cuisines = options.filter((o) => o.tipo === 'cocina')
  const stores = chosen.filter((p) => p.tipo === 'tienda')
  const busy = status === 'saving'

  return (
    <div className="agent-prefs">
      <p className="agent-prefs-note">
        La dieta y las alergias solo sacan lo que {AGENT_NAME} te muestra, por el nombre del producto: revisa siempre
        los ingredientes en la tienda. Las favoritas solo cambian el orden.
      </p>
      <Group title="Dieta y alergias" options={filters} chosen={chosen} onToggle={toggle} disabled={busy} />
      <Group title="Cocinas favoritas" options={cuisines} chosen={chosen} onToggle={toggle} disabled={busy} />
      <h3 className="agent-prefs-title">Tiendas favoritas</h3>
      {stores.length ? (
        <div className="agent-prefs-chips">
          {stores.map((store) => (
            <button
              key={store.valor}
              type="button"
              className="assistant-chip agent-prefs-chip is-on"
              aria-label={`Quitar ${store.nombre}`}
              disabled={busy}
              onClick={() => toggle(store)}
            >
              {store.nombre} ×
            </button>
          ))}
        </div>
      ) : (
        <p className="agent-prefs-note">Dímelas en el chat: «mi tienda favorita es…».</p>
      )}
      {status === 'save-error' && <p role="alert">No pude guardar. No cambió nada: inténtalo de nuevo.</p>}
      <button type="button" className="sheet-confirm-primary tap" disabled={busy} onClick={() => save(chosen)}>
        Guardar
      </button>
      <button
        type="button"
        className="sheet-confirm-secondary tap"
        disabled={busy || chosen.length === 0}
        onClick={() => save([])}
      >
        Olvidar mis preferencias
      </button>
    </div>
  )
}

function Group({ title, options, chosen, onToggle, disabled }) {
  return (
    <>
      <h3 className="agent-prefs-title">{title}</h3>
      <div className="agent-prefs-chips">
        {options.map((option) => {
          const on = chosen.some(same(option))
          return (
            <button
              key={`${option.tipo}-${option.valor}`}
              type="button"
              className={`assistant-chip agent-prefs-chip${on ? ' is-on' : ''}`}
              aria-pressed={on}
              disabled={disabled}
              onClick={() => onToggle(option)}
            >
              {option.nombre}
            </button>
          )
        })}
      </div>
    </>
  )
}
