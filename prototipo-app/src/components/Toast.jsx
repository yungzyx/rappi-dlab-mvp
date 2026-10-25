import { createContext, useCallback, useContext, useRef, useState } from 'react'
import './toast.css'

const TOAST_MS = 1800
const ToastContext = createContext(() => {})

const NOT_REPLICATED = 'Esta sección no está en el prototipo'

export function ToastProvider({ children }) {
  const [message, setMessage] = useState(null)
  const timer = useRef(null)

  const show = useCallback((text = NOT_REPLICATED) => {
    clearTimeout(timer.current)
    setMessage(text)
    timer.current = setTimeout(() => setMessage(null), TOAST_MS)
  }, [])

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className={message ? 'toast is-visible' : 'toast'} role="status" aria-live="polite">
        {message}
      </div>
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)
