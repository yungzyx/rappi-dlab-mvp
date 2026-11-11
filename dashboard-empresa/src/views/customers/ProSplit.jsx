import { ChartPanel } from '../../components/ChartTableSwitch.jsx'
import { DataTable } from '../../components/DataTable.jsx'
import { Panel } from '../../components/Panel.jsx'
import { EmptyState } from '../../components/States.jsx'
import { BarRows } from '../../components/charts/BarRows.jsx'
import { formatNumber, formatPct } from '../../lib/format.js'
import { useAnalytics } from '../../lib/useAnalytics.js'

const GROUP_LABELS = { pro: 'Pro', sin_pro: 'Sin Pro' }
const groupLabel = (row) => GROUP_LABELS[row.grupo] ?? row.grupo

const COLUMNS = [
  { key: 'grupo', header: 'Grupo', primary: true, render: groupLabel },
  { key: 'personas', header: 'Personas con pedidos', numeric: true, render: (row) => formatNumber(row.personas) },
  { key: 'pedidos', header: 'Pedidos (30 días)', numeric: true, render: (row) => formatNumber(row.pedidos_30d) },
  {
    key: 'porPersona',
    header: 'Pedidos por persona (30 días)',
    numeric: true,
    render: (row) => formatNumber(row.pedidos_por_persona_30d, 2),
  },
  { key: 'recompra', header: 'Volvió a comprar', numeric: true, render: (row) => formatPct(row.recompra_pct) },
  {
    key: 'multi',
    header: 'Multi-vertical (60 días)',
    numeric: true,
    render: (row) => formatPct(row.multi_vertical_pct),
  },
  {
    key: 'retencion',
    header: 'Retención (días 61 a 120)',
    numeric: true,
    render: (row) => formatPct(row.retencion_pct),
  },
]

// Las cuatro comparaciones, cada una con su escala desde 0.
const FACETS = [
  {
    key: 'pedidos_por_persona_30d',
    title: 'Pedidos por persona (30 días)',
    format: (value) => formatNumber(value, 2),
  },
  { key: 'recompra_pct', title: 'Volvió a comprar', format: formatPct },
  { key: 'multi_vertical_pct', title: '2 o más verticales (60 días)', format: formatPct },
  { key: 'retencion_pct', title: 'Retención (días 61 a 120)', format: formatPct },
]
const ONE_SERIES = [{ key: 'valor', label: 'Valor' }]

function Facets({ groups }) {
  return (
    <div className="facets" aria-hidden="true">
      {FACETS.map((facet) => (
        <div key={facet.key} className="facet">
          <h4 className="facet-title">{facet.title}</h4>
          <BarRows
            series={ONE_SERIES}
            rows={groups.map((row) => ({
              key: row.grupo,
              label: groupLabel(row),
              values: [row[facet.key] ?? null],
              texts: [facet.format(row[facet.key])],
            }))}
          />
        </div>
      ))}
    </div>
  )
}

/**
 * Pro y sin Pro (/analytics/pro, `app_users.pro`): pedidos, recompra, multi-vertical y retención de cada grupo, en 4
 * facetas y en su tabla. Un grupo con menos personas que el mínimo no llega (privacidad). En los simulados la marca Pro
 * es un supuesto del generador que sigue a cuántas verticales combina cada persona: lo dice la salvedad de la sección.
 */
export function ProSplit({ source }) {
  const split = useAnalytics('pro', source)
  const missing =
    split.sin_dato > 0 ? ` ${formatNumber(split.sin_dato)} personas con pedidos no tienen la marca y no entran.` : ''
  const title = 'Pro frente a sin Pro'
  const help = (
    <p>
      Rappi Pro une las verticales con envío gratis. Volvió a comprar: hizo una segunda compra (un carro dividido en dos
      tiendas es una compra). 2 o más verticales: pidió en dos verticales o más, entre quienes pidieron en los últimos
      60 días. Retención: solo de quien tiene 120 días de historia; se omite con menos de{' '}
      {formatNumber(split.minimo_personas)} personas.{missing}
    </p>
  )
  if (!split.grupos.length) {
    return (
      <Panel title={title} help={help}>
        <EmptyState title="Todavía no hay grupos que mostrar">
          Cada grupo necesita al menos {formatNumber(split.minimo_personas)} personas con pedidos.{missing}
        </EmptyState>
      </Panel>
    )
  }
  const count = (group) => formatNumber(split.grupos.find((row) => row.grupo === group)?.personas)
  return (
    <ChartPanel
      title={title}
      help={help}
      name="Pro y sin Pro"
      meta={`Pro: ${count('pro')} personas con pedidos · Sin Pro: ${count('sin_pro')}`}
      chart={<Facets groups={split.grupos} />}
      table={<DataTable caption="Pro y sin Pro" columns={COLUMNS} rows={split.grupos} rowKey={(row) => row.grupo} />}
    />
  )
}
