// Genera las capturas de docs/screenshots recorriendo la app como un usuario (npm run screenshots).
// Usa el Chrome instalado (playwright-core, sin descargar navegadores; CHROME_PATH apunta a otro ejecutable y
// PLAYWRIGHT_CHANNEL a otro canal, p. ej. chrome-beta) y un servidor Vite propio en el 5199.
// La app no abre sin la API: antes de capturar hay que tener el MVP corriendo (`make mvp`), o una API propia en otro
// puerto (`VITE_API_URL`, la misma variable que lee la app). El recorrido paga dos compras (una en Ofertas y otra en
// Chocolates, para la Home dinámica) y deja pedidos y eventos en la base de la API: por eso no corre sin
// `SCREENSHOTS_ALLOW_WRITES=1`, y se corre sobre una copia (`DATABASE_URL=postgresql:///rappi_staging make mvp`),
// nunca sobre `rappi`.
// La conversación (45, 46 y 48) se pide en el buscador y se refina con los chips "Más barato" y "Sin carne".
// "¿Repetimos?" necesita tres compras con ritmo: esa oferta sale del fixture del contrato, con un café real del catálogo.
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
  // En el checkout: la compra mínima de cada tienda (más unidades hasta llegar, "Te faltan $X para hacer el pedido"),
  // "Hacer pedido", la edad si hay algo +18 (una vez por sesión) y, pasada la ventana de "Deshacer pedido", el pedido
  // en la API (POST /orders).
  const placeOrder = async () => {
    const short = page.locator('.checkout-basket:has(.basket-min.is-short)')
    for (let tries = 0; tries < 60 && (await short.count()) > 0; tries++) {
      await short
        .first()
        .getByRole('button', { name: /^Agregar uno de / })
        .first()
        .click()
      await wait(100)
    }
    const posted = page.waitForResponse(
      (r) => r.request().method() === 'POST' && r.url() === `${API}/orders`, // la URL que arma la app (VITE_API_URL)
      { timeout: 30000 },
    )
    await tap('.checkout-place')
    const adult = page.getByRole('button', { name: 'Sí, soy mayor de edad' })
    if (
      await adult.waitFor({ timeout: 2000 }).then(
        () => true,
        () => false,
      )
    )
      await adult.click()
    const response = await posted
    if (!response.ok()) throw new Error(`la API rechazó el pedido (POST /orders → ${response.status()})`)
  }
  // Del seguimiento de un pedido a la Home: "Volver al inicio" o la flecha de atrás, las veces que haga falta (la Home
  // queda debajo, oculta, y sin la barra de abajo), como checkHome de scripts/mvp-check.mjs.
  const backHome = async () => {
    const home = page.locator('.home-shortcut').first()
    const leave = page.getByRole('button', { name: 'Volver al inicio' }).or(page.locator('[aria-label="Volver"]'))
    for (let tries = 0; tries < 10 && !(await home.isVisible()); tries++) {
      await leave
        .first()
        .click({ timeout: 3000, force: true })
        .catch(() => {})
      await wait(500)
    }
    await home.waitFor()
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

  // Seguir con Mochi sin chat: se le pide algo en el buscador y se refina con los chips de un toque.
  // Se espera a que arriba diga lo pedido ("Pediste '…' · '…'") y a que Mochi termine de escribir.
  const asked = async (text) => {
    await page.locator('.agent-asked', { hasText: text }).waitFor({ timeout: 20000 })
    await wait(3800)
  }
  const askTyped = async (text) => {
    const input = page.locator('[role="dialog"] input[type="search"]')
    await input.fill(text)
    await input.press('Enter')
    await asked(text)
  }
  await askTyped('¿qué llevo para un asado de 6?')
  await shot('45-conversacion-asado')
  await tap('.agent-follow-chip', 'Más barato')
  await asked('"más barato"')
  await shot('46-conversacion-mas-barato')
  await askTyped('¿tienen pizza?')
  await tap('.agent-follow-chip', 'Sin carne')
  await asked('"sin carne"')
  await shot('48-conversacion-sin-carne')
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
  await placeOrder()
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

  // --- La Home que aprende: otra persona pide una vez en Chocolates. Un pedido basta para mover el acceso ("Porque
  // pediste en…"); entrar varias veces el mismo día no lo mueve (motor/home.py: MIN_USE_DAYS) ---
  await reset()
  await wait(4200) // el saludo de Mochi
  await shortcut('Chocolates')
  // El primer producto de las filas de la vertical: la primera tienda puede tener todo agotado.
  const product = page.locator('.vertical-product-row .product-card .add-button').first()
  await product.waitFor()
  await product.click()
  await wait(700)
  await tap('.cart-bar')
  await wait(500)
  await tap('.cart-checkout')
  await wait(800)
  await placeOrder()
  await backHome() // al volver, la Home pide su orden: Chocolates sube y Mochi dice por qué
  // Tras un pedido la API recalcula los segmentos de la persona (en rappi_staging, unos 10 s): se espera más.
  await page.getByText('Ordenadas según lo que más usas').waitFor({ timeout: 60000 })
  // Antes de "Moví…" Mochi puede ofrecer algo para acompañar lo pedido (la oferta del carro): "Ahora no" la cierra y
  // deja pasar la explicación de los accesos, que es la que muestra 03.
  const moved = page.getByRole('button', { name: 'Entendido' })
  const later = page.getByRole('button', { name: 'Ahora no' })
  await moved.or(later).first().waitFor({ timeout: 60000 })
  if (await later.isVisible()) {
    await later.click()
    await moved.waitFor({ timeout: 30000 })
  }
  // Abrir Chocolates corrió la fila hacia la derecha: vuelve al principio, como la ve quien llega a la Home.
  await page.locator('.home-shortcuts').evaluate((row) => {
    for (const el of [row, ...row.querySelectorAll('*')]) el.scrollLeft = 0
  })
  await shot('03-home-dinamica')

  // Mochi explica qué acceso movió (03 lo muestra). "Entendido" lo cierra: si no, su "¿Por qué?" es el que se abre.
  await moved.click()
  await settle(400)
  // Tocar a Mochi en la Home: la API propone la vertical donde la persona aún no pide. El globo escribe letra por
  // letra: se espera la pregunta entera antes de abrir su "¿Por qué?".
  await tap('.live-agent-body')
  await page.waitForFunction(
    () => /¿Y si pruebas algo de [^?]+\?/.test(document.querySelector('.live-bubble')?.textContent ?? ''),
    null,
    { timeout: 15000 },
  )
  await tap('.live-bubble .offer-why-toggle')
  await shot('22-vertical-por-probar')

  // "¿Repetimos?": la recompra del fixture del contrato, con un café molido real del catálogo. Con otra persona, sin
  // pedido en curso: la barra flotante del pedido de Chocolates tapaba "Ver producto" y "Después".
  await reset()
  await wait(4200) // el saludo de Mochi
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
  if (!product) throw new Error('No hay café molido en el catálogo para "¿Repetimos?"')
  return {
    ...fixture,
    products: [product],
    actions: fixture.actions.map((action) => ({ ...action, store_id: product.store_id })),
  }
}

function requireWritesAllowed() {
  if (process.env.SCREENSHOTS_ALLOW_WRITES === '1') return
  console.error(
    'Las capturas pagan dos compras y dejan pedidos y eventos en la base que usa la API.\n' +
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
