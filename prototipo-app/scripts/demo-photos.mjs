// Las fotos de la demo sin conexión (las usa scripts/demo-html.mjs antes de armar el HTML): baja una miniatura de cada
// foto que la muestra puede mostrar y las deja como data URI en src/api/offline/photos.json, que la API simulada pone
// en lugar de los enlaces (src/api/offline/snapshot.js). Así el HTML no pide nada a la red al abrirse.
//
// Las miniaturas las achica el propio CDN de Rappi (`?d=…&e=webp&q=…`), que redondea el tamaño pedido hacia arriba a
// los suyos: `d=100x100` da la más chica, de 128 px, y con calidad 15 una foto de producto pesa ~1,3 kB (con 25, ~1,4
// kB: con el perfil mexicano el HTML pasaba de 15 MB; a ese tamaño no se nota la diferencia). Las tiendas y
// restaurantes (portadas y logos, que se ven más grandes) piden `d=128x128`, que da 256 px. Quedan en .demo-cache/fotos/
// (fuera de git): un armado siguiente solo baja las nuevas. Una foto que no se puede bajar no entra (la app muestra el
// cuadro gris de siempre).
//
// Se bajan con las reglas del scraper (scripts/demo-photos-gate.py, con el Python de rappi-scraper): de a una, con su
// User-Agent, con robots.txt revisado antes y con sus candados de descarga tomados mientras tanto. Si otra descarga
// los tiene, o robots.txt no permite una foto, no baja ninguna.
import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { createInterface } from 'node:readline'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const CACHE = `${ROOT}.demo-cache/fotos/`
const PREFIX = 'https://images.rappi.cl/'
const SCRAPER_PYTHON = `${ROOT}../rappi-scraper/.venv/bin/python`
const GATE = `${ROOT}scripts/demo-photos-gate.py`
// Los campos que traen fotos (los productos, `img`; las tiendas, `logo`; los restaurantes, `cover`).
const STORE_FIELDS = new Set(['logo', 'cover'])
const SIZES = { product: 'd=100x100&e=webp&q=15', store: 'd=128x128&e=webp&q=50' }
const PAUSE_MS = 100
const MAX_PHOTO_BYTES = 200_000

/** Las fotos de la muestra: `Map<url, 'product' | 'store'>`. */
function photosIn(snapshot) {
  const found = new Map()
  const img = snapshot.productFields.indexOf('img')
  for (const row of snapshot.products) {
    const url = row[img]?.startsWith('~') ? `${snapshot.imgPrefix}${row[img].slice(1)}` : row[img]
    if (url) found.set(url, 'product')
  }
  const walk = (value, key) => {
    if (Array.isArray(value)) value.forEach((v) => walk(v, key))
    else if (value && typeof value === 'object') Object.entries(value).forEach(([k, v]) => walk(v, k))
    else if (typeof value === 'string' && value.startsWith(PREFIX) && (key === 'img' || STORE_FIELDS.has(key)))
      found.set(value, STORE_FIELDS.has(key) ? 'store' : (found.get(value) ?? 'product'))
  }
  walk({ ...snapshot, products: [] })
  return found
}

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/** Corta el armado con un mensaje y un código de salida (7: robots.txt no lo permite, como `rappi refresh`). */
export class PhotosStopped extends Error {
  constructor(message, exitCode) {
    super(message)
    this.exitCode = exitCode
  }
}

/**
 * Toma los candados de descarga del scraper y revisa robots.txt para `sources` (demo-photos-gate.py). Devuelve el
 * User-Agent con que bajarlas y `close()`, que suelta los candados; lanza PhotosStopped si no se puede bajar.
 */
async function openGate(sources, python) {
  if (!existsSync(python))
    throw new PhotosStopped(`Falta el Python del scraper (${python}): corre \`make install\` en rappi-scraper/.`, 1)
  const gate = spawn(python, [GATE], { stdio: ['pipe', 'pipe', 'inherit'] })
  const exited = new Promise((resolve) => gate.on('exit', resolve))
  gate.stdin.on('error', () => {}) // si sale antes de leer, lo dice su respuesta (o su falta)
  gate.stdin.write(`${JSON.stringify(sources)}\n`)
  let answer = {}
  for await (const line of createInterface({ input: gate.stdout })) {
    answer = JSON.parse(line)
    break
  }
  gate.stdout.resume()
  const close = () => {
    gate.stdin.end()
    return exited
  }
  if (answer.user_agent) return { userAgent: answer.user_agent, close }
  await close()
  if (answer.denial) throw new PhotosStopped(`${answer.denial}: no bajo las fotos`, 7)
  throw new PhotosStopped(answer.busy ?? 'No pude revisar las reglas del scraper: no bajo las fotos', 1)
}

/** Baja la miniatura `source` a `file`; null si no se pudo. */
async function download(source, file, userAgent) {
  try {
    const response = await fetch(source, { headers: { 'User-Agent': userAgent }, signal: AbortSignal.timeout(20_000) })
    const type = response.headers.get('content-type') ?? ''
    if (!response.ok || !type.startsWith('image/webp')) return null
    const bytes = Buffer.from(await response.arrayBuffer())
    if (!bytes.length || bytes.length > MAX_PHOTO_BYTES) return null
    writeFileSync(file, bytes)
    return bytes
  } catch {
    return null
  } finally {
    await pause(PAUSE_MS)
  }
}

/**
 * Escribe `out` con las miniaturas de las fotos de la muestra `snapshotPath`: `{ prefix, photos }`, donde `photos` va
 * de la dirección sin `prefix` a su data URI. Devuelve cuántas entraron, cuántas no y cuánto pesan. `cache` y `python`
 * son para los tests.
 */
export async function embedPhotos(snapshotPath, out, { cache = CACHE, python = SCRAPER_PYTHON } = {}) {
  mkdirSync(cache, { recursive: true })
  const entries = [...photosIn(JSON.parse(readFileSync(snapshotPath, 'utf8')))].map(([url, size]) => {
    if (!url.startsWith(PREFIX)) return { url }
    const source = `${url}${url.includes('?') ? '&' : '?'}${SIZES[size]}`
    return { url, source, file: `${cache}${createHash('sha1').update(source).digest('hex')}.webp` }
  })
  const pending = entries.filter(({ source, file }) => source && !existsSync(file)).map(({ source }) => source)
  const gate = pending.length ? await openGate(pending, python) : null
  const photos = {}
  let missing = 0
  let bytes = 0
  let done = 0
  try {
    for (const { url, source, file } of entries) {
      const data = !source ? null : existsSync(file) ? readFileSync(file) : await download(source, file, gate.userAgent)
      if (data) {
        photos[url.slice(PREFIX.length)] = `data:image/webp;base64,${data.toString('base64')}`
        bytes += data.length
      } else missing += 1
      done += 1
      if (done % 500 === 0) console.log(`  fotos: ${done}…`)
    }
  } finally {
    await gate?.close()
  }
  writeFileSync(out, JSON.stringify({ prefix: PREFIX, photos }))
  return { embedded: Object.keys(photos).length, missing, bytes }
}
