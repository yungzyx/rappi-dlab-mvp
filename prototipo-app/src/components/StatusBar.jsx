import { BellSlashIcon } from './Icons'
import './status-bar.css'

// Barra de estado de iOS: 10:10 (la hora de las fotos de producto de Apple) y batería llena en verde.
export default function StatusBar() {
  return (
    <div className="status-bar" aria-hidden="true">
      <div className="status-left">
        <span className="status-time">10:10</span>
        <BellSlashIcon size={15} />
      </div>
      <div className="status-right">
        <svg width="20" height="13" viewBox="0 0 20 13">
          <rect x="0" y="8.5" width="3.4" height="4.5" rx="1" fill="currentColor" />
          <rect x="5.3" y="6" width="3.4" height="7" rx="1" fill="currentColor" />
          <rect x="10.6" y="3.2" width="3.4" height="9.8" rx="1" fill="currentColor" opacity="0.3" />
          <rect x="15.9" y="0" width="3.4" height="13" rx="1" fill="currentColor" opacity="0.3" />
        </svg>
        <svg width="18" height="13" viewBox="0 0 18 13">
          <path
            d="M9 2.4c2.6 0 5 1 6.8 2.7l1.2-1.3A11.4 11.4 0 0 0 9 .6 11.4 11.4 0 0 0 1 3.8l1.2 1.3A9.6 9.6 0 0 1 9 2.4zm0 3.6c1.6 0 3.1.6 4.3 1.7l1.2-1.3A8 8 0 0 0 9 4.2a8 8 0 0 0-5.5 2.2l1.2 1.3A6.2 6.2 0 0 1 9 6zm0 3.6c.7 0 1.3.3 1.8.7L9 12.4 7.2 10.3c.5-.4 1.1-.7 1.8-.7z"
            fill="currentColor"
          />
        </svg>
        <span className="status-battery">
          <span className="status-battery-level">100</span>
          <span className="status-battery-nub" />
        </span>
      </div>
    </div>
  )
}
