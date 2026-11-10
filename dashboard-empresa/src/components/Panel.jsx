/**
 * Un bloque con borde: cabecera con su título (si lo hay), cuerpo (las tablas van a sangre) y pie opcional para las
 * notas que lo explican.
 */
export function Panel({ title, foot, className, children }) {
  return (
    <div className={className ? `panel ${className}` : 'panel'}>
      {title && (
        <div className="panel-head">
          <h3 className="subhead">{title}</h3>
        </div>
      )}
      <div className="panel-body">{children}</div>
      {foot && <div className="panel-foot">{foot}</div>}
    </div>
  )
}
