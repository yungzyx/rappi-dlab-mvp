import { AGENT_NAME } from '../../lib/agentName.js'
import { DataTable } from '../../components/DataTable.jsx'
import { EmptyState } from '../../components/States.jsx'
import { formatNumber, formatPct } from '../../lib/format.js'
import { plural, verticalLabel } from '../../lib/labels.js'
import { Panel } from '../../components/Panel.jsx'
import { Stats } from '../../components/Stats.jsx'

const COLUMNS = [
  {
    key: 'vertical',
    header: 'Vertical',
    primary: true,
    render: (row) => (row.vertical ? verticalLabel(row.vertical) : 'Sin vertical'),
  },
  { key: 'concepto', header: 'Concepto', render: (row) => row.concepto ?? 'Sin concepto reconocido' },
  { key: 'sin_resultado', header: 'Sin resultado', numeric: true, render: (row) => formatNumber(row.sin_resultado) },
]

/**
 * El abandono de búsqueda: las que no terminaron en ningún toque, ni en otra búsqueda con toque poco después. Con menos
 * de 10 búsquedas la API no da el %, y se muestra la cuenta.
 */
function abandonmentStat({ busquedas, rescatadas, abandonadas, abandono_pct: pct, plazo_minutos: minutes }) {
  return {
    label: 'Abandono de búsqueda',
    value: pct === null ? `${formatNumber(abandonadas)} de ${formatNumber(busquedas)}` : formatPct(pct),
    note: `de ${formatNumber(busquedas)} ${plural(busquedas, 'búsqueda')}; ${formatNumber(rescatadas)} se ${rescatadas === 1 ? 'salvó' : 'salvaron'} al reformular`,
    help: (
      <p>
        Cuenta las búsquedas que saben qué se tocó desde ellas. Abandonada es la que no terminó en ningún toque ni en
        otra búsqueda con toque en {minutes} minutos.
      </p>
    ),
  }
}

/**
 * Búsquedas que no encontraron nada: las cuentas, el abandono de búsqueda y, con `table`, las sin resultado por
 * vertical y concepto. Nunca el texto buscado (la API no lo entrega).
 */
export function UnmetSearches({ data, table = true }) {
  const { personas, busquedas, sin_resultado: unmet, por_vertical: rows, abandono: abandonment } = data
  if (!busquedas) {
    return <EmptyState title="Todavía no hay búsquedas">Aparecen cuando alguien busca en la app.</EmptyState>
  }
  return (
    <>
      <Stats
        items={[
          {
            label: 'Sin resultado',
            value: `${formatNumber(unmet)} de ${formatNumber(busquedas)}`,
            note: `${plural(busquedas, 'búsqueda o pregunta', 'búsquedas y preguntas')} a ${AGENT_NAME}`,
          },
          // una respuesta guardada antes del 03-11-2026 no trae el abandono
          ...(abandonment?.busquedas ? [abandonmentStat(abandonment)] : []),
          { label: 'Personas que buscaron', value: formatNumber(personas) },
        ]}
      />
      {table && rows.length > 0 && (
        <Panel
          title="Sin resultado por vertical y concepto"
          meta="Hasta 20 filas; nunca el texto que escribió la persona."
        >
          <DataTable
            caption="Búsquedas sin resultado por vertical y concepto"
            columns={COLUMNS}
            rows={rows}
            rowKey={(row) => `${row.vertical}/${row.concepto ?? ''}`}
          />
        </Panel>
      )}
    </>
  )
}
