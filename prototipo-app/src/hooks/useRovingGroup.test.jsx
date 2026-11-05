import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, expect, test } from 'vitest'
import { useRovingGroup } from './useRovingGroup'

const OPTIONS = ['Uno', 'Dos', 'Tres', 'Cuatro']

function Group({ initial = -1, disabled = [] }) {
  const [chosen, setChosen] = useState(initial)
  const roving = useRovingGroup(OPTIONS.length, chosen, setChosen, (i) => disabled.includes(i))
  return (
    <div role="radiogroup" aria-label="Prueba" onKeyDown={roving.onKeyDown}>
      {OPTIONS.map((label, i) => (
        <button
          key={label}
          type="button"
          role="radio"
          aria-checked={chosen === i}
          disabled={disabled.includes(i)}
          onClick={() => setChosen(i)}
          {...roving.itemProps(i)}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

afterEach(cleanup)

const radio = (name) => screen.getByRole('radio', { name })
const stops = () => screen.getAllByRole('radio').filter((el) => el.tabIndex === 0)
const press = (key, extra = {}) => fireEvent.keyDown(document.activeElement, { key, ...extra })

test('una sola parada de Tab: la elegida o, sin elegida, la primera habilitada', () => {
  render(<Group />)
  expect(stops()).toEqual([radio('Uno')])
  cleanup()
  render(<Group initial={2} />)
  expect(stops()).toEqual([radio('Tres')])
  cleanup()
  render(<Group disabled={[0]} />)
  expect(stops()).toEqual([radio('Dos')])
})

test('las flechas eligen y enfocan, con vuelta en los dos sentidos', () => {
  render(<Group initial={0} />)
  radio('Uno').focus()
  press('ArrowRight')
  expect(document.activeElement).toBe(radio('Dos'))
  expect(radio('Dos').getAttribute('aria-checked')).toBe('true')
  expect(stops()).toEqual([radio('Dos')])
  press('ArrowDown')
  expect(document.activeElement).toBe(radio('Tres'))
  press('ArrowUp')
  press('ArrowLeft')
  expect(document.activeElement).toBe(radio('Uno'))
  press('ArrowLeft')
  expect(document.activeElement).toBe(radio('Cuatro'))
  expect(radio('Cuatro').getAttribute('aria-checked')).toBe('true')
  press('ArrowRight')
  expect(document.activeElement).toBe(radio('Uno'))
})

test('Inicio y Fin van a los extremos; las deshabilitadas se saltan', () => {
  render(<Group initial={1} disabled={[2, 3]} />)
  radio('Dos').focus()
  press('End')
  expect(document.activeElement).toBe(radio('Dos'))
  press('Home')
  expect(document.activeElement).toBe(radio('Uno'))
  expect(radio('Uno').getAttribute('aria-checked')).toBe('true')
  press('ArrowRight')
  press('ArrowRight')
  expect(document.activeElement).toBe(radio('Uno'))
  cleanup()
  render(<Group initial={1} />)
  radio('Dos').focus()
  press('End')
  expect(document.activeElement).toBe(radio('Cuatro'))
  press('Home')
  expect(document.activeElement).toBe(radio('Uno'))
})

test('con un modificador o con otra tecla no hace nada', () => {
  render(<Group initial={0} />)
  radio('Uno').focus()
  press('ArrowRight', { shiftKey: true })
  press('ArrowRight', { altKey: true })
  press('ArrowRight', { metaKey: true })
  press('ArrowRight', { ctrlKey: true })
  press('a')
  expect(document.activeElement).toBe(radio('Uno'))
  expect(radio('Uno').getAttribute('aria-checked')).toBe('true')
})
