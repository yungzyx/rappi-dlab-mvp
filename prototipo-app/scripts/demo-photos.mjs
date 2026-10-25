// Las fotos de la demo sin conexión (las usa scripts/demo-html.mjs antes de armar el HTML): baja una miniatura de cada
// foto que la muestra puede mostrar y las deja como data URI en src/api/offline/photos.json, que la API simulada pone
// en lugar de los enlaces (src/api/offline/snapshot.js). Así el HTML no pide nada a la red al abrirse.
//
// Las miniaturas las achica el propio CDN de Rappi (`?d=…&e=webp&q=…`), que redondea el tamaño pedido hacia arriba a
// los suyos: `d=100x100` da la más chica, de 128 px, y con calidad 25 una foto de producto pesa ~1,4 kB. Las tiendas y
// restaurantes (portadas y logos, que se ven más grandes) piden `d=128x128`, que da 256 px. Se bajan pocas a la vez y quedan en .demo-cache/fotos/ (fuera de git): un armado siguiente solo baja
// las nuevas. Una foto que no se puede bajar no entra (la app muestra el cuadro gris de siempre).
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const CACHE = `${ROOT}.demo-cache/fotos/`
const PREFIX = 'https://images.rappi.cl/'
// Los campos que traen fotos (los productos, `img`; las tiendas, `logo`; los restaurantes, `cover`).
const STORE_FIELDS = new Set(['logo', 'cover'])
const SIZES = { product: 'd=100x100&e=webp&q=25', store: 'd=128x128&e=webp&q=50' }
const AT_ONCE = 4
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

/** La miniatura de una foto (de la caché o del CDN), o null si no se pudo bajar. */
async function thumbnail(url, size) {
  const source = `${url}${url.includes('?') ? '&' : '?'}${SIZES[size]}`
  const file = `${CACHE}${createHash('sha1').update(source).digest('hex')}.webp`
  if (existsSync(file)) return readFileSync(file)
  try {
    const response = await fetch(source, { signal: AbortSignal.timeout(20_000) })
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
 * de la dirección sin `prefix` a su data URI. Devuelve cuántas entraron, cuántas no y cuánto pesan.
 */
export async function embedPhotos(snapshotPath, out) {
  mkdirSync(CACHE, { recursive: true })
  const queue = [...photosIn(JSON.parse(readFileSync(snapshotPath, 'utf8')))]
  const photos = {}
  let missing = 0
  let bytes = 0
  let done = 0
  const worker = async () => {
    for (let next = queue.shift(); next; next = queue.shift()) {
      const [url, size] = next
      const data = url.startsWith(PREFIX) ? await thumbnail(url, size) : null
      if (data) {
        photos[url.slice(PREFIX.length)] = `data:image/webp;base64,${data.toString('base64')}`
        bytes += data.length
      } else missing += 1
      done += 1
      if (done % 500 === 0) console.log(`  fotos: ${done}…`)
    }
  }
  await Promise.all(Array.from({ length: AT_ONCE }, worker))
  writeFileSync(out, JSON.stringify({ prefix: PREFIX, photos }))
  return { embedded: Object.keys(photos).length, missing, bytes }
}
