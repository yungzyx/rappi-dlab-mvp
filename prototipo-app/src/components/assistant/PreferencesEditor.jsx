import { useEffect, useState } from 'react'
import { AGENT_NAME } from '../../agent/name'
import { preferences, savePreferences } from '../../api/agent'

export const PREFERENCES_TITLE = 'Mis preferencias'

const same = (a) => (b) => a.tipo === b.tipo && a.valor === b.valor

/**
 * "Mis preferencias", dentro de una hoja: la dieta, las alergias, las cocinas y las tiendas favoritas se eligen entre
 * opciones, sin escribir nada (las tiendas son aquellas donde la persona ya pidió, más las que ya tenía marcadas). Se
 * monta al abrir la hoja (lee lo guardado) y guarda con "Guardar" (`PUT /profile/{id}/preferencias`). `onSaved` recibe
 * la lista que quedó.
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
  // Las marcadas primero (también una que ya no sale entre las de sus pedidos), y después las demás de sus pedidos.
  const marked = chosen.filter((p) => p.tipo === 'tienda')
  const stores = [...marked, ...options.filter((o) => o.tipo === 'tienda' && !marked.some(same(o)))]
  const busy = status === 'saving'

  return (
    <div className="agent-prefs">
      <p className="agent-prefs-note">
        La dieta y las alergias solo sacan lo que {AGENT_NAME} te muestra, por el nombre del producto: revisa siempre
        los ingredientes en la tienda. Las favoritas solo cambian el orden.
      </p>
      <Group title="Dieta y alergias" options={filters} chosen={chosen} onToggle={toggle} disabled={busy} />
      <Group title="Cocinas favoritas" options={cuisines} chosen={chosen} onToggle={toggle} disabled={busy} />
      {stores.length ? (
        <Group title="Tiendas favoritas" options={stores} chosen={chosen} onToggle={toggle} disabled={busy} />
      ) : (
        <>
          <h3 className="agent-prefs-title">Tiendas favoritas</h3>
          <p className="agent-prefs-note">Cuando pidas en una tienda, aparece aquí para marcarla.</p>
        </>
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
