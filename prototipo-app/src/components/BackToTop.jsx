import { ArrowUpIcon } from './Icons'
import './back-to-top.css'

/** Píldora negra «Volver arriba» que aparece al volver a subir en listas largas. */
export default function BackToTop({ visible, onClick, top = 178 }) {
  return (
    <button
      type="button"
      className={visible ? 'back-to-top is-visible' : 'back-to-top'}
      style={{ top }}
      onClick={onClick}
      tabIndex={visible ? 0 : -1}
    >
      <ArrowUpIcon size={17} />
      Volver arriba
    </button>
  )
}
