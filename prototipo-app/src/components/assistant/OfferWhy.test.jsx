import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import OfferWhy from './OfferWhy'

afterEach(cleanup)

describe('¿Por qué? de una oferta', () => {
  test('shows the reason on tap', () => {
    render(<OfferWhy reason={{ text: 'Para completar lo que llevas.', basis: [] }} />)
    const toggle = screen.getByRole('button', { name: '¿Por qué?' })
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(screen.queryByText('Para completar lo que llevas.')).toBeNull()

    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByText('Para completar lo que llevas.')).toBeTruthy()

    fireEvent.click(toggle)
    expect(screen.queryByText('Para completar lo que llevas.')).toBeNull()
  })

  test('tells its owner when it opens and closes', () => {
    const onToggle = vi.fn()
    render(<OfferWhy reason={{ text: 'Porque sí.' }} onToggle={onToggle} />)
    const toggle = screen.getByRole('button', { name: '¿Por qué?' })
    fireEvent.click(toggle)
    fireEvent.click(toggle)
    expect(onToggle.mock.calls).toEqual([[true], [false]])
  })

  test('renders nothing without text', () => {
    const { container, rerender } = render(<OfferWhy reason={undefined} />)
    expect(container.innerHTML).toBe('')
    rerender(<OfferWhy reason={{ concept: 'cerveza' }} />)
    expect(container.innerHTML).toBe('')
    rerender(<OfferWhy reason={{ text: '' }} />)
    expect(container.innerHTML).toBe('')
  })
})
