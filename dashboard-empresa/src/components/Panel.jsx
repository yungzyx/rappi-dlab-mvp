import { csvFileName, downloadCsv, tablesToCsv } from '../lib/csv.js'
import { Help } from './Help.jsx'
import { Icon } from './Icon.jsx'
import { ProvenanceBadge } from './ProvenanceBadge.jsx'

/** Descarga las tablas del panel donde está el botón, tal como se ven (todas, si tiene más de una). */
function exportTable(event, name) {
  const tables = [...(event.currentTarget.closest('.panel')?.querySelectorAll('table') ?? [])]
  if (tables.length) downloadCsv(csvFileName(name), tablesToCsv(tables))
}

/**
 * Un bloque con borde: cabecera con su título, su ayuda (`help`), acciones y procedencia (si los hay); cuerpo (con
 * `meta`, una línea que lo sitúa, primero; las tablas van a sangre) y pie opcional. `helpLabel`: el nombre de la ayuda
 * cuando el título no es solo texto. Si el panel tiene una tabla, su cabecera ofrece bajarla en CSV (el botón está
 * siempre y el CSS lo muestra solo con una tabla dentro); `noExport` lo quita (un bloque con filas de ejemplo).
 */
export function Panel({ title, help, helpLabel, meta, source, actions, foot, className, noExport, children }) {
  const name = typeof title === 'string' ? title : helpLabel
  return (
    <div className={className ? `panel ${className}` : 'panel'}>
      {title && (
        <div className="panel-head">
          <h3 className="subhead">{title}</h3>
          {help && <Help label={name}>{help}</Help>}
          <div className="panel-head-end">
            {actions}
            {!noExport && (
              <button
                type="button"
                className="text-button csv-button"
                aria-label={`Descargar CSV de ${name ?? 'la tabla'}`}
                onClick={(event) => exportTable(event, name ?? 'tabla')}
              >
                <Icon name="download" />
                CSV
              </button>
            )}
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
