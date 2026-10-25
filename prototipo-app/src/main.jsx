import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/figtree'
import './styles/tokens.css'
import './styles/global.css'
import App from './App.jsx'
import { API_URL } from './api/client.js'
import ConnectionGate from './components/ConnectionGate.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import { reloadOnPreloadError } from './preloadError.js'

reloadOnPreloadError()

const render = () =>
  createRoot(document.getElementById('root')).render(
    <StrictMode>
      <ErrorBoundary variant="root">
        <ConnectionGate>
          <App />
        </ConnectionGate>
      </ErrorBoundary>
    </StrictMode>,
  )

// Solo el build de la demo sin conexión («Prototipo MVP.html», `npm run demo:html`) responde la API en el navegador;
// en los demás builds Vite pliega la condición y el código de src/api/offline/ no entra al bundle.
if (import.meta.env.VITE_OFFLINE_DEMO === '1') {
  import('./api/offline/index.js').then(({ installOfflineApi }) => {
    installOfflineApi(API_URL)
    render()
  })
} else {
  render()
}
