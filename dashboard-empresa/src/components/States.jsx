import { Icon } from './Icon.jsx'

/** Estado vacío: una caja; con `inline`, una línea sin caja (lo que falta no ocupa una tarjeta). */
export function EmptyState({ title, inline, children }) {
  if (inline) {
    return (
      <div className="state state--inline">
        <p>
          <strong>{title}</strong>
          {children && <> {children}</>}
        </p>
      </div>
    )
  }
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
      <span className="visually-hidden">Cargando datos…</span>
      <span className="skeleton" aria-hidden="true" />
      <span className="skeleton" aria-hidden="true" />
      <span className="skeleton" aria-hidden="true" />
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
