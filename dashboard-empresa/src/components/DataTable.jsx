/**
 * Tabla accesible. En pantallas angostas cada fila se vuelve una tarjeta (sin scroll horizontal):
 * la columna `primary` hace de título, `wide` ocupa todo el ancho y las demás muestran su encabezado.
 * columns: [{ key, header, render?, numeric?, primary?, wide? }]
 */
const cellClass = ({ numeric, primary, wide }) =>
  [numeric && 'is-num', primary && 'is-primary', wide && 'is-wide'].filter(Boolean).join(' ') || undefined

export function DataTable({ caption, columns, rows, rowKey, rowClassName }) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col" className={column.numeric ? 'is-num' : undefined}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={rowKey(row, index)} className={rowClassName?.(row, index)}>
              {columns.map((column) => (
                <td key={column.key} data-label={column.header} className={cellClass(column)}>
                  {column.render ? column.render(row, index) : row[column.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
