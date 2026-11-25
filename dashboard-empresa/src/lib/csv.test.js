import { describe, expect, test } from 'vitest'
import { csvFileName, tablesToCsv, tableToCsv } from './csv.js'

const table = (html) => {
  const element = document.createElement('table')
  element.innerHTML = html
  return element
}

describe('tableToCsv', () => {
  test('one line per row, headers first, with ";" between cells', () => {
    const csv = tableToCsv(
      table(`<thead><tr><th>Semana del</th><th>Pedidos</th></tr></thead>
             <tbody><tr><td>26 oct</td><td>448</td></tr><tr><td>2 nov</td><td>451</td></tr></tbody>`),
    )
    expect(csv).toBe('Semana del;Pedidos\r\n26 oct;448\r\n2 nov;451')
  })

  test('a cell is its visible text: no decoration, no screen-reader-only words, stacked lines joined', () => {
    const csv = tableToCsv(
      table(`<tbody><tr>
        <td><span class="cell-stack"><strong>Pizza</strong><span class="cell-sub">en Restaurantes</span></span></td>
        <td><span class="meter" aria-hidden="true"><span></span></span> 24</td>
        <td><span class="delta"><svg aria-hidden="true"></svg><span>+1,9 puntos</span><span class="visually-hidden"> (empeora)</span></span></td>
      </tr></tbody>`),
    )
    expect(csv).toBe('Pizza en Restaurantes;24;+1,9 puntos')
  })

  test('a cell with the separator, a quote or a line break goes quoted', () => {
    const csv = tableToCsv(table('<tbody><tr><td>Restaurantes; Turbo</td><td>"Volvemos a…"</td></tr></tbody>'))
    expect(csv).toBe('"Restaurantes; Turbo";"""Volvemos a…"""')
  })
})

describe('tablesToCsv', () => {
  test('one table: the same as tableToCsv', () => {
    const one = table('<caption>Grupos</caption><tbody><tr><td>control</td><td>12</td></tr></tbody>')
    expect(tablesToCsv([one])).toBe('control;12')
  })

  test('several tables: all of them, in order, each under its caption and a blank line apart', () => {
    const groups = table('<caption>Grupos</caption><tbody><tr><td>control</td><td>12</td></tr></tbody>')
    const retention = table(
      '<caption>Retención M+1 por grupo</caption><tbody><tr><td>control</td><td>48,1%</td></tr></tbody>',
    )
    expect(tablesToCsv([groups, retention])).toBe(
      'Grupos\r\ncontrol;12\r\n\r\nRetención M+1 por grupo\r\ncontrol;48,1%',
    )
  })
})

describe('csvFileName', () => {
  test('a title becomes a plain file name', () => {
    expect(csvFileName('Usuarios y pedidos por combinación')).toBe('usuarios-y-pedidos-por-combinacion.csv')
    expect(csvFileName('¿Qué buscan?')).toBe('que-buscan.csv')
    expect(csvFileName('…')).toBe('tabla.csv')
  })
})
