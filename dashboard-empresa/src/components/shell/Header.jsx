import { RappiLogo } from './RappiLogo.jsx'
import { ThemeToggle } from './ThemeToggle.jsx'

/** La marca del panel y el tema: arriba de la barra lateral (en angosto, la primera fila). */
export function Header() {
  return (
    <header className="masthead">
      <div className="brand">
        <RappiLogo />
        <div className="brand-text">
          <p className="brand-name">Panel de negocio</p>
          <p className="masthead-sub">Prototipo dLab con Rappi, no oficial</p>
        </div>
      </div>
      <ThemeToggle />
    </header>
  )
}
