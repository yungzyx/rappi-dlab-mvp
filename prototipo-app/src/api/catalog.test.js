import { afterEach, describe, expect, test, vi } from 'vitest'
import { PLACEHOLDER_IMG } from '../components/Img'
import {
  deals,
  home,
  menu,
  product,
  productStores,
  restaurants,
  store,
  storeForYou,
  storeOfProduct,
  toPrototypeStore,
  verticalStores,
} from './catalog'
import { ApiError, toPrototypeProduct } from './client'
import { fixture, stubApi } from '../test/api'

afterEach(() => vi.unstubAllGlobals())

/** La query de la última petición, como objeto. */
const lastQuery = (fetchMock) => Object.fromEntries(new URL(fetchMock.mock.lastCall[0]).searchParams)
const lastPath = (fetchMock) => new URL(fetchMock.mock.lastCall[0]).pathname

describe('tiendas de una vertical', () => {
  test('verticalStores convierte las tarjetas al formato del prototipo con la vertical del prototipo', async () => {
    const fetchMock = stubApi({ '/catalog/verticals/supermercado/stores': fixture('catalog-vertical-stores') })
    const result = await verticalStores('supermercado')

    expect(result.vertical).toBe('grocery')
    expect(result.stores).toHaveLength(3) // los dos súper y la farmacia que Rappi lista entre ellos
    expect(result.stores[0]).toEqual({
      id: 9101,
      name: 'Supermercado de prueba Centro',
      img: 'https://images.rappi.cl/marketplace/prueba-9101.png',
      logo: true,
      eta: '25 min',
      etaIcon: 'clock',
      vertical: 'grocery',
      hours: { source: 'descarga', open: true, closes_at: null, opens_at: null, opens_tomorrow: false, today: null },
      promos: [
        { type: 'free_shipping', title: 'Envío gratis sobre $15.000 (prueba)', value: 0, threshold: 15000 },
        { type: 'percentage', title: '10% OFF en despensa (prueba)', value: 10, threshold: null },
      ],
      promo: false,
    })
    expect(lastPath(fetchMock)).toBe('/catalog/verticals/supermercado/stores')
  })

  test('verticalStores pide solo las tiendas que se necesitan (limit); sin límite no manda query', async () => {
    const fetchMock = stubApi({ '/catalog/verticals/supermercado/stores': fixture('catalog-vertical-stores') })

    await verticalStores('supermercado')
    expect(lastQuery(fetchMock)).toEqual({})
    await verticalStores('supermercado', { limit: 2 })
    expect(lastQuery(fetchMock)).toEqual({ limit: '2' })
  })

  test('acepta el id del prototipo, que la API traduce', async () => {
    const reply = fixture('catalog-vertical-stores')
    const fetchMock = stubApi({ '/catalog/verticals/liquor/stores': { ...reply, vertical: 'licores' } })
    const result = await verticalStores('liquor')
    expect(result.vertical).toBe('liquor')
    expect(lastPath(fetchMock)).toBe('/catalog/verticals/liquor/stores')
  })

  test('una vertical que la API no conoce falla con el 404, para que la pantalla diga qué pasó', async () => {
    stubApi({ '/catalog/verticals/viajes/stores': 404 })
    await expect(verticalStores('viajes')).rejects.toMatchObject({ kind: 'http', status: 404 })
  })
})

describe('una tienda', () => {
  test('trae la tienda, sus pasillos y la página de productos ya convertidos', async () => {
    const fetchMock = stubApi({ '/catalog/stores/9101': fixture('catalog-store') })
    const result = await store(9101)

    expect(result.store).toMatchObject({
      id: 9101,
      name: 'Supermercado de prueba Centro',
      vertical: 'grocery',
      logo: true,
    })
    expect(result.aisles.map((aisle) => aisle.name)).toEqual([
      'Despensa',
      'Snacks y Dulces',
      'Bebidas',
      'Cuidado del bebé',
      'Cervezas',
    ])
    expect(result.aisle).toEqual({ id: 100, name: 'Despensa', products: 30 })
    expect(result.page).toBe(1)
    expect(result.hasMore).toBe(true)
    expect(result.products).toHaveLength(24)
    expect(result.products[0]).toMatchObject({
      id: 'cat-91111',
      storeId: 9101,
      size: '1 L',
      vertical: 'grocery',
      backendVertical: 'supermercado',
      entityId: '91111',
    })
    expect(lastQuery(fetchMock)).toEqual({})
  })

  test('pide el pasillo y la página que se le indican, y la última página ya no tiene más', async () => {
    const fetchMock = stubApi({ '/catalog/stores/9101': fixture('catalog-store-page-2') })
    const result = await store(9101, { aisle: 100, page: 2 })

    expect(lastQuery(fetchMock)).toEqual({ aisle: '100', page: '2' })
    expect(result.page).toBe(2)
    expect(result.hasMore).toBe(false)
    expect(result.products).toHaveLength(6)
  })

  test('una tienda que no está en el catálogo falla con el 404', async () => {
    stubApi({ '/catalog/stores/7': () => 404 })
    const error = await store(7).catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(404)
  })
})

