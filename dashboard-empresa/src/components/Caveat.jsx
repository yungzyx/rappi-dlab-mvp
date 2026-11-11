import { Icon } from './Icon.jsx'

/** Salvedad que acompaña a una cifra: siempre visible, una línea, con ícono. */
export function Caveat({ children }) {
  return (
    <p className="caveat">
      <Icon name="info" />
      <span>{children}</span>
    </p>
  )
}
