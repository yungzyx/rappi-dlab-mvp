import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { toPrototypeProduct } from '../api/client'
import { fixture } from '../test/api'
import { AssistantProvider } from '../state/AssistantContext'
import { CartProvider } from '../state/CartContext'
import { DemoProvider } from '../state/DemoContext'
import { ProfileProvider } from '../state/ProfileContext'
import { AGENT_CART_EVENT, session } from '../state/liveMemory'
import AddButton from './AddButton'

const events = vi.hoisted(() => ({ track: vi.fn(), flush: async () => {}, clear: () => {}, settled: async () => {} }))
vi.mock('../state/EventsContext', async (importOriginal) => ({ ...(await importOriginal()), useEvents: () => events }))

function Providers({ children }) {
  return (
    <DemoProvider>
      <ProfileProvider>
        <AssistantProvider>
          <CartProvider>{children}</CartProvider>
        </AssistantProvider>
      </ProfileProvider>
    </DemoProvider>
  )
}

const heineken = toPrototypeProduct(fixture('search-grouped').groups[0].products[0])
const add = () => fireEvent.click(screen.getByLabelText(`Agregar ${heineken.name}`))

afterEach(() => {
  cleanup()
  events.track.mockClear()
  session.lastAdded = null
  localStorage.clear()
})

describe('AddButton (extra)', () => {
  test('quitar manda cart_remove con el concepto', () => {
    render(<AddButton product={heineken} />, { wrapper: Providers })
    add()
    fireEvent.click(screen.getByLabelText(/^Quitar uno de /))
    expect(events.track).toHaveBeenCalledWith('cart_remove', expect.objectContaining({ concept_id: 'cerveza' }))
  })

  test('en el prototipo final no hay aviso al agregar: Mochi lo comenta al volver a la Home', () => {
    render(<AddButton product={heineken} />, { wrapper: Providers })
    add()
    expect(session.lastAdded).toMatchObject({ id: heineken.id })
  })

  test('si se quita lo último agregado (p. ej. «Deshacer»), Mochi no lo comenta al volver a la Home', () => {
    render(<AddButton product={heineken} />, { wrapper: Providers })
    add()
    expect(session.lastAdded).toMatchObject({ id: heineken.id })
    fireEvent.click(screen.getByLabelText(/^Quitar uno de /))
    expect(session.lastAdded).toBeNull()
  })

  test('en el prototipo final, agregar avisa a Mochi', () => {
    const heard = vi.fn()
    window.addEventListener(AGENT_CART_EVENT, heard)
    render(<AddButton product={heineken} />, { wrapper: Providers })
    add()
    window.removeEventListener(AGENT_CART_EVENT, heard)
    expect(heard).toHaveBeenCalledTimes(1)
    expect(heard.mock.calls[0][0].detail.product).toMatchObject({ id: heineken.id })
  })

  test('en «Rappi hoy» agregar no avisa a Mochi', () => {
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    const heard = vi.fn()
    window.addEventListener(AGENT_CART_EVENT, heard)
    render(<AddButton product={heineken} />, { wrapper: Providers })
    add()
    window.removeEventListener(AGENT_CART_EVENT, heard)
    expect(heard).not.toHaveBeenCalled()
  })

  test('en «Rappi hoy» no hay memoria de Mochi', () => {
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    render(<AddButton product={heineken} />, { wrapper: Providers })
    add()
    expect(session.lastAdded).toBeNull()
  })
})
