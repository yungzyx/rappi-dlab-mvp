import { useState } from 'react'
import { MAIN_TILES, SHORTCUTS } from '../../data/home'
import { VERTICAL_NAMES } from '../../data/verticals'
import { useProductSheet } from '../../state/ProductSheetContext'
import AddButton from '../AddButton'
import { Dots } from '../Carousel'
import HScroll from '../HScroll'
import Img from '../Img'
import './taste-profile.css'

// Las mismas ilustraciones de los accesos de la Home para cada vertical (RappiTravel tiene id propio en los accesos).
const TILE_IMAGES = Object.fromEntries([...MAIN_TILES, ...SHORTCUTS].map((tile) => [tile.id, tile.img]))
const LEVELS = { bajo: 1, medio: 2, alto: 3 }
const STEP_GAP_PX = 12

/**
 * «Tu perfil»: el perfil de gusto que la API armó con lo que la persona pide (`GET /profile/{id}/gustos`): su nombre,
 * su nivel y por qué. `profile` es el de la API (`{ id, nombre, emoji, nivel, por_que }`).
 */
export function ProfileCard({ profile }) {
  const level = LEVELS[profile.nivel] ?? 1
  return (
    <section className="taste-card" aria-label="Tu perfil">
      <span className="taste-card-kicker">Tu perfil</span>
      <div className="taste-card-main">
        <span className="taste-emoji" aria-hidden="true">
          {profile.emoji}
        </span>
        <span>
          <strong>{profile.nombre}</strong>
          {profile.nivel && (
            <span className="taste-level">
              <span className="taste-level-bar" aria-hidden="true">
                {[1, 2, 3].map((n) => (
                  <i key={n} className={n <= level ? 'is-on' : undefined} />
                ))}
              </span>
              Nivel {profile.nivel}
            </span>
          )}
        </span>
      </div>
      {profile.por_que && <p className="taste-reason">{profile.por_que}</p>}
    </section>
  )
}

function StepProduct({ product, onOpenProduct }) {
  const sheet = useProductSheet()
  return (
    <li className="taste-product">
      <button
        type="button"
        className="taste-product-main tap"
        onClick={() => sheet.open(product, { onOpenStore: () => onOpenProduct(product) })}
      >
        <Img src={product.img} draggable="false" />
        <span className="taste-product-text">
          <span className="taste-product-name">{product.name}</span>
          <span className="taste-product-meta">
            <b>{product.price}</b>
            {product.store ? ` · ${product.store}` : ''}
          </span>
        </span>
      </button>
      <AddButton product={product} className="add-button--taste" />
    </li>
  )
}

/** La idea para RappiTravel al final de la escalera: el destino, dos datos con su fuente. */
function TripStep({ trip, onOpenTravel }) {
  return (
    <>
      <button type="button" className="taste-trip tap" onClick={onOpenTravel}>
        <span className="taste-trip-label">{trip.label}</span>
        <strong>{trip.text}</strong>
      </button>
      <ul className="taste-facts">
        {trip.facts.map((fact) => (
          <li key={fact.url}>
            {fact.text}{' '}
            <a href={fact.url} target="_blank" rel="noreferrer">
              Fuente: {fact.source}
            </a>
          </li>
        ))}
      </ul>
    </>
  )
}

/**
 * «Para ti en otras verticales»: la escalera del perfil (el momento `perfil` de la API), un peldaño por vertical, de lo
 * más cercano a lo más lejano, y al final la idea para RappiTravel. `ladder` es el de `profileLadder`.
 */
export function LadderRail({ ladder, onOpenVertical, onOpenTravel, onOpenProduct }) {
  const [current, setCurrent] = useState(0)
  const cards = [
    ...ladder.steps.map((step) => ({ key: step.backendVertical, step })),
    ...(ladder.trip ? [{ key: 'travel', trip: ladder.trip }] : []),
  ]

  const onScroll = (event) => {
    const rail = event.currentTarget
    const first = rail.children[0]
    if (!first) return
    setCurrent(Math.min(cards.length - 1, Math.round(rail.scrollLeft / (first.offsetWidth + STEP_GAP_PX))))
  }

  return (
    <section className="taste-ladder" aria-labelledby="taste-ladder-title">
      <div className="taste-ladder-head">
        <h2 id="taste-ladder-title">Para ti en otras verticales</h2>
        <small>
          De lo más cercano a lo más lejano · {current + 1} de {cards.length}
        </small>
        <Dots count={cards.length} active={current} className="taste-dots" />
      </div>
      <HScroll className="taste-rail" onScroll={onScroll}>
        {cards.map(({ key, step, trip }, i) => {
          const name = trip ? 'RappiTravel' : (VERTICAL_NAMES[step.vertical] ?? step.backendVertical)
          return (
            <article
              key={key}
              className={`taste-step${trip ? ' taste-step--travel' : ''}`}
              style={{ animationDelay: `${160 + i * 70}ms` }}
              aria-label={`${i + 1}. ${name}`}
            >
              <header className="taste-step-head">
                <span className="taste-step-art" aria-hidden="true">
                  <img src={TILE_IMAGES[trip ? 'rappitravel' : step.vertical]} alt="" draggable="false" />
                </span>
                <span>
                  <strong>{name}</strong>
                  <small>{trip ? trip.name : step.text}</small>
                </span>
                <span className="taste-step-num" aria-hidden="true">
                  {i + 1}
                </span>
              </header>
              {trip ? (
                <TripStep trip={trip} onOpenTravel={onOpenTravel} />
              ) : (
                <ul className="taste-products">
                  {step.products.map((product) => (
                    <StepProduct key={product.id} product={product} onOpenProduct={onOpenProduct} />
                  ))}
                </ul>
              )}
              <button
                type="button"
                className="taste-step-more tap"
                onClick={() => (trip ? onOpenTravel() : onOpenVertical(step.vertical))}
              >
                {trip ? 'Abrir RappiTravel ✈️' : `Ver ${name} ›`}
              </button>
            </article>
          )
        })}
      </HScroll>
    </section>
  )
}
