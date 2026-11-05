import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, test } from 'vitest'
import { Delta } from './Delta.jsx'

const textOf = (goodWhen) => render(<Delta value={2} format={String} goodWhen={goodWhen} />).container.textContent

describe('Delta', () => {
  afterEach(cleanup)

  test('says the judgement in text, not only with the color', () => {
    expect(textOf('down')).toContain('(empeora)')
    expect(textOf('up')).toContain('(mejora)')
    const neutral = textOf(null)
    expect(neutral).not.toContain('(mejora)')
    expect(neutral).not.toContain('(empeora)')
  })
})
