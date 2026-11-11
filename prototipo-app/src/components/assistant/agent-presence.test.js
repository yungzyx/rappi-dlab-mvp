// @vitest-environment node
import { readFileSync } from 'node:fs'
import { expect, test } from 'vitest'
import { TUCK_SCALE, TUCK_SHIFT } from './agentSpot'

// La cuenta sale de la hoja misma (en los tests no se aplica el CSS). Mochi mide 68 px (AgentPresence, SIZE) y su
// contenedor va a `right` px del borde; apartado, se achica desde su esquina y se corre hacia afuera.
const css = readFileSync(new URL('./agent-presence.css', import.meta.url), 'utf8')
const right = Number(css.match(/\.agent-presence \{[^}]*\sright: (\d+)px/)[1])
const [, shift, scale] = css
  .match(/\.agent-presence\.is-tucked \.agent-presence-body \{[^}]*translate\((\d+)px,[^;]*\) scale\(([\d.]+)\)/)
  .map(Number)

test('Mochi apartado deja al menos 24 × 24 px a la vista para tocarlo (WCAG 2.5.8)', () => {
  expect(right + 68 * scale - shift).toBeGreaterThanOrEqual(24) // ancho que queda dentro del teléfono
  expect(68 * scale).toBeGreaterThanOrEqual(24) // alto
})

test('agentSpot.js calcula lo que asoma con las mismas medidas que la hoja', () => {
  expect([shift, scale]).toEqual([TUCK_SHIFT, TUCK_SCALE])
  const left = css.match(/\.agent-presence\.is-left\.is-tucked \.agent-presence-body \{[^}]*translate\((-?\d+)px/)[1]
  expect(Number(left)).toBe(-TUCK_SHIFT)
})
