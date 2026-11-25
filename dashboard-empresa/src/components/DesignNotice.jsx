import { Icon } from './Icon.jsx'

/**
 * El aviso de un bloque diseñado que todavía no tiene datos: dice que sus filas son de ejemplo (no salen de la base) y
 * qué ruta de la API falta para llenarlo. Va siempre arriba del bloque: una fila de ejemplo nunca se ve sin él.
 */
export function DesignNotice({ route, children }) {
  return (
    <p className="design-notice" role="note">
      <Icon name="flask" />
      <span>
        <strong>Diseño, aún sin datos.</strong> Las filas de abajo son de ejemplo: muestran cómo se leería este bloque,
        no salen de la base ni de los datos simulados. {children} Falta la ruta <span className="mono">{route}</span> en
        la API.
      </span>
    </p>
  )
}
