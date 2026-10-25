import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from '../../test/api'
import { CartProvider } from '../../state/CartContext'
import { DemoProvider } from '../../state/DemoContext'
import { ProfileProvider } from '../../state/ProfileContext'
import { SearchResults } from './SearchSections'

const events = vi.hoisted(() => ({ track: vi.fn(), flush: async () => {}, clear: () => {}, settled: async () => {} }))
vi.mock('../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))

function Providers({ children }) {
  return (
    <DemoProvider>
      <ProfileProvider>
        <CartProvider>{children}</CartProvider>
      </ProfileProvider>
    </DemoProvider>
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const EMPTY = { query: 'chela', groups: [], unmet: true, unmetReason: null }
const flush = () => act(async () => {})

describe('SearchResults sin resultados', () => {
  test('sin Mochi (el buscador de «Rappi hoy») sigue el texto de siempre y no llama a la API', async () => {
    const fetchMock = stubApi({})
    render(<SearchResults query="chela" data={EMPTY} />)
    await flush()
    expect(screen.getByText('Sin resultados para «chela».')).toBeTruthy()
    expect(document.querySelector('.mascot')).toBeNull()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  // Primero: lo mostrado se recuerda lo que dura la pestaña (este archivo), y la siguiente prueba muestra la misma oferta.
  test('la oferta sin_resultado registra su mostrada y, al tocar «Ver en…», una aceptada (una sola vez)', async () => {
    events.track.mockClear()
    stubApi({ 'POST /agent/offer': fixture('agent-offer-sin-resultado') })
    render(
      <SearchResults query="pizza hawaiana" data={{ ...EMPTY, query: 'pizza hawaiana' }} onOpenVertical={() => {}} />,
      {
        wrapper: Providers,
      },
    )
    await flush()
    const tracked = (type) => events.track.mock.calls.filter(([name]) => name === type).map(([, fields]) => fields)
    const fields = { concept_id: 'pizza', vertical: 'restaurantes', payload: { origen: 'agent-sin_resultado' } }

    expect(tracked('suggestion_shown')).toEqual([fields])
    expect(tracked('suggestion_accepted')).toEqual([])

    const see = screen.getByRole('button', { name: 'Ver en Restaurantes' })
    fireEvent.click(see)
    fireEvent.click(see)
    expect(tracked('suggestion_accepted')).toEqual([fields]) // una, no una por producto: no se agregó ninguno
    expect(tracked('suggestion_shown')).toHaveLength(1)
  })

  test('the offer has ¿Por qué?', async () => {
    stubApi({ 'POST /agent/offer': fixture('agent-offer-sin-resultado') })
    render(
      <SearchResults query="pizza hawaiana" data={{ ...EMPTY, query: 'pizza hawaiana' }} onOpenVertical={() => {}} />,
    )
    await flush()
    fireEvent.click(screen.getByRole('button', { name: '¿Por qué?' }))
    expect(screen.getByText(fixture('agent-offer-sin-resultado').reason.text)).toBeTruthy()
  })

  test('sin una oferta (204) no hay ¿Por qué?', async () => {
    stubApi({ 'POST /agent/offer': 204 })
    render(<SearchResults query="xyzzy" data={{ ...EMPTY, query: 'xyzzy' }} onOpenVertical={() => {}} />)
    await flush()
    expect(screen.queryByRole('button', { name: '¿Por qué?' })).toBeNull()
  })

  test('sin resultados muestra Ver en la vertical que sí lo tiene', async () => {
    const fetchMock = stubApi({ 'POST /agent/offer': fixture('agent-offer-sin-resultado') })
    const onOpenVertical = vi.fn()
    render(
      <SearchResults
        query="pizza hawaiana"
        data={{ ...EMPTY, query: 'pizza hawaiana' }}
        onOpenVertical={onOpenVertical}
      />,
    )
    await flush()

    expect(screen.getByText('No encontré «pizza hawaiana», pero pizza sí hay en restaurantes.')).toBeTruthy()
    expect(document.querySelector('.search-agent .mascot')).toBeTruthy()
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({
      moment: 'sin_resultado',
      context: { query: 'pizza hawaiana' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Ver en Restaurantes' }))
    expect(onOpenVertical).toHaveBeenCalledWith('restaurants')
  })

  test('si Mochi no tiene nada que ofrecer (204), solo invita a probar otra búsqueda', async () => {
    stubApi({ 'POST /agent/offer': 204 })
    const onTryAnother = vi.fn()
    render(
      <SearchResults
        query="xyzzy"
        data={{ ...EMPTY, query: 'xyzzy' }}
        onOpenVertical={() => {}}
        onTryAnother={onTryAnother}
      />,
    )
    await flush()

    expect(screen.getByText('No encontré «xyzzy». ¿Lo buscamos con otras palabras?')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /^Ver en/ })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Probar otra búsqueda' }))
    expect(onTryAnother).toHaveBeenCalledTimes(1)
  })

  test('si la oferta falla, Mochi no dice nada de más: también solo «Probar otra búsqueda»', async () => {
    stubApi({ 'POST /agent/offer': 'offline' })
    render(
      <SearchResults
        query="xyzzy"
        data={{ ...EMPTY, query: 'xyzzy' }}
        onOpenVertical={() => {}}
        onTryAnother={() => {}}
      />,
    )
    await flush()
    expect(screen.getByRole('button', { name: 'Probar otra búsqueda' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /^Ver en/ })).toBeNull()
  })

  test('mientras se escribe otra consulta no se muestra la oferta de la anterior', async () => {
    stubApi({ 'POST /agent/offer': fixture('agent-offer-sin-resultado') })
    render(
      <SearchResults
        query="pizza hawaianas"
        data={{ ...EMPTY, query: 'pizza hawaiana' }}
        loading
        onOpenVertical={() => {}}
      />,
    )
    await flush()
    expect(screen.queryByRole('button', { name: /^Ver en/ })).toBeNull()
    expect(screen.queryByText(/Sin resultados|No encontré/)).toBeNull()
  })
})

describe('SearchResults con resultados', () => {
  const data = () => {
    const raw = fixture('search-grouped')
    const product = raw.groups[0].products[0]
    // Un grupo con más productos de los que se ven al principio.
    raw.groups[0].products = Array.from({ length: 5 }, (_, i) => ({ ...product, id: `cat-${i}`, name: `Cerveza ${i}` }))
    return {
      query: 'cerveza',
      unmet: false,
      groups: raw.groups.map((g) => ({
        vertical: g.prototype_vertical,
        backendVertical: g.vertical,
        products: g.products.map((p) => ({
          id: p.id,
          name: p.name,
          price: p.price,
          store: p.store,
          storeId: p.store_id,
        })),
      })),
    }
  }

  test('cada grupo lleva el nombre de su vertical y muestra pocos productos con «Ver más»', () => {
    render(<SearchResults query="cerveza" data={data()} />, { wrapper: Providers })
    expect(screen.getByRole('heading', { name: 'Licores' })).toBeTruthy()
    expect(screen.getByText('Cerveza 2')).toBeTruthy()
    expect(screen.queryByText('Cerveza 3')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Ver más (2)' }))
    expect(screen.getByText('Cerveza 4')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Ver más/ })).toBeNull()
  })

  test('«Ver más» vuelve a cerrarse con una consulta nueva', () => {
    const { rerender } = render(<SearchResults query="cerveza" data={data()} />, { wrapper: Providers })
    fireEvent.click(screen.getByRole('button', { name: 'Ver más (2)' }))
    expect(screen.getByText('Cerveza 4')).toBeTruthy()

    rerender(<SearchResults query="cerveza fria" data={{ ...data(), query: 'cerveza fria' }} />)
    expect(screen.queryByText('Cerveza 4')).toBeNull()
    expect(screen.getByRole('button', { name: 'Ver más (2)' })).toBeTruthy()
  })

  test('lo que la vertical de la pantalla no vende sale solo donde se vende, sin un grupo de esa vertical', async () => {
    // Desde Turbo, «televisor 55 pulgadas»: la API ya no trae el cable HDMI de Turbo, solo el grupo del Mall.
    const fetchMock = stubApi({})
    const tv = { id: 'cat-1', name: 'Televisor smart 55 pulgadas', price: '$299.990', store: 'Tienda', storeId: 1 }
    const found = { query: 'televisor 55 pulgadas', unmet: false, groups: [{ vertical: 'retail', products: [tv] }] }
    render(<SearchResults query="televisor 55 pulgadas" data={found} onOpenVertical={vi.fn()} />, {
      wrapper: Providers,
    })
    await flush()

    expect(screen.getByRole('heading', { name: 'Rappi Mall' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'Turbo' })).toBeNull()
    expect(screen.getByText('Televisor smart 55 pulgadas')).toBeTruthy()
    expect(fetchMock).not.toHaveBeenCalled() // con resultados, Mochi no ofrece «Ver en…»
  })

  test('el mismo producto en varios grupos no repite llaves', () => {
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<SearchResults query="cerveza" data={data()} />, { wrapper: Providers })
    expect(errors).not.toHaveBeenCalled()
    errors.mockRestore()
  })
})
