import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import OfflineNotice from '../components/OfflineNotice'
import { store } from './catalog'
import { ApiError } from './client'
import { fixture, stubApi } from '../test/api'
import { useApi } from './useApi'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('useApi', () => {
  test('carga al montar y entrega los datos', async () => {
    const { result } = renderHook(() => useApi(() => Promise.resolve({ ok: true }), []))
    expect(result.current).toMatchObject({ loading: true, data: null, error: null })
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current).toMatchObject({ data: { ok: true }, error: null })
  })

  test('useApi muestra el error y reintenta', async () => {
    const failure = new ApiError('offline')
    const load = vi.fn().mockRejectedValueOnce(failure).mockResolvedValueOnce({ ok: true })
    const { result } = renderHook(() => useApi(load, []))

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.error).toBe(failure)
    expect(result.current.data).toBeNull()

    act(() => result.current.retry())
    // El error de la vuelta anterior ya no vale: vuelve a cargar.
    expect(result.current).toMatchObject({ loading: true, error: null, data: null })
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current).toMatchObject({ data: { ok: true }, error: null })
    expect(load).toHaveBeenCalledTimes(2)
  })

  test('un fallo que se lanza sin devolver una promesa también queda como error', async () => {
    const failure = new Error('roto')
    const { result } = renderHook(() =>
      useApi(() => {
        throw failure
      }, []),
    )
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.error).toBe(failure)
  })

  test('useApi ignora una respuesta vieja cuando cambian las dependencias', async () => {
    const calls = { 1: deferred(), 2: deferred() }
    const { result, rerender } = renderHook(({ id }) => useApi(() => calls[id].promise, [id]), {
      initialProps: { id: 1 },
    })
    rerender({ id: 2 })
    // Los datos de la tienda anterior no se muestran bajo la nueva.
    expect(result.current).toMatchObject({ loading: true, data: null })

    await act(async () => calls[2].resolve('segunda'))
    expect(result.current).toMatchObject({ loading: false, data: 'segunda' })

    await act(async () => calls[1].resolve('primera'))
    expect(result.current).toMatchObject({ loading: false, data: 'segunda' })
  })

  test('el error de una llamada vieja tampoco pisa a la nueva', async () => {
    const calls = { 1: deferred(), 2: deferred() }
    const { result, rerender } = renderHook(({ id }) => useApi(() => calls[id].promise, [id]), {
      initialProps: { id: 1 },
    })
    rerender({ id: 2 })
    await act(async () => calls[2].resolve('segunda'))
    await act(async () => calls[1].reject(new ApiError('timeout')))
    expect(result.current).toMatchObject({ loading: false, data: 'segunda', error: null })
  })

  test('al cambiar las dependencias no deja a la vista los datos de la anterior mientras carga la nueva', async () => {
    const second = deferred()
    const { result, rerender } = renderHook(
      ({ id }) => useApi(() => (id === 1 ? Promise.resolve('primera') : second.promise), [id]),
      {
        initialProps: { id: 1 },
      },
    )
    await waitFor(() => expect(result.current.data).toBe('primera'))
    rerender({ id: 2 })
    expect(result.current).toMatchObject({ loading: true, data: null, error: null })
    await act(async () => second.resolve('segunda'))
    expect(result.current).toMatchObject({ loading: false, data: 'segunda' })
  })

  test('useApi sin keepPrevious no cambia', async () => {
    const second = deferred()
    const { result, rerender } = renderHook(
      ({ id }) => useApi(() => (id === 1 ? Promise.resolve('primera') : second.promise), [id]),
      { initialProps: { id: 1 } },
    )
    await waitFor(() => expect(result.current.data).toBe('primera'))
    rerender({ id: 2 })
    expect(result.current).toMatchObject({ loading: true, data: null, error: null })
    await act(async () => second.resolve('segunda'))
    expect(result.current).toMatchObject({ loading: false, data: 'segunda' })
  })

  test('con keepPrevious los datos anteriores siguen a la vista mientras carga la nueva', async () => {
    const second = deferred()
    const { result, rerender } = renderHook(
      ({ id }) => useApi(() => (id === 1 ? Promise.resolve('primera') : second.promise), [id], { keepPrevious: true }),
      { initialProps: { id: 1 } },
    )
    expect(result.current).toMatchObject({ loading: true, data: null })
    await waitFor(() => expect(result.current.data).toBe('primera'))

    rerender({ id: 2 })
    expect(result.current).toMatchObject({ loading: true, data: 'primera', error: null })
    await act(async () => second.resolve('segunda'))
    expect(result.current).toMatchObject({ loading: false, data: 'segunda' })
  })

  test('con keepPrevious una respuesta vieja tampoco pisa a la nueva', async () => {
    const calls = { 1: deferred(), 2: deferred() }
    const { result, rerender } = renderHook(({ id }) => useApi(() => calls[id].promise, [id], { keepPrevious: true }), {
      initialProps: { id: 1 },
    })
    rerender({ id: 2 })
    await act(async () => calls[2].resolve('segunda'))
    await act(async () => calls[1].resolve('primera'))
    expect(result.current).toMatchObject({ loading: false, data: 'segunda' })
  })

  test('mientras las dependencias no cambian no vuelve a cargar', async () => {
    const load = vi.fn().mockResolvedValue('datos')
    const { result, rerender } = renderHook(({ id }) => useApi(load, [id]), { initialProps: { id: 1 } })
    await waitFor(() => expect(result.current.data).toBe('datos'))
    rerender({ id: 1 })
    expect(load).toHaveBeenCalledTimes(1)
    expect(result.current.data).toBe('datos')
  })
})

describe('OfflineNotice', () => {
  test('OfflineNotice reintenta al tocar Reintentar', () => {
    const onRetry = vi.fn()
    render(<OfflineNotice onRetry={onRetry} />)
    expect(screen.getByText('Sin conexión')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  test('si la API se cae con la pantalla abierta, el aviso va dentro de la pantalla y Reintentar la recupera', async () => {
    function StoreProbe() {
      const { data, error, loading, retry } = useApi(() => store(9101), [])
      if (loading) return <p>Cargando</p>
      if (error) return <OfflineNotice onRetry={retry} />
      return <h1>{data.store.name}</h1>
    }
    let online = false
    stubApi({ '/catalog/stores/9101': () => (online ? fixture('catalog-store') : 'offline') })
    render(
      <>
        <nav>El resto de la app</nav>
        <StoreProbe />
      </>,
    )

    expect(await screen.findByText('Sin conexión')).toBeTruthy()
    expect(screen.getByText('El resto de la app')).toBeTruthy()

    online = true
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByRole('heading', { name: 'Supermercado de prueba Centro' })).toBeTruthy()
    expect(screen.queryByText('Sin conexión')).toBeNull()
  })
})
