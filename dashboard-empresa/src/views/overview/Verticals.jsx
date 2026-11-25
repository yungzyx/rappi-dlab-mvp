import { DataTable } from '../../components/DataTable.jsx'
import { Delta } from '../../components/Delta.jsx'
import { Panel } from '../../components/Panel.jsx'
import { EmptyState } from '../../components/States.jsx'
import { formatNumber, formatPct, formatSignedPct } from '../../lib/format.js'
import { verticalLabel } from '../../lib/labels.js'
import { useAnalytics } from '../../lib/useAnalytics.js'

/** Una cifra de 30 días con su cambio contra los 30 anteriores debajo (si lo hay). */
const withChange = (value, change) => (
  <span className="cell-stack">
    {formatNumber(value)}
    {change !== null && (
      <span className="cell-sub">
        <Delta value={change} format={formatSignedPct} goodWhen="up" />
      </span>
    )}
  </span>
)

const columnsFor = ({ dias: days, dias_combinacion: mixDays }) => [
  { key: 'vertical', header: 'Vertical', primary: true, render: (row) => verticalLabel(row.vertical) },
  {
    key: 'personas_30d',
    header: `Personas con pedido (${days} días)`,
    numeric: true,
    render: (row) => withChange(row.personas_30d, row.cambio_personas_pct),
  },
  {
    key: 'pedidos_30d',
    header: `Pedidos (${days} días)`,
    numeric: true,
    render: (row) => withChange(row.pedidos_30d, row.cambio_pedidos_pct),
  },
  {
    key: 'abandono_carrito_pct',
    header: 'Abandono de carrito',
    numeric: true,
    render: (row) => formatPct(row.abandono_carrito_pct),
  },
  {
    key: 'sin_resultado_pct',
    header: 'Búsquedas sin resultado',
    numeric: true,
    render: (row) => formatPct(row.sin_resultado_pct),
  },
  {
    key: 'combinan_pct',
    header: `También piden en otra (${mixDays} días)`,
    numeric: true,
    render: (row) => formatPct(row.combinan_pct),
  },
]

/** "2 verticales no llegan a 20 personas y no se muestran." (o nada, si todas llegan). */
function hiddenNote({ bajo_el_minimo: hidden, minimo_personas: minimum }) {
  if (!hidden) return null
  const subject = hidden === 1 ? '1 vertical no llega' : `${hidden} verticales no llegan`
  return `${subject} a ${minimum} personas y no ${hidden === 1 ? 'se muestra' : 'se muestran'}.`
}

/**
 * La ficha por vertical, de /analytics/verticales: las verticales lado a lado, de más a menos personas, para ver cuál
 * pierde carros, dónde falta surtido y cuál ya trae gente que combina. Una tasa con pocos casos viene vacía, y una
 * vertical con pocas personas no viene (privacidad): se dice cuántas son.
 */
export function Verticals({ source }) {
  const data = useAnalytics('verticales', source)
  const hidden = hiddenNote(data)
  if (!data.verticales.length) {
    return (
      <EmptyState title="Ninguna vertical llega al mínimo">
        Una vertical se muestra desde {data.minimo_personas} personas con pedido en {data.dias_combinacion} días.
      </EmptyState>
    )
  }
  return (
    <Panel
      title="Verticales lado a lado"
      meta={`El cambio compara con los ${data.dias} días anteriores.`}
      foot={
        <>
          <p className="block-note">
            El abandono es de los carros que tuvieron algo de esa vertical. Una tasa aparece desde {data.minimo_casos}{' '}
            casos; los pedidos cancelados no cuentan.
          </p>
          {hidden && <p className="block-note">{hidden}</p>}
        </>
      }
    >
      <DataTable
        caption="Ficha por vertical"
        columns={columnsFor(data)}
        rows={data.verticales}
        rowKey={(row) => row.vertical}
      />
    </Panel>
  )
}
