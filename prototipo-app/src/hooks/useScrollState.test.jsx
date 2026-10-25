import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { useScrollState } from './useScrollState'

const renders = vi.fn()
function Page() {
  const [{ collapsed, showBackToTop, scrolled }, onScroll] = useScrollState({ collapseAt: 100, backToTopFrom: 500 })
  renders()
  return <div data-testid="scroller" onScroll={onScroll} data-state={`${collapsed} ${showBackToTop} ${scrolled}`} />
}

afterEach(() => {
  cleanup()
  renders.mockClear()
})

const scrollTo = async (element, top) => {
  element.scrollTop = top
  fireEvent.scroll(element)
  await act(() => new Promise((resolve) => requestAnimationFrame(() => resolve())))
}

describe('useScrollState', () => {
  test('entrega booleanos y solo re-renderiza cuando alguno cambia', async () => {
    const { getByTestId } = render(<Page />)
    const scroller = getByTestId('scroller')
    expect(scroller.dataset.state).toBe('false false false')
    expect(renders).toHaveBeenCalledTimes(1)

    await scrollTo(scroller, 50)
    expect(scroller.dataset.state).toBe('false false true')
    await scrollTo(scroller, 60) // mismos booleanos: sin render
    const after = renders.mock.calls.length
    await scrollTo(scroller, 70)
    expect(renders).toHaveBeenCalledTimes(after)

    await scrollTo(scroller, 700)
    expect(scroller.dataset.state).toBe('true false true')
    await scrollTo(scroller, 650) // subiendo, lejos del tope
    expect(scroller.dataset.state).toBe('true true true')
    await scrollTo(scroller, 0)
    expect(scroller.dataset.state).toBe('false false false')
  })

  test('varios scrolls en el mismo cuadro se leen una sola vez', async () => {
    const raf = vi.spyOn(window, 'requestAnimationFrame')
    const { getByTestId } = render(<Page />)
    const scroller = getByTestId('scroller')
    fireEvent.scroll(scroller)
    fireEvent.scroll(scroller)
    fireEvent.scroll(scroller)
    expect(raf).toHaveBeenCalledTimes(1)
    raf.mockRestore()
  })
})
