// La muestra del catálogo (snapshot.json, la escribe `npm run demo:snapshot`) lista para responder: los productos
// vuelven a ser objetos como los de la API y las respuestas grabadas los llevan en su lugar. Las fotos, si el armado
// las bajó (photos.json, `npm run demo:html`), van adentro como data URI.

// Los campos con la foto de un producto, una tienda o un restaurante.
const PHOTO_FIELDS = new Set(['img', 'logo', 'cover'])

/**
 * Arma la muestra a partir del JSON grabado: `{ ...respuestas, pool, byEntity }`. Con `photos` (`{ prefix, photos }`),
 * cada foto es su data URI o, si no se pudo bajar, nada (la app muestra el cuadro gris): la demo no pide fotos a la red.
 */
export function decodeSnapshot(raw, photos = null) {
  const { products: rows, productFields: fields, imgPrefix, ...rest } = raw
  const photo = (url) => {
    if (!photos || typeof url !== 'string') return url
    return (url.startsWith(photos.prefix) && photos.photos[url.slice(photos.prefix.length)]) || null
  }
  const pool = rows.map((row) => {
    const p = Object.fromEntries(fields.map((field, i) => [field, row[i]]))
    if (p.img?.startsWith('~')) p.img = `${imgPrefix}${p.img.slice(1)}`
    p.img = photo(p.img)
    return { id: `${p.entity_type === 'menu_item' ? 'menu' : 'cat'}-${p.entity_id}`, ...p }
  })
  const revive = (value) => {
    if (Array.isArray(value)) return value.map(revive)
    if (!value || typeof value !== 'object') return value
    if ('$p' in value) return pool[value.$p]
    return Object.fromEntries(
      Object.entries(value).map(([key, v]) => [key, PHOTO_FIELDS.has(key) ? photo(v) : revive(v)]),
    )
  }
  const byEntity = new Map()
  for (const p of pool) {
    const key = entityKey(p.entity_type, p.entity_id)
    if (!byEntity.has(key)) byEntity.set(key, p)
  }
  return { ...revive(rest), pool, byEntity }
}

export const entityKey = (type, id) => `${type === 'menu_item' ? 'menu_item' : 'catalog_item'}:${id}`

// La muestra y sus fotos no se suben a git (son datos descargados del catálogo): las escriben `npm run demo:snapshot` y
// `npm run demo:html`. Con un glob, que no falla si el archivo no está, el build normal y los tests no las necesitan.
const SNAPSHOT = import.meta.glob(['./snapshot.json', './photos.json'], { import: 'default' })
let loaded = null

/** La muestra de la demo (se arma una sola vez, al primer uso). */
export async function loadSnapshot() {
  const load = SNAPSHOT['./snapshot.json']
  if (!load) throw new Error('Falta src/api/offline/snapshot.json: corre `npm run demo:snapshot` (ver README).')
  const photos = SNAPSHOT['./photos.json']
  loaded ??= Promise.all([load(), photos ? photos() : null]).then(([raw, found]) => decodeSnapshot(raw, found))
  return loaded
}
