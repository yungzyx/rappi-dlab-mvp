import { useTheme } from '../../lib/useTheme.js'
import { Icon } from '../Icon.jsx'

export function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const next = theme === 'dark' ? 'claro' : 'oscuro'
  return (
    <button type="button" className="icon-button" onClick={toggle} title={`Tema ${next}`}>
      <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
      <span className="visually-hidden">Cambiar a tema {next}</span>
    </button>
  )
}
