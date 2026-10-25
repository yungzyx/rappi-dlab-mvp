import { Component } from 'react'
import './error-boundary.css'

/**
 * Si una pantalla de la pila falla al renderizar, el teléfono muestra un aviso en vez de quedar en blanco.
 * «Volver al inicio» llama a `onReset` (el `reset` de la navegación) y descarta el error.
 * Con `variant="root"` (afuera de toda la app: proveedores, hoja de producto, agente…) no hay pila a la que volver:
 * ofrece «Recargar» (`onReload`, por defecto recarga la página).
 */
export default class ErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error) {
    console.error('Pantalla con error:', error)
  }

  reset = () => {
    this.setState({ error: null })
    this.props.onReset?.()
  }

  render() {
    if (!this.state.error) return this.props.children
    const reload = this.props.onReload ?? (() => window.location.reload())
    if (this.props.variant === 'root') {
      return (
        <div className="error-screen error-screen--root" role="alert">
          <h1>Algo salió mal</h1>
          <p>La app no se pudo mostrar.</p>
          <button type="button" className="error-screen-home tap" onClick={reload}>
            Recargar
          </button>
        </div>
      )
    }
    return (
      <div className="screen error-screen" role="alert">
        <h1>Algo salió mal</h1>
        <p>Esta pantalla no se pudo mostrar.</p>
        <button type="button" className="error-screen-home tap" onClick={this.reset}>
          Volver al inicio
        </button>
        {/* Si el fallo es de un archivo viejo tras un despliegue, solo recargar lo arregla. */}
        <button type="button" className="error-screen-reload tap" onClick={reload}>
          Recargar
        </button>
      </div>
    )
  }
}
