import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import { ToastProvider } from '../../components/Toast'
import { MAIN_TILES, SHORTCUTS, orderShortcuts } from '../../data/home'
import { MainTiles, Promos, Shortcuts } from './HomeSections'

beforeAll(() => {
  Element.prototype.scrollTo = () => {} // jsdom no lo implementa (carruseles)
})
afterAll(() => {
  delete Element.prototype.scrollTo
})
afterEach(cleanup)

const activeDot = () =>
  [...document.querySelectorAll('.home-promo-dots .dot')].findIndex((dot) => dot.classList.contains('is-active'))

test('los puntos de las promos siguen al carrusel y cada promo tiene nombre accesible', () => {
  const push = vi.fn()
  render(<Promos push={push} autoplayMs={0} />, { wrapper: ToastProvider })
  expect(activeDot()).toBe(1) // parte en la segunda promo, como en la captura
  fireEvent.scroll(document.querySelector('.home-promos')) // en jsdom todo mide 0: queda en la primera
  expect(activeDot()).toBe(0)
  fireEvent.click(screen.getByRole('button', { name: 'Descuentos en restaurantes' }))
  expect(push).toHaveBeenCalledWith('restaurants')
})

test('RappiFavor abre solo con `proposal` (el prototipo final); hoy sigue no disponible', () => {
  const push = vi.fn()
  const { unmount } = render(<Shortcuts push={push} />, { wrapper: ToastProvider })
  expect(screen.getByLabelText('RappiFavor (no disponible)')).toBeTruthy()
  unmount()
  render(<Shortcuts push={push} proposal />, { wrapper: ToastProvider })
  fireEvent.click(screen.getByText('RappiFavor'))
  expect(push).toHaveBeenCalledWith('favor')
})

test('no hay atajo a Mascotas', () => {
  expect(SHORTCUTS.map((item) => item.id)).not.toContain('pet')
  const push = vi.fn()
  render(<Shortcuts push={push} />, { wrapper: ToastProvider })
  expect(screen.queryByText(/^(Pet|Mascotas)$/)).toBeNull()
  for (const button of document.querySelectorAll('.home-shortcut')) fireEvent.click(button)
  expect(push.mock.calls.map(([, params]) => params?.id)).not.toContain('pet')
  for (const tile of [...MAIN_TILES, ...SHORTCUTS]) expect(tile.route?.[1]?.id).not.toBe('pet')
})

const ids = (list) => list.map((item) => item.id)
const SIX = ['grocery', 'pharmacy', 'retail', 'liquor', 'express', 'chocolates']
const ENGINE = ['farmacia', 'mall', 'supermercado', 'licores', 'conveniencia', 'chocolateria']
const labels = () => [...document.querySelectorAll('.home-shortcut')].map((button) => button.textContent)

test('orderShortcuts pone Lealtad y Beneficios Pro al final en el Prototipo final', () => {
  const result = ids(orderShortcuts(SHORTCUTS, null, { final: true }))
  expect(result.slice(-2)).toEqual(['loyalty', 'benefitspro'])
  expect(result.slice(0, 6)).toEqual(SIX)
  expect(result).toHaveLength(SHORTCUTS.length)
})

test('orderShortcuts sigue el orden del motor', () => {
  const result = ids(orderShortcuts(SHORTCUTS, ENGINE, { final: true }))
  expect(result.slice(0, 3)).toEqual(['pharmacy', 'retail', 'grocery'])
  expect(result.slice(-4)).toEqual(['rappitravel', 'rappifavor', 'loyalty', 'benefitspro'])
})

test('orderShortcuts ignora ids desconocidos y completa los que faltan', () => {
  const result = ids(orderShortcuts(SHORTCUTS, ['desconocido', 'licores', 'licores', 'turbo'], { final: true }))
  expect(result.slice(0, 6)).toEqual(['liquor', 'grocery', 'pharmacy', 'retail', 'express', 'chocolates'])
  expect(result).toHaveLength(SHORTCUTS.length)
})

test('Rappi hoy no cambia el orden', () => {
  expect(orderShortcuts(SHORTCUTS, ['farmacia'], { final: false })).toBe(SHORTCUTS)
})

test('Shortcuts con `proposal` pinta el orden recibido y el texto de debajo; sin él, el orden de hoy', () => {
  const { unmount } = render(
    <Shortcuts push={vi.fn()} proposal order={ENGINE} caption="Ordenadas según lo que más usas" />,
    {
      wrapper: ToastProvider,
    },
  )
  expect(labels().slice(0, 3)).toEqual(['Farmacia', 'Rappi Mall', 'Súper'])
  expect(screen.getByText('Ordenadas según lo que más usas')).toBeTruthy()
  unmount()
  render(<Shortcuts push={vi.fn()} order={ENGINE} />, { wrapper: ToastProvider })
  expect(labels()[0]).toBe('Súper')
  expect(screen.queryByText(/Ordenadas/)).toBeNull()
})

test('un acceso con vertical llama a onOpen con su código del backend; los demás no', () => {
  const onOpen = vi.fn()
  render(<Shortcuts push={vi.fn()} proposal onOpen={onOpen} />, { wrapper: ToastProvider })
  fireEvent.click(screen.getByText('Farmacia'))
  expect(onOpen).toHaveBeenCalledExactlyOnceWith('farmacia')
  onOpen.mockClear()
  for (const name of ['RappiTravel', 'RappiFavor', 'Lealtad', 'Beneficios Pro']) fireEvent.click(screen.getByText(name))
  expect(onOpen).not.toHaveBeenCalled()
})

test('abrir RappiTravel o RappiFavor llama a onService una vez con su servicio; si no abre, no', () => {
  const onService = vi.fn()
  const { unmount } = render(<Shortcuts push={vi.fn()} onService={onService} />, { wrapper: ToastProvider })
  fireEvent.click(screen.getByLabelText('RappiFavor (no disponible)'))
  expect(onService).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('RappiTravel'))
  expect(onService).toHaveBeenCalledExactlyOnceWith('rappitravel')
  unmount()
  onService.mockClear()
  render(<Shortcuts push={vi.fn()} proposal onService={onService} />, { wrapper: ToastProvider })
  for (const name of ['RappiFavor', 'RappiTravel', 'Farmacia', 'Lealtad']) fireEvent.click(screen.getByText(name))
  expect(onService.mock.calls).toEqual([['rappifavor'], ['rappitravel']])
})

test('los dos accesos grandes llaman a onOpen con restaurantes y turbo', () => {
  const onOpen = vi.fn()
  const push = vi.fn()
  render(<MainTiles push={push} onOpen={onOpen} />)
  fireEvent.click(screen.getByText('Restaurantes'))
  fireEvent.click(screen.getByText('Turbo'))
  expect(onOpen.mock.calls).toEqual([['restaurantes'], ['turbo']])
  expect(push).toHaveBeenCalledTimes(2)
})

test('la leyenda reserva su línea en el prototipo final aunque esté vacía, y Rappi hoy no la pinta', () => {
  const { container, unmount } = render(<Shortcuts push={vi.fn()} proposal order={ENGINE} />, {
    wrapper: ToastProvider,
  })
  expect(container.querySelector('.home-shortcuts-caption')?.textContent).toBe('')
  unmount()
  const today = render(<Shortcuts push={vi.fn()} />, { wrapper: ToastProvider })
  expect(today.container.querySelector('.home-shortcuts-caption')).toBeNull()
})
