import { DataTable } from '../../components/DataTable.jsx'
import { Panel } from '../../components/Panel.jsx'
import { EmptyState } from '../../components/States.jsx'
import { formatNumber } from '../../lib/format.js'
import { useAnalytics } from '../../lib/useAnalytics.js'

const COLUMNS = [
  {
    key: 'nombre',
    header: 'Audiencia',
    primary: true,
    render: (row) => (
      <span className="cell-stack">
        {row.nombre}
        <span className="cell-sub">{row.regla}</span>
      </span>
    ),
  },
  { key: 'personas', header: 'Personas', numeric: true, render: (row) => formatNumber(row.personas) },
  {
    key: 'aceptan_avisos',
    header: 'Aceptan avisos',
    numeric: true,
    render: (row) => `${formatNumber(row.aceptan_avisos)} de ${formatNumber(row.personas)}`,
  },
  { key: 'ofrecer', header: 'Qué ofrecerles', wide: true },
]

/** "2 audiencias no llegan a 20 personas y no se muestran." (o nada, si todas llegan). */
function hiddenNote({ bajo_el_minimo: hidden, minimo_personas: minimum }) {
  if (!hidden) return null
  const subject = hidden === 1 ? '1 audiencia no llega' : `${hidden} audiencias no llegan`
  return `${subject} a ${minimum} personas y no ${hidden === 1 ? 'se muestra' : 'se muestran'}.`
}

/**
 * Audiencias para campañas (RappiAds y CRM), de /analytics/audiencias: grupos de personas que cumplen una regla, con su
 * tamaño, cuántas aceptan avisos y qué ofrecerles. Una persona puede estar en más de una. Las que no llegan al mínimo
 * de personas no vienen (privacidad): se dice cuántas son.
 */
export function Audiences({ source }) {
  const data = useAnalytics('audiencias', source)
  const hidden = hiddenNote(data)
  if (!data.audiencias.length) {
    return (
      <EmptyState title="Ninguna audiencia llega al mínimo">
        Una audiencia se muestra desde {data.minimo_personas} personas: con menos, diría demasiado de cada una.
      </EmptyState>
    )
  }
  return (
    <Panel
      title="Audiencias"
      meta="Una persona puede estar en más de una."
      foot={
        <>
          <p className="block-note">
            Fuera de la app solo se le escribe a quien aceptó avisos. Ninguna audiencia se arma con un concepto sensible
            ni por pedir en Farmacia o Licores.
          </p>
          {hidden && <p className="block-note">{hidden}</p>}
        </>
      }
    >
      <DataTable caption="Audiencias para campañas" columns={COLUMNS} rows={data.audiencias} rowKey={(row) => row.id} />
    </Panel>
  )
}
