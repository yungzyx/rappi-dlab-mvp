import { describe, expect, test } from 'vitest'
import { demandLabel, describeFallbacks, describeOrigins, plural, verticalLabel } from './labels.js'

describe('describeFallbacks', () => {
  test('nombra la consulta y el motivo', () => {
    expect(describeFallbacks([{ name: 'weekly', reason: 'no respondió en 30 s' }])).toBe(
      'serie semanal (no respondió en 30 s)',
    )
  })

  test('resume listas largas y no repite motivos', () => {
    const fallbacks = ['kpis', 'trends', 'offers', 'combos', 'motor'].map((name) => ({
      name,
      reason: 'no responde',
    }))

    expect(describeFallbacks(fallbacks)).toBe('indicadores, tendencias y 3 más (no responde)')
  })

  test('une dos consultas con «y» y junta motivos distintos', () => {
    const fallbacks = [
      { name: 'weekly', reason: 'no respondió en 30 s' },
      { name: 'kpis', reason: 'respondió 500' },
    ]

    expect(describeFallbacks(fallbacks)).toBe('serie semanal y indicadores (no respondió en 30 s; respondió 500)')
  })
})

describe('describeFallbacks de las consultas del MVP', () => {
  test('nombra en español las métricas nuevas y los servicios', () => {
    const fallbacks = ['offers', 'unmet'].map((name) => ({ name, reason: 'no responde' }))
    expect(describeFallbacks(fallbacks)).toBe('ofertas por momento y búsquedas sin resultado (no responde)')
    expect(describeFallbacks([{ name: 'unmet', reason: 'no responde' }])).toBe('búsquedas sin resultado (no responde)')
    expect(describeFallbacks([{ name: 'services', reason: 'no responde' }])).toBe(
      'servicios sin catálogo (no responde)',
    )
  })
})

describe('etiquetas', () => {
  test('verticales del backend con nombre visible, y el código si no se conoce', () => {
    expect(verticalLabel('mall')).toBe('Rappi Mall')
    expect(verticalLabel('chocolateria')).toBe('Chocolatería')
    expect(verticalLabel('nuevo')).toBe('nuevo')
  })

  test('demandLabel cita la consulta cuando no hay concepto', () => {
    expect(demandLabel({ concept_id: 'peruana', que: '🇵🇪 Comida peruana' })).toBe('🇵🇪 Comida peruana')
    expect(demandLabel({ concept_id: null, que: 'kombucha' })).toBe('«kombucha»')
  })

  test('demandLabel no pinta «null» si la consulta se borró por retención', () => {
    expect(demandLabel({ concept_id: null, que: null })).toBe('Consulta borrada (más de 90 días)')
  })

  test('plural', () => {
    expect(`1 ${plural(1, 'tienda')}`).toBe('1 tienda')
    expect(`8 ${plural(8, 'tienda')}`).toBe('8 tiendas')
  })
})

describe('describeOrigins', () => {
  test('lists each saved origin once, with its date', () => {
    const simulated = { origen: 'simulación', fecha: '2026-10-09' }
    expect(
      describeOrigins([
        { guardado: simulated },
        { guardado: simulated },
        { guardado: { origen: 'muestra pública', fecha: '2026-10-09' } },
      ]),
    ).toBe('simulación (2026-10-09) y muestra pública (2026-10-09)')
  })

  test('says so when a saved response has no origin', () => {
    expect(describeOrigins([{ guardado: null }])).toBe('origen sin registrar')
  })
})
