import { DataTable } from '../../components/DataTable.jsx'
import { DesignNotice } from '../../components/DesignNotice.jsx'
import { Panel } from '../../components/Panel.jsx'
import { formatNumber, formatPct } from '../../lib/format.js'

// Filas de ejemplo (cifras redondas a propósito): el diseño de la ficha, no una medición. Cuando exista
// /analytics/verticales, este archivo deja de traer filas y las lee de la API (docs/diseno/, "Elementos nuevos del panel").
export const EXAMPLE_VERTICALS = [
  { vertical: 'Restaurantes', personas: 1000, pedidos: 1500, abandono: 25, sin_resultado: 20, combinan: 30 },
  { vertical: 'Turbo', personas: 300, pedidos: 400, abandono: 30, sin_resultado: 15, combinan: 80 },
  { vertical: 'Supermercado', personas: 200, pedidos: 250, abandono: 35, sin_resultado: 10, combinan: 70 },
  { vertical: 'Farmacia', personas: 100, pedidos: 120, abandono: 20, sin_resultado: 25, combinan: 90 },
]

const COLUMNS = [
  { key: 'vertical', header: 'Vertical', primary: true },
  { key: 'personas', header: 'Personas activas (30 días)', numeric: true, render: (row) => formatNumber(row.personas) },
  { key: 'pedidos', header: 'Pedidos (30 días)', numeric: true, render: (row) => formatNumber(row.pedidos) },
  { key: 'abandono', header: 'Abandono de carrito', numeric: true, render: (row) => formatPct(row.abandono, 0) },
  {
    key: 'sin_resultado',
    header: 'Búsquedas sin resultado',
    numeric: true,
    render: (row) => formatPct(row.sin_resultado, 0),
  },
  {
    key: 'combinan',
    header: 'También piden en otra vertical',
    numeric: true,
    render: (row) => formatPct(row.combinan, 0),
  },
]

/**
 * La ficha por vertical: las verticales lado a lado, para ver cuál pierde carros, dónde falta surtido y cuál ya trae
 * gente que combina. Hoy es un diseño con filas de ejemplo: la API entrega esas cifras repartidas, no en una ruta.
 */
export function Verticals() {
  return (
    <div className="block">
      <DesignNotice route="/analytics/verticales">
        Con datos, cada vertical traería sus cifras de 30 días y su cambio frente a las 4 semanas anteriores.
      </DesignNotice>
      <Panel title="Verticales lado a lado (ejemplo)" noExport>
        <DataTable
          caption="Ficha por vertical: filas de ejemplo"
          columns={COLUMNS}
          rows={EXAMPLE_VERTICALS}
          rowKey={(row) => row.vertical}
        />
      </Panel>
    </div>
  )
}
