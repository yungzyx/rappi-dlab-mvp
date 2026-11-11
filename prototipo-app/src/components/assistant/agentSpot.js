// Mochi flotante tapaba el "+" de los productos que pasaban por debajo (no solo los últimos de la lista: en medio de
// cualquier lista o carrusel). En vez de reservarle un margen a cada pantalla, Mochi mira qué tiene debajo y, si es un
// control, se aparta al borde (AgentPresence, `is-tucked`).

const CONTROL = 'button, a[href], input, select, textarea, [role="button"]'
const MARGIN = 8 // un dedo no es un punto: cuenta también lo que queda justo al lado
const GRID = 5 // muestras por lado: cada ~17 px, menos que el "+" más chico (32 px)

/**
 * ¿Hay un control cuyo centro quede bajo Mochi (`body`, en su lugar de siempre, sin la transformación de cuando se
 * aparta)? Un control grande (una fila, una tarjeta) se puede tocar en otra parte y no cuenta; el "+", "Ver más" o un
 * chip sí. Mira lo que de verdad recibe el toque en cada punto (`elementsFromPoint`), así lo tapado por una hoja o una
 * barra no cuenta.
 */
export function coversControl(body) {
  if (!body?.isConnected || typeof document.elementsFromPoint !== 'function') return false
  const host = body.offsetParent ?? body.parentElement
  const box = host.getBoundingClientRect()
  const left = box.left + body.offsetLeft - MARGIN
  const top = box.top + body.offsetTop - MARGIN
  const width = body.offsetWidth + 2 * MARGIN
  const height = body.offsetHeight + 2 * MARGIN
  const seen = new Set()
  for (let i = 0; i < GRID; i++)
    for (let j = 0; j < GRID; j++) {
      const x = left + ((i + 0.5) * width) / GRID
      const y = top + ((j + 0.5) * height) / GRID
      const under = document.elementsFromPoint(x, y).find((el) => !host.contains(el))
      const control = under?.closest(CONTROL)
      if (!control || seen.has(control)) continue
      seen.add(control)
      const r = control.getBoundingClientRect()
      const cx = r.left + r.width / 2
      const cy = r.top + r.height / 2
      if (cx >= left && cx <= left + width && cy >= top && cy <= top + height) return true
    }
  return false
}
