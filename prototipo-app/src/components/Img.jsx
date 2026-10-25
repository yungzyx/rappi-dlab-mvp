import { useState } from 'react'

/** Cuadro gris claro para productos sin foto o cuya foto no carga (las de images.rappi.cl necesitan internet). */
export const PLACEHOLDER_IMG =
  'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"%3E%3Crect width="1" height="1" fill="%23f1f1f1"/%3E%3C/svg%3E'

/**
 * `<img>` para fotos de productos y tiendas: perezosa y decodificada aparte por defecto (`eager` para las que
 * están arriba del todo); si falla o no hay `src`, muestra el cuadro de respaldo. `onError` propio se sigue llamando.
 */
export default function Img({ src, alt = '', eager = false, onError, ...rest }) {
  const [failed, setFailed] = useState(null)
  const broken = !src || failed === src
  return (
    <img
      src={broken ? PLACEHOLDER_IMG : src}
      alt={alt}
      loading={eager ? 'eager' : 'lazy'}
      decoding="async"
      onError={(event) => {
        setFailed(src)
        onError?.(event)
      }}
      {...rest}
    />
  )
}
