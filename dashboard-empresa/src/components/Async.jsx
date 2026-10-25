import { Component, Suspense } from 'react'
import { retryConnection } from '../lib/api.js'
import { ErrorState, LoadingState } from './States.jsx'

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
    if (this.state.error) return <ErrorState message={this.state.error.message} onRetry={this.retry} />
    return this.props.children
  }
}

/** Frontera de carga y error para un bloque que lee datos con useAnalytics. */
export function Async({ children, fallback = <LoadingState /> }) {
  return (
    <ErrorBoundary>
      <Suspense fallback={fallback}>{children}</Suspense>
    </ErrorBoundary>
  )
}
