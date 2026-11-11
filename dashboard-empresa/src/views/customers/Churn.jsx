import { AGENT_NAME } from '../../lib/agentName.js'
import { DataTable } from '../../components/DataTable.jsx'
import { Meter } from '../../components/Meter.jsx'
import { Panel } from '../../components/Panel.jsx'
import { EmptyState } from '../../components/States.jsx'
import { Stats } from '../../components/Stats.jsx'
import { formatDate, formatNumber } from '../../lib/format.js'
import { useAnalyticsMany } from '../../lib/useAnalytics.js'
import { riskAudiences } from './audiences.js'
import { AtRiskTable } from './AtRiskTable.jsx'

const TOP_AUDIENCES = 8

function Audiences({ rows, audiences }) {
  const top = audiences.slice(0, TOP_AUDIENCES)
  const max = Math.max(...top.map((audience) => audience.people))
  const columns = [
    { key: 'concept', header: 'Lo que más pedían', primary: true, render: (row) => row.concept },
    {
      key: 'people',
      header: 'Personas',
      numeric: true,
      render: (row) => (
        <span className="cell-bar">
          <Meter value={row.people} max={max} />
          {formatNumber(row.people)}
        </span>
      ),
    },
    { key: 'atRisk', header: 'En riesgo', numeric: true, render: (row) => formatNumber(row.atRisk) },
    {
      key: 'consent',
      header: 'Aceptan avisos',
      numeric: true,
      render: (row) => `${formatNumber(row.withConsent)} de ${formatNumber(row.people)}`,
    },
  ].filter((column) => column.key !== 'atRisk' || rows.some((row) => row.estado !== 'en_riesgo'))
  return (
    <DataTable
      caption="Personas en riesgo o perdidas por lo que más pedían"
      columns={columns}
      rows={top}
      rowKey={(row) => row.concept}
    />
  )
}

/**
 * ¿A quién estamos perdiendo y qué le ofrecemos? Las cifras de riesgo (de /analytics/kpis) junto a quién califica para
 * "¿Volvemos a…?" o "¿Repetimos?" (/analytics/volver), y lo que pedían las personas que entrega /analytics/at-risk.
 */
export function Churn({ source }) {
  const [kpis, rows, winback] = useAnalyticsMany(['kpis', 'at-risk', 'volver'], source)
  const shownAtRisk = rows.filter((row) => row.estado === 'en_riesgo').length
  const audiences = riskAudiences(rows)
  return (
    <>
      {winback.dia && <p className="section-meta">Al {formatDate(winback.dia)}</p>}
      <Stats
        items={[
          {
            label: 'En riesgo',
            value: formatNumber(kpis.en_riesgo),
            note: 'Doble de su ritmo sin pedir. Todavía se pueden recuperar.',
          },
          {
            label: 'Perdidas',
            value: formatNumber(kpis.perdidos),
            note: 'Triple de su ritmo sin pedir.',
          },
          {
            label: 'Califican para "¿Volvemos a…?"',
            value: formatNumber(winback.califican),
            note: `${formatNumber(winback.por_concepto)} por un concepto, ${formatNumber(winback.por_vertical)} por una vertical`,
          },
          {
            label: 'Les toca "¿Repetimos?"',
            value: formatNumber(winback.recompra),
            note: 'La recompra va primero: no se las invita a volver.',
          },
        ]}
      />
      {rows.length === 0 ? (
        <EmptyState title="Nadie en riesgo ni perdido">
          Nadie pasó el doble de su propio ritmo sin pedir (o todavía nadie tiene dos compras).
        </EmptyState>
      ) : (
        <Panel
          title="Qué pedían y cómo llegarles"
          help={
            <p>
              Con aviso aceptado: recordatorio en su ritmo con lo que más pedían y un complemento. Sin aviso: solo{' '}
              {AGENT_NAME} en la app.
            </p>
          }
          meta={`Muestra de ${formatNumber(rows.length)} de las ${formatNumber(kpis.en_riesgo + kpis.perdidos)}, primero las en riesgo más atrasadas.`}
          foot={
            <>
              {audiences.length > TOP_AUDIENCES && (
                <p>
                  Los {TOP_AUDIENCES} grupos más grandes de {audiences.length}.
                </p>
              )}
              <details className="disclosure">
                <summary>Ver la lista de personas (id seudónimo)</summary>
                <AtRiskTable rows={rows} />
              </details>
            </>
          }
        >
          {shownAtRisk === 0 && kpis.en_riesgo > 0 && (
            <p className="table-warning status status--warn">
              La API entregó {rows.length} filas y ninguna es de una persona en riesgo: las{' '}
              {formatNumber(kpis.en_riesgo)} en riesgo, las más fáciles de recuperar, no alcanzan a aparecer.
            </p>
          )}
          <Audiences rows={rows} audiences={audiences} />
        </Panel>
      )}
    </>
  )
}
