import { isDemoActive } from '../lib/api.js'

/**
 * Rótulo de las secciones con datos del prototipo: es el uso de pocas personas, nunca evidencia. Con datos simulados no
 * pinta nada: la insignia de la sección y el aviso fijo de arriba ya lo dicen. Mientras corre «Ver cómo funciona» (solo
 * en el HTML suelto), dice además que las cifras traen eventos de ejemplo.
 */
export function SourceNote({ source }) {
  if (source !== 'prototype') return null
  return (
    <p className="mvp-note">
      <strong>uso del MVP, pocas personas: no es evidencia</strong>
      {isDemoActive() && (
        <span className="mvp-note-demo"> · con eventos de ejemplo de la demostración: no son datos reales</span>
      )}
    </p>
  )
}
