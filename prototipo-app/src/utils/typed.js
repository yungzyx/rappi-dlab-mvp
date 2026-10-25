// Sin Intl.Segmenter (navegadores viejos, como Firefox antes de la 125) se corta por puntos de código: no parte un emoji
// simple como 🧡, aunque sí uno de varias piezas como 👩‍🍳.
const graphemes = typeof Intl.Segmenter === 'function' ? new Intl.Segmenter('es') : null

/**
 * Hasta dónde se ve un texto que se escribe letra por letra cuando van `count` unidades: el último grafema entero. Un
 * emoji como 🧡 son dos unidades de UTF-16 (y ❤️ o 👩‍🍳, más); partido, cada mitad se ve como un símbolo raro y más
 * ancho, y la línea puede saltar.
 */
export function typedEnd(text, count) {
  const pieces = graphemes ? Array.from(graphemes.segment(text), ({ segment }) => segment) : Array.from(text)
  let end = 0
  for (const piece of pieces) {
    if (end + piece.length > count) break
    end += piece.length
  }
  return end
}
