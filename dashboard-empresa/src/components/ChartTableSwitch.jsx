import { useState } from 'react'
import { Icon } from './Icon.jsx'

/**
 * Alterna un gráfico con su tabla equivalente (la vista accesible con todos los valores). El botón va arriba, a la
 * derecha; `legend`, la leyenda del gráfico, a su izquierda mientras se ve el gráfico.
 */
export function ChartTableSwitch({ chart, table, legend }) {
  const [showTable, setShowTable] = useState(false)
  return (
    <>
      <div className="view-switch">
        {!showTable && legend}
        <button type="button" className="text-button" onClick={() => setShowTable((value) => !value)}>
          <Icon name={showTable ? 'chart' : 'table'} />
          {showTable ? 'Ver gráfico' : 'Ver tabla'}
        </button>
      </div>
      {showTable ? table : chart}
    </>
  )
}
