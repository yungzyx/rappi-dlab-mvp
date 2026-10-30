// La presentación del MVP (make presentacion o node presentacion/build.mjs): dos páginas de un solo archivo que muestran
// "Prototipo MVP.html" y "Panel de negocio (demo).html" dentro de un marco con sus controles (persona, vista, panel de la
// demo) y un recorrido automático por capítulos. escritorio.html es para un notebook o un proyector; movil.html, para
// un iPhone o un iPad.
//
// Lee los dos HTML ya armados (npm run demo:html en prototipo-app y npm run panel:html en dashboard-empresa), les
// inyecta shim.js al inicio (lo guardado con prefijo propio y el historial en memoria) y los mete como texto en
// `const PROTOS = {mvp, panel}` de cada plantilla, junto con recorrido.js (los controles y el recorrido, comunes a las
// dos). Escribe presentacion/dist/ (ignorada en git) y, con PRESENTACION_COPY=<carpeta>, también una copia ahí.
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const ROOT = `${HERE}../`
const SOURCES = {
  mvp: `${ROOT}prototipo-app/dist-demo/Prototipo MVP.html`,
  panel: `${ROOT}dashboard-empresa/dist-html/Panel de negocio (demo).html`,
}
const OUTPUTS = {
  'escritorio.html': 'Mochi MVP - Presentación.html',
  'movil.html': 'Mochi MVP - iPhone y iPad.html',
}
const DIST = `${HERE}dist/`
// La barra de modos y el "Panel de la demo" de la app quedan ocultos: la presentación muestra sus botones a los lados.
const HIDE = { mvp: '.demo-toggle,.offline-demo{display:none!important}', panel: '' }
const MARK = '/*PROTOS*/null'
const TOUR_MARK = '/*RECORRIDO*/'

for (const [id, file] of Object.entries(SOURCES)) {
  if (!existsSync(file)) {
    const how = id === 'mvp' ? 'npm run demo:html en prototipo-app' : 'npm run panel:html en dashboard-empresa'
    console.error(`Falta ${file}: corre antes ${how} (o make presentacion en la raíz).`)
    process.exit(1)
  }
}

const shim = readFileSync(`${HERE}shim.js`, 'utf8')
const tour = readFileSync(`${HERE}recorrido.js`, 'utf8')
for (const [name, code] of [
  ['shim.js', shim],
  ['recorrido.js', tour],
])
  if (code.includes('</script') || code.includes('<!--')) throw new Error(`${name} no puede traer "</script" ni "<!--"`)

/** El HTML con el shim y el estilo que oculta los controles de la demo, al inicio de <head>. */
function inject(id, html) {
  const head = /<head[^>]*>/i.exec(html)
  if (!head) throw new Error(`${SOURCES[id]} no tiene <head>`)
  const style = HIDE[id] ? `<style>${HIDE[id]}</style>` : ''
  const at = head.index + head[0].length
  return `${html.slice(0, at)}<script>${shim.replace('__NS__', `${id}:`)}</script>${style}${html.slice(at)}`
}

const protos = Object.fromEntries(
  Object.entries(SOURCES).map(([id, file]) => [id, inject(id, readFileSync(file, 'utf8'))]),
)
// Dentro de un <script> no puede aparecer "</script" ni "<!--": todos los "<" van escapados.
const json = JSON.stringify(protos)
  .replace(/</g, '\\u003c')
  .replace(/\u2028/g, '\\u2028')
  .replace(/\u2029/g, '\\u2029')

mkdirSync(DIST, { recursive: true })
const mb = (bytes) => `${(bytes / 1e6).toFixed(1)} MB`
for (const [template, name] of Object.entries(OUTPUTS)) {
  const page = readFileSync(`${HERE}${template}`, 'utf8')
  for (const mark of [MARK, TOUR_MARK])
    if (page.split(mark).length !== 2) throw new Error(`${template} debe traer "${mark}" una vez`)
  // Con una función como reemplazo, el código no pasa por los patrones "$&" o "$1" de String.replace.
  const html = page.replace(TOUR_MARK, () => tour).replace(MARK, () => json)
  const out = `${DIST}${name}`
  writeFileSync(out, html)
  console.log(`Listo: ${out} (${mb(Buffer.byteLength(html))})`)
  if (process.env.PRESENTACION_COPY) {
    mkdirSync(process.env.PRESENTACION_COPY, { recursive: true })
    copyFileSync(out, `${process.env.PRESENTACION_COPY.replace(/\/+$/, '')}/${name}`)
    console.log(`  copia en ${process.env.PRESENTACION_COPY}`)
  }
}
