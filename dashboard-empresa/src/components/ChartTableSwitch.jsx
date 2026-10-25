import { useState } from 'react'
import { Icon } from './Icon.jsx'

/** Alterna un gráfico con su tabla equivalente (la vista accesible con todos los valores). */
export function ChartTableSwitch({ chart, table }) {
  const [showTable, setShowTable] = useState(false)
  return (
    <>
      {showTable ? table : chart}
      <div className="view-switch">
        <button type="button" className="text-button" onClick={() => setShowTable((value) => !value)}>
          <Icon name={showTable ? 'chart' : 'table'} />
          {showTable ? 'Ver gráfico' : 'Ver tabla'}
        </button>
      </div>
    </>
  )
}
