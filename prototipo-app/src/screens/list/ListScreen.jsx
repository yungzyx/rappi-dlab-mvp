import ProductRow from '../../components/ProductRow'
import StoreList from '../../components/StoreList'
import BackButton from '../../components/BackButton'
import './list.css'

/**
 * Lista genérica para "See all", "View more" y categorías (funcionalidad agregada).
 * params: { title, stores?, products? } — muestra lo que el prototipo conoce de esa sección.
 */
export default function ListScreen({ back, push, params }) {
  const { title, stores = [], products = [] } = params

  return (
    <div className="screen list">
      <header className="list-header">
        <BackButton className="round-button" onClick={back} />
        <h1>{title}</h1>
      </header>

      {stores.length > 0 && (
        <>
          <h2 className="list-heading">
            Tiendas <span>{stores.length}</span>
          </h2>
          <StoreList stores={stores} onOpen={(store) => push('store', { store })} />
        </>
      )}

      {products.length > 0 && (
        <>
          <h2 className="list-heading">
            Productos <span>{products.length}</span>
          </h2>
          <ul className="list-products">
            {products.map((product) => (
              <ProductRow key={product.id} product={product} showStore />
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
