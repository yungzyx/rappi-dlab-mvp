import { useEffect, useRef } from 'react'

const FOCUSABLE = [
  'button:not([disabled])',
  '[href]',
  'input:not([disabled]):not([hidden]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ')

// Los diálogos abiertos, el último arriba: con dos a la vez (el panel de Mochi y una hoja encima) solo el de arriba
// atrapa Tab y atiende Escape; si no, cada uno le deshace al otro el foco y Escape cierra los dos.
const stack = []

// Un diálogo tapado (bajo una pantalla inerte, como una hoja que quedó abierta al apilar otra pantalla) u oculto no
// recibe el teclado: nadie puede llegar a él y atraparía el Tab de toda la app.
const isLive = (root) => Boolean(root?.isConnected) && !root.closest('[inert], [hidden]')
const topDialog = () => stack.findLast(isLive)

// Un control inerte u oculto (lo que espera el saludo de Mochi) no cuenta como el primero ni el último: el navegador lo
// salta, y desde el último que sí se alcanza el Tab saldría del diálogo.
const reachable = (el) => !el.closest('[inert]') && el.checkVisibility?.({ visibilityProperty: true }) !== false

/**
 * Diálogo modal usable con teclado y VoiceOver (WCAG 2.1.2 y 2.4.3): al abrir, el foco entra (a `[data-autofocus]`
 * o al primer control); Escape cierra; Tab no sale del diálogo; al cerrar, el foco vuelve a quien lo abrió.
 */
export function useDialog(ref, open, onClose) {
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
  })

  useEffect(() => {
    if (!open) return undefined
    const opener = document.activeElement
    const root = ref.current
    const target = root?.querySelector('[data-autofocus]') ?? root?.querySelector(FOCUSABLE) ?? root
    target?.focus({ preventScroll: true })

    stack.push(root)
    const onKeyDown = (event) => {
      if (topDialog() !== root) return
      if (event.key === 'Escape') {
        event.stopPropagation()
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab' || !root) return
      const items = [...root.querySelectorAll(FOCUSABLE)].filter(reachable)
      if (!items.length) return
      const first = items[0]
      const last = items[items.length - 1]
      if (event.shiftKey && (document.activeElement === first || !root.contains(document.activeElement))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (document.activeElement === last || !root.contains(document.activeElement))) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      stack.splice(stack.indexOf(root), 1)
      if (opener?.isConnected) opener.focus({ preventScroll: true })
    }
  }, [open, ref])
}
