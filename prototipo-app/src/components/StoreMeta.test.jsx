import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, test } from 'vitest'
import { StoreMeta } from './StoreMeta'

afterEach(cleanup)

const meta = (store) => render(<StoreMeta store={store} />).container.querySelector('.featured-meta')

describe('StoreMeta', () => {
  test('sin tiempo de entrega no queda un punto suelto al principio', () => {
    const line = meta({ etaIcon: 'none', fee: '$990' })
    expect(line.textContent).toBe('$990')
    expect(line.querySelector('.meta-sep')).toBeNull()
  })

  test('con tiempo y envío los separa con un punto', () => {
    expect(meta({ eta: '15 min', etaIcon: 'clock', fee: '$990' }).textContent).toBe('15 min•$990')
  })

  test('sin ningún dato la línea queda vacía', () => {
    expect(meta({ etaIcon: 'none' }).textContent).toBe('')
  })
})
