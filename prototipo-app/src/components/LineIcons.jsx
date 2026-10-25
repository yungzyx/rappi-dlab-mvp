// Íconos de línea de la pantalla Cuenta (y del selector de dirección), dibujados a partir del video.
function Line({ size = 24, children, strokeWidth = 1.9 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

export const PinIcon = (p) => (
  <Line {...p}>
    <path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11z" />
    <circle cx="12" cy="10" r="2.4" />
  </Line>
)

export const CreditsIcon = (p) => (
  <Line {...p}>
    <circle cx="12" cy="12" r="9" />
    <text x="12" y="15.3" textAnchor="middle" fontSize="8.4" fontWeight="700" fill="currentColor" stroke="none">
      CR
    </text>
  </Line>
)

export const CouponIcon = (p) => (
  <Line {...p}>
    <path d="M4 6.5h16v3.2a2.3 2.3 0 0 0 0 4.6v3.2H4v-3.2a2.3 2.3 0 0 0 0-4.6z" />
    <path d="M9.5 9.5v5" strokeDasharray="1.6 1.8" />
  </Line>
)

export const LoyaltyIcon = (p) => (
  <Line {...p}>
    <circle cx="12" cy="12" r="9" />
    <path
      d="M12 6.8l1.5 3.1 3.4.5-2.5 2.4.6 3.4-3-1.6-3 1.6.6-3.4-2.5-2.4 3.4-.5z"
      fill="currentColor"
      strokeWidth={1}
    />
  </Line>
)

export const CrownLineIcon = (p) => (
  <Line {...p}>
    <path d="M3 7.5l4.6 4L12 5.5l4.4 6 4.6-4-1.8 10H4.8z" />
  </Line>
)

export const CardIcon = (p) => (
  <Line {...p}>
    <rect x="3" y="5.5" width="18" height="13" rx="3.2" />
    <path d="M3 10h18M7 14.5h3" />
  </Line>
)

export const BillingIcon = (p) => (
  <Line {...p}>
    <path d="M5.5 3.5h13v17l-2.2-1.6-2.1 1.6-2.2-1.6-2.1 1.6-2.2-1.6-2.2 1.6z" />
    <path d="M14 8.6c-.4-.7-1.2-1-2-1-1.2 0-2 .6-2 1.5 0 2.1 4 1.1 4 3.2 0 .9-.9 1.5-2 1.5-.9 0-1.7-.4-2-1.1M12 6.3v1.3M12 13.3v1.3" />
  </Line>
)

export const HeadsetIcon = (p) => (
  <Line {...p}>
    <path d="M4.5 14v-2a7.5 7.5 0 0 1 15 0v2" />
    <rect x="3.5" y="13" width="4" height="6" rx="1.6" />
    <rect x="16.5" y="13" width="4" height="6" rx="1.6" />
  </Line>
)

export const GlobeIcon = (p) => (
  <Line {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M3 12h18M12 3c2.6 2.6 3.8 5.6 3.8 9s-1.2 6.4-3.8 9c-2.6-2.6-3.8-5.6-3.8-9S9.4 5.6 12 3z" />
  </Line>
)

export const BellIcon = (p) => (
  <Line {...p}>
    <path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5h-15z" />
    <path d="M10 20.5a2.2 2.2 0 0 0 4 0" />
  </Line>
)

export const MustacheIcon = ({ size = 24 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
    <path
      d="M12 11.2c1.4-1.9 3.8-2.6 6-1.6 1.4.6 2.4 1.7 3.5 1.5-.5 2.2-2.6 3.6-4.8 3.4-2-.2-3.6-1.4-4.7-2.4-1.1 1-2.7 2.2-4.7 2.4-2.2.2-4.3-1.2-4.8-3.4 1.1.2 2.1-.9 3.5-1.5 2.2-1 4.6-.3 6 1.6z"
      fill="currentColor"
    />
  </svg>
)

export const SparkleLineIcon = (p) => (
  <Line {...p}>
    <path d="M10 3l1.8 5.2L17 10l-5.2 1.8L10 17l-1.8-5.2L3 10l5.2-1.8z" />
    <path d="M18 14.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z" />
  </Line>
)

export const PartnerIcon = (p) => (
  <Line {...p}>
    <path d="M4 9.5 5.5 4h13L20 9.5M4 9.5h16v1a2.7 2.7 0 0 1-5.3 0 2.7 2.7 0 0 1-5.4 0 2.7 2.7 0 0 1-5.3 0z" />
    <path d="M5.5 12.8V20h13v-7.2M10 20v-4.5h4V20" />
  </Line>
)

export const InfoIcon = (p) => (
  <Line {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5.5M12 7.6v.2" strokeWidth={2.4} />
  </Line>
)

export const ShieldIcon = (p) => (
  <Line {...p}>
    <path d="M12 3.2 19 6v5.5c0 4.4-3 7.7-7 9.3-4-1.6-7-4.9-7-9.3V6z" />
    <path d="m9 12 2.2 2.2L15.3 10" />
  </Line>
)

export const LogoutIcon = (p) => (
  <Line {...p}>
    <path d="M13.5 5V4.5a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 4.5v15A1.5 1.5 0 0 0 6 21h6a1.5 1.5 0 0 0 1.5-1.5V19" />
    <path d="M9.5 12h11M17 8.5l3.5 3.5-3.5 3.5" />
  </Line>
)

export const OrdersIcon = (p) => (
  <Line strokeWidth={2.1} {...p}>
    <path d="M5 4h14v16H5z" />
    <path d="M5 4l2.3 2.3L9.6 4l2.4 2.3L14.4 4l2.3 2.3L19 4M9 12.5h.1M15 12.5h.1M9.2 15.6c1.6 1.2 4 1.2 5.6 0" />
  </Line>
)
