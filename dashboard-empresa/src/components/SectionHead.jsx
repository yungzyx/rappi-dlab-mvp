import { Help } from './Help.jsx'
import { ProvenanceBadge } from './ProvenanceBadge.jsx'

/**
 * Fila de título de una sección: h2 con id (recibe el foco al llegar desde un enlace), su ayuda, una meta corta y el
 * rótulo de procedencia. `children`: las salvedades de la sección (<Caveat>), cada una en su línea, debajo.
 */
export function SectionHead({ id, title, help, meta, source, children }) {
  return (
    <div className="section-head">
      <h2 id={id} tabIndex={-1}>
        {title}
      </h2>
      {help && <Help label={title}>{help}</Help>}
      {meta && <p className="section-meta">{meta}</p>}
      {source && (
        <span className="section-source">
          <ProvenanceBadge kind={source} />
        </span>
      )}
      {children}
    </div>
  )
}
