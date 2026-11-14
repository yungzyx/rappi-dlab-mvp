import { useEffect, useState } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { AssistantProvider } from '../../state/AssistantContext'
import { DemoProvider } from '../../state/DemoContext'
import { sessionId } from '../../state/EventsContext'
import { HIDDEN_KEY } from '../../state/agentHidden'
import { SURVEY_DAY_KEY, observeEvent, resetSurvey } from '../../state/survey'
import { tabStore } from '../../state/storage'
import { today } from '../../utils/today'
import FoundItSurvey, { P1_TEXT, P3_TEXT } from './FoundItCard'
import { SETTLE_MS, THANKS_MS } from './useFoundItSurvey'

const events = vi.hoisted(() => ({ track: vi.fn(), flush: async () => {}, clear: () => {}, settled: async () => {} }))
vi.mock('../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))

// La app de prueba: la pregunta sobre la pantalla `screen` (con `depth` en la pila) y, si `talking`, un globo de Mochi.
const probe = {}
const setView = (next) => act(() => probe.set((prev) => ({ ...prev, ...next })))
function Harness() {
  const [view, set] = useState({ screen: 'search', depth: 2, talking: false })
  useEffect(() => {
    probe.set = set
  }, [set])
  return (
    <div className="phone">
      {view.talking && <div className="live-bubble">¿Le sumas una bebida?</div>}
      <FoundItSurvey screen={view.screen} depth={view.depth} raised={view.screen === 'home'} />
    </div>
  )
}
const mount = () =>
  render(
    <DemoProvider>
      <AssistantProvider>
        <Harness />
      </AssistantProvider>
    </DemoProvider>,
  )

const tracked = (type) => events.track.mock.calls.filter(([kind]) => kind === type).map(([, fields]) => fields)
const settle = () => act(() => vi.advanceTimersByTime(SETTLE_MS))
const question = () => screen.queryByRole('heading', { name: P1_TEXT })
const searched = (requestId = 'req-1') => act(() => observeEvent({ type: 'search', request_id: requestId }))
const touched = (type = 'view_item', requestId = 'req-1') => act(() => observeEvent({ type, request_id: requestId }))

/** Busca desde la Home con el buscador plano (`search` en la pila) y vuelve a la Home. */
function searchAndBack({ touch } = {}) {
  setView({ screen: 'search', depth: 2 })
  searched()
  if (touch) touched(touch)
  setView({ screen: 'home', depth: 1 })
}

beforeEach(() => {
  vi.useFakeTimers()
  localStorage.setItem('rappi-proto-demo-mode', 'final')
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  resetSurvey()
  tabStore.clear('rappi-proto-')
  localStorage.clear()
  events.track.mockClear()
})

describe('la pregunta in-app', () => {
  test('after a search with a tapped result, back home it asks, records the answer and says thanks', () => {
    mount()
    searchAndBack({ touch: 'view_item' })
    expect(question()).toBeNull() // espera a que la pantalla llegue
    settle()
    expect(question()).toBeTruthy()
    expect(tracked('survey_shown')).toEqual([
      { surface: 'home', request_id: 'req-1', payload: { question: 'p1', trigger: 'busqueda', mochi: true } },
    ])
    fireEvent.click(screen.getByRole('button', { name: 'En parte' }))
    expect(tracked('survey_answer')).toEqual([
      {
        surface: 'home',
        request_id: 'req-1',
        payload: { question: 'p1', trigger: 'busqueda', mochi: true, answer: 'en_parte' },
      },
    ])
    expect(screen.getByRole('status').textContent).toContain('¡Gracias!')
    act(() => vi.advanceTimersByTime(THANKS_MS))
    expect(screen.queryByRole('status')).toBeNull()
  })

  test('a search without taps is an abandonment, and it can be closed without answering', () => {
    mount()
    searchAndBack()
    settle()
    expect(tracked('survey_shown')[0].payload.trigger).toBe('abandono')
    fireEvent.click(screen.getByRole('button', { name: 'Cerrar sin responder' }))
    expect(question()).toBeNull()
    expect(tracked('survey_dismissed')).toEqual([
      { surface: 'home', request_id: 'req-1', payload: { question: 'p1', trigger: 'abandono', mochi: true } },
    ])
    expect(tracked('survey_answer')).toEqual([])
  })

  test('adding a result to the cart is the cart trigger', () => {
    mount()
    searchAndBack({ touch: 'cart_add' })
    settle()
    expect(tracked('survey_shown')[0].payload.trigger).toBe('carro')
  })

  test('it waits until the person is back where the search started: not while browsing what it opened', () => {
    mount()
    // Desde una tienda (2) abre el buscador de Mochi encima (sigue en 2), toca un producto y abre otra tienda (3).
    setView({ screen: 'store', depth: 2 })
    searched()
    touched('view_store')
    setView({ screen: 'store', depth: 3 })
    settle()
    expect(question()).toBeNull()
    setView({ screen: 'store', depth: 2 })
    settle()
    expect(question()).toBeTruthy()
  })

  test.each(['checkout', 'tracking'])('never on %s (payment lives in the checkout)', (where) => {
    mount()
    setView({ screen: 'store', depth: 2 })
    searched()
    touched('cart_add')
    setView({ screen: where, depth: 2 })
    act(() => vi.advanceTimersByTime(10 * SETTLE_MS))
    expect(question()).toBeNull()
    expect(tracked('survey_shown')).toEqual([])
    setView({ screen: 'home', depth: 1 })
    settle()
    expect(question()).toBeTruthy()
  })

  test('going somewhere else with the question open takes it away without an event', () => {
    mount()
    searchAndBack()
    settle()
    setView({ screen: 'restaurants', depth: 2 })
    expect(question()).toBeNull()
    expect(tracked('survey_dismissed')).toEqual([])
  })

  test('if Mochi is saying something (an offer) the question waits, and hides while Mochi talks', async () => {
    // Mochi aparece o se va del DOM: la pregunta lo ve con un MutationObserver (su aviso llega en una microtarea).
    const talking = async (on) => {
      setView({ talking: on })
      await act(async () => {})
    }
    mount()
    await talking(true)
    searchAndBack()
    act(() => vi.advanceTimersByTime(10 * SETTLE_MS))
    expect(question()).toBeNull()
    await talking(false)
    settle()
    expect(question()).toBeTruthy()
    await talking(true)
    expect(question()).toBeNull()
    await talking(false)
    expect(question()).toBeTruthy()
    expect(tracked('survey_shown')).toHaveLength(1)
  })

  test('once per session: another search in the same session is not asked', () => {
    mount()
    searchAndBack()
    settle()
    fireEvent.click(screen.getByRole('button', { name: 'Sí' }))
    act(() => vi.advanceTimersByTime(THANKS_MS))
    localStorage.removeItem(SURVEY_DAY_KEY) // aunque fuera otro día, la misma sesión no se pregunta dos veces
    searchAndBack()
    act(() => vi.advanceTimersByTime(10 * SETTLE_MS))
    expect(question()).toBeNull()
    expect(tracked('survey_shown')).toHaveLength(1)
  })

  test('once per day: a new session the same day is not asked, another day it is', () => {
    localStorage.setItem(SURVEY_DAY_KEY, today())
    mount()
    searchAndBack()
    act(() => vi.advanceTimersByTime(10 * SETTLE_MS))
    expect(question()).toBeNull()

    localStorage.setItem(SURVEY_DAY_KEY, '2020-01-01')
    searchAndBack()
    settle()
    expect(question()).toBeTruthy()
  })
})

describe('la p3', () => {
  const whyOpened = () => act(() => observeEvent({ type: 'offer_why_open', session_id: sessionId() }))

  test('with Mochi in view and a "¿Por qué?" opened in the session, it follows the p1 in the same card', () => {
    mount()
    whyOpened()
    searchAndBack()
    settle()
    fireEvent.click(screen.getByRole('button', { name: 'Sí' }))
    expect(screen.getByRole('heading', { name: P3_TEXT })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '4' }))
    expect(tracked('survey_shown').map((f) => f.payload)).toEqual([
      { question: 'p1', trigger: 'abandono', mochi: true },
      { question: 'p3', trigger: 'porque', mochi: true },
    ])
    expect(tracked('survey_answer').map((f) => f.payload)).toEqual([
      { question: 'p1', trigger: 'abandono', mochi: true, answer: 'si' },
      { question: 'p3', trigger: 'porque', mochi: true, answer: 4 },
    ])
    expect(screen.getByRole('status').textContent).toContain('¡Gracias!')
  })

  test('without a "¿Por qué?" opened, only the p1', () => {
    mount()
    searchAndBack()
    settle()
    fireEvent.click(screen.getByRole('button', { name: 'No' }))
    expect(screen.queryByRole('heading', { name: P3_TEXT })).toBeNull()
    expect(tracked('survey_shown')).toHaveLength(1)
  })

  test.each([
    ['Mochi oculto', () => localStorage.setItem(HIDDEN_KEY, '1')],
    ['"Rappi hoy"', () => localStorage.setItem('rappi-proto-demo-mode', 'actual')],
  ])('with %s the p1 still shows, without Mochi, and the p3 does not', (_, setUp) => {
    setUp()
    mount()
    whyOpened()
    searchAndBack()
    settle()
    expect(tracked('survey_shown')[0].payload).toEqual({ question: 'p1', trigger: 'abandono', mochi: false })
    fireEvent.click(screen.getByRole('button', { name: 'Sí' }))
    expect(screen.queryByRole('heading', { name: P3_TEXT })).toBeNull()
  })
})

describe('sin almacenamiento', () => {
  const originals = {}
  const thrower = () => {
    throw new DOMException('El acceso al almacenamiento está bloqueado', 'SecurityError')
  }
  beforeEach(() => {
    for (const name of ['sessionStorage', 'localStorage']) {
      originals[name] = Object.getOwnPropertyDescriptor(globalThis, name)
      Object.defineProperty(globalThis, name, { configurable: true, get: thrower })
    }
  })
  afterEach(() => {
    for (const name of ['sessionStorage', 'localStorage']) Object.defineProperty(globalThis, name, originals[name])
  })

  test('the question shows once, can be answered, and nothing breaks', () => {
    mount()
    searchAndBack({ touch: 'view_item' })
    settle()
    fireEvent.click(screen.getByRole('button', { name: 'Sí' }))
    expect(tracked('survey_answer')).toHaveLength(1)
    act(() => vi.advanceTimersByTime(THANKS_MS))
    searchAndBack()
    act(() => vi.advanceTimersByTime(10 * SETTLE_MS))
    expect(question()).toBeNull() // la sesión y el día viven en memoria
  })
})
