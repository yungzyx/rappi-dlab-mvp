import { useEffect, useState } from 'react'
import { SearchIcon } from './Icons'

// Textos que rota el buscador de la Home real (capturas y video del 26-09-2026).
const HINTS = [
  'Encuentra lo que sea en 10 min con Turbo',
  'Busca "Plátano"',
  '¿Qué quieres hoy?',
  'Busca "Agua"',
  'Busca "Chocolate"',
  'Busca "Hamburguesa"',
  'Busca "Cerveza"',
]
const ROTATE_MS = 3000

/** Buscador original de Rappi (modo "Rappi hoy"): placeholder que rota y abre el buscador. */
export default function PlainSearchBar({ onClick, className = '' }) {
  const [index, setIndex] = useState(0)

  useEffect(() => {
    const timer = setInterval(() => setIndex((i) => (i + 1) % HINTS.length), ROTATE_MS)
    return () => clearInterval(timer)
  }, [])

  return (
    <button type="button" className={`search-bar tap ${className}`} onClick={onClick}>
      <SearchIcon size={21} />
      <span className="search-hint-window">
        <span key={index} className="search-hint">
          {HINTS[index]}
        </span>
      </span>
    </button>
  )
}
