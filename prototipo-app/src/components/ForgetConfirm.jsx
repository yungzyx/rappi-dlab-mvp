export const FORGET_TITLE = 'Borrar mis datos'

/**
 * La confirmación de «Borrar mis datos», dentro de una hoja: la misma en Cuenta y en «Olvidar» del buscador.
 * `failed` muestra el aviso de que no se borró nada (se puede reintentar); `forgetting` deja los botones quietos.
 */
export default function ForgetConfirm({ forgetting, failed, onConfirm, onCancel }) {
  return (
    <div className="sheet-confirm">
      <p>
        Borramos de nuestro servidor tus búsquedas, lo que hiciste en la app y tus pedidos, y de este navegador tu carro
        y tus preferencias. Después la app te trata como a una persona nueva. No se puede deshacer.
      </p>
      {failed && (
        <p role="alert">No pude borrar tus datos en el servidor. No se borró nada: inténtalo de nuevo en un rato.</p>
      )}
      <button type="button" className="sheet-confirm-primary tap" disabled={forgetting} onClick={onConfirm}>
        Sí, borrar
      </button>
      <button type="button" className="sheet-confirm-secondary tap" disabled={forgetting} onClick={onCancel}>
        Cancelar
      </button>
    </div>
  )
}
