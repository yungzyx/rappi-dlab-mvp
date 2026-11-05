import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import Carousel from './Carousel'

const matchMedia = (reduce) => (query) => ({
  matches: reduce && query.includes('prefers-reduced-motion'),
  addEventListener() {},
  removeEventListener() {},
})

// jsdom no desplaza: el avance se ve en las llamadas a scrollTo del carrusel.
const scrollTo = vi.fn()

function mount() {
  render(
    <>
      <Carousel autoplayMs={4500}>
        <button type="button">Banner 1</button>
        <button type="button">Banner 2</button>
      </Carousel>
      <button type="button">Fuera</button>
    </>,
  )
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('matchMedia', matchMedia(false))
  Element.prototype.scrollTo = scrollTo
})
afterEach(() => {
  cleanup()
  scrollTo.mockClear()
  delete Element.prototype.scrollTo
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('Carousel con autoplay', () => {
  test('sin foco ni puntero encima, avanza a los 4,5 s', () => {
    mount()
    act(() => vi.advanceTimersByTime(4500))
    expect(scrollTo).toHaveBeenCalledTimes(1)
  })

  test('con el foco en un banner no avanza, y sigue cuando el foco sale del carrusel', () => {
    mount()
    act(() => screen.getByText('Banner 1').focus())
    act(() => vi.advanceTimersByTime(9000))
    expect(scrollTo).not.toHaveBeenCalled()

    // Pasar de un banner a otro no lo suelta
    act(() => screen.getByText('Banner 2').focus())
    act(() => vi.advanceTimersByTime(9000))
    expect(scrollTo).not.toHaveBeenCalled()

    act(() => screen.getByText('Fuera').focus())
    act(() => vi.advanceTimersByTime(4500))
    expect(scrollTo).toHaveBeenCalledTimes(1)
  })

  test('con el puntero encima no avanza', () => {
    mount()
    const carousel = screen.getByText('Banner 1').parentElement
    fireEvent.pointerEnter(carousel)
    act(() => vi.advanceTimersByTime(9000))
    expect(scrollTo).not.toHaveBeenCalled()

    fireEvent.pointerLeave(carousel)
    act(() => vi.advanceTimersByTime(4500))
    expect(scrollTo).toHaveBeenCalledTimes(1)
  })

  test('con "reducir movimiento" no avanza solo', () => {
    vi.stubGlobal('matchMedia', matchMedia(true))
    mount()
    act(() => vi.advanceTimersByTime(9000))
    expect(scrollTo).not.toHaveBeenCalled()
  })
})
