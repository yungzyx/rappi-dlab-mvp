// Graba las respuestas que lee el panel (npm run panel:snapshot) en snapshot/panel.json, para armarlo en un solo HTML
// que abre sin la API ni internet (npm run panel:html). Solo pide (GET): no escribe nada en la base.
//
// La API debe correr sobre una COPIA de la base, nunca sobre `rappi`: el archivo se comparte suelto y lleva lo que la
// gente hizo en la app (cuentas y, en la lista de riesgo, personas con id seudónimo y su concepto top no sensible).
// Desde rappi-ia:
//   DATABASE_URL=postgresql:///rappi_staging HF_HUB_OFFLINE=1 API_PREWARM=0 \
//     .venv/bin/python -m uvicorn rappi_ia.api.app:app --host 127.0.0.1 --port 8020
//   PANEL_API_URL=http://127.0.0.1:8020 npm run panel:snapshot
// Se niega a usar el puerto 8000 (la API de `make mvp`, sobre `rappi`) o un host que no sea de este equipo. La API no
// dice sobre qué base corre: el nombre que muestra el archivo es el que declara PANEL_SNAPSHOT_BASE (por defecto,
// rappi_staging), y quien graba responde por él.
import { mkdirSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { PANEL_METRICS } from '../src/lib/metrics.js'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const OUT_DIR = `${ROOT}snapshot/`
const API = (process.env.PANEL_API_URL || 'http://127.0.0.1:8020').replace(/\/+$/, '')
const BASE = process.env.PANEL_SNAPSHOT_BASE || 'rappi_staging'
const SOURCES = ['synthetic', 'prototype']
const MAIN_API_PORT = '8000'
const LOOPBACK = new Set(['127.0.0.1', 'localhost', '[::1]', '::1'])

const target = new URL(API)
const port = target.port || (target.protocol === 'https:' ? '443' : '80')
if (port === MAIN_API_PORT || !LOOPBACK.has(target.hostname)) {
  console.error(
    `No grabo desde ${API}: el puerto ${MAIN_API_PORT} es la API del MVP (base \`rappi\`) y solo se aceptan hosts de ` +
      'este equipo. Levanta una API sobre `rappi_staging` en otro puerto (ver el inicio de este archivo).',
  )
  process.exit(1)
}
if (BASE === 'rappi') {
  console.error('La foto no se graba desde la base `rappi`: usa una copia (PANEL_SNAPSHOT_BASE=rappi_staging).')
  process.exit(1)
}

console.log(`Grabando desde ${API} (base ${BASE})…`)
const respuestas = {}
for (const source of SOURCES) {
  for (const name of PANEL_METRICS) {
    const response = await fetch(`${API}/analytics/${name}?source=${source}`)
    if (!response.ok) throw new Error(`/analytics/${name}?source=${source} respondió ${response.status}`)
    const body = await response.json()
    if (body.source !== source) throw new Error(`/analytics/${name} respondió la fuente ${body.source}, no ${source}`)
    respuestas[`${name}.${source}`] = body
  }
}

const fecha = new Date().toLocaleDateString('en-CA') // AAAA-MM-DD en la hora local
mkdirSync(OUT_DIR, { recursive: true })
writeFileSync(`${OUT_DIR}panel.json`, `${JSON.stringify({ grabado: { fecha, base: BASE }, respuestas })}\n`)
console.log(`Listo: snapshot/panel.json (${Object.keys(respuestas).length} respuestas, ${fecha})`)
