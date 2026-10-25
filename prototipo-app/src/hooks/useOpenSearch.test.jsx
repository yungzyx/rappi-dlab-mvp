import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { AssistantProvider, useAssistant } from '../state/AssistantContext'
import { DemoProvider, useDemo } from '../state/DemoContext'
import { useOpenSearch } from './useOpenSearch'

const wrapper = ({ children }) => (
  <DemoProvider>
    <AssistantProvider>{children}</AssistantProvider>
  </DemoProvider>
)

afterEach(() => {
  cleanup()
  localStorage.clear()
})

describe('useOpenSearch', () => {
  const setup = (mode) => {
    const push = vi.fn()
    const { result } = renderHook(() => ({ open: useOpenSearch(push), demo: useDemo(), assistant: useAssistant() }), {
      wrapper,
    })
    act(() => result.current.demo.setMode(mode))
    return { push, result }
  }

  test('en el prototipo final abre el buscador con Mochi, no el plano', () => {
    const { push, result } = setup('final')
    act(() => result.current.open('liquor'))
    expect(push).not.toHaveBeenCalled()
    expect(result.current.assistant.isOpen).toBe(true)
    expect(result.current.assistant.session.search).toBeUndefined()
  })

  test('en el prototipo final, desde la Home, también lo abre', () => {
    const { push, result } = setup('final')
    act(() => result.current.open())
    expect(push).not.toHaveBeenCalled()
    expect(result.current.assistant.isOpen).toBe(true)
  })

  test('con una consulta (una categoría), el buscador de Mochi arranca con ella', () => {
    const { push, result } = setup('final')
    act(() => result.current.open('liquor', 'cerveza'))
    expect(push).not.toHaveBeenCalled()
    expect(result.current.assistant.session).toMatchObject({ search: 'cerveza' })
  })

  test('con una consulta, en «Rappi hoy» el buscador plano la recibe con su vertical', () => {
    const { push, result } = setup('actual')
    act(() => result.current.open('liquor', 'cerveza'))
    expect(push).toHaveBeenCalledWith('search', { vertical: 'liquor', query: 'cerveza' })
  })

  test('en «Rappi hoy» abre el buscador plano', () => {
    const { push, result } = setup('actual')
    act(() => result.current.open('turbo'))
    expect(push).toHaveBeenCalledWith('search', { vertical: 'turbo' })
    expect(result.current.assistant.isOpen).toBe(false)
  })
})
