import { DataTable } from '../../components/DataTable.jsx'
import { Delta } from '../../components/Delta.jsx'
import { Sparkline } from '../../components/charts/Sparkline.jsx'
import { formatNumber, formatPct, formatShortDate } from '../../lib/format.js'
import { useAnalyticsMany } from '../../lib/useAnalytics.js'
import { COMPARE_WEEKS, isPartialWeek, WEEKLY_SERIES, weeklySeries } from './weekly.js'

const SPARK_WEEKS = 12
// Con menos semanas la línea dibuja el arranque del MVP, no una tendencia.
const MIN_SPARK_WEEKS = 5
const series = (key) => WEEKLY_SERIES.find((item) => item.key === key)

/** Un indicador semanal: la última semana completa, su cambio contra 4 semanas antes y la tendencia de 12 semanas. */
function WeeklyTile({ rows, item, asOf }) {
  const { points, latest, change, formatChange } = weeklySeries(rows, item, asOf)
  const complete = points.filter((point) => !point.partial).slice(-SPARK_WEEKS)
  return (
    <article className="pulse-tile" aria-label={item.title}>
      <h3>{item.title}</h3>
      <p className="pulse-value">
        <strong>{latest ? item.format(latest.value) : '—'}</strong>
        <span>{latest ? item.unit : 'sin una semana completa'}</span>
      </p>
      {change === null ? (
        <p className="pulse-context">Sin la semana de hace {COMPARE_WEEKS} para comparar.</p>
      ) : (
        <Delta
          value={change}
          format={formatChange}
          goodWhen={item.goodWhen}
          suffix={`vs hace ${COMPARE_WEEKS} semanas`}
        />
      )}
      {complete.length >= MIN_SPARK_WEEKS && (
        <Sparkline
          values={complete.map((point) => point.value)}
          label={`${item.title}, últimas ${complete.length} semanas completas`}
        />
      )}
    </article>
  )
}

/** Un indicador sin serie semanal: su cifra y lo que la explica. */
function KpiTile({ title, value, unit, context }) {
  return (
    <article className="pulse-tile" aria-label={title}>
      <h3>{title}</h3>
      <p className="pulse-value">
        <strong>{value}</strong>
        <span>{unit}</span>
      </p>
      <p className="pulse-context">{context}</p>
    </article>
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

/** «Cómo va»: 3 indicadores con su tendencia semanal y 2 de 30 y 60 días con lo que los explica; la serie, en tabla. */
export function Pulse({ source }) {
  const [rows, kpis] = useAnalyticsMany(['weekly', 'kpis'], source)
  return (
    <>
      <div className="pulse">
        <WeeklyTile rows={rows} item={series('usuarios_activos')} asOf={kpis.as_of} />
        <WeeklyTile rows={rows} item={series('pedidos')} asOf={kpis.as_of} />
        <KpiTile
          title="Frecuencia (30 días)"
          value={formatNumber(kpis.frecuencia, 2)}
          unit="pedidos por persona activa"
          context={`${formatNumber(kpis.pedidos_30d)} pedidos de ${formatNumber(kpis.usuarios_activos)} personas en 30 días.`}
        />
        <KpiTile
          title="Piden en 2 o más verticales (60 días)"
          value={formatPct(kpis.multi_vertical_pct)}
          unit="de quienes pidieron en 60 días"
          context="Es la palanca: en la tabla de Rappi, quien combina verticales vuelve más."
        />
        <WeeklyTile rows={rows} item={series('abandono_carrito_pct')} asOf={kpis.as_of} />
      </div>
      {rows.length > 0 && (
        <details className="disclosure">
          <summary>Ver la serie semanal completa</summary>
          <WeeklyTable rows={rows} asOf={kpis.as_of} />
        </details>
      )}
    </>
  )
}
