// Guarda en el repo las respuestas simuladas del panel (npm run fixtures), sacadas de la foto de la API que graba
// `npm run panel:snapshot` (snapshot/panel.json): una sola grabación, de una sola API sobre una copia de la base, así
// que todas las cifras calzan entre sí. Escribe:
//  - src/fixtures/sin-conexion/<métrica>.json: las métricas que el panel muestra si la API no responde (todas las de
//    src/lib/metrics.js, con la fuente simulada);
//  - src/fixtures/<métrica>.synthetic.json: los ejemplos de los tests de las métricas que no fija `make contract`
//    (offers, unmet, combos, motor y volver los escribe rappi-ia con su simulación chica, y el CI los compara).
// Solo la fuente simulada: el uso del prototipo lleva lo que hizo la gente en la app y no se versiona (sin la API, el
// panel no lo muestra). Cada respuesta lleva su `guardado` ({ origen, fecha }), que el panel cita en el aviso.
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { PANEL_METRICS } from '../src/lib/metrics.js'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const SNAPSHOT = `${ROOT}snapshot/panel.json`
const FIXTURES = `${ROOT}src/fixtures/`
const OFFLINE = `${FIXTURES}sin-conexion/`
// Las que escribe `make contract` en rappi-ia (tests/integration/test_contract.py, PANEL_METRICS): aquí no se tocan.
const CONTRACT = new Set(['offers', 'unmet', 'combos', 'motor', 'volver'])

if (!existsSync(SNAPSHOT)) {
  console.error('Falta la foto de la API (snapshot/panel.json): corre antes `npm run panel:snapshot`.')
  process.exit(1)
}

const { grabado, respuestas } = JSON.parse(readFileSync(SNAPSHOT, 'utf8'))
const guardado = { origen: `npm run panel:snapshot · usuarios simulados de ${grabado.base}`, fecha: grabado.fecha }
const write = (file, body) => writeFileSync(file, `${JSON.stringify({ ...body, guardado }, null, 2)}\n`)

rmSync(OFFLINE, { recursive: true, force: true }) // una métrica que salió del panel no deja su respuesta vieja
mkdirSync(OFFLINE, { recursive: true })
for (const name of PANEL_METRICS) {
  const body = respuestas[`${name}.synthetic`]
  if (!body) throw new Error(`La foto no trae «${name}» con la fuente simulada: vuelve a correr npm run panel:snapshot`)
  write(`${OFFLINE}${name}.json`, body)
  if (!CONTRACT.has(name)) write(`${FIXTURES}${name}.synthetic.json`, body)
  console.log(`  ✓ ${name}`)
}
console.log(`Listo: respuestas del ${grabado.fecha} (base ${grabado.base})`)
