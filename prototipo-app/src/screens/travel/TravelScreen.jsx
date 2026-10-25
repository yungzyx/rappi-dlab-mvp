import { useState } from 'react'
import BackButton from '../../components/BackButton'
import { useToast } from '../../components/Toast'
import hero from '../../assets/v/travel-hero1.webp'
import hoteles from '../../assets/v/travel-hoteles.webp'
import vuelos from '../../assets/v/travel-vuelos.webp'
import paquetes from '../../assets/v/travel-paquetes.webp'
import tours from '../../assets/v/travel-tours.webp'
import autos from '../../assets/v/travel-autos.webp'
import proWeek from '../../assets/v/travel-proweek.webp'
import './travel.css'

// Los botones del hero (volver, campana, Ayuda, Mis Viajes, "Ver destinos") vienen dibujados en la imagen; encima van
// zonas táctiles invisibles (en % del hero de 402 × 335, para que sigan sobre el botón en un teléfono más angosto).
const HERO_CTA = { left: '9%', top: '71%', width: '20.4%', height: '6%' }

const TILES = [
  { id: 'hoteles', label: 'Hoteles', img: hoteles },
  { id: 'vuelos', label: 'Vuelos', img: vuelos },
  { id: 'paquetes', label: 'Paquetes', img: paquetes },
  { id: 'tours', label: 'Tours y Actividades', img: tours },
  { id: 'autos', label: 'Autos', img: autos },
]

/** RappiTravel (de las capturas de la app iOS). Reservas de viaje: simuladas con avisos. */
export default function TravelScreen({ back }) {
  const toast = useToast()
  const [query, setQuery] = useState('')

  const submit = (e) => {
    e.preventDefault()
    toast(query.trim() ? `Buscando viajes a “${query.trim()}”…` : 'Escribe un destino')
  }

  return (
    <div className="screen travel">
      <div className="travel-hero">
        <img src={hero} alt="" draggable="false" />
        <BackButton className="travel-hit travel-hit--back" icon={false} onClick={back} />
        <button
          type="button"
          className="travel-hit travel-hit--bell"
          aria-label="Notificaciones"
          onClick={() => toast('No tienes notificaciones')}
        />
        <button type="button" className="travel-hit travel-hit--help" aria-label="Ayuda" onClick={() => toast()} />
        <button
          type="button"
          className="travel-hit travel-hit--trips"
          aria-label="Mis Viajes"
          onClick={() => toast('Aún no tienes viajes')}
        />
        <button
          type="button"
          className="travel-hit"
          aria-label="Ver destinos"
          style={HERO_CTA}
          onClick={() => toast('Las reservas no están en el prototipo')}
        />
      </div>

      <section className="travel-sheet">
        <form className="travel-search" onSubmit={submit}>
          <input
            type="search"
            placeholder="¿A dónde te llevamos hoy?"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit" aria-label="Buscar">
            <svg
              width="26"
              height="26"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.7"
              aria-hidden="true"
            >
              <circle cx="10" cy="10" r="6.5" />
              <path d="M15 15l5.5 5.5M7.2 8.3a3.3 3.3 0 0 1 3-2" />
            </svg>
          </button>
        </form>

        <div className="travel-tiles">
          {TILES.map((tile) => (
            <button
              key={tile.id}
              type="button"
              className="travel-tile tap"
              onClick={() => toast(`${tile.label}: las reservas no están en el prototipo`)}
            >
              <img src={tile.img} alt="" loading="lazy" />
              <span>{tile.label}</span>
            </button>
          ))}
        </div>

        <button type="button" className="travel-proweek tap" onClick={() => toast()}>
          <img src={proWeek} alt="Pro week: vuela sin pagar cargo de servicio" loading="lazy" />
        </button>
      </section>
    </div>
  )
}
