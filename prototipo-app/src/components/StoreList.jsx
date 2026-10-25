import { storeItem } from '../api/impressions'
import { useImpressions } from '../hooks/useImpressions'
import Img from './Img'
import { PromoTag, StoreMeta } from './StoreMeta'
import { isClosed } from './storeHours'
import './store-list.css'

/**
 * Lista vertical de tiendas o restaurantes (buscador y pantallas "View more"), con su estado y su promo. Con
 * `impression`, cada tienda con lugar cuenta como vista cuando aparece en pantalla (api/impressions.js).
 */
export default function StoreList({ stores, onOpen, impression = false }) {
  const watch = useImpressions()
  return (
    <ul className="search-stores">
      {stores.map((store) => (
        <li key={store.id ?? store.name} ref={impression ? watch(store, storeItem(store)) : undefined}>
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
