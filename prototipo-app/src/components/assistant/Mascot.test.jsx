import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, test } from 'vitest'
import Mascot from './Mascot'

afterEach(cleanup)

const mascot = (props) => render(<Mascot {...props} />).container.firstChild

// jsdom no tiene AnimationEvent, así que React escucha la versión con prefijo (webkitAnimationEnd);
// el evento se arma con el nombre de la animación, como en el navegador.
const animationEnd = (el, animationName, type = 'webkitAnimationEnd') => {
  const event = new Event(type, { bubbles: true })
  Object.defineProperty(event, 'animationName', { value: animationName })
  act(() => el.dispatchEvent(event))
}

describe('Mochi, la mascota', () => {
  test('es Mochi (no el dibujo anterior) y queda fuera del lector de pantalla', () => {
    const el = mascot()
    expect(el.classList).toContain('mascot')
    expect(el.getAttribute('aria-hidden')).toBe('true')
    expect(el.querySelector('svg')).toBeNull()
  })

  test('el estado elige la pose', () => {
    expect(mascot({ mood: 'think' }).classList).toContain('mascot--think')
    cleanup()
    expect(mascot().classList).toContain('mascot--idle')
  })

  test('de cuerpo entero mide 1,2 × el ancho; como avatar es un círculo', () => {
    const full = mascot({ size: 50 })
    expect(full.style.width).toBe('50px')
    expect(full.style.height).toBe('60px')
    cleanup()
    const badge = mascot({ size: 40, badge: true })
    expect(badge.classList).toContain('mascot--badge')
    expect(badge.style.height).toBe('40px')
  })

  test('al tocarlo salta, y vuelve a su pose al terminar el salto', () => {
    const el = mascot()
    fireEvent.pointerDown(el)
    expect(el.classList).toContain('mascot--boop')
    animationEnd(el, 'mascot-boop')
    expect(el.classList).not.toContain('mascot--boop')
  })

  test('si el salto se cancela (p. ej. Mochi se oculta a mitad), no queda pegado en esa pose', () => {
    const el = mascot()
    fireEvent.pointerDown(el)
    animationEnd(el, 'mascot-boop', 'animationcancel')
    expect(el.classList).not.toContain('mascot--boop')
  })

  test('el fin de otra animación no corta el salto', () => {
    const el = mascot()
    fireEvent.pointerDown(el)
    animationEnd(el, 'mascot-breathe')
    expect(el.classList).toContain('mascot--boop')
  })
})
