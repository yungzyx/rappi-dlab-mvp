import { afterEach, describe, expect, test, vi } from 'vitest'
import { PLACEHOLDER_IMG } from '../components/Img'
import {
  API_URL,
  ApiError,
  apiUrl,
  beaconEvents,
  ask,
  checkConnection,
  ensureSession,
  forget,
  health,
  profile,
  recommendations,
  resetHealthCache,
  toMessage,
  toPrototypeProduct,
} from './client'
import { lineKey } from '../state/CartContext'
import { fixture, stubApi } from '../test/api'
import { userId, userToken } from './user'

const API_PRODUCT = {
  id: 'cat-200',
  entity_type: 'catalog_item',
  entity_id: '200',
  name: 'Cerveza Escudo Lata 470 cc',
  vertical: 'licores',
  concept: 'cerveza',
  price: '$1.290',
  price_value: 1290,
  before: '$1.590',
  discount: '-19%',
  store: 'Botillería',
  img: 'https://images.rappi.cl/products/escudo.png',
  age_restricted: true,
}

afterEach(() => {
  vi.unstubAllGlobals()
  resetHealthCache()
  localStorage.clear()
})

describe('de la API al prototipo', () => {
  test('un producto conserva los ids del catálogo real para eventos y pedidos', () => {
    const product = toPrototypeProduct(API_PRODUCT)
    expect(product).toMatchObject({
      id: 'cat-200',
      price: '$1.290',
      discount: '-19%',
      entityId: '200',
      concept: 'cerveza',
    })
    expect(product.ageRestricted).toBe(true)
  })

  test('un producto lleva la vertical del prototipo, guarda la del backend y trae su tienda y presentación', () => {
    expect(toPrototypeProduct(fixture('catalog-product'))).toMatchObject({
      vertical: 'grocery',
      backendVertical: 'supermercado',
      storeId: 9101,
      size: '180 g',
      etaIcon: 'none',
    })
    // La API no sabe el tiempo de entrega de un producto: no se inventa uno.
    expect(toPrototypeProduct(fixture('catalog-product')).eta).toBeUndefined()
    // Una vertical que el prototipo no conoce queda con su código.
    expect(toPrototypeProduct({ ...API_PRODUCT, vertical: 'otra' })).toMatchObject({
      vertical: 'otra',
      backendVertical: 'otra',
    })
    // Un plato no trae presentación ni siempre foto: no queda «undefined» ni «null» a la vista.
    const dish = toPrototypeProduct(fixture('catalog-menu').sections[2].items[0])
    expect(dish.size).toBeUndefined()
    expect(dish.img).toBe(PLACEHOLDER_IMG)
  })

  test('un producto de la API cae en la misma línea del carrito que el mismo producto agregado desde otra pantalla', () => {
    const dict = fixture('catalog-product')
    const fromScreen = toPrototypeProduct(dict)
    const fromOtherScreen = toPrototypeProduct(structuredClone(dict))
    const fromAsk = toMessage({ text: 'Mira', products: [dict] }).products[0]
    expect(lineKey(fromOtherScreen)).toBe(lineKey(fromScreen))
    expect(lineKey(fromAsk)).toBe(lineKey(fromScreen))
    expect(lineKey(fromScreen)).toBe('cat-91001|9101') // la oferta es producto + tienda: la vertical depende de la pantalla
  })

  test('la sugerencia cruzada va aparte, marcada, y las aclaraciones vuelven a preguntar', () => {
    const message = toMessage({
      text: 'Mira estas opciones',
      products: [API_PRODUCT],
      reason: 'Porque llevas 🍺 cerveza',
      suggestion: {
        reason: 'Porque llevas 🍺 cerveza',
        concept: 'snacks-salados',
        vertical: 'supermercado',
        prototype_vertical: 'grocery',
        products: [API_PRODUCT],
      },
      actions: [{ label: 'Pedir de un restaurante', query: 'pizza', vertical: 'restaurantes' }],
      intent: { concepts: ['cerveza'] },
      unmet: false,
    })
    expect(message.source).toBe('api')
    expect(message.reason).toBeNull() // la razón se muestra con la sugerencia, no dos veces
    expect(message.suggestion).toMatchObject({ vertical: 'supermercado', concept: 'snacks-salados' })
    expect(message.suggestion.products[0].fromSuggestion).toBe(true)
    expect(message.actions[0]).toEqual({
      label: 'Pedir de un restaurante',
      ask: { text: 'pizza', vertical: 'restaurantes' },
    })
  })

  test('«Ir a Farmacia» (una vertical sin pregunta) lleva a su pantalla', () => {
    const message = toMessage({ text: 'No puedo…', actions: [{ label: 'Ir a Farmacia', vertical: 'farmacia' }] })
    expect(message.actions).toEqual([{ label: 'Ir a Farmacia', route: ['vertical', { id: 'pharmacy' }] }])
  })

  test('la sugerencia dice de qué vertical viene y a qué pantalla lleva', () => {
    const from = (vertical, prototypeVertical) =>
      toMessage({
        text: 'Mira',
        suggestion: { concept: 'x', vertical, prototype_vertical: prototypeVertical, products: [] },
      }).suggestion
    expect(from('licores', 'liquor')).toMatchObject({ verticalLabel: 'Licores', route: ['vertical', { id: 'liquor' }] })
    expect(from('turbo', 'express')).toMatchObject({ verticalLabel: 'Turbo', route: ['turbo'] })
    expect(from('restaurantes', 'restaurants')).toMatchObject({ verticalLabel: 'Restaurantes', route: ['restaurants'] })
    expect(from('chocolateria', 'chocolates')).toMatchObject({
      verticalLabel: 'Chocolatería',
      route: ['vertical', { id: 'chocolates' }],
    })
  })

  test('"también en": otras verticales con su nombre, su pantalla y sus tiendas', () => {
    const message = toMessage({
      text: 'Mira',
      also_in: {
        concept: 'cerveza',
        label: '🍺 Cerveza',
        verticals: [
          {
            vertical: 'supermercado',
            prototype_vertical: 'grocery',
            items: 262,
            stores: [{ name: 'Unimarc', logo: 'https://x/u.png' }],
          },
          {
            vertical: 'turbo',
            prototype_vertical: 'express',
            items: 50,
            stores: [{ name: 'Rappi Drinks', logo: null }],
          },
        ],
      },
    })
    expect(message.alsoIn.label).toBe('🍺 Cerveza')
    expect(message.alsoIn.verticals).toEqual([
      {
        label: 'Súper',
        route: ['vertical', { id: 'grocery' }],
        items: 262,
        stores: [{ name: 'Unimarc', logo: 'https://x/u.png' }],
      },
      { label: 'Turbo', route: ['turbo'], items: 50, stores: [{ name: 'Rappi Drinks', logo: null }] },
    ])
    expect(toMessage({ text: 'Mira' }).alsoIn).toBeNull()
  })

  test('la sugerencia se registra con el código del backend: Turbo no se confunde con conveniencia', () => {
    const message = toMessage({
      text: 'Mira',
      suggestion: { concept: 'snacks-salados', vertical: 'turbo', prototype_vertical: 'express', products: [] },
    })
    expect(message.suggestion.vertical).toBe('turbo')
  })

  test('el aviso +18 viaja al mensaje y a cada tarjeta', () => {
    const message = toMessage({ text: 'Mira', products: [API_PRODUCT], age_notice: true })
    expect(message.ageNotice).toBe(true)
    expect(message.products[0].ageRestricted).toBe(true)
  })
})

