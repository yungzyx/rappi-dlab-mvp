import { useState } from 'react'
import BackButton from '../../components/BackButton'
import Sheet from '../../components/Sheet'
import { useToast } from '../../components/Toast'
import { ChevronRight } from '../../components/Icons'
import { useLoyalty } from '../../state/LoyaltyContext'
import './loyalty.css'

// Programas ficticios: la app real muestra los de aerolíneas y hoteles asociados, que aquí no se nombran.
const PROGRAMS = [
  { id: 'millas', name: 'Millas Aéreas (ejemplo)', emoji: '✈️', unit: 'millas' },
  { id: 'hoteles', name: 'Puntos Hoteleros (ejemplo)', emoji: '🏨', unit: 'puntos' },
  { id: 'viajes', name: 'Club de Viajes (ejemplo)', emoji: '🧳', unit: 'puntos' },
]

/** Logo de un programa: su emoji en un cuadro de color (los programas son de ejemplo). */
function ProgramLogo({ program, large = false }) {
  return (
    <span className={large ? 'loyalty-logo loyalty-logo--large' : 'loyalty-logo'} aria-hidden="true">
      {program.emoji}
    </span>
  )
}

/**
 * Lealtad (de las capturas de la app iOS). Funcionalidad agregada: vincular un programa y cambiarlo;
 * el vinculado pasa a "Tu programa" y sale de "Otros programas disponibles".
 */
export default function LoyaltyScreen({ back }) {
  const toast = useToast()
  const loyalty = useLoyalty()
  const [pendingId, setPendingId] = useState(null)
  const active = PROGRAMS.find((program) => program.id === loyalty.activeId)
  const pending = PROGRAMS.find((program) => program.id === pendingId)
  const others = PROGRAMS.filter((program) => program.id !== loyalty.activeId)

  const confirm = () => {
    loyalty.link(pending.id)
    setPendingId(null)
    toast(`Acumulando ${pending.unit} en ${pending.name}`)
  }

  return (
    <div className="screen loyalty">
      <header className="loyalty-header">
        <BackButton className="loyalty-back" onClick={back} />
        <h1>Lealtad</h1>
      </header>

      <h2 className="loyalty-title">Elige un programa</h2>
      <p className="loyalty-text">
        Acumula puntos/millas en un (1) programa siendo PRO. Selecciona &quot;cambiar&quot; cuando desees acumular en
        otro programa.
        <br />
        ¡Canjea a créditos en cuantos programas quieras!
      </p>

      {active && (
        <>
          <h3 className="loyalty-subtitle">Tu programa</h3>
          <div className="loyalty-active">
            <ProgramLogo program={active} />
            <span>
              <strong>{active.name}</strong>
              <span className="loyalty-badge">Acumulando {active.unit}</span>
            </span>
            <button type="button" className="loyalty-change" onClick={loyalty.unlink}>
              Desvincular
            </button>
          </div>
        </>
      )}

      <h3 className="loyalty-subtitle">Otros programas disponibles</h3>
      <ul className="loyalty-list">
        {others.map((program) => (
          <li key={program.id}>
            <button type="button" className="loyalty-row" onClick={() => setPendingId(program.id)}>
              <ProgramLogo program={program} />
              <strong>{program.name}</strong>
              <ChevronRight size={20} />
            </button>
          </li>
        ))}
      </ul>

      <button type="button" className="loyalty-terms" onClick={() => toast()}>
        Ver términos y condiciones
      </button>

      <Sheet open={Boolean(pending)} onClose={() => setPendingId(null)} title={pending && `Vincular ${pending.name}`}>
        {pending && (
          <div className="loyalty-sheet">
            <ProgramLogo program={pending} large />
            <p>
              {active
                ? `Dejarás de acumular en ${active.name} y empezarás a acumular ${pending.unit} en ${pending.name}.`
                : `Acumula ${pending.unit} en cada pedido siendo Rappi Pro.`}
            </p>
            <button type="button" className="loyalty-sheet-primary tap" onClick={confirm}>
              {active ? 'Cambiar programa' : 'Vincular cuenta'}
            </button>
          </div>
        )}
      </Sheet>
    </div>
  )
}
