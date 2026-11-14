import { afterEach, describe, expect, test, vi } from 'vitest'
import { offer, plans, profileLadder } from './agent'
import { fixture, stubApi } from '../test/api'
import { userId } from './user'
import { setAgentEnabled } from '../state/agentEnabled'

afterEach(() => vi.unstubAllGlobals())

describe('agent', () => {
  test('offer devuelve null en un 204 y marca los productos como sugerencia del agente', async () => {
    stubApi({ 'POST /agent/offer': (req) => (req.body.moment === 'carrito' ? fixture('agent-offer-carrito') : 204) })
    const made = await offer('carrito', { product: { entity_type: 'catalog_item', entity_id: '94001' } })
    expect(made).toMatchObject({
      moment: 'carrito',
      vertical: 'express',
      backendVertical: 'conveniencia',
      text: 'Para completar tu pedido: snacks salados, en Express.',
      reason: { concept: 'snacks-salados', from_concept: 'cerveza' },
      actions: [{ label: 'Ver snacks salados', query: 'snacks salados', route: ['vertical', { id: 'express' }] }],
    })
    expect(made.products[0]).toMatchObject({
      entityId: '91001',
      vertical: 'express',
      concept: 'snacks-salados',
      fromSuggestion: true,
      suggestionOrigin: 'agent-carrito',
    })

    expect(await offer('checkout', { cart: [] })).toBeNull()
  })

  test('la escalera del perfil lleva las posiciones de corrido entre peldaños: ninguna se repite', async () => {
    const reply = fixture('agent-offer-perfil')
    reply.escalera[0].products = [...reply.escalera[0].products, ...reply.escalera[1].products]
    stubApi({ 'POST /agent/offer': reply })
    const ladder = await profileLadder('sushi')
    const positions = ladder.steps.flatMap((step) => step.products.map((p) => p.placement.position))
    expect(positions).toEqual([...positions.keys()])
    expect(ladder.steps[1].products[0].placement).toMatchObject({ origin: 'agent-perfil', position: 2 })
  })

  test('las ofertas usan /agent/offer y el origen agent-<momento>', async () => {
    const calls = stubApi({ 'POST /agent/offer': fixture('agent-offer-plan') })
    const made = await offer('plan', { occasion: 'carrete' })
    expect(String(calls.mock.calls[0][0])).toMatch(/\/agent\/offer$/)
    expect(made.products.length).toBeGreaterThan(0)
    expect(made.products.every((p) => p.suggestionOrigin === 'agent-plan')).toBe(true)
  })

  test('offer manda el momento, el contexto, el usuario y su sesión (para el grupo de control)', async () => {
    const calls = stubApi({ 'POST /agent/offer': fixture('agent-offer-plan') })
    await offer('plan', { occasion: 'carrete' }, { userId: 'u1' })
    expect(JSON.parse(calls.mock.calls[0][1].body)).toEqual({
      moment: 'plan',
      user_id: 'u1',
      session_id: expect.stringMatching(/^s-[0-9a-f]{16}$/),
      context: { occasion: 'carrete' },
    })
    // Sin persona no va la sesión: nadie entra al grupo de control.
    await offer('plan', { occasion: 'carrete' })
    expect(JSON.parse(calls.mock.calls[1][1].body)).toEqual({ moment: 'plan', context: { occasion: 'carrete' } })
  })

  test('offer manda la pantalla: lo pedido desde el buscador (agent) el grupo de control lo ve', async () => {
    const calls = stubApi({ 'POST /agent/offer': 204 })
    await offer('recompra', {}, { userId: 'u1', surface: 'agent' })
    expect(JSON.parse(calls.mock.calls[0][1].body)).toEqual({
      moment: 'recompra',
      user_id: 'u1',
      session_id: expect.stringMatching(/^s-[0-9a-f]{16}$/),
      surface: 'agent',
      context: {},
    })
  })

  test('un 204 retenido al grupo de control es null y avisa con onWithheld; uno sin oferta, no', async () => {
    const withheld = new Response(null, { status: 204, headers: { 'X-Offer-Withheld': '1' } })
    stubApi({ 'POST /agent/offer': (req) => (req.body.moment === 'recompra' ? withheld : 204) })
    const onWithheld = vi.fn()
    expect(await offer('recompra', {}, { userId: 'u1', surface: 'home', onWithheld })).toBeNull()
    expect(onWithheld).toHaveBeenCalledTimes(1)
    expect(await offer('volver', {}, { userId: 'u1', surface: 'home', onWithheld })).toBeNull()
    expect(onWithheld).toHaveBeenCalledTimes(1)
  })

  test('con Mochi apagado (el grupo de control) la oferta se pide igual, pero nunca se entrega a la app', async () => {
    const calls = stubApi({ 'POST /agent/offer': fixture('agent-offer-carrito') })
    setAgentEnabled(false)
    const onWithheld = vi.fn()
    expect(await offer('carrito', {}, { userId: 'u1', surface: 'home', onWithheld })).toBeNull()
    expect(calls).toHaveBeenCalledTimes(1) // la API la anota como en tratamiento
    expect(onWithheld).not.toHaveBeenCalled()
    setAgentEnabled(true)
    expect((await offer('carrito', {}, { userId: 'u1', surface: 'home' })).products.length).toBeGreaterThan(0)
  })

  test('las acciones traen la ruta de la pantalla de la app (Turbo tiene la suya) o ninguna si la vertical no se conoce', async () => {
    const body = fixture('agent-offer-carrito')
    body.actions = [
      { label: 'Ver hielo', query: 'hielo', route: ['turbo'] },
      { label: 'Más ideas', query: 'cerveza' },
      { label: 'Sin pantalla', route: [null] },
    ]
    stubApi({ 'POST /agent/offer': body })
    const made = await offer('carrito', { product: { entity_type: 'catalog_item', entity_id: '94001' } })
    expect(made.actions).toEqual([
      { label: 'Ver hielo', query: 'hielo', route: ['turbo'] },
      { label: 'Más ideas', query: 'cerveza' },
      { label: 'Sin pantalla' },
    ])
  })

  test('plans sends the user and keeps the reason of the personalized occasions', async () => {
    const api = stubApi({ '/agent/plans': fixture('agent-plans-afin') })
    const list = await plans()
    expect(new URL(api.mock.calls[0][0], 'http://localhost').searchParams.get('user_id')).toBe(userId())
    expect(list[0].reason.text).toMatch(/^Por tu interés en/)
    expect(list.at(-1).reason).toBeUndefined()
  })

  test('plans devuelve las ocasiones', async () => {
    stubApi({ '/agent/plans': fixture('agent-plans') })
    const list = await plans()
    expect(list[0]).toEqual({ id: 'once', name: 'Once', emoji: '☕' })
  })
})
