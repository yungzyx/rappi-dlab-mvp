import { scaleLinear } from './geometry.js'
import { useElementWidth } from './useElementWidth.js'

const HEIGHT = 36
const PAD = 5 // aire para el punto final (radio 4 y su anillo)

/**
 * Tendencia de un indicador (línea de 2 px en el gris de contexto y el último punto marcado, con anillo
 * del color de la superficie; en tinta y no en el acento, que junto a «rojo si empeora» se leería como juicio).
 * Decorativa: la cifra, el cambio y la tabla dicen lo mismo; `label` lo resume para lectores de pantalla. `values`:
 * números en orden; un null corta la línea.
 */
export function Sparkline({ values, label }) {
  const [ref, width] = useElementWidth()
  const known = values.filter((value) => value !== null && value !== undefined)
  if (known.length < 2) return null
  const min = Math.min(...known)
  const max = Math.max(...known)
  const x = scaleLinear([0, values.length - 1], [PAD, width - PAD])
  const y = scaleLinear(min === max ? [min - 1, max + 1] : [min, max], [HEIGHT - PAD, PAD])
  let path = ''
  let pen = false
  values.forEach((value, index) => {
    if (value === null || value === undefined) {
      pen = false
      return
    }
    path += `${pen ? 'L' : 'M'}${x(index).toFixed(1)},${y(value).toFixed(1)}`
    pen = true
  })
  const lastIndex = values.findLastIndex((value) => value !== null && value !== undefined)
  return (
    <div ref={ref} className="sparkline" role="img" aria-label={label}>
      {width > 0 && (
        <svg width={width} height={HEIGHT} aria-hidden="true">
          <path className="sparkline-path" d={path} />
          <circle className="sparkline-dot" cx={x(lastIndex)} cy={y(values[lastIndex])} r="4" />
        </svg>
      )}
    </div>
  )
}
