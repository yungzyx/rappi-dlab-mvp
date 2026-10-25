import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'
import { CartProvider } from '../state/CartContext'
import ProductRow from './ProductRow'

afterEach(cleanup)

const beer = {
  id: 'cat-94001',
  name: 'Cerveza rubia lata 470 cc (prueba)',
  img: '',
  price: '$1.290',
  store: 'Botillería de prueba Centro',
}
const renderRow = (product) =>
  render(
    <CartProvider>
      <ul>
        <ProductRow product={product} />
      </ul>
    </CartProvider>,
  )

test('un producto +18 lleva la marca también en la fila de la tienda (como en la tarjeta)', () => {
  renderRow({ ...beer, ageRestricted: true })
  const badge = screen.getByLabelText('Solo mayores de 18')
  expect(badge.textContent).toBe('+18')
  // La marca va sobre la foto, igual que en ProductCard.
  expect(badge.className).toBe('product-age')
  expect(badge.closest('.product-row-media')).not.toBeNull()
})

test('un producto sin restricción de edad no lleva la marca', () => {
  renderRow({ ...beer, ageRestricted: false })
  expect(screen.queryByLabelText('Solo mayores de 18')).toBeNull()
  cleanup()
  renderRow(beer) // sin el campo
  expect(screen.queryByLabelText('Solo mayores de 18')).toBeNull()
})
