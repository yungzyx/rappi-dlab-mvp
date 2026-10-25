import { useAddress } from '../state/AddressContext'
import { PinIcon } from './LineIcons'
import Sheet from './Sheet'
import { useToast } from './Toast'
import './address-sheet.css'

/** Hoja para elegir la dirección de entrega (se abre desde la Home y desde Cuenta → Direcciones). */
export default function AddressSheet() {
  const address = useAddress()
  const toast = useToast()

  const choose = (id) => {
    address.select(id)
    address.closeSheet()
  }

  return (
    <Sheet open={address.sheetOpen} onClose={address.closeSheet} title="¿Dónde te lo llevamos?">
      <ul className="address-list">
        {address.addresses.map((item) => {
          const isSelected = item.id === address.selected.id
          return (
            <li key={item.id}>
              <button
                type="button"
                className={isSelected ? 'address-option is-selected' : 'address-option'}
                aria-pressed={isSelected}
                onClick={() => choose(item.id)}
              >
                <PinIcon size={22} />
                <span>
                  <strong>{item.label}</strong>
                  <span>{item.line}</span>
                </span>
                <span className="address-radio" />
              </button>
            </li>
          )
        })}
      </ul>
      <button type="button" className="address-add tap" onClick={() => toast()}>
        + Agregar dirección
      </button>
    </Sheet>
  )
}
