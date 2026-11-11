import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test } from 'vitest'
import { Help } from './Help.jsx'

describe('Help', () => {
  afterEach(cleanup)

  const renderHelp = () =>
    render(
      <div>
        <Help label="Cómo va">Cada indicador compara la última semana completa.</Help>
        <button type="button">Fuera</button>
      </div>,
    )

  test('opens on demand, closes with Escape and gives the focus back to its button', async () => {
    renderHelp()
    const summary = screen.getByLabelText('Ayuda: Cómo va')
    const details = summary.closest('details')
    expect(details.open).toBe(false)

    await act(async () => fireEvent.click(summary))
    expect(details.open).toBe(true)

    await act(async () => fireEvent.keyDown(document.body, { key: 'Escape' }))
    expect(details.open).toBe(false)
    expect(document.activeElement).toBe(summary)
  })

  test('a pointer down outside closes it, and one inside does not', async () => {
    renderHelp()
    const summary = screen.getByLabelText('Ayuda: Cómo va')
    const details = summary.closest('details')

    await act(async () => fireEvent.click(summary))
    await act(async () => fireEvent.pointerDown(screen.getByText(/Cada indicador compara/)))
    expect(details.open).toBe(true)

    await act(async () => fireEvent.pointerDown(screen.getByRole('button', { name: 'Fuera' })))
    expect(details.open).toBe(false)
  })

  test('with text, the button says it and needs no extra name', () => {
    render(
      <Help label="Qué es real" text="¿Qué es real?">
        La tabla de Rappi.
      </Help>,
    )
    const summary = screen.getByText('¿Qué es real?')
    expect(summary.tagName).toBe('SUMMARY')
    expect(summary.getAttribute('aria-label')).toBeNull()
  })
})
