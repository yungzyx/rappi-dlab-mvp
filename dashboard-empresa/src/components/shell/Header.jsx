import { use } from 'react'
import { loadCatalogDates, SNAPSHOT_INFO } from '../../lib/api.js'
import { formatDate } from '../../lib/format.js'
import { useAnalytics } from '../../lib/useAnalytics.js'
import { Async } from '../Async.jsx'
import { Icon } from '../Icon.jsx'
import { SourceSwitch } from './SourceSwitch.jsx'
import { ThemeToggle } from './ThemeToggle.jsx'

const AS_OF_LABELS = { synthetic: 'último evento simulado', prototype: 'último evento del prototipo' }

function AsOf({ source }) {
  const kpis = useAnalytics('kpis', source)
  return (
    <>
      Datos al <strong className="num">{formatDate(kpis.as_of)}</strong> · {AS_OF_LABELS[source]}
    </>
  )
}

/** De qué fecha son los precios del catálogo; sin fecha (la API no la da o no responde), nada. */
function CatalogDates() {
  const dates = use(loadCatalogDates())
  if (!dates?.desde || !dates?.hasta) return null
  return (
    <span className="masthead-catalog">
      Precios de Rappi Chile{' '}
      {dates.desde !== dates.hasta && (
        <>
          del <strong className="num">{formatDate(dates.desde)}</strong>{' '}
        </>
      )}
      al <strong className="num">{formatDate(dates.hasta)}</strong>
    </span>
  )
}

/**
 * De dónde salen los datos que se ven ahora: el único punto de color de estado de la página. Sale del estado que ya hay
 * (la foto grabada, el prototipo sin la API, los bloques con datos guardados); el detalle va en el aviso de procedencia.
 */
function dataStatus({ source, fallbacks, prototypeOffline }) {
  if (SNAPSHOT_INFO) return { kind: 'snapshot', label: 'Foto grabada' }
  if (source === 'prototype' && prototypeOffline) return { kind: 'offline', label: 'API sin conexión' }
  if (fallbacks.length > 0) return { kind: 'saved', label: 'Datos guardados' }
  return { kind: 'live', label: 'API en vivo' }
}

export function Header({ source, reloadKey, fallbacks, prototypeOffline, onSourceChange, onRefresh }) {
  const status = dataStatus({ source, fallbacks, prototypeOffline })
  return (
    <header className="masthead">
      <div className="brand">
        {/* Marca del panel: tres barras en el naranja-rojo de Rappi (decorativa). */}
        <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
          <rect width="32" height="32" rx="8" />
          <path className="brand-bar" d="M9 22v-5" />
          <path className="brand-bar" d="M16 22V10" />
          <path className="brand-bar" d="M23 22v-8" />
        </svg>
        <div className="brand-text">
          <h1>Panel de negocio</h1>
          <p className="masthead-sub">Prototipo dLab con Rappi, no oficial</p>
        </div>
      </div>
      <div className="masthead-source">
        <SourceSwitch value={source} onChange={onSourceChange} />
      </div>
      <div className="masthead-meta">
        <p className="masthead-asof">
          <span className={`data-status data-status--${status.kind}`}>{status.label}</span>
          <span className="masthead-sep" aria-hidden="true">
            ·
          </span>
          {/* Sin caja de error en el encabezado; la clave la vuelve a intentar al cambiar de fuente o al reintentar. */}
          <span>
            <Async
              key={`${source}-${reloadKey}`}
              fallback={<span>Cargando fecha de corte…</span>}
              errorFallback={<span>fecha de corte: sin conexión</span>}
            >
              <AsOf source={source} />
            </Async>
          </span>
          {SNAPSHOT_INFO ? (
            // En el archivo suelto no hay nada que volver a pedir: se dice de cuándo es la foto.
            <span>
              <span className="masthead-sep" aria-hidden="true">
                ·
              </span>
              foto del <strong className="num">{formatDate(SNAPSHOT_INFO.fecha)}</strong>
            </span>
          ) : (
            <button type="button" className="masthead-refresh" onClick={onRefresh}>
              <Icon name="refresh" />
              Actualizar
            </button>
          )}
        </p>
        <Async key={`catalogo-${reloadKey}`} fallback={null}>
          <CatalogDates />
        </Async>
      </div>
      <div className="masthead-theme">
        <ThemeToggle />
      </div>
    </header>
  )
}
