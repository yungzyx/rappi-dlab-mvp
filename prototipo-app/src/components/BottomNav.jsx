import { SearchIcon } from './Icons'
import './bottom-nav.css'

/**
 * Barra inferior flotante de vidrio (estilo iOS 26) + botón de búsqueda aparte.
 * `items`: [{ id, label, Icon }]. El ícono recibe `active` por si cambia de relleno.
 */
export default function BottomNav({ items, active, onSelect, onSearch, className = '' }) {
  return (
    <nav className={`bottom-nav ${className}`} aria-label="Navegación principal">
      <div className="bottom-nav-pill glass">
        {items.map(({ id, label, Icon }) => {
          const isActive = id === active
          return (
            <button
              key={id}
              type="button"
              className={isActive ? 'bottom-nav-item is-active' : 'bottom-nav-item'}
              aria-current={isActive ? 'page' : undefined}
              onClick={() => onSelect(id)}
            >
              <Icon size={27} active={isActive} />
              <span>{label}</span>
            </button>
          )
        })}
      </div>
      <button type="button" className="bottom-nav-search glass tap" aria-label="Buscar" onClick={onSearch}>
        <SearchIcon size={24} />
      </button>
    </nav>
  )
}
