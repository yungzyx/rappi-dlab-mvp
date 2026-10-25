// «Panel de negocio (demo).html» (npm run panel:html): el panel en un solo archivo que abre con doble clic (file://), sin la API ni
// internet. Construye el modo panel-html (`vite build --mode panel-html`: las respuestas de snapshot/panel.json en vez de
// la API, ver vite.config.js) y mete el JS, el CSS (con las fuentes ya en base64), el tema y el ícono dentro del HTML.
// Escribe dist-html/Panel de negocio (demo).html y, con PANEL_HTML_COPY=<ruta>, también una copia ahí.
import { copyFileSync, existsSync, readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const DIST = `${ROOT}dist-html/`
const OUT = `${DIST}Panel de negocio (demo).html`
const SNAPSHOT = `${ROOT}snapshot/panel.json`

if (!existsSync(SNAPSHOT)) {
  console.error('Falta la foto de la API (snapshot/panel.json): corre antes `npm run panel:snapshot`.')
  process.exit(1)
}

await build({ root: ROOT, mode: 'panel-html', logLevel: 'warn' })

let html = readFileSync(`${DIST}index.html`, 'utf8')
const read = (href) => readFileSync(`${DIST}${href.replace(/^\.\//, '')}`)

// Dentro de un <script> o <style> en línea no puede aparecer su etiqueta de cierre (ni «<!--» en un script).
function inlineText(text, tag) {
  if (text.includes(`</${tag}`) || (tag === 'script' && text.includes('<!--')))
    throw new Error(`El ${tag} trae «</${tag}» o «<!--»: no se puede meter en línea tal cual`)
  return text
}

// Con una función como reemplazo, el código no pasa por los patrones «$&» o «$1» de String.replace.
html = html
  // Primero los comentarios del HTML de Vite (antes de meter el código: en el JS no se tocan).
  .replace(/\s*<!--[\s\S]*?-->/g, '')
  .replace(/<script type="module" crossorigin src="([^"]+)"><\/script>/, (_, src) => {
    const code = inlineText(read(src).toString('utf8'), 'script')
    return `<script type="module">${code}</script>`
  })
  .replace(/<link rel="stylesheet" crossorigin href="([^"]+)">/, (_, href) => {
    const css = inlineText(read(href).toString('utf8'), 'style')
    return `<style>${css}</style>`
  })
  // El tema elegido antes de pintar (public/tema.js), en línea: sin servidor no hay archivo aparte que cargar.
  .replace(/<script\s+(?:vite-ignore\s+)?src="[^"]*tema\.js"><\/script>/, () => {
    const code = inlineText(readFileSync(`${ROOT}public/tema.js`, 'utf8'), 'script')
    return `<script>${code}</script>`
  })
  .replace(/<link rel="icon" type="image\/svg\+xml" href="[^"]*favicon\.svg" \/>/, () => {
    const icon = readFileSync(`${ROOT}public/favicon.svg`).toString('base64')
    return `<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,${icon}" />`
  })
  .replace(/<title>[^<]*<\/title>/, '<title>Panel de negocio (foto sin conexión)</title>')

for (const marker of ['src="./', 'href="./', 'src="/', 'href="/', 'tema.js'])
  if (html.includes(marker)) throw new Error(`El HTML todavía apunta a un archivo aparte («${marker}»)`)

writeFileSync(OUT, html)
const size = Buffer.byteLength(html)
console.log(`Listo: ${OUT} (${(size / 1e6).toFixed(2)} MB)`)
if (process.env.PANEL_HTML_COPY) {
  copyFileSync(OUT, process.env.PANEL_HTML_COPY)
  console.log(`Copia en ${process.env.PANEL_HTML_COPY}`)
}
