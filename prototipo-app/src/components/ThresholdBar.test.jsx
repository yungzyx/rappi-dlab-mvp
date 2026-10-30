import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, test } from 'vitest'
import ThresholdBar from './ThresholdBar'
import { hoursLabel, promoLabel } from './storeHours'

afterEach(cleanup)

const bar = (total) =>
  render(
    <ThresholdBar
      goal={15000}
      total={total}
      title="Envío gratis"
      pending={(amount) => <>Agrega {amount} para lograrlo.</>}
      done="Listo."
    />,
  ).container

describe('ThresholdBar', () => {
  test('dice cuánto falta y avanza con lo que suma el carro', () => {
    const view = bar(5000)
    expect(view.textContent).toContain('Agrega $10.000 para lograrlo.')
    expect(view.querySelector('.threshold-bar-fill').style.width).toBe(`${(5000 / 15000) * 100}%`)
  })

  test('al llegar al monto dice que está listo', () => {
    const view = bar(20000)
    expect(view.textContent).toContain('Listo.')
    expect(view.querySelector('.threshold-bar-check').className).toContain('is-done')
  })
})

describe('storeHours', () => {
  const hours = (fields) => ({
    source: 'horario',
    open: false,
    closes_at: null,
    opens_at: null,
    opens_tomorrow: false,
    ...fields,
  })
  test('abierto, cerrado con la hora a la que abre (hoy o mañana) o sin saber', () => {
    expect(hoursLabel(hours({ open: true, closes_at: '23:00' }))).toBe('Abierto hasta las 23:00')
    expect(hoursLabel(hours({ opens_at: '11:00' }))).toBe('Cerrado · Abre a las 11:00')
    expect(hoursLabel(hours({ opens_at: '11:00', opens_tomorrow: true }))).toBe('Cerrado · Abre mañana a las 11:00')
    expect(hoursLabel(hours({}))).toBe('Cerrado hoy')
    expect(hoursLabel(hours({ source: 'descarga' }))).toBe('Cerrada')
    expect(hoursLabel(hours({ open: null }))).toBeNull()
    expect(hoursLabel(null)).toBeNull()
  })

  test('la promo de la tarjeta es la primera publicada, o "Con promociones" en un restaurante', () => {
    expect(promoLabel({ promos: [{ title: '10% OFF' }, { title: 'otra' }] })).toBe('10% OFF')
    expect(promoLabel({ promos: [], promo: true })).toBe('Con promociones')
    expect(promoLabel({ promos: [] })).toBeNull()
  })
})
