// "Prototipo MVP.html" (npm run demo:html): la app en un solo archivo que abre con doble clic (file://), sin la API ni
// internet. Primero baja las miniaturas de las fotos de la muestra (scripts/demo-photos.mjs, con caché local); después
// construye el modo demo (`vite build --mode demo`: la API simulada de src/api/offline/, la muestra del catálogo y sus
// fotos) y mete el JS, el CSS (con fuentes e imágenes ya en base64) y el ícono dentro del HTML.
// Escribe dist-demo/Prototipo MVP.html y, con DEMO_HTML_COPY=<ruta>, también una copia ahí.
import { copyFileSync, existsSync, readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { build } from 'vite'
import { embedPhotos, PhotosStopped } from './demo-photos.mjs'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const DIST = `${ROOT}dist-demo/`
const OUT = `${DIST}Prototipo MVP.html`
const SNAPSHOT = `${ROOT}src/api/offline/snapshot.json`
const PHOTOS = `${ROOT}src/api/offline/photos.json`
// En MB como los cuenta el Finder (1 MB = 10⁶ bytes): el tope es lo que la persona ve junto al archivo.
const MAX_BYTES = 15_000_000
const mb = (bytes) => `${(bytes / 1e6).toFixed(1)} MB`

/**
 * Escribe el HTML en `out` y, con `copy`, también ahí; devuelve si se pudo. Se mide antes: un HTML sobre el tope no se
 * escribe ni se copia, así un armado fallido no reemplaza el entregable que ya estaba (en `out` o en la copia).
 */
export function saveDemoHtml(html, { out, copy, max = MAX_BYTES }) {
  const size = Buffer.byteLength(html)
  if (size > max) {
    console.error(
      `Pesa ${mb(size)}, más de ${mb(max)}: achica la muestra (scripts/demo-snapshot.mjs). No escribí nada.`,
    )
    return false
  }
  writeFileSync(out, html)
  console.log(`Listo: ${out} (${mb(size)})`)
  if (copy) {
    copyFileSync(out, copy)
    console.log(`Copia en ${copy}`)
  }
  return true
}

async function main() {
  if (!existsSync(SNAPSHOT)) {
    console.error('Falta la muestra del catálogo (src/api/offline/snapshot.json): corre antes `npm run demo:snapshot`.')
    process.exit(1)
  }

  console.log('Fotos de la muestra…')
  const photos = await embedPhotos(SNAPSHOT, PHOTOS).catch((error) => {
    if (!(error instanceof PhotosStopped)) throw error
    console.error(error.message)
    process.exit(error.exitCode)
  })
  console.log(
    `  ${photos.embedded} fotos adentro (${mb(photos.bytes)}); ${photos.missing} sin bajar, con el cuadro gris`,
  )

  await build({ root: ROOT, mode: 'demo', logLevel: 'warn' })

  let html = readFileSync(`${DIST}index.html`, 'utf8')
  const read = (href) => readFileSync(`${DIST}${href.replace(/^\.\//, '')}`)

  // Dentro de un <script> o <style> en línea no puede aparecer su etiqueta de cierre (ni "<!--" en un script).
  function inlineText(text, tag) {
    if (text.includes(`</${tag}`) || (tag === 'script' && text.includes('<!--')))
      throw new Error(`El ${tag} trae "</${tag}" o "<!--": no se puede meter en línea tal cual`)
    return text
  }

  // Con una función como reemplazo, el código no pasa por los patrones "$&" o "$1" de String.replace.
  html = html
    .replace(/<script type="module" crossorigin src="([^"]+)"><\/script>/, (_, src) => {
      const code = inlineText(read(src).toString('utf8'), 'script')
      return `<script type="module">${code}</script>`
    })
    .replace(/<link rel="stylesheet" crossorigin href="([^"]+)">/, (_, href) => {
      const css = inlineText(read(href).toString('utf8'), 'style')
      return `<style>${css}</style>`
    })
    // Sin servidor no hay manifiesto ni ícono para la pantalla de inicio; el de la pestaña va en base64.
    .replace(/\s*<!-- Con credenciales[^\n]*\n\s*<link rel="manifest"[^>]*>/, '')
    .replace(/\s*<link rel="apple-touch-icon"[^>]*>/, '')
    .replace(/<link rel="icon" type="image\/png" href="([^"]+)" \/>/, (_, href) => {
      const icon = read(href).toString('base64')
      return `<link rel="icon" type="image/png" href="data:image/png;base64,${icon}" />`
    })
    .replace(/<title>[^<]*<\/title>/, '<title>Prototipo MVP (demo sin conexión)</title>')

  for (const marker of ['src="./assets/', 'href="./assets/', 'rel="manifest"'])
    if (html.includes(marker)) throw new Error(`El HTML todavía apunta a un archivo aparte ("${marker}")`)

  if (!saveDemoHtml(html, { out: OUT, copy: process.env.DEMO_HTML_COPY })) process.exitCode = 1
}

// Solo como script (`npm run demo:html`): los tests importan saveDemoHtml sin armar la demo.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main()
