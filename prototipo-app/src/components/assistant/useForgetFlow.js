import { useState } from 'react'
import { useForgetAll } from '../../state/forgetAll'

/**
 * "Olvidar" desde el buscador: la hoja que lo confirma (`confirming`), el borrado en curso (`forgetting`: mientras
 * tanto no se envía nada, una pregunta nueva recrearía lo borrado) y si falló (`failed`: el servidor sigue con sus
 * datos, la hoja lo dice y se puede reintentar). `prepare` borra lo del panel antes de pedir el borrado; `settle`
 * devuelve lo que ya salió y hay que esperar antes del DELETE.
 */
export function useForgetFlow({ prepare, settle }) {
  const forgetEverything = useForgetAll()
  const [forgetting, setForgetting] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [failed, setFailed] = useState(false)

  const confirm = async () => {
    setForgetting(true)
    setFailed(false)
    prepare()
    try {
      // Lo que ya salió (preguntas pendientes, un lote de eventos, un pedido) podría recrear lo olvidado en el
      // servidor: forgetAll lo espera antes del DELETE, descarta lo que haya dejado en cola, y deja el navegador en
      // cero.
      await forgetEverything({ settle }) // si salió bien, la app se recarga
      setConfirming(false)
    } catch {
      setFailed(true)
    } finally {
      setForgetting(false)
    }
  }

  const cancel = () => {
    if (forgetting) return
    setConfirming(false)
    setFailed(false)
  }

  return { forgetting, confirming, failed, open: () => setConfirming(true), confirm, cancel }
}
