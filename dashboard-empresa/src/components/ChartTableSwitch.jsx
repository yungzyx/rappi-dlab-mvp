import { useState } from 'react'
import { Icon } from './Icon.jsx'
import { Panel } from './Panel.jsx'

/** El estado y el botón "Ver tabla" / "Ver gráfico"; `name` le da un nombre único ("Ver tabla de …"). */
function useChartTable(name) {
  const [showTable, setShowTable] = useState(false)
  const label = showTable ? 'Ver gráfico' : 'Ver tabla'
  const button = (
    <button
      type="button"
      className="text-button"
      aria-label={name ? `${label} de ${name}` : undefined}
      onClick={() => setShowTable((value) => !value)}
    >
      <Icon name={showTable ? 'chart' : 'table'} />
      {label}
    </button>
  )
  return { showTable, button }
}

/**
 * El gráfico o su tabla. Con `keepTable` la tabla está siempre en el DOM (oculta a la vista mientras se ve el gráfico):
 * el lector de pantalla la tiene siempre; sin él, el gráfico trae su propio texto oculto.
 */
function ChartOrTable({ showTable, chart, table, keepTable }) {
  return (
    <>
      {!showTable && chart}
      {keepTable ? <div className={showTable ? 'chart-table' : 'visually-hidden'}>{table}</div> : showTable && table}
    </>
  )
}

/**
 * Alterna un gráfico con su tabla equivalente (la vista accesible con todos los valores). El botón va arriba, a la
 * derecha; `legend`, la leyenda del gráfico, a su izquierda mientras se ve el gráfico.
 */
export function ChartTableSwitch({ chart, table, legend, name, keepTable = true }) {
  const { showTable, button } = useChartTable(name)
  return (
    <>
      <div className="view-switch">
        {!showTable && legend}
        {button}
      </div>
      <ChartOrTable showTable={showTable} chart={chart} table={table} keepTable={keepTable} />
    </>
  )
}

/**
 * Un panel con un gráfico: "Ver tabla" va en su cabecera, junto al título; la leyenda (o el selector), arriba del
 * gráfico. `name`, el de la tabla (por defecto, el título). El resto, como en Panel.
 */
export function ChartPanel({ name, legend, chart, table, keepTable = true, ...panel }) {
  const { showTable, button } = useChartTable(name ?? panel.title)
  return (
    <Panel {...panel} actions={button}>
      {!showTable && legend}
      <ChartOrTable showTable={showTable} chart={chart} table={table} keepTable={keepTable} />
    </Panel>
  )
}
