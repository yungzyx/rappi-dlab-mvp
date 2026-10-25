// Pantalla Cuenta, del video de la app iOS del 26-09-2026 (no versionado).
import { version } from '../../../package.json'
import { AGENT_NAME } from '../../agent/name'
import {
  BellIcon,
  BillingIcon,
  CardIcon,
  CouponIcon,
  CreditsIcon,
  CrownLineIcon,
  GlobeIcon,
  HeadsetIcon,
  InfoIcon,
  LoyaltyIcon,
  MustacheIcon,
  PartnerIcon,
  PinIcon,
  ShieldIcon,
  SparkleLineIcon,
} from '../../components/LineIcons'

export const PROFILE = { initials: 'CD', name: 'Cliente Demo' }

export const PRO_PLAN = { savings: '$15.400', note: 'Es lo que ahorra en promedio al mes un usuario Pro.' }

// La versión del prototipo (package.json), no la de la app de Rappi.
export const APP_VERSION = `Versión ${version} · prototipo`

// `action` dice qué hace la fila en el prototipo; sin `action` muestra el aviso de pantalla no incluida.
export const SECTIONS = [
  {
    title: 'Beneficios',
    rows: [
      { id: 'credits', label: 'Créditos', Icon: CreditsIcon, value: '$1.900' },
      { id: 'coupons', label: 'Cupones', Icon: CouponIcon },
      { id: 'loyalty', label: 'Lealtad', Icon: LoyaltyIcon, action: 'loyalty' },
    ],
  },
  {
    title: 'Mi cuenta',
    rows: [
      { id: 'rappipro', label: 'Rappi Pro', Icon: CrownLineIcon },
      { id: 'addresses', label: 'Direcciones', Icon: PinIcon, action: 'addresses' },
      { id: 'payment', label: 'Medios de pago', Icon: CardIcon },
      { id: 'billing', label: 'Datos de facturación', Icon: BillingIcon },
      { id: 'help', label: 'Ayuda', Icon: HeadsetIcon },
    ],
  },
  {
    title: 'Configuración',
    rows: [
      { id: 'language', label: 'Idioma', Icon: GlobeIcon, action: 'language' },
      { id: 'notifications', label: 'Notificaciones', Icon: BellIcon, action: 'notifications' },
      { id: 'icon', label: 'Cambiar el ícono de Rappi', Icon: MustacheIcon },
      // Solo del prototipo: alterna entre Rappi hoy y el prototipo final (en notebook también con la tecla D).
      { id: 'demo', label: 'Modo demo', Icon: SparkleLineIcon, action: 'demo' },
      // Solo en el prototipo final: en el celular no está el botón «Repetir escena» de la notebook.
      {
        id: 'replay',
        label: `Repetir escena de ${AGENT_NAME}`,
        Icon: SparkleLineIcon,
        action: 'replay',
        finalOnly: true,
      },
    ],
  },
  {
    title: 'Más información',
    rows: [
      { id: 'partner', label: 'Súmate como aliado de Rappi', Icon: PartnerIcon },
      { id: 'terms', label: 'Términos y condiciones', Icon: InfoIcon },
      { id: 'privacy', label: 'Política de privacidad', Icon: ShieldIcon },
    ],
  },
]

export const LANGUAGES = ['Español', 'English', 'Português']

export const NOTIFICATION_CHANNELS = [
  { id: 'push', label: 'Notificaciones push', defaultOn: true },
  { id: 'email', label: 'Correo', defaultOn: true },
  { id: 'sms', label: 'SMS', defaultOn: false },
  { id: 'whatsapp', label: 'WhatsApp', defaultOn: false },
]
