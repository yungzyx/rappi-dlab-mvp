import { useState } from 'react'
import { formatShortDate } from '../../lib/format.js'
import { nearestIndex, niceMax, scaleLinear } from './geometry.js'
import { useElementWidth } from './useElementWidth.js'

const MARGIN = { top: 12, right: 12, bottom: 24, left: 44 }
const MIN_LABEL_GAP = 56

const known = (point) => point.value !== null && point.value !== undefined

/** El trazo de una serie: un null corta la línea. */
function pathOf(points, x, y) {
  let path = ''
  let pen = false
  points.forEach((point, index) => {
    if (!known(point)) {
      pen = false
      return
    }
    path += `${pen ? 'L' : 'M'}${x(index).toFixed(1)},${y(point.value).toFixed(1)}`
    pen = true
  })
  return path
}

/** El primer lunes de cada mes, sin rótulos que queden a menos de 56 px del anterior. */
function monthTicks(points, x) {
  const ticks = []
  points.forEach((point, index) => {
    if (Number(point.date.slice(8, 10)) > 7) return
    const at = x(index)
    if (ticks.length && at - ticks.at(-1).at < MIN_LABEL_GAP) return
    ticks.push({ index, at, label: formatShortDate(point.date) })
  })
  return ticks
}

/**
 * Una serie semanal en línea (SVG, con el ancho de su contenedor). Eje Y desde 0, tres guías, un rótulo por mes y un
 * punto en la última semana completa; el tramo hacia una semana parcial va punteado y su punto, hueco. Arriba, la lectura
 * de una semana: la última completa o la más cercana al puntero. Decorativo para el lector de pantalla: `label` lo
 * resume y la tabla equivalente va aparte. `points`: [{ date, value, partial }]; `format`, el de la lectura;
 * `tickFormat`, el del eje (por defecto, `format`).
 */
export function LineChart({ points, format, tickFormat = format, label }) {
  const [ref, width] = useElementWidth()
  const [hover, setHover] = useState(null)
  const complete = points.filter((point) => !point.partial)
  const lastIndex = points.findLastIndex((point) => !point.partial && known(point))
  const height = width && width < 420 ? 180 : 220
  const x0 = MARGIN.left
  const x1 = Math.max(x0 + 1, width - MARGIN.right)
  const top = niceMax(Math.max(0, ...points.filter(known).map((point) => point.value)))
  const x = scaleLinear([0, points.length - 1], [x0, x1])
  const y = scaleLinear([0, top], [height - MARGIN.bottom, MARGIN.top])
  const shown = hover ?? lastIndex
  const point = points[shown]

  // El tramo hacia la semana parcial, punteado; el resto, continuo.
  const partialIndex = points.findIndex((item) => item.partial)
  const solid = partialIndex === -1 ? points : points.slice(0, partialIndex)
  const dashed =
    partialIndex > 0 && known(points[partialIndex]) && known(points[partialIndex - 1])
      ? `M${x(partialIndex - 1).toFixed(1)},${y(points[partialIndex - 1].value).toFixed(1)}L${x(partialIndex).toFixed(1)},${y(points[partialIndex].value).toFixed(1)}`
      : ''

  const onPointerMove = (event) => {
    const box = event.currentTarget.getBoundingClientRect()
    setHover(nearestIndex(event.clientX - box.left, points.length, x0, x1))
  }

  return (
    <div className="line-chart">
      <p className="chart-readout">
        {point ? (
          <>
            Semana del {formatShortDate(point.date)}
            {point.partial && ' (parcial)'}: <strong className="num">{format(point.value)}</strong>
          </>
        ) : (
          ' '
        )}
      </p>
      <div
        ref={ref}
        className="line-chart-plot"
        style={{ height }}
        role="img"
        aria-label={`${label}: ${complete.length} semanas; última completa, ${lastIndex === -1 ? '—' : format(points[lastIndex].value)}`}
        onPointerMove={onPointerMove}
        onPointerLeave={() => setHover(null)}
      >
        {width > 0 && (
          <svg width={width} height={height} aria-hidden="true">
            {[0, top / 2, top].map((tick) => (
              <g key={tick}>
                <line className="chart-grid" x1={x0} x2={x1} y1={y(tick)} y2={y(tick)} />
                <text className="chart-axis" x={x0 - 8} y={y(tick)} dy="0.32em" textAnchor="end">
                  {tickFormat(tick)}
                </text>
              </g>
            ))}
            {monthTicks(points, x).map((tick) => (
              <text
                key={tick.index}
                className="chart-axis"
                x={tick.at}
                y={height - 6}
                textAnchor={tick.at - x0 < 20 ? 'start' : 'middle'}
              >
                {tick.label}
              </text>
            ))}
            {hover !== null && <line className="chart-guide" x1={x(hover)} x2={x(hover)} y1={MARGIN.top} y2={y(0)} />}
            <path className="chart-line" d={pathOf(solid, x, y)} />
            {dashed && <path className="chart-line chart-line--partial" d={dashed} />}
            {partialIndex !== -1 && known(points[partialIndex]) && (
              <circle
                className="chart-dot chart-dot--partial"
                cx={x(partialIndex)}
                cy={y(points[partialIndex].value)}
                r="3.5"
              />
            )}
            {lastIndex !== -1 && (
              <circle className="chart-dot" cx={x(lastIndex)} cy={y(points[lastIndex].value)} r="3.5" />
            )}
            {hover !== null && known(points[hover]) && hover !== lastIndex && (
              <circle className="chart-dot chart-dot--hover" cx={x(hover)} cy={y(points[hover].value)} r="3.5" />
            )}
          </svg>
        )}
      </div>
    </div>
  )
}