describe('un producto', () => {
  test('viene en el formato del prototipo, con su presentación y su tienda', async () => {
    const fetchMock = stubApi({ '/catalog/products/catalog_item/91001': fixture('catalog-product') })
    const result = await product('catalog_item', '91001')

    expect(lastPath(fetchMock)).toBe('/catalog/products/catalog_item/91001')
    expect(result).toMatchObject({
      id: 'cat-91001',
      name: 'Papas fritas clásicas 180 g (prueba)',
      price: '$1.990',
      size: '180 g',
      store: 'Supermercado de prueba Centro',
      storeId: 9101,
      entityType: 'catalog_item',
      entityId: '91001',
      etaIcon: 'none',
    })
    expect(result.eta).toBeUndefined()
  })
})

describe('restaurantes', () => {
  test('la tarjeta usa la foto del plato como portada, no como logo, y la vertical del prototipo', async () => {
    stubApi({ '/catalog/restaurants': fixture('catalog-restaurants') })
    const list = await restaurants()

    expect(list).toHaveLength(7)
    expect(list[0]).toEqual({
      id: 9804,
      name: 'Parrilla de prueba',
      img: 'https://imagenes.prueba.invalid/platos/98012.png',
      logo: false,
      eta: '40 min',
      etaIcon: 'clock',
      vertical: 'restaurants',
      rating: '4.8',
      fee: '$2.490',
      // Su horario publicado comparado con la hora fija de los tests del backend (jueves 13:00).
      hours: {
        source: 'horario',
        open: true,
        closes_at: '01:00',
        opens_at: null,
        opens_tomorrow: false,
        today: '12:00–01:00',
      },
      promos: [],
      promo: false,
    })
  })

  test('sin tiempo de entrega, sin nota, sin portada o con envío en $0 no inventa nada', async () => {
    stubApi({ '/catalog/restaurants': fixture('catalog-restaurants') })
    const list = await restaurants()
    const byName = (name) => list.find((card) => card.name === name)

    const noEta = byName('Café de prueba')
    expect(noEta.eta).toBeUndefined()
    expect(noEta.etaIcon).toBe('none')
    expect(noEta.fee).toBe('$1.990')

    const freeLooking = byName('Sushi y hamburguesas de prueba Norte')
    expect(freeLooking.fee).toBeUndefined()
    expect(freeLooking.deliveryLabel).toBeUndefined()
    expect(freeLooking.rating).toBeUndefined()

    const noCover = byName('Cevichería de prueba')
    expect(noCover.img).toBe(PLACEHOLDER_IMG)
    expect(noCover.logo).toBe(false)
    // El horario dice con null lo que no aplica (un abierto no tiene «abre a las»): el resto no inventa nada.
    expect(JSON.stringify(list.map(({ hours: _hours, ...card }) => card))).not.toMatch(/null|undefined/)
  })

  test('manda la cocina, el orden y el límite que se piden, y nada más', async () => {
    const fetchMock = stubApi({ '/catalog/restaurants': [] })
    await restaurants({ cuisine: 'Pizzas', sort: 'eta', limit: 10 })
    expect(lastQuery(fetchMock)).toEqual({ cuisine: 'Pizzas', sort: 'eta', limit: '10' })
    await restaurants()
    expect(lastQuery(fetchMock)).toEqual({})
  })

  test('el menú trae el restaurante y sus secciones con platos del prototipo (store_id es el del restaurante)', async () => {
    const fetchMock = stubApi({ '/catalog/restaurants/9801/menu': fixture('catalog-menu') })
    const result = await menu(9801)

    expect(lastPath(fetchMock)).toBe('/catalog/restaurants/9801/menu')
    expect(result.restaurant).toMatchObject({
      id: 9801,
      name: 'Pizzería de prueba Centro',
      logo: false,
      vertical: 'restaurants',
    })
    expect(result.sections.map((section) => section.name)).toEqual(['Lo más pedido', 'Pizzas', 'Bebidas', 'Postres'])
    const [dish] = result.sections[0].items
    expect(dish).toMatchObject({
      id: 'menu-98002',
      entityType: 'menu_item',
      entityId: '98002',
      storeId: 9801,
      vertical: 'restaurants',
      backendVertical: 'restaurantes',
    })
    const drink = result.sections[2].items[0]
    expect(drink.img).toBe(PLACEHOLDER_IMG)
    expect(drink.size).toBeUndefined()
  })
})

