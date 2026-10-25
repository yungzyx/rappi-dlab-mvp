import './offline-notice.css'

/**
 * Aviso dentro de una pantalla de catálogo cuando la API no contesta (`offline` o `timeout`): el resto de la app sigue
 * usable. Un 404 no es esto: cada pantalla dice lo suyo («Esta tienda no está en el catálogo»).
 */
export default function OfflineNotice({ onRetry }) {
  return (
    <div className="offline-notice" role="status">
      <h2>Sin conexión</h2>
      <p>No se pudo cargar esta pantalla.</p>
      <button type="button" className="offline-notice-retry tap" onClick={onRetry}>
        Reintentar
      </button>
    </div>
  )
}
