import { useState } from 'react'
import BackButton from '../../components/BackButton'
import { useToast } from '../../components/Toast'
import Img from '../../components/Img'
import { ChevronRight } from '../../components/Icons'
import { CardIcon, HeadsetIcon, LogoutIcon, OrdersIcon } from '../../components/LineIcons'
import { useAddress } from '../../state/AddressContext'
import { MODE_LABELS, nextMode, useDemo } from '../../state/DemoContext'
import { resetLive } from '../../state/liveMemory'
import { useOrders } from '../../state/OrdersContext'
import { formatPrice } from '../../state/CartContext'
import { relativeDay } from '../orders/dates'
import dealsCrown from '../../assets/deals-crown.webp'
import AccountSheets from './AccountSheets'
import { APP_VERSION, PRO_PLAN, PROFILE, SECTIONS } from './data'
import './account.css'

/** Pestaña Cuenta. `onBack` vuelve a la pestaña Inicio. */
export default function AccountScreen({ onBack, push }) {
  const toast = useToast()
  const address = useAddress()
  const demo = useDemo()
  const { orders } = useOrders()
  const [sheet, setSheet] = useState(null)
  // «Modo demo» cambia toda la app de modo: como el interruptor de la presentación, solo en desarrollo o con VITE_DEMO=1.
  const showDemoRow = import.meta.env.DEV || import.meta.env.VITE_DEMO === '1'

  const runRow = (row) => {
    if (row.action === 'addresses') address.openSheet()
    else if (row.action === 'loyalty') push('loyalty')
    else if (row.action === 'demo') {
      demo.toggle()
      toast(`Modo demo: ${MODE_LABELS[nextMode(demo.mode)]}`)
    } else if (row.action === 'replay') {
      resetLive()
      onBack()
    } else if (row.action) setSheet(row.action)
    else toast()
  }

  return (
    <>
      <div className="screen account">
        <header className="account-header">
          <BackButton className="account-back" onClick={onBack} size={18} />
          <h1>Cuenta</h1>
        </header>

        <section className="account-top">
          <button type="button" className="account-profile tap" onClick={() => toast()}>
            <span className="account-avatar">{PROFILE.initials}</span>
            <span>
              <strong>{PROFILE.name}</strong>
              <span className="account-edit">
                Editar perfil <ChevronRight size={13} />
              </span>
            </span>
          </button>

          <button type="button" className="account-pro tap" onClick={() => toast()}>
            <span className="account-pro-label">Tu plan</span>
            <span className="account-pro-name">
              <img src={dealsCrown} alt="" />
              Rappi Pro
              <ChevronRight size={18} />
            </span>
            <span className="account-pro-savings">{PRO_PLAN.savings}</span>
            <span className="account-pro-note">{PRO_PLAN.note}</span>
          </button>

          <div className="account-quick">
            {[
              { id: 'orders', label: 'Pedidos', Icon: OrdersIcon },
              { id: 'help', label: 'Ayuda', Icon: HeadsetIcon },
              { id: 'payment', label: 'Medios de pago', Icon: CardIcon },
            ].map(({ id, label, Icon }) => (
              <button
                key={id}
                type="button"
                className="account-quick-tile tap"
                onClick={() => (id === 'orders' ? push('orders') : toast())}
              >
                <Icon size={27} />
                <span>{label}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="account-body">
          <div className="account-section-head">
            <h2>Pedidos recientes</h2>
            <button type="button" className="see-more tap" onClick={() => push('orders')}>
              Ver todos
            </button>
          </div>
          {/* Los pedidos hechos en la demo (abren su seguimiento) */}
          {orders.length === 0 && <p className="account-orders-empty">Aún no tienes pedidos.</p>}
          {orders.map((order) => (
            <button
              key={order.id}
              type="button"
              className="account-order tap"
              onClick={() => push('tracking', { orderId: order.id })}
            >
              <Img src={order.items[0]?.img} className="account-order-photo" />
              <span>
                <strong>{order.stores.join(', ') || 'Tu pedido'}</strong>
                <span>
                  {relativeDay(order.placedAt)} · {formatPrice(order.total)}
                </span>
              </span>
              <ChevronRight size={18} />
            </button>
          ))}

          {SECTIONS.map((section) => (
            <div key={section.title} className="account-section">
              <h2>{section.title}</h2>
              <ul>
                {section.rows
                  .filter((row) => (!row.finalOnly || demo.isFinal) && (showDemoRow || row.action !== 'demo'))
                  .map((row) => (
                    <li key={row.id}>
                      <button type="button" className="account-row" onClick={() => runRow(row)}>
                        <span className="account-row-icon">
                          <row.Icon size={24} />
                        </span>
                        <span className="account-row-label">{row.label}</span>
                        {row.action === 'demo' ? (
                          <strong className="account-demo-value">{MODE_LABELS[demo.mode]}</strong>
                        ) : row.value ? (
                          <strong>{row.value}</strong>
                        ) : (
                          <ChevronRight size={18} />
                        )}
                      </button>
                    </li>
                  ))}
              </ul>
            </div>
          ))}

          <button
            type="button"
            className="account-forget tap"
            aria-label="Borrar mis datos"
            aria-describedby="account-forget-note"
            onClick={() => setSheet('forget')}
          >
            <span className="account-forget-title">Borrar mis datos</span>
            <span id="account-forget-note" className="account-forget-note">
              Borra del servidor lo que guardamos con tu identificador anónimo y lo que hay en este navegador.
            </span>
          </button>
          <button type="button" className="account-logout tap" onClick={() => setSheet('logout')}>
            <LogoutIcon size={25} />
            Cerrar sesión
          </button>
          <button
            type="button"
            className="account-logout account-logout--all tap"
            onClick={() => setSheet('logout-all')}
          >
            <LogoutIcon size={25} />
            Cerrar todas las sesiones
          </button>
          <p className="account-version">{APP_VERSION}</p>
          <p className="account-version">Hecho con 🧡 en Latinoamérica</p>
        </section>
      </div>

      <AccountSheets sheet={sheet} onClose={() => setSheet(null)} />
    </>
  )
}
