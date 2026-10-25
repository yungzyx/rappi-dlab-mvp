import { AGENT_NAME } from '../../agent/name'
import { VERTICAL_NAMES } from '../../data/verticals'
import { MAIN_TILES, SHORTCUTS } from '../../data/home'
import Img from '../Img'
import './discover.css'

// Las mismas ilustraciones de la Home: la persona reconoce cada vertical de un vistazo.
const TILE_IMAGES = Object.fromEntries([...MAIN_TILES, ...SHORTCUTS].map((tile) => [tile.id, tile.img]))

const THUMBS = 3

/** «snacks-salados» → «Snacks salados». */
const conceptLabel = (concept) => {
  const words = concept.replace(/-/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** El título de una tarjeta: el complemento y su vertical, o «Lo más pedido en…» (fila sin concepto). */
const cardTitle = (row) => {
  const vertical = VERTICAL_NAMES[row.prototype_vertical]
  return row.kind === 'lo_mas_pedido' ? `Lo más pedido en ${vertical}` : `${conceptLabel(row.concept)} en ${vertical}`
}

/**
 * «Descubre con el agente»: tarjetas de /recommendations, cada una con un complemento de lo que le gusta a la persona en una
 * vertical que quizá aún no abre, o con lo más pedido en una vertical (`kind: 'lo_mas_pedido'`). `rows` son las filas de
 * la API (hasta 3); tocar una tarjeta abre su vertical.
 */
export default function DiscoverSection({ rows, onOpen }) {
  const cards = rows.filter((row) => VERTICAL_NAMES[row.prototype_vertical])
  if (cards.length === 0) return null

  return (
    <section className="discover" aria-labelledby="discover-title">
      <h2 id="discover-title" className="search-heading">
        Descubre con {AGENT_NAME}
      </h2>

      <div className="discover-cards">
        {cards.map((row, i) => (
          <button
            key={`${row.concept ?? row.kind}-${row.prototype_vertical}`}
            type="button"
            className="discover-card tap"
            style={{ animationDelay: `${180 + i * 80}ms` }}
            onClick={() => onOpen(row.prototype_vertical)}
          >
            <span className="discover-card-art" aria-hidden="true">
              <img src={TILE_IMAGES[row.prototype_vertical]} alt="" draggable="false" loading="lazy" />
            </span>
            <span className="discover-card-body">
              <small>{row.reason}</small>
              <strong>{cardTitle(row)}</strong>
              <span className="discover-card-foot">
                <span className="discover-thumbs" aria-hidden="true">
                  {row.products.slice(0, THUMBS).map((product) => (
                    <Img key={product.id} src={product.img} draggable="false" />
                  ))}
                </span>
                <em>Explorar</em>
              </span>
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}
