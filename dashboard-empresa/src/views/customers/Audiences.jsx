import { DataTable } from '../../components/DataTable.jsx'
import { DesignNotice } from '../../components/DesignNotice.jsx'
import { Panel } from '../../components/Panel.jsx'
import { formatNumber } from '../../lib/format.js'

// Filas de ejemplo (cifras redondas a propósito): el diseño de la tabla, no una medición. Cuando exista
// /analytics/audiencias, este archivo deja de traer filas y las lee de la API (docs/diseno/, "Elementos nuevos del panel").
export const EXAMPLE_AUDIENCES = [
  {
    id: 'solo-restaurantes',
    nombre: 'Solo Restaurantes, con hábito',
    regla: 'Pide solo en Restaurantes y lleva 2 o más pedidos en 30 días',
    personas: 1000,
    aceptan_avisos: 400,
    ofrecer: 'Turbo, su vertical por probar',
  },
  {
    id: 'en-riesgo',
    nombre: 'En riesgo, con algo que pedía seguido',
    regla: 'Pasó el doble de su ritmo sin pedir y tiene un concepto con ritmo propio',
    personas: 300,
    aceptan_avisos: 100,
    ofrecer: '"¿Volvemos a…?" con ese concepto',
  },
  {
    id: 'probo-turbo',
    nombre: 'Probó Turbo una vez',
    regla: 'Un solo pedido en Turbo en 60 días, después de pedir en Restaurantes',
    personas: 200,
    aceptan_avisos: 80,
    ofrecer: 'Repetir en Turbo lo que pidió',
  },
  {
    id: 'pro-una-vertical',
    nombre: 'Pro que no combina',
    regla: 'Es Pro y pide en una sola vertical',
    personas: 150,
    aceptan_avisos: 90,
    ofrecer: 'Una segunda vertical con su beneficio Pro',
  },
  {
    id: 'multivertical',
    nombre: 'Ya combina 3 o más',
    regla: 'Pidió en 3 o más verticales en 60 días',
    personas: 250,
    aceptan_avisos: 120,
    ofrecer: 'Nada nuevo: no molestar',
  },
]

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

/**
 * Audiencias para campañas (RappiAds y CRM): grupos de personas con su regla, su tamaño, cuántas aceptan avisos y qué
 * ofrecerles. Hoy es un diseño con filas de ejemplo: la API todavía no las entrega.
 */
export function Audiences() {
  return (
    <div className="block">
      <DesignNotice route="/analytics/audiencias">
        Con datos, cada audiencia traería su tamaño real y la lista de ids seudónimos para una campaña; nunca por un
        concepto sensible, y fuera de la app solo a quien aceptó avisos.
      </DesignNotice>
      <Panel title="Audiencias (ejemplo)" noExport>
        <DataTable
          caption="Audiencias para campañas: filas de ejemplo"
          columns={COLUMNS}
          rows={EXAMPLE_AUDIENCES}
          rowKey={(row) => row.id}
        />
      </Panel>
    </div>
  )
}
