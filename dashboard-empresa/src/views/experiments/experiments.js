// Etiquetas y cuentas de los experimentos del MVP (/analytics/experimentos, migración 047 en rappi-scraper).
import { AGENT_NAME } from '../../lib/agentName.js'

const EXPERIMENTS = {
  modo_app: 'Modo de la app',
  ofertas_control: `Grupo de control de las ofertas de ${AGENT_NAME}`,
}

const VARIANTS = {
  propuesta: `Propuesta (con ${AGENT_NAME})`,
  actual: '"Rappi hoy"',
  tratamiento: 'Tratamiento (ve las ofertas)',
  control: 'Control (no las ve)',
}

export const experimentLabel = (id) => EXPERIMENTS[id] ?? id
export const variantLabel = (variant) => VARIANTS[variant] ?? variant

/** Personas asignadas en todas sus variantes: 0 es que nadie tiene variante todavía. */
export const assignedPeople = (experiment) => experiment.variantes.reduce((total, row) => total + row.personas, 0)

/** % de las asignadas que pidió, o null sin personas. */
export const orderedPct = (row) => (row.personas > 0 ? (row.con_pedido * 100) / row.personas : null)

/** Personas de la cohorte con su mes siguiente completo, en todas las variantes. */
export const cohortPeople = (retention) => retention.variantes.reduce((total, row) => total + row.personas, 0)
