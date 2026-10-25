import Img from '../../components/Img'
import { StarIcon } from '../../components/Icons'
import { EtaIcon, StoreMeta } from '../../components/StoreMeta'
import './home.css'

/**
 * Tarjeta ancha de restaurante o tienda (Inicio, Ofertas, Favoritos).
 * Campos opcionales: rating, deliveryLabel (píldora amarilla), fee (costo de envío), distance, logo (la foto es un logo y
 * se ve entera).
 */
export function RestaurantCard({ store, onClick }) {
  return (
    <button type="button" className="featured-card tap" onClick={onClick}>
      <span className={store.logo ? 'featured-media is-logo' : 'featured-media'}>
        <Img src={store.img} draggable="false" />
      </span>
      <span className="featured-name">
        <span className="featured-title">{store.name}</span>
        {store.rating && (
          <span className="featured-rating">
            <StarIcon filled size={15} />
            {store.rating}
          </span>
        )}
      </span>
      <StoreMeta store={store} />
    </button>
  )
}

/** Logo de tienda + nombre + tiempo de entrega (si lo hay), para la grilla «Cerca de ti». */
export function StoreTile({ store, onClick }) {
  return (
    <button type="button" className="store-tile tap" onClick={onClick}>
      <Img src={store.img} />
      <span className="store-name">{store.name}</span>
      {store.eta && (
        <span className="store-when">
          <EtaIcon kind={store.etaIcon} size={15} />
          <span>{store.eta}</span>
        </span>
      )}
    </button>
  )
}
