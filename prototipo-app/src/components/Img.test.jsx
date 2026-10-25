import { cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import Img, { PLACEHOLDER_IMG } from './Img'

afterEach(cleanup)

describe('Img', () => {
  test('perezosa y decodificada aparte por defecto; eager para las de arriba', () => {
    const { container, rerender } = render(<Img src="a.webp" />)
    const img = container.querySelector('img')
    expect(img.getAttribute('loading')).toBe('lazy')
    expect(img.getAttribute('decoding')).toBe('async')
    expect(img.getAttribute('alt')).toBe('')
    rerender(<Img src="a.webp" eager alt="Foto" />)
    expect(img.getAttribute('loading')).toBe('eager')
    expect(img.getAttribute('alt')).toBe('Foto')
  })

  test('si la foto falla o no hay src, muestra el cuadro de respaldo y avisa al onError propio', () => {
    const onError = vi.fn()
    const { container, rerender } = render(<Img src="rota.webp" onError={onError} />)
    const img = container.querySelector('img')
    fireEvent.error(img)
    expect(img.getAttribute('src')).toBe(PLACEHOLDER_IMG)
    expect(onError).toHaveBeenCalledTimes(1)
    // Otra foto vuelve a intentarse.
    rerender(<Img src="nueva.webp" onError={onError} />)
    expect(img.getAttribute('src')).toBe('nueva.webp')
    rerender(<Img src={undefined} />)
    expect(img.getAttribute('src')).toBe(PLACEHOLDER_IMG)
  })
})
