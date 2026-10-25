// @vitest-environment node
import { readFileSync } from 'node:fs'
import { describe, expect, test } from 'vitest'

// Las hojas reales (en los tests, Vite no procesa el CSS importado) y los tokens.
const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const tokens = read('./tokens.css')

const luminance = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  const linear = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)
}
const contrast = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

// Valor final de una propiedad de una regla: un #rrggbb directo o el token de tokens.css (un gradiente no vale: no es un color).
const colorOf = (raw) => {
  const value = raw.trim()
  if (/^#[0-9a-f]{6}$/i.test(value)) return value
  const name = value.match(/^var\((--[\w-]+)\)$/)?.[1]
  if (!name) throw new Error(`«${value}» no es un color sólido`)
  return colorOf(tokens.match(new RegExp(`${name}:\\s*([^;]+);`))[1].replace(/\/\*.*?\*\//g, ''))
}
const property = (file, selector, name) => {
  const rule = read(file).match(new RegExp(`(?:^|\\n)${selector.replace('.', '\\.')} \\{([^}]*)\\}`))[1]
  return colorOf(rule.match(new RegExp(`(?:^|[\\s;])${name}:\\s*([^;]+);`))[1])
}

// [qué es, hoja, selector, color del texto o ícono, fondo, mínimo WCAG AA: 4,5 texto y 3 ícono o texto grande]
const PAIRS = [
  ['«Go to checkout» del carro (17 px)', '../components/cart.css', '.cart-checkout', 'color', 'background', 4.5],
  ['«+» y contador del botón de agregar', '../components/add-button.css', '.add-button', 'color', 'background', 4.5],
  ['«Place order» (17 px)', '../screens/checkout/checkout.css', '.checkout-place', 'color', 'background', 4.5],
  ['tarifa de servicio de Turbo', '../screens/turbo/turbo.css', '.turbo-fee', 'color', 'background', 4.5],
]

describe('contraste de los botones principales (WCAG AA)', () => {
  test.each(PAIRS)('%s', (_name, file, selector, fg, bg, min) => {
    expect(contrast(property(file, selector, fg), property(file, selector, bg))).toBeGreaterThanOrEqual(min)
  })
})