describe('health', () => {
  test('sin API responde null (la app muestra «Sin conexión») y lo cachea', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    vi.stubGlobal('fetch', fetchMock)
    expect(await health()).toBeNull()
    expect(await health()).toBeNull()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  test('con API devuelve sus capacidades', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue({ ok: true, json: async () => ({ ok: true, capacidades: { voz: true, fotos: false } }) }),
    )
    expect(await health({ force: true })).toEqual({ voz: true, fotos: false })
  })

  test('si una pregunta al agente falla, la siguiente pregunta vuelve a revisar la API en vez de fiarse del caché', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ capacidades: { voz: true } }) })
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce({ ok: true, json: async () => ({ capacidades: { voz: true } }) })
    vi.stubGlobal('fetch', fetchMock)
    await health()
    await expect(ask({ message: 'cerveza' })).rejects.toThrow()

    await health()

    expect(fetchMock).toHaveBeenCalledTimes(3) // health, ask y health de nuevo (sin esperar los 30 s del caché)
  })
})

describe('ask', () => {
  test('ask llama a /agent/ask', async () => {
    const seen = []
    stubApi({
      'POST /agent/ask': (req) => {
        seen.push({ path: req.path, body: req.body })
        return { text: 'Mira' }
      },
    })
    expect(await ask({ message: 'cerveza' })).toEqual({ text: 'Mira' })
    expect(seen).toEqual([{ path: '/agent/ask', body: { message: 'cerveza' } }])
  })

  test('se rinde a los 8 s con un error de tiempo agotado, para que el agente muestre «Sin conexión» con «Reintentar»', async () => {
    vi.useFakeTimers()
    try {
      vi.stubGlobal(
        'fetch',
        vi.fn(
          (_url, { signal }) =>
            new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('abortado')))),
        ),
      )
      const pending = ask({ message: 'cerveza' })
      const outcome = expect(pending).rejects.toMatchObject({ kind: 'timeout' })
      await vi.advanceTimersByTimeAsync(7999)
      await vi.advanceTimersByTimeAsync(1)
      await outcome
    } finally {
      vi.useRealTimers()
    }
  })
})

