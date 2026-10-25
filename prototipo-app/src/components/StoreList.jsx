import Img from './Img'
import { PromoTag, StoreMeta } from './StoreMeta'
import { isClosed } from './storeHours'
import './store-list.css'

/** Lista vertical de tiendas o restaurantes (buscador y pantallas "View more"), con su estado y su promo. */
export default function StoreList({ stores, onOpen }) {
  return (
    <ul className="search-stores">
      {stores.map((store) => (
        <li key={store.id ?? store.name}>
          <button type="button" className="search-store tap" onClick={() => onOpen(store)}>
            <Img src={store.img} className={store.logo ? 'is-logo' : undefined} />
            <span>
              <strong>{store.name}</strong>
              {(store.eta || isClosed(store.hours)) && (
                <StoreMeta store={{ ...store, deliveryLabel: undefined }} className="search-store-meta" />
              )}
              <PromoTag store={store} />
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}
