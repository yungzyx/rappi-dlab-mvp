import { AGENT_NAME } from '../../lib/agentName.js'
import { DataTable } from '../../components/DataTable.jsx'
import { Meter } from '../../components/Meter.jsx'
import { EmptyState } from '../../components/States.jsx'
import { Stats } from '../../components/Stats.jsx'
import { formatDate, formatNumber } from '../../lib/format.js'
import { useAnalyticsMany } from '../../lib/useAnalytics.js'
import { riskAudiences } from './audiences.js'
import { AtRiskTable } from './AtRiskTable.jsx'

const TOP_AUDIENCES = 8

function Audiences({ rows }) {
  const audiences = riskAudiences(rows)
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
    <>
      <DataTable
        caption="Personas en riesgo o perdidas por lo que más pedían"
        columns={columns}
        rows={top}
        rowKey={(row) => row.concept}
      />
      {audiences.length > TOP_AUDIENCES && (
        <p className="cell-sub">
          Los {TOP_AUDIENCES} grupos más grandes de {audiences.length}.
        </p>
      )}
    </>
  )
}

/**
 * ¿A quién estamos perdiendo y qué le ofrecemos? Las cifras de riesgo (de /analytics/kpis) junto a quién califica para
 * «¿Volvemos a…?» o «¿Repetimos?» (/analytics/volver), y lo que pedían las personas que entrega /analytics/at-risk.
 */
export function Churn({ source }) {
  const [kpis, rows, winback] = useAnalyticsMany(['kpis', 'at-risk', 'volver'], source)
  const shownAtRisk = rows.filter((row) => row.estado === 'en_riesgo').length
  return (
    <>
      <Stats
        items={[
          {
            label: 'En riesgo',
            value: formatNumber(kpis.en_riesgo),
            note: 'Pasaron el doble de su ritmo sin pedir (mínimo 21 días). Todavía se pueden recuperar.',
          },
          {
            label: 'Perdidas',
            value: formatNumber(kpis.perdidos),
            note: 'Pasaron el triple de su ritmo sin pedir (mínimo 45 días).',
          },
          {
            label: 'Califican para «¿Volvemos a…?»',
            value: formatNumber(winback.califican),
            note: `Dejaron algo que pedían con ritmo: ${formatNumber(winback.por_concepto)} un concepto y ${formatNumber(winback.por_vertical)} una vertical. Es otra regla que la del riesgo.`,
          },
          {
            label: 'Les toca «¿Repetimos?»',
            value: formatNumber(winback.recompra),
            note: 'La recompra va primero: a ellas no se las invita a volver.',
          },
        ]}
      />
      {winback.dia && (
        <p className="cell-sub">Califican al {formatDate(winback.dia)}, el último día de los pedidos simulados.</p>
      )}
      {rows.length === 0 ? (
        <EmptyState title="Nadie en riesgo ni perdido">
          Nadie pasó el doble de su propio ritmo sin pedir (o todavía nadie tiene dos compras).
        </EmptyState>
      ) : (
        <>
          <h3 className="subhead">Qué pedían y cómo llegarles</h3>
          <p className="block-note">
            Con aviso aceptado: recordatorio en su ritmo con lo que más pedían y un complemento. Sin aviso: solo{' '}
            {AGENT_NAME}
            en la app. Muestra de {formatNumber(rows.length)} de las {formatNumber(kpis.en_riesgo + kpis.perdidos)},
            primero las en riesgo más atrasadas respecto de su ritmo.
          </p>
          {shownAtRisk === 0 && kpis.en_riesgo > 0 && (
            <p className="table-warning status status--warn">
              La API entregó {rows.length} filas y ninguna es de una persona en riesgo: las{' '}
              {formatNumber(kpis.en_riesgo)} en riesgo, las más fáciles de recuperar, no alcanzan a aparecer.
            </p>
          )}
          <Audiences rows={rows} />
          <details className="disclosure">
            <summary>Ver la lista de personas (id seudónimo)</summary>
            <AtRiskTable rows={rows} />
          </details>
        </>
      )}
    </>
  )
}
