import { pricesDate } from '../api/usePricesDate'
import { localStore, tabStore } from '../state/storage'
import './demo-disclaimer.css'

/**
 * El aviso fijo de la Home: esto es un prototipo hecho con Rappi, no su app oficial. Con `dates` (las de `catalogDates`),
 * dice también de qué fecha son los precios.
 */
export default function DemoDisclaimer({ dates = null }) {
  const prices = pricesDate(dates)
  return (
    <>
      <p className="demo-disclaimer">Prototipo dLab con Rappi · demo, no es la app oficial</p>
      {prices && <p className="demo-disclaimer demo-disclaimer--prices">Precios de Rappi Chile {prices}</p>}
      {/* Solo en "Prototipo MVP.html" (`npm run demo:html`): la API la responde el navegador. */}
      {import.meta.env.VITE_OFFLINE_DEMO === '1' && <OfflineNote />}
    </>
  )
}

function OfflineNote() {
  // Lo que la demo recuerda (pedidos, toques, carro) vive en este navegador con el prefijo de la app.
  const restart = () => {
    for (const store of [localStore, tabStore]) store.clear('rappi-proto-')
    // Sin el estado de la pantalla en que estaba (useNavigation lo lee antes que el hash): vuelve a la Home.
    window.history.replaceState(null, '', `${window.location.pathname}#/home`)
    window.location.reload()
  }
  return (
    <p className="demo-disclaimer demo-disclaimer--offline">
      Demo sin conexión: datos de una muestra del catálogo y una API simulada en el navegador.{' '}
      <button type="button" className="demo-disclaimer-reset" onClick={restart}>
        Empezar de cero
      </button>
    </p>
  )
}
