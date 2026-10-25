import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { ToastProvider } from '../../components/Toast'
import { AddressProvider } from '../../state/AddressContext'
import FavorScreen from './FavorScreen'

afterEach(cleanup)

const renderFavor = (back = vi.fn()) =>
  render(
    <ToastProvider>
      <AddressProvider>
        <FavorScreen back={back} />
      </AddressProvider>
    </ToastProvider>,
  )

describe('FavorScreen', () => {
  test('muestra los tres usos de RappiFavor', () => {
    renderFavor()
    expect(screen.getByText('Envíos de un punto a otro')).toBeTruthy()
    expect(screen.getByText('Compras en cualquier tienda')).toBeTruthy()
    expect(screen.getByText('Trámites rápidos')).toBeTruthy()
  })

  test('pedir un favor exige decir qué hay que hacer y confirma', () => {
    renderFavor()
    fireEvent.click(screen.getByText('Envíos de un punto a otro'))
    fireEvent.click(screen.getByRole('button', { name: 'Pedir RappiFavor' }))
    expect(screen.getByText('Cuéntanos qué hay que hacer')).toBeTruthy()

    fireEvent.change(screen.getByLabelText('Qué hay que hacer'), { target: { value: 'Llevar unas llaves' } })
    fireEvent.change(screen.getByLabelText('Retiro en'), { target: { value: 'Av. Providencia 1234' } })
    fireEvent.click(screen.getByRole('button', { name: 'Pedir RappiFavor' }))
    expect(screen.getByText(/Un Rappitendero va en camino/)).toBeTruthy()
  })

  test('vuelve atrás', () => {
    const back = vi.fn()
    renderFavor(back)
    fireEvent.click(screen.getByRole('button', { name: 'Volver' }))
    expect(back).toHaveBeenCalled()
  })
})
