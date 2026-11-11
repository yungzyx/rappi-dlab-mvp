import { ThemeToggle } from './ThemeToggle.jsx'

/** La marca del panel y el tema: arriba de la barra lateral (en angosto, la primera fila). */
export function Header() {
  return (
    <header className="masthead">
      <div className="brand">
        {/* Marca del panel: tres barras en el naranja-rojo de Rappi (decorativa). */}
        <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
          <rect width="32" height="32" rx="8" />
          <path className="brand-bar" d="M9 22v-5" />
          <path className="brand-bar" d="M16 22V10" />
          <path className="brand-bar" d="M23 22v-8" />
        </svg>
        <div className="brand-text">
          <p className="brand-name">Panel de negocio</p>
          <p className="masthead-sub">Prototipo dLab con Rappi, no oficial</p>
        </div>
      </div>
      <ThemeToggle />
    </header>
  )
}
