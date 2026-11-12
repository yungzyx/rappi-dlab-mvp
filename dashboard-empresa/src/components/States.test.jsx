import { render } from '@testing-library/react'
import { describe, expect, test } from 'vitest'
import { EmptyState } from './States.jsx'

describe('EmptyState en una línea', () => {
  test('separa el título del texto con un punto', () => {
    const { container } = render(
      <EmptyState title="El grupo de control está apagado" inline>
        Nadie tiene variante.
      </EmptyState>,
    )
    expect(container.querySelector('p').textContent).toBe('El grupo de control está apagado. Nadie tiene variante.')
  })

  test('si el título ya termina en puntuación, solo un espacio', () => {
    const { container } = render(
      <EmptyState title="¿Por qué no hay datos?" inline>
        Falta correr el motor.
      </EmptyState>,
    )
    expect(container.querySelector('p').textContent).toBe('¿Por qué no hay datos? Falta correr el motor.')
  })

  test('sin texto, solo el título', () => {
    const { container } = render(<EmptyState title="Sin evaluación todavía" inline />)
    expect(container.querySelector('p').textContent).toBe('Sin evaluación todavía')
  })
})
