// @vitest-environment node
import { readFileSync } from 'node:fs'
import { describe, expect, test } from 'vitest'

// Las hojas reales (en los tests, Vite no procesa el CSS importado) y sus tokens.
const tokens = readFileSync(new URL('../../styles/tokens.css', import.meta.url), 'utf8')
const token = (name) => tokens.match(new RegExp(`${name}: (#[0-9a-f]{6})`, 'i'))[1]

/** La regla `selector` de la hoja `sheet` (ruta relativa a este archivo): el valor final de cada propiedad, en hex. */
function rule(sheet, selector) {
  const css = readFileSync(new URL(sheet, import.meta.url), 'utf8')
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const body = css.match(new RegExp(`(?:^|\\n)${escaped} \\{([^}]*)\\}`))[1]
  // Un hex directo o el token de tokens.css.
  return (property) => {
    const raw = body.match(new RegExp(`\\s${property}:\\s*([^;]+)`, 'i'))[1]
    return raw.match(/#[0-9a-f]{6}/i)?.[0] ?? token(raw.match(/var\((--[\w-]+)/)[1])
  }
}

// Contraste WCAG entre dos colores #rrggbb.
const luminance = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  const linear = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)
}
const contrast = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

describe('contraste', () => {
  test('la etiqueta "De otra tienda" (11 px) cumple AA: 4,5:1 sobre su fondo', () => {
    const value = rule('./assistant.css', '.agent-msg-suggestion-tag')
    expect(contrast(value('color'), value('background'))).toBeGreaterThanOrEqual(4.5)
  })

  test('"Pídele a Mochi" resaltada se lee (AA, 4,5:1): el título y lo escrito sobre el naranja claro', () => {
    for (const ink of ['--accent-ink', '--ink-2'])
      expect(contrast(token(ink), token('--accent-soft'))).toBeGreaterThanOrEqual(4.5)
  })

  // Texto chico (bajo 18,7 px en negrita): AA pide 4,5:1. La × de borrar es un control: 3:1.
  test.each([
    ['la cuenta regresiva de los créditos', '../../screens/home/home.css', '.credits-timer', 4.5],
    ['"Explorar" en Descubre', './discover.css', '.discover-card-foot em', 4.5],
    ['la insignia de lealtad', '../../screens/loyalty/loyalty.css', '.loyalty-badge', 4.5],
    ['Pro en el pago, ya socio', '../../screens/checkout/checkout.css', '.checkout-pro.is-member', 4.5],
    ['la × de borrar la búsqueda', '../search/search.css', '.search-clear', 3],
  ])('%s cumple AA sobre su fondo', (_label, sheet, selector, min) => {
    const value = rule(sheet, selector)
    expect(contrast(value('color'), value('background'))).toBeGreaterThanOrEqual(min)
  })
})
