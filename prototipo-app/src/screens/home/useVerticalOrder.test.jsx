import { act, cleanup, render, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'
import { fixture, stubApi } from '../../test/api'
import { ProfileProvider, useProfile } from '../../state/ProfileContext'
import { useVerticalOrder } from './useVerticalOrder'

afterEach(cleanup)

const wrapper = ProfileProvider
const requests = (api) => api.mock.calls.filter(([url]) => url.includes('/verticales')).length

test('pide el orden al montar: los códigos del motor y si es personal', async () => {
  stubApi({ 'GET /profile/*': fixture('profile-verticales') })
  const { result } = renderHook(() => useVerticalOrder(), { wrapper })
  await waitFor(() => expect(result.current.personalized).toBe(true))
  expect(result.current.order).toEqual(['farmacia', 'supermercado', 'mall', 'licores', 'conveniencia', 'chocolateria'])
})

test('una persona nueva no es personal', async () => {
  const api = stubApi({ 'GET /profile/*': fixture('profile-verticales-nueva') })
  const { result } = renderHook(() => useVerticalOrder(), { wrapper })
  await waitFor(() => expect(requests(api)).toBe(1))
  await waitFor(() => expect(result.current.order).not.toBeNull())
  expect(result.current.personalized).toBe(false)
})

test('con la API caída: sin orden y sin personalizar', async () => {
  const api = stubApi({ 'GET /profile/*': 'offline' })
  const { result } = renderHook(() => useVerticalOrder(), { wrapper })
  await waitFor(() => expect(requests(api)).toBe(1))
  expect(result.current).toEqual({ order: null, personalized: false })
})

test('al olvidar (cambian las `resets`) queda el orden fijo sin pedir, y la respuesta de antes no lo pisa', async () => {
  let calls = 0
  const api = stubApi({
    'GET /profile/*': () => {
      calls += 1
      // La primera tarda y es personal (de antes de olvidar); la segunda, al volver a la Home, es la de una persona nueva.
      return calls === 1 ? { slow: 300, body: fixture('profile-verticales') } : fixture('profile-verticales-nueva')
    },
  })
  let reset
  function Probe({ active, onResult }) {
    reset = useProfile().reset
    onResult(useVerticalOrder(active))
    return null
  }
  let latest
  const tree = (active) => (
    <ProfileProvider>
      <Probe active={active} onResult={(value) => (latest = value)} />
    </ProfileProvider>
  )
  const { rerender } = render(tree(true))
  await waitFor(() => expect(requests(api)).toBe(1))
  act(() => reset())
  await new Promise((resolve) => setTimeout(resolve, 400)) // la primera ya contestó: es de antes de olvidar
  expect(requests(api)).toBe(1) // el servidor puede no haber borrado todavía: pedir traería el orden de antes
  expect(latest).toEqual({ order: null, personalized: false })
  rerender(tree(false)) // si el borrado falló, la app no se recarga: al volver de otra pantalla pide otra vez
  rerender(tree(true))
  await waitFor(() => expect(requests(api)).toBe(2))
  await waitFor(() => expect(latest.order).not.toBeNull())
  expect(latest.personalized).toBe(false)
  expect(latest.order[0]).toBe('supermercado')
})

test('al volver a estar arriba pide otra vez; mientras llega deja el orden que había, sin parpadear', async () => {
  let calls = 0
  const api = stubApi({
    'GET /profile/*': () => {
      calls += 1
      return calls === 1 ? fixture('profile-verticales-nueva') : { slow: 200, body: fixture('profile-verticales') }
    },
  })
  const { result, rerender } = renderHook(({ active }) => useVerticalOrder(active), {
    wrapper,
    initialProps: { active: true },
  })
  await waitFor(() => expect(result.current.order).not.toBeNull())
  rerender({ active: true })
  await new Promise((resolve) => setTimeout(resolve, 50))
  expect(requests(api)).toBe(1) // seguir arriba no pide de nuevo
  rerender({ active: false })
  rerender({ active: true })
  await waitFor(() => expect(requests(api)).toBe(2))
  expect(result.current).toMatchObject({ personalized: false }) // la respuesta aún no llega: queda el orden de antes
  expect(result.current.order[0]).toBe('supermercado')
  await waitFor(() => expect(result.current.personalized).toBe(true))
  expect(result.current.order[0]).toBe('farmacia')
})
