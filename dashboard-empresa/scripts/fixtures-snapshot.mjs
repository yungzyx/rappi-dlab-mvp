// Arma snapshot/panel.json desde las respuestas de ejemplo de src/fixtures/<métrica>.<fuente>.json (las del contrato y
// las de `npm run fixtures`), con el mismo formato que graba `npm run panel:snapshot` ({ grabado, respuestas }). Sirve
// para probar `npm run panel:html` sin una API (el CI lo hace): el HTML que sale muestra esos ejemplos, no una foto de
// la base. No pisa una foto grabada: si snapshot/panel.json ya existe, se detiene.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { PANEL_METRICS } from '../src/lib/metrics.js'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const FIXTURES = `${ROOT}src/fixtures/`
const OUT_DIR = `${ROOT}snapshot/`
const OUT = `${OUT_DIR}panel.json`
const SOURCES = ['synthetic', 'prototype']

if (existsSync(OUT)) {
  console.error(
    'Ya hay una foto en snapshot/panel.json: no la piso (bórrala antes si quieres armarla desde los ejemplos).',
  )
  process.exit(1)
}

const respuestas = {}
for (const source of SOURCES) {
  for (const name of PANEL_METRICS) {
    const file = `${FIXTURES}${name}.${source}.json`
    if (!existsSync(file)) throw new Error(`Falta el ejemplo src/fixtures/${name}.${source}.json`)
    const body = JSON.parse(readFileSync(file, 'utf8'))
    delete body.guardado // de dónde salió el ejemplo: la API no lo manda
    if (body.source !== source) throw new Error(`src/fixtures/${name}.${source}.json trae la fuente ${body.source}`)
    respuestas[`${name}.${source}`] = body
  }
}

const fecha = new Date().toLocaleDateString('en-CA') // AAAA-MM-DD en la hora local
mkdirSync(OUT_DIR, { recursive: true })
writeFileSync(OUT, `${JSON.stringify({ grabado: { fecha, base: 'ejemplos de src/fixtures' }, respuestas })}\n`)
console.log(`Listo: snapshot/panel.json desde los ejemplos (${Object.keys(respuestas).length} respuestas)`)
