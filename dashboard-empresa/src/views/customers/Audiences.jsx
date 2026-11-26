import { useState } from 'react'
import { DataTable } from '../../components/DataTable.jsx'
import { Delta } from '../../components/Delta.jsx'
import { Icon } from '../../components/Icon.jsx'
import { Panel } from '../../components/Panel.jsx'
import { EmptyState } from '../../components/States.jsx'
import { CAN_LIST_PEOPLE, loadAudienceMembers } from '../../lib/api.js'
import { downloadCsv, rowsToCsv } from '../../lib/csv.js'
import { formatNumber, formatSignedPct } from '../../lib/format.js'
import { useAnalytics } from '../../lib/useAnalytics.js'

const SOURCE_WORD = { synthetic: 'simulados', prototype: 'prototipo' }
// En cada fila: el texto copiado no lleva el nombre del archivo, y una planilla puede separar las filas.
const SOURCE_CELL = { synthetic: 'Simulado (no es evidencia)', prototype: 'Prototipo (no es evidencia)' }

/** El CSV de una audiencia: su id seudónimo, si acepta avisos y de qué fuente es, una persona por línea. */
export function membersCsv(members, source) {
  return rowsToCsv([
    ['Usuario', 'Acepta avisos', 'Fuente'],
    ...members.personas.map((row) => [row.usuario, row.acepta_avisos ? 'Sí' : 'No', SOURCE_CELL[source]]),
  ])
}

/**
 * Llevarse una audiencia: bajar sus ids seudónimos en CSV o copiarlos (el mismo CSV), pedidos a la API al tocar. Dice
 * qué pasó al lado, también al lector de pantalla. En el HTML suelto no hay lista que pedir: la tabla no lo ofrece.
 */
function MembersExport({ audience, source }) {
  const [status, setStatus] = useState('')
  const run = async (action) => {
    setStatus('Pidiendo la lista…')
    try {
      const csv = membersCsv(await loadAudienceMembers(audience.id, source), source)
      if (action === 'copy') {
        await navigator.clipboard.writeText(csv)
        setStatus('Copiada')
      } else {
        downloadCsv(`audiencia-${audience.id}-${SOURCE_WORD[source]}.csv`, csv)
        setStatus('Descargada')
      }
    } catch {
      setStatus('No se pudo: la lista sale de la API en marcha.')
    }
  }
  return (
    <span className="audience-export" data-no-csv>
      <button
        type="button"
        className="text-button"
        aria-label={`Descargar la lista de ${audience.nombre} en CSV`}
        onClick={() => run('download')}
      >
        <Icon name="download" />
        CSV
      </button>
      <button
        type="button"
        className="text-button"
        aria-label={`Copiar la lista de ${audience.nombre}`}
        onClick={() => run('copy')}
      >
        Copiar
      </button>
      <span className="cell-sub" role="status">
        {status}
      </span>
    </span>
  )
}

/** Su tamaño contra el de 4 semanas antes, sin juicio (crecer no es bueno ni malo en todas). */
function change(row, minimum) {
  if (row.cambio_personas_pct === undefined) return '—' // una foto grabada antes del cambio
  if (row.personas_antes === null) {
    return <span className="cell-sub">Hace 4 semanas no llegaba a {formatNumber(minimum)}</span>
  }
  return (
    <span className="cell-stack">
      <Delta value={row.cambio_personas_pct} format={formatSignedPct} goodWhen={null} />
      <span className="cell-sub">antes {formatNumber(row.personas_antes)}</span>
    </span>
  )
}

const columnsFor = (source, minimum) => [
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
  { key: 'cambio', header: 'Cambio en 4 semanas', numeric: true, render: (row) => change(row, minimum) },
  {
    key: 'aceptan_avisos',
    header: 'Aceptan avisos',
    numeric: true,
    render: (row) => `${formatNumber(row.aceptan_avisos)} de ${formatNumber(row.personas)}`,
  },
  { key: 'ofrecer', header: 'Qué ofrecerles', wide: true },
  ...(CAN_LIST_PEOPLE
    ? [{ key: 'lista', header: 'Lista', render: (row) => <MembersExport audience={row} source={source} /> }]
    : []),
]

/** "2 audiencias no llegan a 20 personas y no se muestran." (o nada, si todas llegan). */
function hiddenNote({ bajo_el_minimo: hidden, minimo_personas: minimum }) {
  if (!hidden) return null
  const subject = hidden === 1 ? '1 audiencia no llega' : `${hidden} audiencias no llegan`
  return `${subject} a ${minimum} personas y no ${hidden === 1 ? 'se muestra' : 'se muestran'}.`
}

/**
 * Audiencias para campañas (RappiAds y CRM), de /analytics/audiencias: grupos de personas que cumplen una regla, con su
 * tamaño y su cambio en 4 semanas, cuántas aceptan avisos y qué ofrecerles; la lista de ids seudónimos de cada una se
 * baja o se copia en CSV (/analytics/audiencias/{id}). Una persona puede estar en más de una. Las que no llegan al
 * mínimo de personas no vienen (privacidad): se dice cuántas son.
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
          <p className="block-note">
            {CAN_LIST_PEOPLE
              ? 'La lista de cada audiencia trae ids seudónimos (los mismos de la lista de riesgo) y si aceptan avisos.'
              : 'Este archivo no trae las listas de personas: se bajan desde el panel con la API.'}
          </p>
          {hidden && <p className="block-note">{hidden}</p>}
        </>
      }
    >
      <DataTable
        caption="Audiencias para campañas"
        columns={columnsFor(source, data.minimo_personas)}
        rows={data.audiencias}
        rowKey={(row) => row.id}
      />
    </Panel>
  )
}
