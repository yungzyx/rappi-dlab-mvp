import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { toPrototypeProduct } from '../../api/client'
import { fixture } from '../../test/api'
import DiscoverSection from './DiscoverSection'

afterEach(cleanup)

const rows = () =>
  fixture('recommendations').rows.map((row) => ({ ...row, products: row.products.map(toPrototypeProduct) }))

test('muestra una tarjeta por fila de recomendaciones y abre su vertical', () => {
  const onOpen = vi.fn()
  render(<DiscoverSection rows={rows()} onOpen={onOpen} />)

  expect(screen.getByRole('heading', { name: 'Descubre con Mochi' })).toBeTruthy()
  const [card] = document.querySelectorAll('.discover-card')
  expect(card.textContent).toContain('Por tu interés en 🍕 pizza')
  expect(card.textContent).toContain('Gaseosas en Express')
  fireEvent.click(card)
  expect(onOpen).toHaveBeenCalledWith('express')
})

test('la fila de lo más pedido (sin concepto) se titula con su vertical', () => {
  const onOpen = vi.fn()
  render(<DiscoverSection rows={rows()} onOpen={onOpen} />)

  const card = document.querySelectorAll('.discover-card')[1]
  expect(card.textContent).toContain('Lo más pedido estas semanas en el súper')
  expect(card.textContent).toContain('Lo más pedido en Súper')
  fireEvent.click(card)
  expect(onOpen).toHaveBeenCalledWith('grocery')
})

test('no muestra nada sin filas, ni filas de una vertical que la app no conoce', () => {
  const unknown = rows().map((row) => ({ ...row, prototype_vertical: null }))
  render(<DiscoverSection rows={unknown} onOpen={() => {}} />)
  expect(screen.queryByText('Descubre con Mochi')).toBeNull()
  cleanup()
  render(<DiscoverSection rows={[]} onOpen={() => {}} />)
  expect(screen.queryByText('Descubre con Mochi')).toBeNull()
})
