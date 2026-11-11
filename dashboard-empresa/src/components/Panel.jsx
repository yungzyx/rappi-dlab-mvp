import { Help } from './Help.jsx'
import { ProvenanceBadge } from './ProvenanceBadge.jsx'

/**
 * Un bloque con borde: cabecera con su título, su ayuda (`help`), acciones y procedencia (si los hay); cuerpo (con
 * `meta`, una línea que lo sitúa, primero; las tablas van a sangre) y pie opcional. `helpLabel`: el nombre de la ayuda
 * cuando el título no es solo texto.
 */
export function Panel({ title, help, helpLabel, meta, source, actions, foot, className, children }) {
  return (
    <div className={className ? `panel ${className}` : 'panel'}>
      {title && (
        <div className="panel-head">
          <h3 className="subhead">{title}</h3>
          {help && <Help label={typeof title === 'string' ? title : helpLabel}>{help}</Help>}
          {(actions || source) && (
            <div className="panel-head-end">
              {actions}
              {source && <ProvenanceBadge kind={source} />}
            </div>
          )}
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
