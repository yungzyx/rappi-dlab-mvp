// Genera las capturas de docs/screenshots (npm run screenshots): cada vista en escritorio y móvil, tema claro y oscuro.
// Usa el Chrome instalado (playwright-core, sin descargar navegadores; CHROME_PATH apunta a otro ejecutable y
// PLAYWRIGHT_CHANNEL a otro canal, p. ej. chrome-beta) y un servidor Vite propio en el 5198.
// Con la API de rappi-ia arriba usa datos en vivo; si no, el panel cae a los datos guardados (y lo avisa).
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'
import { createServer } from 'vite'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const OUT = `${ROOT}docs/screenshots`
const CHROME_PATH = process.env.CHROME_PATH
const CHROME_CHANNEL = process.env.PLAYWRIGHT_CHANNEL || 'chrome'
const PORT = 5198
const BASE = `http://localhost:${PORT}/`
const LOAD_TIMEOUT_MS = 45_000 // margen para una base fría (hoy /analytics/weekly responde en menos de 1 s)

const VIEWS = ['resumen', 'clientes', 'mochi']
const VIEWPORTS = [
  { name: 'escritorio', options: { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 } },
  {
    name: 'movil',
    options: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
  },
]
const THEMES = [
  { name: 'claro', colorScheme: 'light' },
  { name: 'oscuro', colorScheme: 'dark' },
]

async function settle(page) {
  await page.waitForFunction(() => !document.querySelector('.state--loading'), null, { timeout: LOAD_TIMEOUT_MS })
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(300)
}

async function capture(page, file) {
  await settle(page)
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  if (overflow > 0) console.warn(`  ! ${file}: ${overflow}px de scroll horizontal`)
  await page.screenshot({ path: `${OUT}/${file}.jpg`, type: 'jpeg', quality: 80, fullPage: true })
  console.log(`  ✓ ${file}`)
}

async function newPage(browser, { viewport, theme, offline = false }) {
  const context = await browser.newContext({
    ...viewport.options,
    colorScheme: theme.colorScheme,
    reducedMotion: 'reduce',
  })
  if (offline) await context.route(/localhost:80\d\d/, (route) => route.abort())
  return context.newPage()
}

async function run(browser) {
  for (const viewport of VIEWPORTS) {
    for (const theme of THEMES) {
      const page = await newPage(browser, { viewport, theme })
      for (const [index, view] of VIEWS.entries()) {
        await page.goto(`${BASE}?vista=${view}&fuente=simulados`)
        await capture(page, `${index + 1}-${view}-${viewport.name}-${theme.name}`)
      }
      await page.context().close()
    }
  }

  // Estados especiales: fuente del prototipo (métricas vacías) y API caída (datos guardados).
  const [desktop] = VIEWPORTS
  const [light] = THEMES
  const prototype = await newPage(browser, { viewport: desktop, theme: light })
  await prototype.goto(`${BASE}?vista=resumen&fuente=prototipo`)
  await capture(prototype, 'extra-resumen-prototipo-escritorio-claro')
  await prototype.context().close()

  const offline = await newPage(browser, { viewport: desktop, theme: light, offline: true })
  await offline.goto(`${BASE}?vista=resumen&fuente=simulados`)
  await capture(offline, 'extra-resumen-sin-conexion-escritorio-claro')
  await offline.context().close()
}

async function main() {
  mkdirSync(OUT, { recursive: true })
  const server = await createServer({ root: ROOT, server: { port: PORT, strictPort: true }, logLevel: 'error' })
  let browser
  try {
    await server.listen()
    browser = await chromium.launch(CHROME_PATH ? { executablePath: CHROME_PATH } : { channel: CHROME_CHANNEL })
    console.log(`Capturas en ${OUT}`)
    await run(browser)
  } finally {
    await browser?.close()
    await server.close()
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