describe('ofertas y Home', () => {
  test('las ofertas son productos del prototipo, de cualquier vertical', async () => {
    const fetchMock = stubApi({ '/catalog/deals': fixture('catalog-deals') })
    const list = await deals()

    expect(lastQuery(fetchMock)).toEqual({})
    expect(list).toHaveLength(9)
    expect(list[0]).toMatchObject({ id: 'cat-91002', discount: '-25%', before: '$1.790', vertical: 'grocery' })
    expect(list[1]).toMatchObject({ id: 'cat-92002', vertical: 'express', backendVertical: 'conveniencia' })
  })

  test('las ofertas de una vertical mandan esa vertical', async () => {
    const fetchMock = stubApi({ '/catalog/deals': [] })
    await deals('liquor')
    expect(lastQuery(fetchMock)).toEqual({ vertical: 'liquor' })
  })

  test('la Home trae sus tres listas ya convertidas', async () => {
    stubApi({ '/catalog/home': fixture('catalog-home') })
    const result = await home()

    expect(result.nearbyStores).toHaveLength(6)
    expect(result.nearbyStores[0]).toMatchObject({ id: 9402, vertical: 'liquor', logo: true })
    expect(result.fastRestaurants).toHaveLength(2)
    expect(result.fastRestaurants[0]).toMatchObject({
      id: 9803,
      vertical: 'restaurants',
      logo: false,
      rating: '4.2',
      fee: '$990',
    })
    expect(result.lowFeeRestaurants).toHaveLength(6)
  })
})

describe('toPrototypeStore', () => {
  test('una tienda sin logo cae en la imagen de reemplazo', () => {
    const card = { id: 1, name: 'Tienda', logo: null, eta: null, products: 3, vertical: 'mall' }
    expect(toPrototypeStore(card)).toEqual({
      id: 1,
      name: 'Tienda',
      img: PLACEHOLDER_IMG,
      logo: true,
      etaIcon: 'none',
      vertical: 'retail',
      hours: null,
      promos: [],
      promo: false,
    })
  })

  test('una vertical que el prototipo no conoce queda con su código', () => {
    const card = { id: 1, name: 'T', logo: 'x.png', eta: '10 min', products: 1, vertical: 'otra' }
    expect(toPrototypeStore(card).vertical).toBe('otra')
  })
})

describe('storeOfProduct', () => {
  test('la tienda de un producto de la API se abre por su id, con la vertical del prototipo', () => {
    const [cola] = fixture('catalog-deals')
    expect(storeOfProduct(toPrototypeProduct(cola))).toEqual({
      id: 9102,
      name: 'Supermercado de prueba Norte',
      vertical: 'grocery',
    })
  })
})

describe('descubrimiento', () => {
  test('los filtros de restaurantes viajan como parámetros de la API', async () => {
    const fetchMock = stubApi({ '/catalog/restaurants': fixture('catalog-restaurants-filtros') })
    const list = await restaurants({ sort: 'recommended', maxEta: 35, minRating: 4.5, top: true, promo: true })
    expect(lastQuery(fetchMock)).toEqual({
      sort: 'recommended',
      max_eta: '35',
      min_rating: '4.5',
      top: 'true',
      promo: 'true',
    })
    expect(list.map((card) => card.name)).toEqual(['Parrilla de prueba', 'Pizzería de prueba Centro'])
  })

  test('productStores: cada tienda con sus marcas y su lugar en la ficha', async () => {
    const fetchMock = stubApi({ '/catalog/products/catalog_item/92002/stores': fixture('catalog-product-stores') })
    const reply = await productStores('92002', 9201)
    expect(lastQuery(fetchMock)).toEqual({ store_id: '9201' })
    expect(reply.count).toBe(4)
    expect(reply.stores[0]).toMatchObject({
      storeId: 9201,
      store: 'Tienda express de prueba Centro',
      vertical: 'express',
      price: '$1.490',
      eta: '25 min',
      fee: '$990',
      bestPrice: true,
      fastest: true,
      available: true,
      placement: { surface: 'store', origin: 'comparar-tiendas', position: 0 },
    })
    expect(reply.here).toBeNull()
  })

  test('productStores: agotado en la tienda trae los similares ya en el formato del prototipo', async () => {
    stubApi({ '/catalog/products/catalog_item/91101/stores': fixture('catalog-product-stores-agotado') })
    const reply = await productStores('91101', 9101)
    expect(reply.here).toMatchObject({ storeId: 9101, available: false })
    expect(reply.similar[0]).toMatchObject({ entityId: expect.any(String), storeId: 9101, vertical: 'grocery' })
    expect(reply.similar[0].placement.origin).toBe('similares')
  })

  test('storeForYou: los productos de la tienda con su lugar y el id de la respuesta', async () => {
    const fetchMock = stubApi({ '/catalog/stores/9201/para-ti': fixture('catalog-store-para-ti') })
    const reply = await storeForYou(9201, 'u-afin')
    expect(lastQuery(fetchMock)).toEqual({ user_id: 'u-afin' })
    expect(reply.products.map((p) => p.entityId)).toEqual(['92002'])
    expect(reply.products[0].placement).toEqual({
      surface: 'store',
      origin: 'para-ti',
      position: 0,
      requestId: 'contrato-catalog-store-para-ti',
    })
  })
})
