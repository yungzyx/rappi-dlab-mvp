import { use } from 'react'
import { loadCatalogDates, SNAPSHOT_INFO } from '../../lib/api.js'
import { formatDate } from '../../lib/format.js'
import { useAnalytics } from '../../lib/useAnalytics.js'
import { Async } from '../Async.jsx'
import { Icon } from '../Icon.jsx'
import { SubNav } from './SubNav.jsx'

const Sep = () => (
  <span className="page-meta-sep" aria-hidden="true">
    ·
  </span>
)

function AsOf({ source }) {
  const kpis = useAnalytics('kpis', source)
  return (
    <>
      Datos al <strong className="num">{formatDate(kpis.as_of)}</strong>
    </>
  )
}

/** De qué fecha son los precios del catálogo; sin fecha (la API no la da o no responde), nada. */
function CatalogDates() {
  const dates = use(loadCatalogDates())
  if (!dates?.desde || !dates?.hasta) return null
  return (
    <span className="page-meta-catalog">
      <Sep />
      <span className="masthead-catalog">
        Precios de Rappi Chile{' '}
        {dates.desde !== dates.hasta && (
          <>
            del <strong className="num">{formatDate(dates.desde)}</strong>{' '}
          </>
        )}
        al <strong className="num">{formatDate(dates.hasta)}</strong>
      </span>
    </span>
  )
}

/**
 * De dónde salen los datos que se ven ahora: el único punto de color de estado de la página. Sale del estado que ya hay
 * (la foto grabada, el prototipo sin la API, los bloques con datos guardados); el detalle va en los avisos de arriba.
 */
function dataStatus({ source, fallbacks, prototypeOffline }) {
  if (SNAPSHOT_INFO) return { kind: 'snapshot', label: 'Foto grabada' }
  if (source === 'prototype' && prototypeOffline) return { kind: 'offline', label: 'API sin conexión' }
  if (fallbacks.length > 0) return { kind: 'saved', label: 'Datos guardados' }
  return { kind: 'live', label: 'API en vivo' }
}

/**
 * Cabecera de la página: el nombre de la vista, de cuándo son los datos (y los precios del catálogo), "Actualizar" y,
 * si la vista tiene más de una, sus subpestañas.
 */
export function PageHeader({ title, source, reloadKey, fallbacks, prototypeOffline, onRefresh, tabs, tab, onTab }) {
  const status = dataStatus({ source, fallbacks, prototypeOffline })
  return (
    <div className="page-head">
      <div className="page-head-row">
        <div className="page-head-text">
          <h1 className="page-title">{title}</h1>
          <p className="page-meta">
            <span className={`data-status data-status--${status.kind}`}>{status.label}</span>
            <Sep />
            {/* Sin caja de error en la cabecera; la clave la vuelve a intentar al cambiar de fuente o al reintentar. */}
            <span>
              <Async
                key={`${source}-${reloadKey}`}
                fallback={<span>Cargando fecha de corte…</span>}
                errorFallback={<span>fecha de corte: sin conexión</span>}
              >
                <AsOf source={source} />
              </Async>
            </span>
            {SNAPSHOT_INFO && (
              // En el archivo suelto no hay nada que volver a pedir: se dice de cuándo es la foto.
              <span>
                <Sep />
                foto del <strong className="num">{formatDate(SNAPSHOT_INFO.fecha)}</strong>
              </span>
            )}
            <Async key={`catalogo-${reloadKey}`} fallback={null}>
              <CatalogDates />
            </Async>
          </p>
        </div>
        {!SNAPSHOT_INFO && (
          <div className="page-actions">
            <button type="button" className="text-button" onClick={onRefresh}>
              <Icon name="refresh" />
              Actualizar
            </button>
          </div>
        )}
      </div>
      {tabs.length > 1 && <SubNav tabs={tabs} active={tab} onSelect={onTab} />}
    </div>
  )
}
