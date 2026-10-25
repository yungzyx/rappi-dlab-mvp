// @vitest-environment node
import { readFileSync } from 'node:fs'
import { describe, expect, test } from 'vitest'

// La hoja real (en los tests, Vite no procesa el CSS importado) y sus tokens.
const css = readFileSync(new URL('./assistant.css', import.meta.url), 'utf8')
const tokens = readFileSync(new URL('../../styles/tokens.css', import.meta.url), 'utf8')
const token = (name) => tokens.match(new RegExp(`${name}: (#[0-9a-f]{6})`, 'i'))[1]

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
    const rule = css.match(/\.agent-msg-suggestion-tag \{([^}]*)\}/)[1]
    // Valor final de la propiedad: un hex directo o el token de tokens.css.
    const value = (property) => {
      const raw = rule.match(new RegExp(`\\s${property}:\\s*([^;]+)`, 'i'))[1]
      return raw.match(/#[0-9a-f]{6}/i)?.[0] ?? token(raw.match(/var\((--[\w-]+)/)[1])
    }
    expect(contrast(value('color'), value('background'))).toBeGreaterThanOrEqual(4.5)
  })

  test('«Pregúntale a Mochi» resaltada se lee (AA, 4,5:1): el título y lo escrito sobre el naranja claro', () => {
    for (const ink of ['--accent-ink', '--ink-2'])
      expect(contrast(token(ink), token('--accent-soft'))).toBeGreaterThanOrEqual(4.5)
  })
})
