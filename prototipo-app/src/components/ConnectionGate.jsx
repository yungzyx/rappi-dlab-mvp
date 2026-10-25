import { useEffect, useState } from 'react'
import { AGENT_NAME } from '../agent/name'
import { API_URL, checkConnection, ensureSession } from '../api/client'
import Mascot from './assistant/Mascot'
import './connection-gate.css'

const RETRY_MS = 2000 // sin conexión, se vuelve a preguntar solo: el MVP puede estar arrancando (carga modelos)

/**
 * Sin la API no hay agente, y la app no arranca con reglas locales: antes de montar `children` revisa la API y saca la
 * sesión de este navegador (la primera vez, `POST /session` con el id que ya tenía): sin sesión es «Sin conexión».
 * Mientras revisa o sin conexión no se monta la app, así que ningún contexto llama a la API. Sin conexión
 * vuelve a preguntar cada 2 s, en silencio (la pantalla no cambia), y «Reintentar» pregunta ya. Una vez dentro,
 * la app sigue sola: sus propios errores de red los maneja ella.
 */
export default function ConnectionGate({ children }) {
  const [status, setStatus] = useState('checking') // 'checking' (solo la primera vez) | 'online' | 'offline'
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let current = true
    let timer
    const check = async () => {
      const result = await checkConnection()
      const ready =
        result.ok &&
        (await ensureSession().then(
          () => true,
          () => false,
        ))
      if (!current) return
      if (ready) {
        setStatus('online')
      } else {
        setStatus('offline')
        timer = setTimeout(check, RETRY_MS)
      }
    }
    check()
    return () => {
      current = false
      clearTimeout(timer)
    }
  }, [attempt])

  if (status === 'online') return children

  return <ConnectionNotice status={status} onRetry={() => setAttempt((n) => n + 1)} />
}

/**
 * El aviso de «Conectando…» (`status` 'checking') o «Sin conexión» con «Reintentar» (`status` 'offline'): lo usa la puerta
 * de conexión.
 */
function ConnectionNotice({ status, onRetry }) {
  return (
    <main className="connection-gate">
      <div className="connection-card">
        <Mascot size={96} mood="think" />
        {/* El aviso existe siempre y solo cambia lo de adentro: los lectores de pantalla anuncian el cambio. */}
        <div className="connection-message" role="status">
          {status === 'checking' ? (
            <p className="connection-checking">Conectando con {AGENT_NAME}…</p>
          ) : (
            <>
              <h1>Sin conexión con {AGENT_NAME}</h1>
              {/* Las instrucciones de desarrollador y la dirección de la API no llegan al sitio desplegado. */}
              {import.meta.env.DEV || import.meta.env.VITE_DEMO === '1' ? (
                <>
                  <p>No pude conectar con la API del MVP ({API_URL}).</p>
                  <p className="connection-help">
                    Levanta el MVP con <code>make mvp</code> en la carpeta del proyecto y vuelve a intentar.
                  </p>
                  <p>
                    Si acabas de correr <code>make mvp</code>, espera «MVP listo».
                  </p>
                </>
              ) : (
                <p>Sin conexión. Intenta de nuevo en un momento.</p>
              )}
            </>
          )}
        </div>
        {/* Siempre montado una vez sin conexión: así el foco no cae al body con cada «Reintentar». */}
        {status === 'offline' && (
          <button type="button" className="connection-retry tap" onClick={onRetry}>
            Reintentar
          </button>
        )}
      </div>
    </main>
  )
}
