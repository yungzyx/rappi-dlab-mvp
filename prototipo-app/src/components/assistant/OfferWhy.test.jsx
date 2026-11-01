import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import OfferWhy from './OfferWhy'

const events = { track: vi.fn() }
vi.mock('../../state/EventsContext', () => ({ useEvents: () => events }))

afterEach(() => {
  cleanup()
  events.track.mockClear()
})

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

  test('with the origin of its offer, opening it is an offer_why_open with the sources of the reason, not its text', () => {
    const reason = {
      text: 'Porque pides café cada 7 días.',
      concept: 'cafe',
      basis: [{ id: 'cafe', kind: 'recompra', source: 'pedidos' }],
    }
    render(<OfferWhy reason={reason} origin="agent-recompra" />)
    const toggle = screen.getByRole('button', { name: '¿Por qué?' })
    fireEvent.click(toggle)
    fireEvent.click(toggle) // cerrarlo no se anota
    expect(events.track.mock.calls).toEqual([
      ['offer_why_open', { origin: 'agent-recompra', concept_id: 'cafe', payload: { basis: ['recompra'] } }],
    ])
  })

  test('without an origin (not an offer), opening it is not tracked', () => {
    render(<OfferWhy reason={{ text: 'Porque pides seguido en farmacia.' }} />)
    fireEvent.click(screen.getByRole('button', { name: '¿Por qué?' }))
    expect(events.track).not.toHaveBeenCalled()
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
