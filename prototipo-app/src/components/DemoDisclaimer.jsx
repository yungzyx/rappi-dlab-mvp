import './demo-disclaimer.css'

/** El aviso fijo de la Home: esto es una demo independiente, no la app de Rappi. */
export default function DemoDisclaimer() {
  return (
    <>
      <p className="demo-disclaimer">Demo no oficial · prototipo independiente, no afiliado a Rappi</p>
      {/* Solo en «Prototipo MVP.html» (`npm run demo:html`): la API la responde el navegador. */}
      {import.meta.env.VITE_OFFLINE_DEMO === '1' && <OfflineNote />}
    </>
  )
}

function OfflineNote() {
  // Lo que la demo recuerda (pedidos, toques, carro) vive en este navegador con el prefijo de la app.
  const restart = () => {
    for (const storage of [localStorage, sessionStorage]) {
      try {
        for (const key of Object.keys(storage)) if (key.startsWith('rappi-proto-')) storage.removeItem(key)
      } catch {
        // Sin almacenamiento no hay nada que borrar.
      }
    }
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
