import { Caveat } from '../../components/Caveat.jsx'
import { ChartPanel } from '../../components/ChartTableSwitch.jsx'
import { DataTable } from '../../components/DataTable.jsx'
import { Meter } from '../../components/Meter.jsx'
import { Panel } from '../../components/Panel.jsx'
import { EmptyState } from '../../components/States.jsx'
import { BarRows } from '../../components/charts/BarRows.jsx'
import { formatNumber, formatPct } from '../../lib/format.js'

// Los pasos del embudo por sesión (/analytics/embudo-sesion): cada uno exige los anteriores.
export const FUNNEL_STEPS = [
  { key: 'sesiones', label: 'Sesiones' },
  { key: 'vieron', label: 'Vieron una lista' },
  { key: 'tocaron', label: 'Tocaron algo' },
  { key: 'agregaron', label: 'Agregaron al carro' },
  { key: 'pidieron', label: 'Pidieron' },
]
const MODE_LABELS = { propuesta: 'Prototipo con Mochi', actual: 'Rappi hoy' }
const ONE_SERIES = [{ key: 'valor', label: 'Valor' }]

const CTR_TITLE = 'CTR por posición'
const FUNNEL_TITLE = 'Embudo por sesión'

/**
 * CTR por posición (/analytics/ctr-posicion, capa.v_ctr_posicion): de lo que quedó a la vista en cada lugar de las
 * listas, cuánto se tocó desde ahí, en barras y en su tabla. Solo el prototipo con Mochi.
 */
export function CtrByPosition({ data }) {
  const { posiciones } = data
  if (!posiciones.length) {
    return (
      <Panel title={CTR_TITLE}>
        <EmptyState title="Todavía no hay impresiones" inline>
          Aparecen cuando las listas de la app (Home, búsqueda, tiendas, Turbo, Mochi) quedan a la vista.
        </EmptyState>
      </Panel>
    )
  }
  const top = Math.max(...posiciones.map((row) => row.ctr ?? 0))
  const columns = [
    { key: 'posicion', header: 'Lugar', primary: true, render: (row) => `${row.posicion + 1}.º` },
    { key: 'impresiones', header: 'Vistos', numeric: true, render: (row) => formatNumber(row.impresiones) },
    { key: 'clics', header: 'Tocados', numeric: true, render: (row) => formatNumber(row.clics) },
    {
      key: 'ctr',
      header: 'CTR',
      numeric: true,
      render: (row) => (
        <span className="cell-bar">
          <Meter value={row.ctr} max={top} />
          {formatPct(row.ctr * 100)}
        </span>
      ),
    },
  ]
  return (
    <ChartPanel
      title={CTR_TITLE}
      className="bars-panel"
      chart={
        <BarRows
          series={ONE_SERIES}
          max={top * 100}
          rows={posiciones.map((row) => ({
            key: row.posicion,
            label: `${row.posicion + 1}.º`,
            values: [row.ctr === null ? null : row.ctr * 100],
            texts: [formatPct(row.ctr * 100)],
            note: `${formatNumber(row.clics)} de ${formatNumber(row.impresiones)}`,
          }))}
        />
      }
      table={
        <DataTable
          caption="CTR por posición en las listas"
          columns={columns}
          rows={posiciones}
          rowKey={(row) => row.posicion}
        />
      }
      foot={
        <Caveat>
          El primer lugar se toca más también por estar primero: hay que descontar ese sesgo antes de comparar órdenes.
        </Caveat>
      }
    />
  )
}

const stepsOf = (row) => FUNNEL_STEPS.map((step) => ({ ...step, n: row[step.key] }))
const shareOf = (row, n) => (row.sesiones ? (n * 100) / row.sesiones : null)

function FunnelBars({ row, title }) {
  return (
    <div className="funnel-mode">
      {title && <h4 className="subhead">{title}</h4>}
      <BarRows
        series={ONE_SERIES}
        max={row.sesiones}
        rows={stepsOf(row).map((step) => ({
          key: step.key,
          label: step.label,
          values: [step.n],
          texts: [`${formatNumber(step.n)} · ${formatPct(shareOf(row, step.n))}`],
        }))}
      />
    </div>
  )
}

function FunnelTable({ row, title }) {
  const columns = [
    { key: 'label', header: 'Paso', primary: true },
    { key: 'n', header: 'Sesiones', numeric: true, render: (step) => formatNumber(step.n) },
    {
      key: 'pct',
      header: 'De todas',
      numeric: true,
      render: (step) => (
        <span className="cell-bar">
          <Meter value={step.n} max={row.sesiones} />
          {formatPct(shareOf(row, step.n))}
        </span>
      ),
    },
  ]
  return (
    <DataTable
      caption={`${FUNNEL_TITLE}${title ? `: ${title}` : ''}`}
      columns={columns}
      rows={stepsOf(row)}
      rowKey={(step) => step.key}
    />
  )
}

/** El embudo por sesión (/analytics/embudo-sesion, capa.v_embudo_sesion): barras y tabla, un bloque por modo de la app. */
export function SessionFunnel({ rows }) {
  if (!rows.length) {
    return (
      <Panel title={FUNNEL_TITLE}>
        <EmptyState title="Todavía no hay sesiones" inline>
          Aparecen con el primer uso de la app.
        </EmptyState>
      </Panel>
    )
  }
  const titleOf = (row) => (rows.length > 1 ? (MODE_LABELS[row.modo] ?? row.modo) : null)
  return (
    <ChartPanel
      title={FUNNEL_TITLE}
      className="bars-panel"
      chart={
        <div className="funnel">
          {rows.map((row) => (
            <FunnelBars key={row.modo} row={row} title={titleOf(row)} />
          ))}
        </div>
      }
      table={rows.map((row) => (
        <FunnelTable key={row.modo} row={row} title={titleOf(row)} />
      ))}
    />
  )
}
