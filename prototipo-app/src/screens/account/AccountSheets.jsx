import { useState } from 'react'
import ForgetConfirm, { FORGET_TITLE } from '../../components/ForgetConfirm'
import Sheet from '../../components/Sheet'
import { useToast } from '../../components/Toast'
import { useForgetAll } from '../../state/forgetAll'
import { useProfile } from '../../state/ProfileContext'
import { LANGUAGES, NOTIFICATION_CHANNELS } from './data'

const TITLES = {
  language: 'Idioma',
  notifications: 'Notificaciones',
  logout: '¿Cerrar sesión?',
  'logout-all': '¿Cerrar todas las sesiones?',
  forget: FORGET_TITLE,
}

/** Hojas de Cuenta: idioma, notificaciones y confirmación de cierre de sesión (simulados), y «Borrar mis datos» (real). */
export default function AccountSheets({ sheet, onClose }) {
  const toast = useToast()
  const forgetAll = useForgetAll()
  const profile = useProfile()
  const [forgetting, setForgetting] = useState(false)
  const [forgetFailed, setForgetFailed] = useState(false)
  const [language, setLanguage] = useState(LANGUAGES[0])
  const [channels, setChannels] = useState(() =>
    Object.fromEntries(NOTIFICATION_CHANNELS.map((channel) => [channel.id, channel.defaultOn])),
  )
  const [lastSheet, setLastSheet] = useState(sheet)
  if (sheet && sheet !== lastSheet) setLastSheet(sheet)
  const shown = sheet ?? lastSheet

  const confirmLogout = () => {
    onClose()
    toast('Sesión cerrada')
  }

  const confirmForget = async () => {
    setForgetting(true)
    setForgetFailed(false)
    try {
      await forgetAll({ profile }) // si salió bien, la app se recarga en la Home
      onClose()
    } catch {
      setForgetFailed(true) // el servidor sigue con sus datos y el navegador no se tocó: se puede reintentar
    } finally {
      setForgetting(false)
    }
  }

  return (
    <Sheet open={Boolean(sheet)} onClose={onClose} title={TITLES[shown]}>
      {shown === 'language' && (
        <ul className="sheet-options">
          {LANGUAGES.map((option) => (
            <li key={option}>
              <button
                type="button"
                className={option === language ? 'sheet-option is-selected' : 'sheet-option'}
                aria-pressed={option === language}
                onClick={() => setLanguage(option)}
              >
                {option}
                <span className="sheet-radio" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {shown === 'notifications' && (
        <ul className="sheet-options">
          {NOTIFICATION_CHANNELS.map((channel) => (
            <li key={channel.id}>
              <button
                type="button"
                className="sheet-option"
                role="switch"
                aria-checked={channels[channel.id]}
                onClick={() => setChannels((prev) => ({ ...prev, [channel.id]: !prev[channel.id] }))}
              >
                {channel.label}
                <span className={channels[channel.id] ? 'sheet-switch is-on' : 'sheet-switch'} />
              </button>
            </li>
          ))}
        </ul>
      )}

      {(shown === 'logout' || shown === 'logout-all') && (
        <div className="sheet-confirm">
          <p>Puedes volver a entrar cuando quieras con tu número de teléfono.</p>
          <button type="button" className="sheet-confirm-primary tap" onClick={confirmLogout}>
            Cerrar sesión
          </button>
          <button type="button" className="sheet-confirm-secondary tap" onClick={onClose}>
            Cancelar
          </button>
        </div>
      )}

      {shown === 'forget' && (
        <ForgetConfirm forgetting={forgetting} failed={forgetFailed} onConfirm={confirmForget} onCancel={onClose} />
      )}
    </Sheet>
  )
}
