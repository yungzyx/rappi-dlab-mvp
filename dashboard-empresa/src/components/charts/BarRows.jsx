/**
 * Barras horizontales, una fila por ítem y una barra por serie (1 o 2), con el valor escrito al final de cada barra.
 * Sin pista de fondo. Decorativas para el lector de pantalla: la tabla equivalente va aparte.
 * series: [{ key, label }]; rows: [{ key, label, sub?, values: [number | null], texts: [string], note? }]; `max`, el
 * tope de la escala (por defecto, el mayor valor). Un valor null no pinta barra y su texto dice "—".
 */
export function BarRows({ rows, series, max }) {
  const top = max ?? Math.max(0, ...rows.flatMap((row) => row.values.filter((value) => value !== null)))
  const fraction = (value) => (top > 0 && value > 0 ? Math.min(1, value / top) : 0)
  // El lugar del valor escrito: la barra más larga termina antes, así el texto nunca se sale.
  const longest = Math.max(1, ...rows.flatMap((row) => row.texts.map((text) => String(text).length)))
  return (
    <div className="bars" aria-hidden="true" style={{ '--value-w': `${longest + 1}ch` }}>
      {series.length > 1 && (
        <div className="legend">
          {series.map((item, index) => (
            <span key={item.key} className="legend-item">
              <span className={`legend-swatch legend-swatch--${index + 1}`} />
              {item.label}
            </span>
          ))}
        </div>
      )}
      <ol className="bars-rows">
        {rows.map((row) => (
          <li key={row.key} className="bars-row">
            <div className="bars-label">
              <strong>{row.label}</strong>
              {row.sub && <span>{row.sub}</span>}
            </div>
            <div className="bars-tracks">
              {row.values.map((value, index) => (
                <div key={series[index].key} className="bars-track">
                  {fraction(value) > 0 && (
                    <span className={`bars-bar bars-bar--${index + 1}`} style={{ '--f': fraction(value) }} />
                  )}
                  <span className="bars-value num">{row.texts[index]}</span>
                </div>
              ))}
            </div>
            {row.note && <span className="bars-note">{row.note}</span>}
          </li>
        ))}
      </ol>
    </div>
  )
}
