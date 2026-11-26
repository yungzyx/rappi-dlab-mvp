// @vitest-environment node
import { readFileSync } from 'node:fs'
import { describe, expect, test } from 'vitest'
import { redact } from './redact'

// Los mismos casos que el backend (rappi-ia/tests/unit/test_privacy.py), leídos del .py: si cambian allá, se prueban acá.
const PY = readFileSync(new URL('../../../../rappi-ia/tests/unit/test_privacy.py', import.meta.url), 'utf8')
const block = (name) => PY.match(new RegExp(`^${name} = \\[([\\s\\S]*?)^\\]`, 'm'))[1]
const REDACTED = [...block('REDACTED').matchAll(/^\s*\("(.+?)", "(.+?)"\),/gm)].map(([, text, expected]) => [
  text,
  expected,
])
const UNCHANGED = [...block('UNCHANGED').matchAll(/^\s*"(.+?)",/gm)].map(([, text]) => text)

describe('la demo sin conexión redacta las consultas como el backend (events/store.py: redact)', () => {
  test('lee los casos del backend', () => {
    expect(REDACTED.length).toBeGreaterThan(10)
    expect(UNCHANGED.length).toBeGreaterThan(5)
  })

  test.each(REDACTED)('%s → %s', (text, expected) => {
    expect(redact(text)).toBe(expected)
  })

  test.each(UNCHANGED)('"%s" queda igual', (text) => {
    expect(redact(text)).toBe(text)
  })

  test('sin texto, nada', () => {
    expect(redact(null)).toBeNull()
    expect(redact(undefined)).toBeUndefined()
  })
})
