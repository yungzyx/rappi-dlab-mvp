import Img from './Img'
import { StoreMeta } from './StoreMeta'
import './store-list.css'

/** Lista vertical de tiendas (buscador y pantallas "View more"). */
export default function StoreList({ stores, onOpen }) {
  return (
    <ul className="search-stores">
      {stores.map((store) => (
        <li key={store.id ?? store.name}>
          <button type="button" className="search-store tap" onClick={() => onOpen(store)}>
            <Img src={store.img} className={store.logo ? 'is-logo' : undefined} />
            <span>
              <strong>{store.name}</strong>
              {store.eta && <StoreMeta store={{ ...store, deliveryLabel: undefined }} className="search-store-meta" />}
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}
