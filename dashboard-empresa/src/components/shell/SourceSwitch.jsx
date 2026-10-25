import { SOURCES } from '../../lib/api.js'
import { SOURCE_LABELS } from '../../lib/labels.js'

/** Elige de dónde vienen usuarios y eventos. Radios nativos: las flechas cambian la opción. */
export function SourceSwitch({ value, onChange }) {
  return (
    <fieldset className="segmented">
      <legend className="segmented-legend">Usuarios y eventos</legend>
      <div className="segmented-options">
        {SOURCES.map((source) => (
          <label key={source} className="segmented-option">
            <input
              type="radio"
              name="fuente"
              value={source}
              checked={value === source}
              onChange={() => onChange(source)}
            />
            <span>{SOURCE_LABELS[source]}</span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}
