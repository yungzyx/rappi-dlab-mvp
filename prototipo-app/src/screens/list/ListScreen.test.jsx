import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { placeList } from '../../api/attribution'
import ListScreen from './ListScreen'

afterEach(cleanup)

test('cada tienda lleva su lugar en esta lista, no el de la sección de donde vino', () => {
  const push = vi.fn()
  const stores = placeList(
    [
      { id: 9101, name: 'Supermercado de prueba Centro', vertical: 'grocery' },
      { id: 9102, name: 'Supermercado de prueba Norte', vertical: 'grocery' },
    ],
    { surface: 'vertical', origin: 'tiendas' },
  )
  render(<ListScreen back={() => {}} push={push} params={{ title: 'Tiendas', stores }} />)
  fireEvent.click(screen.getByText('Supermercado de prueba Norte'))
  expect(push.mock.calls[0][1].store.placement).toMatchObject({ surface: 'list', origin: 'tiendas', position: 1 })
})
