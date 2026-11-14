import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, test } from 'vitest'
import { emote, setThinking } from '../../state/mochiMood'
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
    expect(mascot({ mood: 'thinking' }).classList).toContain('mascot--thinking')
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

describe('Mochi con ánimo (state/mochiMood.js)', () => {
  const fx = (el) => el.querySelector('.mascot-fx')?.className ?? null

  test('la mascota que acompaña (`live`) muestra la emoción que corre, con su adorno; las demás, no', () => {
    const { container } = render(
      <>
        <Mascot live />
        <Mascot />
      </>,
    )
    const [live, still] = container.children
    act(() => emote('celebrate'))
    expect(live.classList).toContain('mascot--celebrate')
    expect(live.classList).toContain('is-feeling')
    expect(fx(live)).toContain('mascot-fx--sparks')
    expect(live.querySelectorAll('.mascot-fx i')).toHaveLength(8)
    expect(still.classList).toContain('mascot--idle')
    expect(fx(still)).toBeNull()
  })

  test('cada emoción tiene su adorno (sin texto) y "contento" y "bailar" solo se mueven', () => {
    const cases = { worried: 'mascot-fx--drop', surprised: 'mascot-fx--bang', happy: null, dance: null }
    for (const [emotion, adornment] of Object.entries(cases)) {
      cleanup()
      const el = mascot({ live: true, mood: emotion })
      expect(el.classList).toContain(`mascot--${emotion}`)
      expect(fx(el) && fx(el).split(' ')[1]).toBe(adornment)
      expect(el.textContent).toBe('')
    }
  })

  test('pensando manda sobre la emoción y sobre su propio ánimo; con tres puntos', () => {
    const token = {}
    const el = mascot({ live: true, mood: 'listen' })
    act(() => setThinking(token, true))
    expect(el.classList).toContain('mascot--thinking')
    expect(el.querySelectorAll('.mascot-fx--dots i')).toHaveLength(3)
    act(() => setThinking(token, false))
    expect(el.classList).toContain('mascot--listen')
  })

  test('dormido ("z z") no muestra emociones', () => {
    const el = mascot({ live: true, mood: 'sleepy', badge: true })
    expect(fx(el)).toContain('mascot-fx--zz')
    act(() => emote('dance'))
    expect(el.classList).toContain('mascot--sleepy')
  })

  test('sigue fuera del lector de pantalla con cualquier ánimo', () => {
    const el = mascot({ live: true })
    act(() => emote('surprised'))
    expect(el.getAttribute('aria-hidden')).toBe('true')
    expect(el.querySelector('[tabindex], button')).toBeNull()
  })
})
