import { useState } from 'react'
import { ChartTableSwitch } from '../../components/ChartTableSwitch.jsx'
import { DataTable } from '../../components/DataTable.jsx'
import { Delta } from '../../components/Delta.jsx'
import { Meter } from '../../components/Meter.jsx'
import { LineChart } from '../../components/charts/LineChart.jsx'
import { Sparkline } from '../../components/charts/Sparkline.jsx'
import { formatNumber, formatPct, formatShortDate } from '../../lib/format.js'
import { useAnalyticsMany } from '../../lib/useAnalytics.js'
import { COMPARE_WEEKS, isPartialWeek, WEEKLY_SERIES, weeklySeries } from './weekly.js'

const SPARK_WEEKS = 12
// Con menos semanas la línea dibuja el arranque del MVP, no una tendencia.
const MIN_SPARK_WEEKS = 5
// Con menos semanas completas con dato no hay línea que dibujar: se muestra la tabla.
const MIN_CHART_WEEKS = 2
const series = (key) => WEEKLY_SERIES.find((item) => item.key === key)

/**
 * Una celda de la tira: siempre 4 filas en el mismo orden (rótulo, cifra, cambio o unidad, y una ranura para la
 * tendencia, una barra o una nota), así todas las celdas alinean sus filas aunque alguna quede vacía.
 */
function Tile({ title, value, line, slot }) {
  return (
    <article className="pulse-tile" aria-label={title}>
      <h3>{title}</h3>
      <p className="pulse-value">{value}</p>
      <div className="pulse-line">{line}</div>
      <div className="pulse-slot">{slot}</div>
    </article>
  )
}

/** Un indicador semanal: la última semana completa, su cambio contra 4 semanas antes y la tendencia de 12 semanas. */
function WeeklyTile({ rows, item, asOf }) {
  const { points, latest, change, formatChange } = weeklySeries(rows, item, asOf)
  const complete = points.filter((point) => !point.partial).slice(-SPARK_WEEKS)
  let line
  if (!latest) line = <p className="pulse-context">Sin una semana completa.</p>
  else if (change === null) line = <p className="pulse-context">Sin la semana de hace {COMPARE_WEEKS} para comparar.</p>
  else line = <Delta value={change} format={formatChange} goodWhen={item.goodWhen} />
  return (
    <Tile
      title={item.title}
      value={latest ? item.format(latest.value) : '—'}
      line={line}
      slot={
        complete.length >= MIN_SPARK_WEEKS && (
          <Sparkline
            values={complete.map((point) => point.value)}
            label={`${item.title}, últimas ${complete.length} semanas completas`}
          />
        )
      }
    />
  )
}

function WeeklyTable({ rows, asOf }) {
  const columns = [
    {
      key: 'semana',
      header: 'Semana del',
      primary: true,
      render: (row) => `${formatShortDate(row.semana)}${isPartialWeek(row.semana, asOf) ? ' (parcial)' : ''}`,
    },
    ...WEEKLY_SERIES.map((item) => ({
      key: item.key,
      header: item.title,
      numeric: true,
      render: (row) => item.format(row[item.key]),
    })),
  ]
  return <DataTable caption="Serie semanal" columns={columns} rows={rows} rowKey={(row) => row.semana} />
}

/**
 * "Cómo va": la tira de 5 indicadores. 3 con su tendencia semanal y 2 de 30 y 60 días con lo que los explica; la serie
 * completa va en la tarjeta "Serie semanal" (WeeklyChart).
 */
export function Pulse({ source }) {
  const [rows, kpis] = useAnalyticsMany(['weekly', 'kpis'], source)
  return (
    <div className="pulse">
      <WeeklyTile rows={rows} item={series('usuarios_activos')} asOf={kpis.as_of} />
      <WeeklyTile rows={rows} item={series('pedidos')} asOf={kpis.as_of} />
      <WeeklyTile rows={rows} item={series('abandono_carrito_pct')} asOf={kpis.as_of} />
      <Tile
        title="Frecuencia (30 días)"
        value={formatNumber(kpis.frecuencia, 2)}
        line={<p className="pulse-unit">pedidos por persona activa</p>}
        slot={
          <p className="pulse-context">
            {formatNumber(kpis.pedidos_30d)} pedidos de {formatNumber(kpis.usuarios_activos)} personas en 30 días.
          </p>
        }
      />
      <Tile
        title="2 o más verticales (60 días)"
        value={formatPct(kpis.multi_vertical_pct)}
        line={<p className="pulse-unit">de quienes pidieron</p>}
        slot={<Meter value={kpis.multi_vertical_pct} max={100} />}
      />
    </div>
  )
}

/**
 * La serie semanal completa, una serie a la vez: un selector, la línea y su tabla (siempre en el DOM; a la vista con
 * "Ver tabla"). Con menos de 2 semanas completas no hay línea: la tabla directamente.
 */
export function WeeklyChart({ source }) {
  const [rows, kpis] = useAnalyticsMany(['weekly', 'kpis'], source)
  const [key, setKey] = useState(WEEKLY_SERIES[0].key)
  const item = series(key)
  const { points } = weeklySeries(rows, item, kpis.as_of)
  const table = <WeeklyTable rows={rows} asOf={kpis.as_of} />
  if (points.filter((point) => !point.partial && point.value !== null).length < MIN_CHART_WEEKS) {
    return (
      <>
        <p className="panel-meta">Faltan semanas para dibujar la serie.</p>
        {rows.length > 0 && table}
      </>
    )
  }
  const picker = (
    <div className="chart-picker">
      <label className="visually-hidden" htmlFor="serie">
        Indicador
      </label>
      <select id="serie" className="select" value={key} onChange={(event) => setKey(event.target.value)}>
        {WEEKLY_SERIES.map((option) => (
          <option key={option.key} value={option.key}>
            {option.title}
          </option>
        ))}
      </select>
    </div>
  )
  return (
    <ChartTableSwitch
      name="Serie semanal"
      legend={picker}
      chart={
        <LineChart
          points={points}
          format={item.format}
          tickFormat={item.rate ? (value) => formatPct(value, 0) : formatNumber}
          label={item.title}
        />
      }
      table={table}
    />
  )
}
