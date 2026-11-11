import { API_URL, PROTOTYPE_OFFLINE_MESSAGE, SNAPSHOT_INFO } from '../../lib/api.js'
import { formatDate } from '../../lib/format.js'
import { describeFallbacks, describeOrigins } from '../../lib/labels.js'
import { Icon } from '../Icon.jsx'

const MESSAGES = {
  synthetic: (
    <>
      <strong>Usuarios y eventos SIMULADOS:</strong> muestran la mecánica del panel, no evidencia. Son reales la tabla
      de combinaciones que compartió Rappi y los ítems del catálogo (muestra pública de rappi.cl).
    </>
  ),
  prototype: (
    <>
      <strong>Usuarios y eventos del PROTOTIPO:</strong> pruebas hechas en la app de demostración, no clientes reales;
      con tan pocos datos varias métricas quedan vacías. Son reales la tabla de combinaciones que compartió Rappi y los
      ítems del catálogo (muestra pública de rappi.cl).
    </>
  ),
}

/** Aviso permanente de procedencia, fijo arriba del contenido (nunca se oculta). */
export function ProvenanceBanner({ source }) {
  return (
    <div className="provenance" role="note" aria-label="Procedencia de los datos">
      <div className={`provenance-row provenance-row--${source}`}>
        <div className="provenance-inner">
          <Icon name="flask" />
          <p>{MESSAGES[source]}</p>
        </div>
      </div>
    </div>
  )
}

/**
 * Los avisos de conexión, bajo la franja (no fijos): la foto sin conexión y, si alguna consulta cayó a los datos
 * guardados, cuál y por qué. Con el prototipo sin la API (`prototypeOffline`), el único aviso de error de la página,
 * con su Reintentar.
 */
export function ConnectionNotices({ source, fallbacks, prototypeOffline, onRetry }) {
  const offline = source === 'prototype' && prototypeOffline
  if (!SNAPSHOT_INFO && !offline && fallbacks.length === 0) return null
  return (
    <div className="notices">
      {SNAPSHOT_INFO && (
        <div className="provenance-row provenance-row--offline">
          <div className="provenance-inner">
            <Icon name="offline" />
            <p>
              <strong>Foto sin conexión:</strong> respuestas de la API de rappi-ia grabadas el{' '}
              {formatDate(SNAPSHOT_INFO.fecha)} desde una copia de la base ({SNAPSHOT_INFO.base}). No se actualizan; la
              procedencia de cada bloque sigue valiendo.
            </p>
          </div>
        </div>
      )}
      {offline && (
        <div className="provenance-row provenance-row--offline" role="alert">
          <div className="provenance-inner">
            <Icon name="offline" />
            <p>
              <strong>Sin conexión con la API:</strong> {PROTOTYPE_OFFLINE_MESSAGE}
            </p>
            <button type="button" className="link-button" onClick={onRetry}>
              Reintentar
            </button>
          </div>
        </div>
      )}
      {fallbacks.length > 0 && (
        <div className="provenance-row provenance-row--offline" role="status">
          <div className="provenance-inner">
            <Icon name="offline" />
            <p>
              <strong>Modo sin conexión (datos guardados):</strong> la API de rappi-ia en{' '}
              <span className="mono">{API_URL}</span> falló en {describeFallbacks(fallbacks)}. Esos bloques muestran
              respuestas guardadas en el repo ({describeOrigins(fallbacks)}).
            </p>
            <button type="button" className="link-button" onClick={onRetry}>
              Reintentar
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
