import { isDemoActive } from '../lib/api.js'
import {
  csvFileName,
  downloadCsv,
  pageStatus,
  provenanceOf,
  provenanceRows,
  rowsToCsv,
  tablesToCsv,
} from '../lib/csv.js'
import { Help } from './Help.jsx'
import { Icon } from './Icon.jsx'
import { ProvenanceBadge } from './ProvenanceBadge.jsx'

/**
 * Descarga las tablas del panel donde está el botón, tal como se ven (todas, si tiene más de una). Arriba, de dónde
 * salen: la fuente (la insignia del bloque o de su sección) y, con datos de personas, la línea de estado de la página.
 */
function exportTable(event, name) {
  const button = event.currentTarget
  const tables = [...(button.closest('.panel')?.querySelectorAll('table') ?? [])]
  if (!tables.length) return
  const kind = provenanceOf(button)
  const provenance = rowsToCsv(provenanceRows(kind, { status: pageStatus(), demo: isDemoActive() }))
  const csv = tablesToCsv(tables)
  downloadCsv(csvFileName(name, kind), provenance ? `${provenance}\r\n\r\n${csv}` : csv)
}

/**
 * Un bloque con borde: cabecera con su título, su ayuda (`help`), acciones y procedencia (si los hay); cuerpo (con
 * `meta`, una línea que lo sitúa, primero; las tablas van a sangre) y pie opcional. `helpLabel`: el nombre de la ayuda
 * cuando el título no es solo texto. Si el panel tiene una tabla, su cabecera ofrece bajarla en CSV (el botón está
 * siempre y el CSS lo muestra solo con una tabla dentro).
 */
export function Panel({ title, help, helpLabel, meta, source, actions, foot, className, children }) {
  const name = typeof title === 'string' ? title : helpLabel
  return (
    <div className={className ? `panel ${className}` : 'panel'}>
      {title && (
        <div className="panel-head">
          <h3 className="subhead">{title}</h3>
          {help && <Help label={name}>{help}</Help>}
          <div className="panel-head-end">
            {actions}
            <button
              type="button"
              className="text-button csv-button"
              aria-label={`Descargar CSV de ${name ?? 'la tabla'}`}
              onClick={(event) => exportTable(event, name ?? 'tabla')}
            >
              <Icon name="download" />
              CSV
            </button>
            {source && <ProvenanceBadge kind={source} />}
          </div>
        </div>
      )}
      <div className="panel-body">
        {meta && <p className="panel-meta">{meta}</p>}
        {children}
      </div>
      {foot && <div className="panel-foot">{foot}</div>}
    </div>
  )
}
