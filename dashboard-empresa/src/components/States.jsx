import { Icon } from './Icon.jsx'

export function EmptyState({ title, children }) {
  return (
    <div className="state">
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  )
}

export function LoadingState() {
  return (
    <div className="state state--loading" role="status" aria-live="polite">
      <span>Cargando datos…</span>
    </div>
  )
}

export function ErrorState({ message, onRetry }) {
  return (
    <div className="state state--error" role="alert">
      <strong className="status status--bad">
        <Icon name="stop" />
        No se pudieron cargar estos datos
      </strong>
      <p>{message}</p>
      <button type="button" className="link-button" onClick={onRetry}>
        Reintentar
      </button>
    </div>
  )
}
