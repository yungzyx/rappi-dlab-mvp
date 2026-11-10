/** "En esta vista": un botón por sección de la vista abierta, que lleva a su título (sin seguir el scroll). */
export function SectionNav({ sections, onSelect }) {
  if (!sections?.length) return null
  return (
    <nav aria-label="Secciones de esta vista" className="section-nav">
      <p className="section-nav-title">En esta vista</p>
      <ul>
        {sections.map((section) => (
          <li key={section.id}>
            <button type="button" onClick={() => onSelect(section.id)}>
              {section.label}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}
