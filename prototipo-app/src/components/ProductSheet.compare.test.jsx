import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { stubApi } from '../test/api'
import { AssistantProvider } from '../state/AssistantContext'
import { CartProvider } from '../state/CartContext'
import { DemoProvider } from '../state/DemoContext'
import { ProductSheetProvider } from '../state/ProductSheetContext'
import { ProfileProvider } from '../state/ProfileContext'
import ProductRow from './ProductRow'
import ProductSheet from './ProductSheet'

const events = vi.hoisted(() => ({ track: vi.fn(), flush: async () => {}, clear: () => {}, settled: async () => {} }))
vi.mock('../state/EventsContext', async (importOriginal) => ({ ...(await importOriginal()), useEvents: () => events }))

const chocolate = {
  id: 'cat-92002',
  name: 'Chocolate con leche 100 g (prueba)',
  img: '',
  price: '$1.590',
  store: 'Tienda express de prueba Oriente',
  storeId: 9202,
  vertical: 'express',
  entityType: 'catalog_item',
  entityId: '92002',
}

const offer = (storeId, store, price, extra = {}) => ({
  store_id: storeId,
  store,
  logo: null,
  vertical: 'conveniencia',
  price,
  price_value: Number(price.slice(1).replace('.', '')),
  before: null,
  eta: '25 min',
  eta_minutes: 25,
  fee: '$990',
  available: true,
  low_stock: false,
  best_price: false,
  fastest: false,
  ...extra,
})

const compare = {
  count: 2,
  stores: [
    offer(9201, 'Tienda express de prueba Centro', '$1.490', { best_price: true, fastest: true }),
    offer(9202, 'Tienda express de prueba Oriente', '$1.590', { low_stock: true }),
  ],
  here: offer(9202, 'Tienda express de prueba Oriente', '$1.590', { low_stock: true }),
  similar: [],
}

function renderRow(product) {
  render(
    <DemoProvider>
      <ProfileProvider>
        <AssistantProvider>
          <CartProvider>
            <ProductSheetProvider>
              <ul>
                <ProductRow product={product} />
              </ul>
              <ProductSheet />
            </ProductSheetProvider>
          </CartProvider>
        </AssistantProvider>
      </ProfileProvider>
    </DemoProvider>,
  )
  fireEvent.click(screen.getByText(product.name))
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('la ficha compara el producto entre tiendas', () => {
  test('«Disponible en N tiendas» con precio, tiempo, envío y las marcas; «Pocas unidades» en la suya', async () => {
    const fetchMock = stubApi({ '/catalog/products/catalog_item/92002/stores': compare })
    renderRow(chocolate)
    const block = within(await screen.findByRole('region', { name: 'Comparar tiendas' }))
    expect(block.getByText('Disponible en 2 tiendas')).toBeTruthy()
    expect(block.getByText('Mejor precio')).toBeTruthy()
    expect(block.getByText('Más rápido')).toBeTruthy()
    expect(block.getAllByText('25 min · Envío $990')).toHaveLength(2)
    expect(screen.getAllByText('Pocas unidades').length).toBeGreaterThan(0)
    expect(new URL(fetchMock.mock.calls[0][0]).searchParams.get('store_id')).toBe('9202')
    // Elegir la otra tienda abre el producto con su precio y su tienda.
    fireEvent.click(block.getByText('Tienda express de prueba Centro'))
    await waitFor(() => expect(screen.getByRole('button', { name: /Agregar 1 · \$1\.490/ })).toBeTruthy())
  })

  test('agotado en su tienda: no se agrega y ofrece los similares de esa tienda', async () => {
    const similar = {
      id: 'cat-92005',
      entity_type: 'catalog_item',
      entity_id: '92005',
      name: 'Otro chocolate (prueba)',
      vertical: 'conveniencia',
      concept: 'chocolates',
      price: '$1.190',
      price_value: 1190,
      before: null,
      discount: null,
      store: 'Tienda express de prueba Oriente',
      img: null,
      age_restricted: false,
      store_id: 9202,
      presentation: null,
    }
    const soldOut = {
      count: 1,
      stores: [compare.stores[0]],
      here: { ...compare.here, available: false, low_stock: false },
      similar: [similar],
    }
    stubApi({ '/catalog/products/catalog_item/*': soldOut })
    renderRow(chocolate)
    expect(await screen.findByRole('button', { name: 'Agotado en esta tienda' })).toHaveProperty('disabled', true)
    fireEvent.click(
      within(screen.getByRole('list', { name: 'Productos similares' })).getByText('Otro chocolate (prueba)'),
    )
    await waitFor(() => expect(screen.getByRole('button', { name: /Agregar 1 · \$1\.190/ })).toBeTruthy())
  })

  test('un plato no pregunta por otras tiendas', () => {
    const fetchMock = stubApi({})
    renderRow({ ...chocolate, entityType: 'menu_item', entityId: '98001' })
    expect(fetchMock.mock.calls.filter(([url]) => url.includes('/stores'))).toHaveLength(0)
  })
})
