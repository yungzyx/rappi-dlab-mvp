// Escala lineal para dibujar las marcas en píxeles.
export function scaleLinear([d0, d1], [r0, r1]) {
  return (value) => (d1 === d0 ? r0 : r0 + ((value - d0) / (d1 - d0)) * (r1 - r0))
}
