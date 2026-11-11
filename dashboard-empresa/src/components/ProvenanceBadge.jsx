import { isDemoActive } from '../lib/api.js'
import { Icon } from './Icon.jsx'

// Procedencia de cada bloque. Lo simulado y lo del prototipo, un rótulo gris discreto (la franja fija de arriba ya dice
// que no es evidencia); lo real, sólido: donde conviven, lo real es lo único que resalta. Nunca solo por color.
// "Dato de Rappi" es la tabla de combinaciones que compartió Rappi (cohortes ene a jun 2026): real, pero agregada.
const KINDS = {
  synthetic: { className: 'badge--quiet', icon: 'flask', label: 'Simulado' },
  prototype: { className: 'badge--quiet', icon: 'flask', label: 'Prototipo · no es evidencia' },
  rappi: { className: 'badge--real', icon: 'check', label: 'Dato de Rappi' },
}

/** Mientras corre "Ver cómo funciona" (solo en el HTML suelto), lo del prototipo dice además que trae eventos de ejemplo. */
export function ProvenanceBadge({ kind }) {
  const { className, icon, label } = KINDS[kind]
  const badge = (
    <span className={`badge ${className}`}>
      <Icon name={icon} />
      {label}
    </span>
  )
  if (kind !== 'prototype' || !isDemoActive()) return badge
  return (
    <>
      {badge}
      <span className="mvp-note-demo">con eventos de ejemplo de la demostración: no son datos reales</span>
    </>
  )
}
