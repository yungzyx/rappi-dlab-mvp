import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { quietToday, wake } from './agentQuiet'
import {
  COOLDOWN_MS,
  EMOTIONS,
  THINK_DELAY_MS,
  emote,
  observeMood,
  resetMochiMood,
  setThinking,
  useMochiMood,
  useMochiThinking,
} from './mochiMood'
import { today } from '../utils/today'

beforeEach(() => {
  vi.useFakeTimers()
  localStorage.clear()
  resetMochiMood()
})
afterEach(() => {
  vi.useRealTimers()
  localStorage.clear()
})

const mood = () => renderHook(() => useMochiMood()).result
const advance = (ms) => act(() => vi.advanceTimersByTime(ms))

describe('el bus de ánimo de Mochi', () => {
  test('una emoción a la vez: otra igual o menos importante no entra; una más importante la reemplaza', () => {
    const now = mood()
    act(() => expect(emote('surprised')).toBe(true))
    expect(now.current.emotion).toBe('surprised')
    act(() => expect(emote('happy')).toBe(false))
    act(() => expect(emote('worried')).toBe(false)) // del mismo rango
    expect(now.current.emotion).toBe('surprised')
    act(() => expect(emote('celebrate')).toBe(true))
    expect(now.current.emotion).toBe('celebrate')
  })

  test('vuelve sola a quieto cuando termina, con su duración o la que se le pida', () => {
    const now = mood()
    act(() => emote('dance'))
    advance(EMOTIONS.dance.ms - 1)
    expect(now.current.emotion).toBe('dance')
    advance(1)
    expect(now.current.emotion).toBeNull()

    advance(COOLDOWN_MS)
    act(() => emote('dance', { ms: 500 }))
    advance(500)
    expect(now.current.emotion).toBeNull()
  })

  test('tras una emoción, otra igual o menos importante espera el enfriamiento; una más importante, no', () => {
    const now = mood()
    act(() => emote('surprised'))
    advance(EMOTIONS.surprised.ms)
    act(() => expect(emote('happy')).toBe(false))
    act(() => expect(emote('surprised')).toBe(false))
    act(() => expect(emote('celebrate')).toBe(true)) // aceptar algo de Mochi siempre se celebra
    advance(EMOTIONS.celebrate.ms + COOLDOWN_MS)
    act(() => expect(emote('happy')).toBe(true))
    expect(now.current.emotion).toBe('happy')
  })

  test('cada emoción lleva su id: la misma dos veces se distingue (la mascota la vuelve a correr)', () => {
    const now = mood()
    act(() => emote('celebrate'))
    const first = now.current.id
    advance(EMOTIONS.celebrate.ms + COOLDOWN_MS)
    act(() => emote('celebrate'))
    expect(now.current.id).toBeGreaterThan(first)
  })

  test('una emoción que no existe no hace nada', () => {
    const now = mood()
    act(() => expect(emote('angry')).toBe(false))
    expect(now.current.emotion).toBeNull()
  })

  test('el fondo manda: pensando corta la emoción y no deja entrar otra hasta que termina', () => {
    const now = mood()
    const token = {}
    act(() => emote('celebrate'))
    act(() => setThinking(token, true))
    expect(now.current).toMatchObject({ thinking: true, emotion: null })
    act(() => expect(emote('dance')).toBe(false))
    act(() => setThinking(token, false))
    expect(now.current.thinking).toBe(false)
    act(() => expect(emote('dance')).toBe(true))
  })

  test('piensa mientras quede alguna espera', () => {
    const now = mood()
    const [a, b] = [{}, {}]
    act(() => setThinking(a, true))
    act(() => setThinking(b, true))
    act(() => setThinking(a, false))
    expect(now.current.thinking).toBe(true)
    act(() => setThinking(b, false))
    expect(now.current.thinking).toBe(false)
  })

  test('silenciado por hoy dormita: corta la emoción y no deja entrar otra; al despertar, vuelve', () => {
    const now = mood()
    act(() => emote('happy'))
    act(() => quietToday(today()))
    expect(now.current).toMatchObject({ quiet: true, emotion: null })
    act(() => expect(emote('dance')).toBe(false))
    act(() => wake())
    expect(now.current.quiet).toBe(false)
    act(() => expect(emote('dance')).toBe(true))
  })
})

describe('qué lo dispara', () => {
  test('una búsqueda con resultados lo alegra; una sin nada lo preocupa', () => {
    const now = mood()
    act(() => observeMood({ type: 'search', results: 12, unmet: false }))
    expect(now.current.emotion).toBe('happy')
    act(() => resetMochiMood())
    act(() => observeMood({ type: 'search', results: 0, unmet: true }))
    expect(now.current.emotion).toBe('worried')
  })

  test('una búsqueda que solo trajo tiendas (sin productos, pero calzó) no le cambia el ánimo', () => {
    const now = mood()
    act(() => observeMood({ type: 'search', results: 0, unmet: false }))
    expect(now.current.emotion).toBeNull()
  })

  test('aceptar algo de Mochi (un producto de su sugerencia, su oferta) lo hace celebrar', () => {
    const now = mood()
    act(() => observeMood({ type: 'suggestion_accepted', origin: 'agent-carrito' }))
    expect(now.current.emotion).toBe('celebrate')
  })

  test('los demás eventos no le cambian el ánimo', () => {
    const now = mood()
    for (const type of ['app_open', 'cart_add', 'view_item', 'suggestion_shown', 'agent_open'])
      act(() => observeMood({ type }))
    expect(now.current.emotion).toBeNull()
  })

  test('useMochiThinking: piensa solo si la espera pasa del umbral, y deja de pensar al terminar', () => {
    const now = mood()
    const { rerender, unmount } = renderHook(({ active }) => useMochiThinking(active), {
      initialProps: { active: true },
    })
    advance(THINK_DELAY_MS - 1)
    expect(now.current.thinking).toBe(false) // una respuesta rápida no lo hace parpadear
    advance(1)
    expect(now.current.thinking).toBe(true)
    rerender({ active: false })
    expect(now.current.thinking).toBe(false)
    rerender({ active: true })
    advance(THINK_DELAY_MS)
    unmount()
    expect(now.current.thinking).toBe(false)
  })
})
