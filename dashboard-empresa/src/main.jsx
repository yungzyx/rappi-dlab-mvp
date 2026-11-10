import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/figtree'
import './styles/tokens.css'
import './styles/global.css'
import './styles/shared.css'
import './components/components.css'
import './components/charts/charts.css'
import './components/shell/shell.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
