import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'
import { AssistantProvider, useAssistant } from './AssistantContext'
import { DemoProvider, useDemo } from './DemoContext'

function Probe() {
  const assistant = useAssistant()
  const demo = useDemo()
  return (
    <>
      <button type="button" onClick={() => assistant.open()}>
        abrir
      </button>
      <button type="button" onClick={demo.toggle}>
        cambiar modo
      </button>
      <output>{assistant.isOpen ? 'abierto' : 'cerrado'}</output>
    </>
  )
}

afterEach(() => {
  cleanup()
  localStorage.clear()
})

test('al pasar a "Rappi hoy" el buscador con Mochi se cierra, y volver atrás no lo reabre ahí', () => {
  render(
    <DemoProvider>
      <AssistantProvider>
        <Probe />
      </AssistantProvider>
    </DemoProvider>,
  )
  fireEvent.click(screen.getByText('abrir'))
  expect(screen.getByText('abierto')).toBeTruthy()
  fireEvent.click(screen.getByText('cambiar modo'))
  expect(screen.getByText('cerrado')).toBeTruthy()
  act(() => window.dispatchEvent(new PopStateEvent('popstate', { state: { assistant: true } })))
  expect(screen.getByText('cerrado')).toBeTruthy()

  // En la propuesta, volver a su entrada del historial sí lo reabre.
  fireEvent.click(screen.getByText('cambiar modo'))
  act(() => window.dispatchEvent(new PopStateEvent('popstate', { state: { assistant: true } })))
  expect(screen.getByText('abierto')).toBeTruthy()
})
