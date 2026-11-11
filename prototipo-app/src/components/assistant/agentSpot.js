// Mochi flotante tapaba el "+" de los productos que pasaban por debajo (no solo los últimos de la lista: en medio de
// cualquier lista o carrusel). En vez de reservarle un margen a cada pantalla, Mochi mira qué tiene debajo y, si es un
// control, se aparta al borde (AgentPresence, `is-tucked`).

const CONTROL = 'button, a[href], input, select, textarea, [role="button"]'
const MARGIN = 18 // un dedo no es un punto: cuenta también el "+" (35 px) que solo asoma bajo un borde de Mochi
const GRID = 5 // muestras por lado: cada ~17 px, menos que el "+" más chico (32 px)

// Apartado (agent-presence.css, `.is-tucked`; agent-presence.test.js revisa que coincidan): se achica desde su esquina
// de abajo y se corre hacia el borde, y asoman 12 + 68 × 0,6 − 28 = 24,8 px. El borde libre a la derecha de los "+" mide
// 19 px, así que lo que asoma puede pisar el borde de un "+": entonces sube (`--tuck-lift`) de a 24 px hasta que no pise.
export const TUCK_SCALE = 0.6
export const TUCK_SHIFT = 28
const LIFT_STEP = 24
const LIFT_MAX = 168 // un poco más que una fila de productos (117 px)
const STRIP_GRID = [8, 8] // muestras alrededor de lo que asoma: cada ~5 px de ancho y ~8 de alto
// Se busca también un poco afuera: la esquina de un "+" redondo no recibe toques, pero su caja sí puede quedar bajo
// lo que asoma (y lo que asoma, su mascota, sí los recibe)
const STRIP_REACH = 8
// Un control chico (del tamaño de un "+" o una ×) cuenta con cualquier parte tapada; uno grande (una tarjeta, un chip
// largo que llega al borde), solo si lo que asoma le tapa al menos el 10 %.
const SMALL_CONTROL = 64
const STRIP_SHARE = 0.1

/** El cuadro de Mochi en su lugar de siempre (sin la transformación de cuando se aparta) y su contenedor. */
function restBox(body) {
  const host = body.offsetParent ?? body.parentElement
  const box = host.getBoundingClientRect()
  return {
    host,
    left: box.left + body.offsetLeft,
    top: box.top + body.offsetTop,
    width: body.offsetWidth,
    height: body.offsetHeight,
  }
}

/** El control que recibiría un toque en (x, y) si Mochi no estuviera, o null. */
function controlAt(host, x, y) {
  const under = document.elementsFromPoint(x, y).find((el) => !host.contains(el))
  return under?.closest(CONTROL) ?? null
}

const ready = (body) => body?.isConnected && typeof document.elementsFromPoint === 'function'

/**
 * ¿Hay un control cuyo centro quede bajo Mochi (`body`, en su lugar de siempre, sin la transformación de cuando se
 * aparta)? Un control grande (una fila, una tarjeta) se puede tocar en otra parte y no cuenta; el "+", "Ver más" o un
 * chip sí. Mira lo que de verdad recibe el toque en cada punto (`elementsFromPoint`), así lo tapado por una hoja o una
 * barra no cuenta.
 */
export function coversControl(body) {
  if (!ready(body)) return false
  const { host, ...box } = restBox(body)
  const left = box.left - MARGIN
  const top = box.top - MARGIN
  const width = box.width + 2 * MARGIN
  const height = box.height + 2 * MARGIN
  const seen = new Set()
  for (let i = 0; i < GRID; i++)
    for (let j = 0; j < GRID; j++) {
      const control = controlAt(host, left + ((i + 0.5) * width) / GRID, top + ((j + 0.5) * height) / GRID)
      if (!control || seen.has(control)) continue
      seen.add(control)
      const r = control.getBoundingClientRect()
      const cx = r.left + r.width / 2
      const cy = r.top + r.height / 2
      if (cx >= left && cx <= left + width && cy >= top && cy <= top + height) return true
    }
  return false
}

/** ¿Lo que asoma de Mochi apartado (`strip`, dentro del teléfono) le tapa a algún control una parte que cuente? */
function stripTouchesControl(host, strip) {
  const [cols, rows] = STRIP_GRID
  const left = strip.left - STRIP_REACH
  const top = strip.top - STRIP_REACH
  const width = strip.right - strip.left + 2 * STRIP_REACH
  const height = strip.bottom - strip.top + 2 * STRIP_REACH
  const seen = new Set()
  for (let i = 0; i < cols; i++)
    for (let j = 0; j < rows; j++) {
      const control = controlAt(host, left + ((i + 0.5) * width) / cols, top + ((j + 0.5) * height) / rows)
      if (!control || seen.has(control)) continue
      seen.add(control)
      const r = control.getBoundingClientRect()
      const ox = Math.min(r.right, strip.right) - Math.max(r.left, strip.left)
      const oy = Math.min(r.bottom, strip.bottom) - Math.max(r.top, strip.top)
      if (ox <= 0 || oy <= 0) continue
      const small = r.width <= SMALL_CONTROL && r.height <= SMALL_CONTROL
      if (small || ox * oy >= STRIP_SHARE * r.width * r.height) return true
    }
  return false
}

/**
 * Cuánto sube Mochi apartado (0, 24, 48… px) para que lo que asoma desde el borde no pise ningún control: lo menos
 * posible. Si ninguna altura sirve, 0 (el centro de los controles igual queda libre).
 */
export function tuckLift(body) {
  if (!ready(body)) return 0
  const { host, left, top, width, height } = restBox(body)
  const phone = host.closest('.phone')?.getBoundingClientRect() ?? { left: 0, right: window.innerWidth }
  const tuckedWidth = width * TUCK_SCALE
  const tuckedHeight = height * TUCK_SCALE // Mochi es más alto que ancho (68 × 82)
  const isLeft = host.classList.contains('is-left')
  const x = isLeft ? left - TUCK_SHIFT : left + width - tuckedWidth + TUCK_SHIFT
  const bottom = top + height
  for (let lift = 0; lift <= LIFT_MAX; lift += LIFT_STEP) {
    const strip = {
      left: Math.max(x, phone.left),
      right: Math.min(x + tuckedWidth, phone.right),
      top: bottom - tuckedHeight - lift,
      bottom: bottom - lift,
    }
    if (!stripTouchesControl(host, strip)) return lift
  }
  return 0
}
