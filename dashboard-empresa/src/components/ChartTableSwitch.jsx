import { useState } from 'react'
import { Icon } from './Icon.jsx'

/**
 * Alterna un gráfico con su tabla equivalente (la vista accesible con todos los valores). El botón va arriba, a la
 * derecha; `legend`, la leyenda del gráfico, a su izquierda mientras se ve el gráfico. `name` le da al botón un nombre
 * único ("Ver tabla de …"). Con `keepTable` la tabla está siempre en el DOM (oculta a la vista mientras se ve el
 * gráfico): el lector de pantalla la tiene siempre; sin él, el gráfico trae su propio texto oculto.
 */
export function ChartTableSwitch({ chart, table, legend, name, keepTable = true }) {
  const [showTable, setShowTable] = useState(false)
  const label = showTable ? 'Ver gráfico' : 'Ver tabla'
  return (
    <>
      <div className="view-switch">
        {!showTable && legend}
        <button
          type="button"
          className="text-button"
          aria-label={name ? `${label} de ${name}` : undefined}
          onClick={() => setShowTable((value) => !value)}
        >
          <Icon name={showTable ? 'chart' : 'table'} />
          {label}
        </button>
      </div>
      {!showTable && chart}
      {keepTable ? <div className={showTable ? 'chart-table' : 'visually-hidden'}>{table}</div> : showTable && table}
    </>
  )
}
