// Una tabla del panel a CSV, tal como se ve: mismos encabezados, mismas filas y el mismo texto de cada celda. Con ";"
// y BOM, que es como una planilla en español abre los decimales con coma y los acentos.
const SEPARATOR = ';'

/** El texto de una celda: sus trozos de texto en orden, sin lo decorativo (`aria-hidden`), lo que es solo para el
 * lector de pantalla (el juicio de un cambio ya va en su signo) ni las acciones de una fila (`data-no-csv`). */
function cellText(cell) {
  const parts = []
  const walk = (node) => {
    if (node.nodeType === 3) {
      const text = node.textContent.replace(/\s+/g, ' ').trim()
      if (text) parts.push(text)
      return
    }
    if (node.nodeType !== 1) return
    if (node.getAttribute('aria-hidden') === 'true' || node.classList.contains('visually-hidden')) return
    if (node.hasAttribute('data-no-csv')) return
    node.childNodes.forEach(walk)
  }
  walk(cell)
  return parts.join(' ')
}

const quote = (text) => (/[";\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text)

/** El CSV de una `<table>`: una línea por fila, encabezados primero. */
export function tableToCsv(table) {
  return [...table.querySelectorAll('tr')]
    .map((row) => [...row.querySelectorAll('th, td')].map((cell) => quote(cellText(cell))).join(SEPARATOR))
    .join('\r\n')
}

/** El CSV de filas que no están en pantalla (`rows`: una lista de textos por fila, encabezados primero). */
export function rowsToCsv(rows) {
  return rows.map((row) => row.map((cell) => quote(String(cell))).join(SEPARATOR)).join('\r\n')
}

/**
 * El CSV de todas las tablas de un bloque. Con una, igual que `tableToCsv`; con varias, cada una precedida por su
 * título (el `<caption>`) y separada de la siguiente por una línea vacía, en el orden en que se ven.
 */
export function tablesToCsv(tables) {
  if (tables.length === 1) return tableToCsv(tables[0])
  return tables
    .map((table) => {
      const title = table.caption?.textContent.trim()
      return title ? `${quote(title)}\r\n${tableToCsv(table)}` : tableToCsv(table)
    })
    .join('\r\n\r\n')
}

// De dónde salen las cifras, en el CSV: la planilla no lleva la insignia ni la etiqueta de la página.
const PROVENANCE = {
  synthetic: 'Datos simulados: no son evidencia',
  prototype: 'Datos del prototipo (uso del MVP, pocas personas): no son evidencia',
  rappi: 'Dato de Rappi (tabla de combinaciones, cohortes de enero a junio de 2026): es una correlación',
}
const FILE_SOURCE = { synthetic: 'simulados', prototype: 'prototipo' }

/**
 * Un nombre de archivo a partir de un título: "Serie semanal" → "serie-semanal.csv". Con datos simulados o del
 * prototipo (`kind`), la fuente va en el nombre: "serie-semanal-simulados.csv".
 */
export function csvFileName(title, kind = null) {
  const slug = title
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
  return `${slug || 'tabla'}${FILE_SOURCE[kind] ? `-${FILE_SOURCE[kind]}` : ''}.csv`
}

/**
 * Las filas que van al comienzo del CSV de un bloque (`kind`: su fuente, o null): si no es evidencia, si trae eventos
 * de la demostración y, con datos de personas, la línea de estado de la página (`status`: API en vivo, datos guardados o
 * foto, y la fecha de corte). La tabla de Rappi no es de esa fecha de corte.
 */
export function provenanceRows(kind, { status = '', demo = false } = {}) {
  if (!PROVENANCE[kind]) return []
  const rows = [['Procedencia', PROVENANCE[kind]]]
  if (kind === 'prototype' && demo) rows.push(['Demostración', 'Con eventos de ejemplo: no son datos reales'])
  if (kind !== 'rappi' && status) rows.push(['Datos', status])
  return rows
}

/** La fuente de las cifras de un bloque: su propia insignia o, si no tiene, la de su sección; null sin ninguna. */
export function provenanceOf(element) {
  const own = element.closest('.panel')?.querySelector('.panel-head [data-provenance]')
  const section = element.closest('.section')?.querySelector('.section-head [data-provenance]')
  return (own ?? section)?.dataset.provenance ?? null
}

/** La línea de estado bajo el título de la página ("Datos guardados · Datos al 03-11-2026"), o '' sin ella. */
export function pageStatus() {
  const meta = document.querySelector('.page-meta')
  if (!meta) return ''
  return [...meta.children]
    .filter((child) => child.getAttribute('aria-hidden') !== 'true')
    .map(cellText)
    .filter(Boolean)
    .join(' · ')
}

/** Descarga `csv` como archivo (en el navegador; también en el panel de un solo HTML, sin red). */
export function downloadCsv(fileName, csv) {
  const url = URL.createObjectURL(new Blob(['﻿', csv], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
