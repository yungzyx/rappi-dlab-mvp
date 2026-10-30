import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { fixture } from '../../test/api'
import { ProfileCard } from './TasteProfile'

afterEach(cleanup)

const asian = () => fixture('profile-gustos').perfiles[0]

test('«Tu perfil»: nombre, nivel en minúscula, el «por qué» y «Olvidar» arriba a la derecha', () => {
  const onForget = vi.fn()
  render(<ProfileCard profile={asian()} onForget={onForget} />)
  const card = screen.getByRole('region', { name: 'Tu perfil' })
  expect(card.querySelector('.taste-card-top').textContent).toBe('Tu perfilOlvidar')
  expect(card.textContent).toContain('Amante de lo asiático')
  expect(card.querySelector('.taste-level').textContent).toBe('nivel medio')
  expect(card.querySelectorAll('.taste-level-bar i.is-on')).toHaveLength(2)
  expect(card.querySelector('.taste-reason').textContent).toBe(
    'Pediste 🍣 sushi 2 veces, y buscaste 🥡 comida asiática 1 vez.',
  )
  fireEvent.click(screen.getByRole('button', { name: 'Olvidar' }))
  expect(onForget).toHaveBeenCalledTimes(1)
})

test('sin `onForget` no hay «Olvidar», y mientras se olvida no se toca dos veces', () => {
  render(<ProfileCard profile={asian()} />)
  expect(screen.queryByRole('button', { name: 'Olvidar' })).toBeNull()
  cleanup()
  render(<ProfileCard profile={asian()} onForget={() => {}} forgetting />)
  expect(screen.getByRole('button', { name: 'Olvidar' }).disabled).toBe(true)
})

test('«¿Por qué?» junta pedidos y búsquedas de cada concepto; sin su nombre, el id', () => {
  const profile = {
    ...asian(),
    basis: [
      { kind: 'concepto', id: 'sushi', score: 2, source: 'segmento:sushi' },
      { kind: 'concepto', id: 'sushi', score: 1, source: 'pedidos' },
      { kind: 'concepto', id: 'sushi', score: 3, source: 'busquedas' },
      { kind: 'concepto', id: 'ramen', score: 2, source: 'busquedas' },
    ],
    conceptos: { sushi: { nombre: 'Sushi', emoji: '🍣' } },
  }
  render(<ProfileCard profile={profile} />)
  const toggle = screen.getByRole('button', { name: /¿Por qué\?/ })
  fireEvent.click(toggle)
  expect(document.getElementById(toggle.getAttribute('aria-controls'))).toBe(document.querySelector('.taste-why'))
  expect([...document.querySelectorAll('.taste-why li')].map((li) => li.textContent)).toEqual([
    '🍣 Sushi · 1 pedido · 3 búsquedas',
    'ramen · 2 búsquedas',
  ])
})

test('sin pedidos ni búsquedas que mostrar, no hay «¿Por qué?»', () => {
  const profile = { ...asian(), basis: [{ kind: 'concepto', id: 'sushi', score: 2, source: 'segmento:sushi' }] }
  render(<ProfileCard profile={profile} />)
  expect(screen.queryByRole('button', { name: /¿Por qué\?/ })).toBeNull()
})
