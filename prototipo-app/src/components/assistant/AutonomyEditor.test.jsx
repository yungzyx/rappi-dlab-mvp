import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from '../../test/api'
import AutonomyEditor from './AutonomyEditor'

const off = () => ({ ...fixture('profile-autonomia'), modo: 'revisar', tiendas: [], tope: null })
const calls = (fetchMock, method) =>
  fetchMock.mock.calls.filter(([url, init]) => url.endsWith('/autonomia') && init?.method === method)

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('"Pedir por mí" en su hoja', () => {
  test('por defecto revisa antes; encenderlo guarda las tiendas elegidas y el tope', async () => {
    const fetchMock = stubApi({
      'GET /profile/*': off(),
      'PUT /profile/*': (req) => ({ ...fixture('profile-autonomia'), tiendas: req.body.tiendas, tope: req.body.tope }),
    })
    const onSaved = vi.fn()
    render(<AutonomyEditor onSaved={onSaved} />)
    expect((await screen.findByRole('radio', { name: /Revisar antes de pedir/ })).getAttribute('aria-checked')).toBe(
      'true',
    )

    fireEvent.click(screen.getByRole('radio', { name: /Pedir por mí/ }))
    const save = screen.getByRole('button', { name: 'Guardar' })
    expect(save.disabled).toBe(true) // sin tiendas elegidas no se guarda
    fireEvent.click(screen.getByRole('button', { name: 'Supermercado de prueba Centro' }))
    fireEvent.change(screen.getByLabelText(/Tope por pedido/), { target: { value: '15000' } })
    fireEvent.click(save)

    await vi.waitFor(() => expect(onSaved).toHaveBeenCalled())
    const [[, init]] = calls(fetchMock, 'PUT')
    expect(JSON.parse(init.body)).toEqual({ tiendas: [9101], tope: 15000 })
    expect(screen.getByText(/nunca alcohol, \+18, farmacia/i)).toBeTruthy()
  })

  test('volver a "Revisar antes de pedir" lo apaga en un toque', async () => {
    const fetchMock = stubApi({ 'GET /profile/*': fixture('profile-autonomia'), 'DELETE /profile/*': off() })
    const onTurnedOff = vi.fn()
    render(<AutonomyEditor onTurnedOff={onTurnedOff} />)
    expect((await screen.findByRole('radio', { name: /Pedir por mí/ })).getAttribute('aria-checked')).toBe('true')

    fireEvent.click(screen.getByRole('radio', { name: /Revisar antes de pedir/ }))
    await vi.waitFor(() => expect(onTurnedOff).toHaveBeenCalled())
    expect(calls(fetchMock, 'DELETE')).toHaveLength(1)
  })

  test('sin pedidos todavía, no hay tiendas que elegir', async () => {
    const empty = off()
    empty.opciones.tiendas = []
    stubApi({ 'GET /profile/*': empty })
    render(<AutonomyEditor />)
    expect(await screen.findByText(/Cuando pidas en una tienda/)).toBeTruthy()
    expect(screen.getByRole('radio', { name: /Pedir por mí/ }).disabled).toBe(true)
  })
})
