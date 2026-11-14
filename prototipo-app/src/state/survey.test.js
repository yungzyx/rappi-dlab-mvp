import { afterEach, expect, test } from 'vitest'
import {
  canAsk,
  currentJourney,
  endJourney,
  markAsked,
  observeEvent,
  resetSurvey,
  surveyTrigger,
  whyOpened,
} from './survey'

afterEach(() => {
  resetSurvey()
  localStorage.clear()
})

const NOW = Date.UTC(2026, 10, 13, 15)
const path = () => currentJourney(NOW)

test('una búsqueda empieza el recorrido; un toque en otra lista no lo marca', () => {
  observeEvent({ type: 'search', request_id: 'r1' }, NOW)
  observeEvent({ type: 'view_item', request_id: 'otra-lista' }, NOW)
  observeEvent({ type: 'cart_add', request_id: 'otra-lista' }, NOW)
  expect(surveyTrigger(path())).toBe('abandono')
  expect(path().requestId).toBe('r1')
})

test('un toque en sus resultados lo marca, y lo agregado después (desde la tienda que abrió) es carro', () => {
  observeEvent({ type: 'search', request_id: 'r1' }, NOW)
  observeEvent({ type: 'view_store', request_id: 'r1' }, NOW)
  expect(surveyTrigger(path())).toBe('busqueda')
  observeEvent({ type: 'cart_add', request_id: 'lista-de-la-tienda' }, NOW)
  expect(surveyTrigger(path())).toBe('carro')
})

test('con varias búsquedas, la respuesta va con la que se tocó', () => {
  observeEvent({ type: 'search', request_id: 'r1' }, NOW)
  observeEvent({ type: 'view_item', request_id: 'r1' }, NOW)
  observeEvent({ type: 'search', request_id: 'r2' }, NOW)
  expect(path()).toMatchObject({ requestId: 'r1', touched: true, requestIds: ['r1', 'r2'] })
})

test('un recorrido de una sesión que ya terminó (30 min) no se pregunta', () => {
  observeEvent({ type: 'search', request_id: 'r1' }, NOW)
  expect(currentJourney(NOW + 31 * 60_000)).toBeNull()
  endJourney()
  expect(path()).toBeNull()
})

test('una por sesión y una por día', () => {
  expect(canAsk('s1', '2026-11-13')).toBe(true)
  markAsked('s1', '2026-11-13')
  expect(canAsk('s1', '2026-11-14')).toBe(false)
  expect(canAsk('s2', '2026-11-13')).toBe(false)
  expect(canAsk('s2', '2026-11-14')).toBe(true)
})

test('el "¿Por qué?" abierto vale para su sesión', () => {
  observeEvent({ type: 'offer_why_open', session_id: 's1' }, NOW)
  expect(whyOpened('s1')).toBe(true)
  expect(whyOpened('s2')).toBe(false)
})
