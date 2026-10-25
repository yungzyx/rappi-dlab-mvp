import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// El panel en un solo HTML (`vite build --mode panel-html`, ver scripts/panel-html.mjs) lee las respuestas grabadas por
// `npm run panel:snapshot` en vez de la API. Llegan por un módulo virtual: en la app normal (dev, build y tests) vale
// null, así las respuestas grabadas nunca entran en dist/.
const SNAPSHOT_ID = 'virtual:panel-snapshot'
const SNAPSHOT_FILE = fileURLToPath(new URL('./snapshot/panel.json', import.meta.url))

function panelSnapshot(mode) {
  return {
    name: 'panel-snapshot',
    resolveId: (source) => (source === SNAPSHOT_ID ? `\0${SNAPSHOT_ID}` : null),
    load(id) {
      if (id !== `\0${SNAPSHOT_ID}`) return null
      if (mode !== 'panel-html') return 'export default null'
      if (!existsSync(SNAPSHOT_FILE)) this.error('Falta snapshot/panel.json: corre antes `npm run panel:snapshot`.')
      return `export default ${readFileSync(SNAPSHOT_FILE, 'utf8')}`
    },
  }
}

// Un solo JS, con las fuentes adentro en base64, listo para meterse entero en un HTML que abre con doble clic.
const HTML_BUILD = {
  outDir: 'dist-html',
  assetsInlineLimit: () => true,
  cssCodeSplit: false,
  modulePreload: false,
  rolldownOptions: { input: { panel: 'index.html' }, output: { codeSplitting: false } },
}

export default defineConfig(({ mode }) => ({
  // Bajo una subruta (p. ej. PANEL_BASE=/panel/ detrás de un proxy); por defecto, la raíz. El HTML suelto, relativo.
  base: mode === 'panel-html' ? './' : (process.env.PANEL_BASE ?? '/'),
  plugins: [react(), panelSnapshot(mode)],
  server: { port: 5175 },
  // Dos páginas: el panel (index.html) y la presentación estática (presentacion.html).
  build:
    mode === 'panel-html'
      ? HTML_BUILD
      : { rolldownOptions: { input: { panel: 'index.html', presentacion: 'presentacion.html' } } },
  test: {
    environment: 'jsdom',
  },
}))
