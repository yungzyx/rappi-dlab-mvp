import { useLayoutEffect } from 'react'

// Lo que flota abajo del teléfono (la barra del carro, «Pedido en curso» y Mochi) tapaba el «+» de los últimos productos.
// Cada uno se registra aquí y el teléfono lleva en `--floating-bottom` cuánto ocupa lo más alto de ellos, más un margen:
// las pantallas lo usan como relleno inferior (`max(<el suyo>, var(--floating-bottom))`), así el final de la lista
// siempre se puede subir por encima de lo que flota, y el relleno cambia cuando aparece o se va algo.
export const FLOATING_GAP = 12

const floating = new Map() // elemento → el teléfono donde está

/** La distancia desde arriba del teléfono hasta `el`, sin transformaciones (una animación de entrada no la cambia). */
function topWithin(el, phone) {
  let top = 0
  for (let node = el; node && node !== phone; node = node.offsetParent) top += node.offsetTop
  return top
}

/** Cuánto sube lo que flota desde abajo del teléfono (0 si no hay nada), con su margen. */
export function floatingInset(phone, elements) {
  let inset = 0
  for (const el of elements) {
    if (!el.isConnected || !el.offsetHeight) continue
    inset = Math.max(inset, phone.clientHeight - topWithin(el, phone))
  }
  return inset > 0 ? Math.ceil(inset + FLOATING_GAP) : 0
}

function update(phone) {
  if (!phone) return
  const mine = [...floating].filter(([, where]) => where === phone).map(([el]) => el)
  phone.style.setProperty('--floating-bottom', `${floatingInset(phone, mine)}px`)
}

/**
 * Registra lo que flota (`target()` da el elemento, o null si no se ve) y vuelve a medir en cada render: las clases que
 * lo suben sobre el carro o la barra inferior cambian con el render, y al desmontarse deja de contar.
 */
export function useFloatingInset(target) {
  useLayoutEffect(() => {
    const el = target()
    const phone = el?.closest('.phone')
    if (!el || !phone) return undefined
    floating.set(el, phone)
    update(phone)
    return () => {
      floating.delete(el)
      // Después del render, no en medio: entre la limpieza y el efecto siguiente el relleno bajaría un instante (sin
      // este elemento) y, al medir, el navegador recortaría el scroll de la pantalla al fondo.
      queueMicrotask(() => update(phone))
    }
  })
}