const failure = (promise) =>
  promise.then(
    () => null,
    (error) => error,
  )

describe('errores de la API', () => {
  test('una respuesta 500 es ApiError http con su estado', async () => {
    stubApi({ 'POST /agent/ask': 500 })
    const error = await failure(ask({ message: 'cerveza' }))
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ kind: 'http', status: 500 })
  })

  test('sin red es ApiError offline', async () => {
    stubApi({ 'POST /agent/ask': 'offline' })
    const error = await failure(ask({ message: 'cerveza' }))
    expect(error).toBeInstanceOf(ApiError)
    expect(error.kind).toBe('offline')
  })

  test('pasado el tiempo límite es ApiError timeout', async () => {
    vi.useFakeTimers()
    try {
      stubApi({ 'POST /agent/ask': 'slow:60000' })
      const outcome = failure(ask({ message: 'cerveza' }))
      await vi.advanceTimersByTimeAsync(8000)
      const error = await outcome
      expect(error).toBeInstanceOf(ApiError)
      expect(error.kind).toBe('timeout')
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('checkConnection', () => {
  test('checkConnection con la API arriba devuelve ok y sus capacidades', async () => {
    const body = fixture('health')
    stubApi({ '/health': body })
    expect(await checkConnection()).toEqual({ ok: true, capabilities: body.capacidades, documents: body.documentos })
  })

  test('lo que aprendió la puerta lo comparte health(): sin otra llamada a la red', async () => {
    const body = fixture('health')
    const fetchMock = stubApi({ '/health': body })
    await checkConnection()
    expect(await health()).toEqual(body.capacidades)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  test('checkConnection exige ok: true en /health', async () => {
    // Otro servidor que contesta JSON en /health no es la API del agente.
    stubApi({ '/health': { capacidades: { voz: true }, documentos: 3 } })
    expect(await checkConnection()).toEqual({ ok: false, kind: 'offline' })
    stubApi({ '/health': { ok: false, capacidades: { voz: true }, documentos: 3 } })
    expect(await checkConnection()).toEqual({ ok: false, kind: 'offline' })
    stubApi({ '/health': 204 })
    expect(await checkConnection()).toEqual({ ok: false, kind: 'offline' })
    stubApi({ '/health': { ok: true, capacidades: { voz: true }, documentos: 3 } })
    expect(await checkConnection()).toMatchObject({ ok: true, documents: 3 })
  })

  test('checkConnection sin API devuelve ok: false y el motivo', async () => {
    stubApi({ '/health': 'offline' })
    expect(await checkConnection()).toEqual({ ok: false, kind: 'offline' })
    stubApi({ '/health': 500 })
    expect(await checkConnection()).toEqual({ ok: false, kind: 'http' })
  })

  test('health con 503 cuenta como sin conexión', async () => {
    // La API viva pero no lista (sin base, sin documentos, migraciones pendientes) contesta 503 con { ok: false, motivos }.
    stubApi({ '/health': 503 })
    expect(await checkConnection()).toEqual({ ok: false, kind: 'http' })
    resetHealthCache()
    expect(await health({ force: true })).toBeNull()
  })

  test('checkConnection no espera a una API más lenta que su tiempo límite', async () => {
    vi.useFakeTimers()
    try {
      stubApi({ '/health': 'slow:6000' })
      const outcome = checkConnection()
      await vi.advanceTimersByTimeAsync(5000)
      expect(await outcome).toEqual({ ok: false, kind: 'timeout' })
    } finally {
      vi.useRealTimers()
    }
  })

  test('una API lenta pero dentro del tiempo límite responde con sus capacidades', async () => {
    vi.useFakeTimers()
    try {
      stubApi({ '/health': 'slow:3000' })
      const outcome = checkConnection()
      await vi.advanceTimersByTimeAsync(3000)
      expect(await outcome).toMatchObject({ ok: true, documents: fixture('health').documentos })
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('stubApi', () => {
  test('lo que no está en las rutas responde 404, y una ruta sin método es GET', async () => {
    const fetchMock = stubApi({ '/health': fixture('health') })
    expect(await failure(ask({ message: 'cerveza' }))).toMatchObject({ kind: 'http', status: 404 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect((await checkConnection()).ok).toBe(true)
  })

  test('stubApi distingue GET de POST en la misma ruta', async () => {
    stubApi({ '/orders': { via: 'get' }, 'POST /orders': { via: 'post' } })
    const call = (method) => fetch(`${API_URL}/orders`, { method }).then((response) => response.json())
    expect(await call('GET')).toEqual({ via: 'get' })
    expect(await call('POST')).toEqual({ via: 'post' })

    // También cuando cada método responde con una función.
    stubApi({ 'GET /orders': (req) => ({ via: req.method }), 'POST /orders': (req) => ({ via: req.method }) })
    expect(await call('GET')).toEqual({ via: 'GET' })
    expect(await call('POST')).toEqual({ via: 'POST' })

    stubApi({ 'GET /orders': { via: 'get' } })
    expect((await fetch(`${API_URL}/orders`, { method: 'POST' })).status).toBe(404)
  })

  test('recommendations entrega los productos de cada fila en el formato del prototipo', async () => {
    stubApi({ '/recommendations': fixture('recommendations') })
    const response = await recommendations('u-contrato')
    expect(response.interests).toEqual(['pizza'])
    expect(response.rows[0]).toMatchObject({
      concept: 'gaseosas',
      vertical: 'conveniencia',
      prototype_vertical: 'express',
    })
    expect(response.rows[0].products[0]).toMatchObject({ vertical: 'express', backendVertical: 'conveniencia' })
    expect(response.rows[0].products[0].entityId).toBeTruthy()
  })

  test('stubApi entrega query y cuerpo a una función', async () => {
    const seen = []
    stubApi({
      '/recommendations': (req) => {
        seen.push(req)
        return { user: req.query.get('user_id'), vertical: req.query.get('vertical'), rows: [] }
      },
      'POST /agent/ask': (req) => {
        seen.push(req)
        return req.body.message === 'cerveza' ? { text: 'Mira' } : 500
      },
    })

    expect(await recommendations('proto 1', 'licores')).toEqual({ user: 'proto 1', vertical: 'licores', rows: [] })
    expect(await ask({ message: 'cerveza', vertical: null })).toEqual({ text: 'Mira' })
    expect(await failure(ask({ message: 'pizza' }))).toMatchObject({ kind: 'http', status: 500 })

    expect(seen[0]).toMatchObject({ method: 'GET', path: '/recommendations', body: undefined })
    expect(seen[0].query).toBeInstanceOf(URLSearchParams)
    expect(seen[1]).toMatchObject({ method: 'POST', path: '/agent/ask', body: { message: 'cerveza', vertical: null } })
    expect(seen[1].query.size).toBe(0)
  })

  test('una clave mal escrita en stubApi falla en vez de dar 404', () => {
    for (const key of ['health', 'FETCH /health', 'get /health', 'PATCH /health', 'GET health', '/health?x=1', '']) {
      expect(() => stubApi({ [key]: {} })).toThrow(/^stubApi: clave inválida/)
    }
    expect(() =>
      stubApi({ '/health': {}, 'GET /health2': {}, 'POST /agent/ask': {}, 'PUT /a': {}, 'DELETE /a/b': {} }),
    ).not.toThrow()
  })

  test('un 204 es null, no un error', async () => {
    stubApi({ 'DELETE /profile/proto-1': 204 })
    expect(await forget('proto-1')).toBeNull()

    const response = await fetch(`${API_URL}/profile/proto-1`, { method: 'DELETE' })
    expect(response.status).toBe(204)
    expect(response.body).toBeNull()
  })

  test('un valor {slow, body} responde ese cuerpo pasado el tiempo', async () => {
    vi.useFakeTimers()
    try {
      stubApi({
        '/health': { slow: 3000, body: fixture('health') },
        'DELETE /profile/proto-1': { slow: 100, body: 500 },
      })
      let settled = false
      const connection = checkConnection().then((result) => {
        settled = true
        return result
      })
      await vi.advanceTimersByTimeAsync(2999)
      expect(settled).toBe(false)
      await vi.advanceTimersByTimeAsync(1)
      expect(await connection).toMatchObject({ ok: true })

      const outcome = failure(forget('proto-1'))
      await vi.advanceTimersByTimeAsync(100)
      expect(await outcome).toMatchObject({ kind: 'http', status: 500 })
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('sesión firmada', () => {
  const OLD = 'proto-1111111111111111'
  const NEW = 'proto-2222222222222222'
  const signIn = (id, token) => {
    localStorage.setItem('rappi-proto-user', id)
    localStorage.setItem('rappi-proto-token', token)
  }
  const paths = (api) => api.mock.calls.map(([url, init]) => `${init?.method ?? 'GET'} ${new URL(url).pathname}`)

  test('client manda X-User-Token', async () => {
    signIn(OLD, `${OLD}.firma`)
    const api = stubApi({ '/profile/*': { user_id: OLD, interests: [] } })
    await profile(OLD)
    await health({ force: true })
    expect(api.mock.calls.map(([, init]) => init.headers['X-User-Token'])).toEqual([`${OLD}.firma`, `${OLD}.firma`])
  })

  test('sin sesión no inventa la cabecera', async () => {
    const api = stubApi({ '/health': fixture('health') })
    await health({ force: true })
    expect(api.mock.calls[0][1].headers?.['X-User-Token']).toBeUndefined()
  })

  test('un 401 renueva la sesión una sola vez', async () => {
    signIn(OLD, `${OLD}.de-otro-secreto`)
    const api = stubApi({
      'POST /session': (req) => {
        expect(req.body).toEqual({ legacy_user_id: OLD })
        return { user_id: NEW, token: `${NEW}.firma` }
      },
      'GET /profile/*': (req) => (req.path === `/profile/${NEW}` ? { user_id: NEW, interests: [] } : 401),
    })
    // Dos peticiones a la vez con el token viejo: una sola sesión nueva, y cada una se repite como la persona nueva
    const [first, second] = await Promise.all([profile(OLD), profile(OLD)])
    expect(first.user_id).toBe(NEW)
    expect(second.user_id).toBe(NEW)
    expect(paths(api).filter((p) => p === 'POST /session')).toHaveLength(1)
    expect(userId()).toBe(NEW)
    expect(userToken()).toBe(`${NEW}.firma`)
    const retried = api.mock.calls.filter(([url]) => url.endsWith(`/profile/${NEW}`))
    expect(retried.map(([, init]) => init.headers['X-User-Token'])).toEqual([`${NEW}.firma`, `${NEW}.firma`])
  })

  test('un 401 que llega después de renovar no pide otra sesión y se repite desde el id con que salió', async () => {
    signIn(OLD, `${OLD}.vencido`)
    let oldCalls = 0
    const api = stubApi({
      'POST /session': { user_id: NEW, token: `${NEW}.firma` },
      'GET /profile/*': (req) => {
        if (req.path === `/profile/${NEW}`) return { user_id: NEW, interests: [] }
        oldCalls += 1
        return oldCalls === 1 ? 401 : { slow: 30, body: 401 } // el segundo, con el token viejo, contesta tarde
      },
    })
    const first = profile(OLD)
    const late = profile(OLD)
    expect((await first).user_id).toBe(NEW)
    expect((await late).user_id).toBe(NEW)
    expect(paths(api).filter((p) => p === 'POST /session')).toHaveLength(1)
    expect(userId()).toBe(NEW)
  })

  test('si el reintento también da 401, falla sin pedir otra sesión', async () => {
    signIn(OLD, `${OLD}.vencido`)
    const api = stubApi({ 'POST /session': { user_id: NEW, token: `${NEW}.firma` }, 'GET /profile/*': 401 })
    await expect(profile(OLD)).rejects.toMatchObject({ kind: 'http', status: 401 })
    expect(paths(api)).toEqual([`GET /profile/${OLD}`, 'POST /session', `GET /profile/${NEW}`])
  })

  test('un 403 no renueva la sesión', async () => {
    signIn(OLD, `${OLD}.firma`)
    const api = stubApi({ 'GET /profile/*': 403 })
    await expect(profile('proto-ajeno')).rejects.toMatchObject({ status: 403 })
    expect(paths(api)).toEqual(['GET /profile/proto-ajeno'])
  })

  test('con sesión, ensureSession no vuelve a pedirla', async () => {
    signIn(OLD, `${OLD}.firma`)
    const api = stubApi({})
    await ensureSession()
    expect(api).not.toHaveBeenCalled()
  })
})

describe('usuario compartido', () => {
  test('el usuario guardado conserva su id', () => {
    localStorage.setItem('rappi-proto-user', 'proto-0123456789abcdef')
    expect(userId()).toBe('proto-0123456789abcdef')
  })

  test('un id que se inventa de nuevo no hereda el token de otro (sin token, la API pide sesión con un 401)', () => {
    localStorage.setItem('rappi-proto-token', 'proto-0123456789abcdef.firma') // se perdió el id, quedó el token
    const id = userId()
    expect(id).not.toBe('proto-0123456789abcdef')
    expect(userToken()).toBeNull()
  })
})

describe('envíos', () => {
  test('al cerrar la pestaña los eventos van como text/plain a /events/beacon (sin preflight CORS)', async () => {
    const sendBeacon = vi.fn(() => true)
    Object.defineProperty(navigator, 'sendBeacon', { value: sendBeacon, configurable: true })
    localStorage.setItem('rappi-proto-token', 'proto-1.firma')
    try {
      expect(beaconEvents('proto-1', [{ type: 'app_open', session_id: 's-1' }])).toBe(true)
      const [url, blob] = sendBeacon.mock.calls[0]
      expect(url).toMatch(/\/events\/beacon$/)
      expect(blob.type).toBe('text/plain')
      expect(JSON.parse(await blob.text())).toEqual({
        user_id: 'proto-1',
        events: [{ type: 'app_open', session_id: 's-1' }],
        token: 'proto-1.firma', // sendBeacon no manda cabeceras: el token va en el cuerpo
      })
    } finally {
      delete navigator.sendBeacon
    }
  })
})

describe('apiUrl', () => {
  test('en producción sin variable devuelve /api (el mismo origen)', () => {
    expect(apiUrl({ PROD: true }, { hostname: 'demo.example.cl' })).toBe('/api')
  })

  test('quita la barra final de VITE_API_URL', () => {
    expect(apiUrl({ VITE_API_URL: 'https://api.example.cl/', PROD: true }, {})).toBe('https://api.example.cl')
    expect(apiUrl({ VITE_API_URL: 'https://api.example.cl//' }, {})).toBe('https://api.example.cl')
  })

  test('una variable vacía (el .env.example) cuenta como ausente', () => {
    expect(apiUrl({ VITE_API_URL: '', PROD: true }, {})).toBe('/api')
  })

  test('en desarrollo usa el host de la página en el puerto 8000', () => {
    expect(apiUrl({ PROD: false }, { hostname: '10.0.0.5' })).toBe('http://10.0.0.5:8000')
    expect(apiUrl({ PROD: false }, { hostname: '' })).toBe('http://localhost:8000')
    expect(apiUrl({ PROD: false }, undefined)).toBe('http://localhost:8000')
  })
})
