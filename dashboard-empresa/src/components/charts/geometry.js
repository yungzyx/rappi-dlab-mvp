// Escala lineal para dibujar las marcas en píxeles.
export function scaleLinear([d0, d1], [r0, r1]) {
  return (value) => (d1 === d0 ? r0 : r0 + ((value - d0) / (d1 - d0)) * (r1 - r0))
}

/**
 * El tope "redondo" de un eje: el menor de 1; 1,5; 2; 2,5; 3; 4; 5; 6 u 8 por una potencia de 10 que sea mayor o igual a
 * `value` (con pasos más finos que 1, 2 y 5, la línea no queda aplastada en la mitad de abajo).
 */
export function niceMax(value) {
  if (!(value > 0)) return 1
  const power = 10 ** Math.floor(Math.log10(value))
  for (const step of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) {
    const candidate = step * power
    if (candidate >= value * (1 - 1e-9)) return candidate
  }
  return 10 * power
}

/** El índice (de 0 a `count` − 1) del punto más cercano a la coordenada `x`, con los puntos repartidos de `x0` a `x1`. */
export function nearestIndex(x, count, x0, x1) {
  if (count <= 1 || x1 === x0) return 0
  const index = Math.round(((x - x0) / (x1 - x0)) * (count - 1))
  return Math.min(count - 1, Math.max(0, index))
}
