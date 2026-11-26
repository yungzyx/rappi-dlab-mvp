import { pricesDate } from '../api/usePricesDate'
import { localStore, tabStore } from '../state/storage'
import { ChevronDown } from './Icons'
import './demo-disclaimer.css'

const NOTICE = 'Prototipo dLab con Rappi · demo, no es la app oficial'

/**
 * El aviso fijo de la Home, en una línea: esto es un prototipo hecho con Rappi, no su app oficial. Al tocarla se abre el
 * resto: con `dates` (las de `catalogDates`), de qué fecha son los precios y, en la demo sin conexión, de dónde salen
 * los datos y "Empezar de cero".
 */
export default function DemoDisclaimer({ dates = null }) {
  const prices = pricesDate(dates)
  // Solo en "Prototipo MVP.html" (`npm run demo:html`): la API la responde el navegador.
  const offline = import.meta.env.VITE_OFFLINE_DEMO === '1'
  if (!prices && !offline) return <p className="demo-disclaimer">{NOTICE}</p>
  return (
    <details className="demo-disclaimer">
      <summary>
        <span>{NOTICE}</span>
        <ChevronDown size={13} />
      </summary>
      {prices && <p className="demo-disclaimer-detail">Precios de Rappi Chile {prices}</p>}
      {offline && <OfflineNote />}
    </details>
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
    <p className="demo-disclaimer-detail">
      Demo sin conexión: datos de una muestra del catálogo y una API simulada en el navegador.{' '}
      <button type="button" className="demo-disclaimer-reset" onClick={restart}>
        Empezar de cero
      </button>
    </p>
  )
}
