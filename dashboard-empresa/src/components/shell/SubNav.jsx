/**
 * Subpestañas de una vista: navegación con botones; la activa lleva aria-current="page". No usa role=tab a propósito:
 * el panel de la vista ya es el único tabpanel y el recorrido de la presentación busca las vistas por [role=tab].
 */
export function SubNav({ tabs, active, onSelect }) {
  return (
    <nav aria-label="Secciones de esta vista" className="subnav">
      <ul>
        {tabs.map((tab) => (
          <li key={tab.id}>
            <button
              type="button"
              aria-current={tab.id === active ? 'page' : undefined}
              onClick={() => onSelect(tab.id)}
            >
              {tab.label}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}
