import { Component, Suspense } from 'react'
import { PROTOTYPE_OFFLINE_MESSAGE, retryConnection } from '../lib/api.js'
import { EmptyState, ErrorState, LoadingState } from './States.jsx'

class ErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error) {
    console.error('Error al mostrar datos del panel:', error)
  }

  retry = () => {
    retryConnection()
    this.setState({ error: null })
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    if (this.props.errorFallback) return this.props.errorFallback
    // Sin la API, el prototipo se avisa una sola vez (con su Reintentar) en el aviso de procedencia, no en cada bloque.
    if (error.message === PROTOTYPE_OFFLINE_MESSAGE) return <EmptyState title="Sin conexión con la API" />
    return <ErrorState message={error.message} onRetry={this.retry} />
  }
}

/** Frontera de carga y error para un bloque que lee datos con useAnalytics; `errorFallback` reemplaza al aviso de error. */
export function Async({ children, fallback = <LoadingState />, errorFallback }) {
  return (
    <ErrorBoundary errorFallback={errorFallback}>
      <Suspense fallback={fallback}>{children}</Suspense>
    </ErrorBoundary>
  )
}
