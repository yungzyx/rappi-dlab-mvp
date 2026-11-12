// @vitest-environment node
import { readFileSync } from 'node:fs'
import { expect, test } from 'vitest'
import { TRIP_PHOTOS } from './trips'

const DESTINATIONS = new URL('../../../rappi-ia/src/rappi_ia/offers/destinos.toml', import.meta.url)

test('cada destino de offers/destinos.toml tiene su foto y su crédito', () => {
  const ids = [...readFileSync(DESTINATIONS, 'utf8').matchAll(/^id = "([^"]+)"/gm)].map((m) => m[1])
  expect(ids.length).toBeGreaterThan(0)
  for (const id of ids) {
    expect(TRIP_PHOTOS[id], id).toEqual(
      expect.objectContaining({ img: expect.any(String), credit: expect.any(String) }),
    )
    expect(TRIP_PHOTOS[id].creditUrl, id).toMatch(/^https:\/\//)
  }
})
