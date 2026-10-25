// Íconos de la app instalada (manifiesto, pantalla de inicio del iPhone y pestaña) desde la mascota que ya trae la app:
// la pose de frente de src/assets/mochi-poses.webp sobre el fondo durazno. La mochila trae pintado el logo de Rappi
// (abajo a la derecha): se borra rellenando cada fila con el naranja de sus dos bordes, así ningún ícono lleva marcas.
// Dibuja con Chrome (playwright-core, como `npm run screenshots`): node scripts/make-icons.mjs → public/.
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const SPRITE = `data:image/webp;base64,${readFileSync(`${ROOT}src/assets/mochi-poses.webp`).toString('base64')}`

// `fill`: cuánto del lado ocupa la pose. Los «any» y el del iPhone van como el ícono anterior (iOS redondea las
// esquinas solo); el «maskable» deja la mascota dentro del círculo seguro (80 % del lado) que Android recorta.
// Los del manifiesto van en WebP: Chrome los baja al cargar la página para ofrecer instalarla, y en PNG el de 512
// pesaba ~340 kB. El del iPhone tiene que ser PNG (lo baja solo al agregarla a la pantalla de inicio); la pestaña, PNG.
const ICONS = [
  { file: 'icon-192.webp', size: 192, fill: 0.87 },
  { file: 'icon-512.webp', size: 512, fill: 0.87 },
  { file: 'icon-maskable-512.webp', size: 512, fill: 0.68 },
  { file: 'apple-touch-icon.png', size: 180, fill: 0.87 },
  { file: 'favicon-48.png', size: 48, fill: 0.96 },
]

const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' })
try {
  const page = await browser.newPage()
  const pngs = await page.evaluate(
    async ({ sprite, icons }) => {
      const img = new Image()
      img.src = sprite
      await img.decode()

      // La pose de frente es el cuarto de arriba a la izquierda del sprite (512 × 512, cuatro poses).
      const pose = document.createElement('canvas')
      pose.width = pose.height = 256
      const ctx = pose.getContext('2d')
      ctx.drawImage(img, 0, 0, 256, 256, 0, 0, 256, 256)
      ctx.clearRect(250, 0, 6, 256) // un borde de la pose vecina que asoma en la última columna
      const data = ctx.getImageData(0, 0, 256, 256)
      const px = (x, y) => (y * 256 + x) * 4

      // Borra el logo: en cada fila de la caja, el color va del borde izquierdo al último punto opaco del derecho (el
      // borde de la mochila se curva). La transparencia queda como estaba: solo cambia el color.
      const erase = (x0, x1, y0, y1) => {
        for (let y = y0; y <= y1; y++) {
          let right = x1
          while (data.data[px(right, y) + 3] < 250) right--
          for (let x = x0 + 1; x < right; x++) {
            const t = (x - x0) / (right - x0)
            for (let c = 0; c < 3; c++)
              data.data[px(x, y) + c] = Math.round(data.data[px(x0, y) + c] * (1 - t) + data.data[px(right, y) + c] * t)
          }
        }
      }
      erase(154, 200, 185, 202) // la palabra, bajo la franja gris de abajo
      erase(186, 198, 181, 184) // el punto de la «i», sobre el borde de la franja de arriba
      ctx.putImageData(data, 0, 0)

      return icons.map(({ size, fill, type }) => {
        const canvas = document.createElement('canvas')
        canvas.width = canvas.height = size
        const c = canvas.getContext('2d')
        const bg = c.createRadialGradient(size / 2, size * 0.35, 0, size / 2, size * 0.35, size * 0.75)
        bg.addColorStop(0, '#ffece8')
        bg.addColorStop(1, '#fbcfc4')
        c.fillStyle = bg
        c.fillRect(0, 0, size, size)
        c.imageSmoothingQuality = 'high'
        const side = Math.round(size * fill)
        const at = Math.round((size - side) / 2)
        c.drawImage(pose, at, at, side, side)
        return canvas.toDataURL(type, 0.9).split(',')[1]
      })
    },
    {
      sprite: SPRITE,
      icons: ICONS.map(({ file, size, fill }) => ({ size, fill, type: `image/${file.split('.').pop()}` })),
    },
  )
  ICONS.forEach(({ file }, i) => {
    writeFileSync(`${ROOT}public/${file}`, Buffer.from(pngs[i], 'base64'))
    console.log(`public/${file}`)
  })
} finally {
  await browser.close()
}
