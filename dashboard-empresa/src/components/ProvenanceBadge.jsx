import { Icon } from './Icon.jsx'

// Procedencia de cada bloque. Lo simulado va rayado en ámbar; lo real, sólido. Nunca solo por color: siempre con texto.
// «Dato de Rappi» es la tabla de combinaciones que compartió Rappi (cohortes ene a jun 2026): real, pero agregada.
const KINDS = {
  synthetic: { className: 'badge--simulated', icon: 'flask', label: 'Simulado' },
  prototype: { className: 'badge--prototype', icon: 'flask', label: 'Prototipo' },
  rappi: { className: 'badge--real', icon: 'check', label: 'Dato de Rappi' },
}

export function ProvenanceBadge({ kind }) {
  const { className, icon, label } = KINDS[kind]
  return (
    <span className={`badge ${className}`}>
      <Icon name={icon} />
      {label}
    </span>
  )
}
