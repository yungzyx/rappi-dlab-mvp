import { AGENT_NAME } from '../../lib/agentName.js'
import { SNAPSHOT_INFO } from '../../lib/api.js'
import { formatDate } from '../../lib/format.js'
import { useAnalytics } from '../../lib/useAnalytics.js'
import { Async } from '../Async.jsx'
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

export function Header({ source, onSourceChange, onRefresh }) {
  return (
    <header className="masthead">
      <div className="container masthead-inner">
        <div className="brand">
          {/* Marca del panel: tres barras que crecen, en el naranja-rojo de Rappi (decorativa). */}
          <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="9" />
            <path className="brand-bar" d="M9 22v-5" />
            <path className="brand-bar" d="M16 22V10" />
            <path className="brand-bar" d="M23 22v-8" />
          </svg>
          <div>
            <p className="eyebrow">Prototipo independiente, no afiliado a Rappi</p>
            <h1>Panel de negocio</h1>
          </div>
        </div>
        <div className="masthead-controls">
          <SourceSwitch value={source} onChange={onSourceChange} />
          <ThemeToggle />
        </div>
        <p className="masthead-lede">
          Para la <strong>gerencia</strong> y <strong>RappiAds</strong>: venta cruzada, retención y lo que ofrece{' '}
          {AGENT_NAME}.
        </p>
        <div className="masthead-meta">
          <Async fallback={<span>Cargando fecha de corte…</span>}>
            <AsOf source={source} />
          </Async>
          {' · '}
          {SNAPSHOT_INFO ? (
            // En el archivo suelto no hay nada que volver a pedir: se dice de cuándo es la foto.
            <span>
              foto del <strong className="num">{formatDate(SNAPSHOT_INFO.fecha)}</strong>
            </span>
          ) : (
            <button type="button" className="text-button" onClick={onRefresh}>
              Actualizar
            </button>
          )}
        </div>
      </div>
    </header>
  )
}
