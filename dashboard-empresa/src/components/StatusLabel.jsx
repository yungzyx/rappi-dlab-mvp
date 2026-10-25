import { RISK_STATUS } from '../lib/labels.js'
import { Icon } from './Icon.jsx'

const ICONS = { bad: 'stop', warn: 'warn' }

export function StatusLabel({ status }) {
  const { label, tone } = RISK_STATUS[status] ?? { label: status, tone: 'muted' }
  return (
    <span className={`status status--${tone}`}>
      {ICONS[tone] && <Icon name={ICONS[tone]} />}
      {label}
    </span>
  )
}
