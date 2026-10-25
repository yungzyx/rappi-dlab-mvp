// Genera las capturas de docs/screenshots recorriendo la app como un usuario (npm run screenshots).
// Usa el Chrome instalado (playwright-core, sin descargar navegadores; CHROME_PATH apunta a otro ejecutable y
// PLAYWRIGHT_CHANNEL a otro canal, p. ej. chrome-beta) y un servidor Vite propio en el 5199.
// La app no abre sin la API: antes de capturar hay que tener el MVP corriendo (`make mvp`), o una API propia en otro
// puerto (`VITE_API_URL`, la misma variable que lee la app). El recorrido paga una compra y deja eventos en la base de
// la API: por eso no corre sin `SCREENSHOTS_ALLOW_WRITES=1`, y se corre sobre una copia
// (`DATABASE_URL=postgresql:///rappi_staging make mvp`), nunca sobre `rappi`.
// «¿Repetimos?» necesita tres compras con ritmo: esa oferta sale del fixture del contrato, con un café real del catálogo.
import { mkdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'
import { createServer } from 'vite'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const OUT = `${ROOT}docs/screenshots`
const CHROME_PATH = process.env.CHROME_PATH
const CHROME_CHANNEL = process.env.PLAYWRIGHT_CHANNEL || 'chrome'
const PORT = 5199
const BASE = `http://localhost:${PORT}/`
// La app del servidor Vite de abajo lee la misma variable (import.meta.env.VITE_API_URL).
const API = (process.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/+$/, '')
const API_HEALTH = `${API}/health`
const REPEAT_FIXTURE = `${ROOT}src/api/fixtures/agent-offer-recompra.json`

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function run(page) {
  // Espera a que carguen las imágenes visibles y a que terminen las transiciones de pantalla.
  // Las imágenes con loading="lazy" fuera de pantalla no cargan hasta hacer scroll: no se esperan.
  const settle = async (ms = 500) => {
    await page.evaluate(() =>
      Promise.all(
        [...document.images]
          .filter((img) => !img.complete && img.loading !== 'lazy')
          .map((img) => new Promise((done) => (img.onload = img.onerror = done))),
      ),
    )
    await wait(ms)
  }
  const shot = async (name, { full = false } = {}) => {
    await settle()
    // El interruptor de modo demo flota fuera del teléfono pero puede montarse sobre el marco: solo va en la portada.
    await page.evaluate((show) => {
      const toggle = document.querySelector('.demo-toggle')
      if (toggle) toggle.style.visibility = show ? '' : 'hidden'
    }, full)
    const target = full ? page : page.locator('.phone')
    await target.screenshot({ path: `${OUT}/${name}.jpg`, type: 'jpeg', quality: 82 })
    console.log(`  ✓ ${name}`)
  }
  const tap = (selector, text) =>
    page
      .locator(selector, text ? { hasText: text } : {})
      .first()
      .click()
  const back = () => tap('[aria-label="Volver"]')
  const tab = (label) => tap('.bottom-nav-item', label)
  // Lo que viene del catálogo llega después de abrir la pantalla: se espera a que esté (y a que carguen sus fotos).
  const loaded = async (selectors = []) => {
    for (const selector of selectors) await page.locator(selector).first().waitFor()
    if (selectors.length > 0) await settle(1500)
  }
  const shortcut = async (label) => {
    await page.locator('.home-shortcut', { hasText: label }).first().scrollIntoViewIfNeeded()
    await tap('.home-shortcut', label)
  }
  const reset = async () => {
    // Como quien ya vio la guía de la primera vez y el aviso de privacidad: taparían las capturas de la Home.
    await page.evaluate(() => {
      localStorage.clear()
      localStorage.setItem('rappi-proto-guia-vista', '1')
      localStorage.setItem('rappi-proto-privacy-seen', '1')
    })
    await page.goto(`${BASE}?r=${Date.now()}`)
    await page.waitForSelector('.home-shortcuts')
  }

  await page.goto(BASE)
  await reset()

  // --- Portada: modo demo y la Home en ambos modos (arranca en el prototipo final) ---
  await wait(4200) // Mochi entra a los 0,9 s y termina de escribir su saludo
  await shot('00-modo-demo', { full: true })
  await shot('01-home-final')
  await page.keyboard.press('d')
  await shot('02-home-rappi-hoy')

  // --- Pantallas replicadas de Rappi (modo "Rappi hoy": sin agregados del prototipo final) ---
  for (const [name, open, ready] of [
    ['10-restaurants', () => tap('.home-tile--restaurants'), ['.rest-list .featured-card']],
    ['11-turbo', () => tap('.home-tile--turbo'), ['.turbo-grid .product-card']],
    ['15-grocery', () => shortcut('Súper'), ['.vertical-store', '.vertical-product-row .product-card']],
    ['16-liquor', () => shortcut('Licores'), ['.vertical-store', '.vertical-product-row .product-card']],
    ['17-rappitravel', () => shortcut('RappiTravel')],
  ]) {
    await open()
    await loaded(ready)
    await shot(name)
    await back()
    await settle(400)
  }
  for (const [name, label, ready] of [
    ['12-deals', 'Ofertas', ['.deals .product-card', '.deals .featured-card']],
    [
      '13-favorites',
      'Favoritos',
      ['.favorites-row:not(.favorites-row--restaurants) .featured-card', '.favorites-row--restaurants .featured-card'],
    ],
    ['14-account', 'Cuenta'],
  ]) {
    await tab(label)
    await loaded(ready)
    await shot(name)
  }
  await tab('Inicio')
  await page.keyboard.press('d') // Rappi hoy → prototipo final
  await settle(400)

  // --- Lo nuevo del prototipo final ---
  await tap('.home-top .smart-bar') // la barra de la Home abre el buscador con Mochi
  await wait(1200) // animación de entrada del panel
  await tap('.assistant-chip', 'carrete')
  await wait(3800) // Mochi responde
  await shot('20-asistente')
  await tap('[role="dialog"] .search-back')
  await wait(600)

  await tab('Ofertas')
  // Un producto de las bajas de precio reales: el primero con la marca +18 (como la cerveza de antes) o, si no hay, el primero.
  await page.locator('.product-card').first().waitFor() // las bajas de precio llegan juntas, de una sola llamada
  const restricted = page.locator('.product-card').filter({ has: page.getByLabel('Solo mayores de 18') })
  const deal = (await restricted.count()) > 0 ? restricted : page.locator('.product-card')
  await deal.first().locator('.add-button').click()
  await wait(700)

  await tap('.cart-bar')
  await wait(500)
  await tap('.cart-checkout')
  await wait(800)
  await shot('25-checkout')
  await tap('.checkout-place')
  await wait(13000)
  await shot('26-seguimiento')
  await wait(10000) // el pedido llega
  await shot('27-entregado')
  await back()
  await settle(400)

  await tab('Cuenta')
  await tap('.account-row', 'Lealtad')
  await wait(700)
  await tap('.loyalty-row')
  await wait(500)
  await tap('.loyalty-sheet-primary')
  await wait(900)
  await shot('28-loyalty-vinculado')

  // --- La Home que aprende: otra persona entra dos veces a Chocolates y una a Rappi Mall ---
  await reset()
  await wait(4200) // el saludo de Mochi
  for (const label of ['Chocolates', 'Chocolates', 'Rappi Mall']) {
    await shortcut(label)
    await page.locator('.vertical-store').first().waitFor()
    await back()
    await settle(400)
  }
  await page.getByText('Ordenadas según lo que más usas').waitFor()
  // Abrir Rappi Mall corrió la fila hacia la derecha: vuelve al principio, como la ve quien llega a la Home.
  await page.locator('.home-shortcuts').evaluate((row) => {
    for (const el of [row, ...row.querySelectorAll('*')]) el.scrollLeft = 0
  })
  await shot('03-home-dinamica')

  // Tocar a Mochi en la Home: la API propone la vertical donde la persona aún no pide.
  await tap('.live-agent-body')
  await page.locator('.live-bubble .offer-why-toggle').waitFor({ timeout: 15000 })
  await tap('.live-bubble .offer-why-toggle')
  await shot('22-vertical-por-probar')

  // «¿Repetimos?»: la recompra del fixture del contrato, con un café molido real del catálogo.
  const repeat = await repeatOffer()
  await page.route('**/agent/offer', async (route) => {
    if (route.request().postDataJSON()?.moment !== 'recompra') return route.continue()
    const response = await route.fetch() // la API real (204 para esta persona): sus cabeceras CORS
    await route.fulfill({ response, status: 200, json: repeat })
  })
  await tab('Ofertas')
  await tab('Inicio') // al volver a estar arriba, la Home pide la recompra
  const block = page.locator('.live-card--repeat')
  await block.waitFor()
  // La Home baja hasta que los dos accesos grandes quedan justo bajo la barra de estado: se ven los accesos y el bloque.
  await page.locator('.home-tile--restaurants').evaluate((tile) => {
    let scroller = tile.parentElement
    while (scroller && scroller.scrollHeight <= scroller.clientHeight) scroller = scroller.parentElement
    const phone = tile.closest('.phone').getBoundingClientRect()
    scroller.scrollTop += tile.getBoundingClientRect().top - phone.top - 36
  })
  // La foto del producto es diferida (loading="lazy"): carga recién al quedar a la vista.
  await block
    .locator('img')
    .first()
    .evaluate((img) => img.complete || new Promise((done) => (img.onload = img.onerror = done)))
  await shot('21-recompra')
}

async function repeatOffer() {
  const fixture = JSON.parse(readFileSync(REPEAT_FIXTURE, 'utf8'))
  const params = new URLSearchParams({ q: 'café molido', vertical: fixture.vertical, limit: '10' })
  const { products } = await (await fetch(`${API}/search?${params}`)).json()
  const product = products.find((p) => p.img && !p.age_restricted)
  if (!product) throw new Error('No hay café molido en el catálogo para «¿Repetimos?»')
  return {
    ...fixture,
    products: [product],
    actions: fixture.actions.map((action) => ({ ...action, store_id: product.store_id })),
  }
}

function requireWritesAllowed() {
  if (process.env.SCREENSHOTS_ALLOW_WRITES === '1') return
  console.error(
    'Las capturas pagan una compra y dejan un pedido y eventos en la base que usa la API.\n' +
      'Apunta la API a una copia, nunca a `rappi`: `DATABASE_URL=postgresql:///rappi_staging make mvp`,\n' +
      'y después corre `SCREENSHOTS_ALLOW_WRITES=1 npm run screenshots`.',
  )
  process.exit(1)
}

async function requireApi() {
  const response = await fetch(API_HEALTH, { signal: AbortSignal.timeout(3000) }).catch(() => null)
  if (response?.ok) return
  console.error(
    'Las capturas necesitan el MVP corriendo sobre una copia: `DATABASE_URL=postgresql:///rappi_staging make mvp`',
  )
  process.exit(1)
}

async function main() {
  requireWritesAllowed()
  await requireApi()
  mkdirSync(OUT, { recursive: true })

  const server = await createServer({ root: ROOT, server: { port: PORT, strictPort: true }, logLevel: 'error' })
  let browser
  try {
    await server.listen()
    browser = await chromium.launch(CHROME_PATH ? { executablePath: CHROME_PATH } : { channel: CHROME_CHANNEL })
    const page = await browser.newPage({ viewport: { width: 560, height: 960 }, deviceScaleFactor: 2 })
    console.log(`Capturas en ${OUT}`)
    await run(page)
  } finally {
    await browser?.close()
    await server.close()
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
