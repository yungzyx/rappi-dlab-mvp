import { describe, expect, test } from 'vitest'
import { looksLikeQuestion } from './question'

describe('looksLikeQuestion', () => {
  test.each([
    '¿qué llevo para un asado de 6?',
    'algo para la tos de mi hija',
    'qué me recomiendas',
    'quiero algo dulce y barato',
    'tengo hambre',
    'sushi para 2',
    'qué puedo cenar con 8 mil pesos',
    'qué es un poke',
    'con qué acompaño un salmón',
    'necesito cosas para limpiar la casa',
  ])('«%s» es una pregunta', (text) => {
    expect(looksLikeQuestion(text)).toBe(true)
  })

  test.each([
    'cerveza',
    'pañales talla G',
    'leche sin lactosa',
    'papas fritas lays',
    'coca cola 3 litros',
    'coca cola zero 3 litros',
    'papas fritas lays 250 gr',
    'leche descremada sin lactosa colun',
    'torta mil hojas',
    'como agua para chocolate',
    '',
    '  ',
  ])('«%s» es una búsqueda', (text) => {
    expect(looksLikeQuestion(text)).toBe(false)
  })
})
