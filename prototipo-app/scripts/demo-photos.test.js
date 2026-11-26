// @vitest-environment node
import { chmodSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { embedPhotos, PhotosStopped } from './demo-photos.mjs'

const PHOTO = 'https://images.rappi.cl/products/a.png'
const OTHER = 'https://images.rappi.cl/products/b.png'

let dir
beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), 'demo-photos-'))
  writeFileSync(
    join(dir, 'snapshot.json'),
    JSON.stringify({ productFields: ['img'], products: [[PHOTO], [OTHER]], imgPrefix: '' }),
  )
})
afterEach(() => {
  vi.unstubAllGlobals()
  rmSync(dir, { recursive: true, force: true })
})

/** Un "Python del scraper" falso: anota lo que recibe, responde `answer` y espera a que se cierre su entrada. */
function fakeGate(answer) {
  const path = join(dir, 'python')
  writeFileSync(
    path,
    `#!/bin/sh\nread -r line\nprintf '%s' "$line" > '${dir}/asked.json'\necho '${JSON.stringify(answer)}'\ncat > /dev/null\necho closed > '${dir}/closed'\n`,
  )
  chmodSync(path, 0o755)
  return path
}

const webp = () => new Response(new Uint8Array([1, 2, 3]), { headers: { 'content-type': 'image/webp' } })
const run = (python) =>
  embedPhotos(join(dir, 'snapshot.json'), join(dir, 'photos.json'), { cache: `${dir}/cache/`, python })

describe('embedPhotos', () => {
  it('baja de a una, con el User-Agent del scraper, y suelta los candados al terminar', async () => {
    let inFlight = 0
    let most = 0
    const fetchMock = vi.fn(async () => {
      most = Math.max(most, ++inFlight)
      await new Promise((resolve) => setTimeout(resolve, 5))
      inFlight -= 1
      return webp()
    })
    vi.stubGlobal('fetch', fetchMock)
    const result = await run(fakeGate({ user_agent: 'rappi-dlab-scraper/9.9 (prueba)' }))
    expect(result).toMatchObject({ embedded: 2, missing: 0 })
    expect(most).toBe(1)
    expect(fetchMock.mock.calls.map(([, init]) => init.headers['User-Agent'])).toEqual([
      'rappi-dlab-scraper/9.9 (prueba)',
      'rappi-dlab-scraper/9.9 (prueba)',
    ])
    expect(JSON.parse(readFileSync(join(dir, 'asked.json'), 'utf8'))).toHaveLength(2)
    expect(readFileSync(join(dir, 'closed'), 'utf8')).toContain('closed')
  })

  it('con todo en la caché no toma los candados ni pide nada', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => webp()),
    )
    await run(fakeGate({ user_agent: 'ua' }))
    rmSync(join(dir, 'asked.json'))
    vi.stubGlobal('fetch', vi.fn())
    const result = await run(join(dir, 'no-existe'))
    expect(result).toMatchObject({ embedded: 2, missing: 0 })
    expect(fetch).not.toHaveBeenCalled()
  })

  it('si otra descarga tiene el candado, avisa y no baja nada', async () => {
    vi.stubGlobal('fetch', vi.fn())
    const error = await run(fakeGate({ busy: 'Ya hay una descarga en curso contra rappi.cl' })).catch((e) => e)
    expect(error).toBeInstanceOf(PhotosStopped)
    expect(error).toMatchObject({ message: 'Ya hay una descarga en curso contra rappi.cl', exitCode: 1 })
    expect(fetch).not.toHaveBeenCalled()
  })

  it('si robots.txt no permite una foto, sale con 7 sin bajar ninguna', async () => {
    vi.stubGlobal('fetch', vi.fn())
    const error = await run(fakeGate({ denial: 'robots.txt de images.rappi.cl no permite /products/a.png' })).catch(
      (e) => e,
    )
    expect(error).toMatchObject({ exitCode: 7 })
    expect(error.message).toContain('robots.txt de images.rappi.cl no permite')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('no sigue una redirección: robots.txt solo se revisó para la dirección pedida (la foto queda sin bajar)', async () => {
    // Como fetch de Node: con `redirect: 'manual'` entrega el 302; si no, lo sigue y trae la foto de otro lado.
    const fetchMock = vi.fn(async (url, init) =>
      url.startsWith(PHOTO) && init.redirect !== 'manual'
        ? webp()
        : url.startsWith(PHOTO)
          ? new Response(null, { status: 302, headers: { location: 'https://otro.invalid/a.webp' } })
          : webp(),
    )
    vi.stubGlobal('fetch', fetchMock)
    const result = await run(fakeGate({ user_agent: 'ua' }))
    expect(result).toMatchObject({ embedded: 1, missing: 1 })
    expect(fetchMock.mock.calls.every(([, init]) => init.redirect === 'manual')).toBe(true)
  })
})
