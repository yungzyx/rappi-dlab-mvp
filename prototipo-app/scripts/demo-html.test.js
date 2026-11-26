// @vitest-environment node
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { saveDemoHtml } from './demo-html.mjs'

let dir
beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), 'demo-html-'))
  vi.spyOn(console, 'log').mockImplementation(() => {})
  vi.spyOn(console, 'error').mockImplementation(() => {})
})
afterEach(() => {
  rmSync(dir, { recursive: true, force: true })
  vi.restoreAllMocks()
})

describe('el HTML de la demo sin conexión', () => {
  test('dentro del tope se escribe y se copia', () => {
    const out = join(dir, 'Prototipo MVP.html')
    const copy = join(dir, 'copia.html')
    expect(saveDemoHtml('<html>ok</html>', { out, copy, max: 100 })).toBe(true)
    expect(readFileSync(out, 'utf8')).toBe('<html>ok</html>')
    expect(readFileSync(copy, 'utf8')).toBe('<html>ok</html>')
  })

  test('sobre el tope no reemplaza el entregable ni su copia', () => {
    const out = join(dir, 'Prototipo MVP.html')
    const copy = join(dir, 'copia.html')
    writeFileSync(copy, 'la copia que ya se entregó')
    expect(saveDemoHtml('x'.repeat(101), { out, copy, max: 100 })).toBe(false)
    expect(existsSync(out)).toBe(false)
    expect(readFileSync(copy, 'utf8')).toBe('la copia que ya se entregó')
  })
})
