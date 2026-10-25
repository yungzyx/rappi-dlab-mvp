import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { AGENT_NAME } from './src/agent/name.js'

// El título y la descripción de index.html llevan el nombre del agente desde la misma constante que la app.
const agentName = {
  name: 'agent-name',
  transformIndexHtml: { order: 'pre', handler: (html) => html.replaceAll('%AGENT_NAME%', AGENT_NAME) },
}

// La demo sin conexión (`vite build --mode demo`, ver scripts/demo-html.mjs): un solo JS, con las imágenes y las
// fuentes adentro en base64, listo para meterse entero en un HTML que abre con doble clic.
const DEMO_BUILD = {
  outDir: 'dist-demo',
  assetsInlineLimit: () => true,
  cssCodeSplit: false,
  modulePreload: false,
  rolldownOptions: { output: { codeSplitting: false } },
}

// Sus variables (no van en un .env: solo los ejemplos se versionan): la API la responde el navegador
// (src/api/offline/), con una dirección que no existe (.invalid nunca resuelve), y quedan los controles de la demo.
const DEMO_ENV = {
  'import.meta.env.VITE_OFFLINE_DEMO': JSON.stringify('1'),
  'import.meta.env.VITE_API_URL': JSON.stringify('https://api-simulada.invalid'),
  'import.meta.env.VITE_DEMO': JSON.stringify('1'),
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), agentName],
  server: { port: 5174 },
  base: mode === 'demo' ? './' : '/',
  define: mode === 'demo' ? DEMO_ENV : {},
  // Sin imágenes embebidas en base64: los recortes pequeños inflaban el JS a ~500 kB.
  build: mode === 'demo' ? DEMO_BUILD : { assetsInlineLimit: 0 },
  // Hora de Chile en las pruebas: «silenciar por hoy» usa la fecha local (CI corre en UTC).
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    env: { TZ: 'America/Santiago' },
  },
}))
