// Iconos SVG que imitan los de la app (los que no se pueden recortar limpios de las capturas).
// `active` lo manda BottomNav a todos los íconos; solo HomeIcon lo usa, así que aquí se descarta.
// eslint-disable-next-line no-unused-vars
function Svg({ size = 24, children, strokeWidth = 2, fill = 'none', active, ...rest }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={fill}
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  )
}

const HOUSE = 'M12 2.8 3.2 10v10.1c0 .5.4.9.9.9h5.3v-5.3c0-.5.4-.9.9-.9h3.4c.5 0 .9.4.9.9V21h5.3c.5 0 .9-.4.9-.9V10z'
const STAR = 'M12 2.6l2.8 5.9 6.4.8-4.7 4.5 1.2 6.4L12 17.1l-5.7 3.1 1.2-6.4-4.7-4.5 6.4-.8z'

export const SearchIcon = (p) => (
  <Svg strokeWidth={2.8} {...p}>
    <circle cx="10.5" cy="10.5" r="6.8" />
    <path d="M15.6 15.6 20.5 20.5" />
  </Svg>
)

export const ChevronDown = (p) => (
  <Svg strokeWidth={2.6} {...p}>
    <path d="M7 10l5 5 5-5" />
  </Svg>
)

export const ArrowUpIcon = (p) => (
  <Svg strokeWidth={2.6} {...p}>
    <path d="M12 20V5M6 11l6-6 6 6" />
  </Svg>
)

export const ScooterIcon = (p) => (
  <Svg fill="currentColor" strokeWidth={0} {...p}>
    <path d="M9.5 3.5h3.2l.9 3.2H11l1.1 4.1c1.8.3 3.3 1.5 4 3.1h-2.6a2.9 2.9 0 0 0-5.1 0H6.6c.6-2.3 2.6-4 5-4.1L10 6.7H8.6z" />
    <circle cx="8.3" cy="17.5" r="2.6" />
    <circle cx="17.2" cy="17.5" r="2.6" />
    <path d="M13.8 6.7h3.4l1.6 5.6h-1.9z" />
  </Svg>
)

export const ChevronLeft = (p) => (
  <Svg strokeWidth={2.8} {...p}>
    <path d="M14.5 6 8.5 12l6 6" />
  </Svg>
)

export const ChevronRight = (p) => (
  <Svg strokeWidth={2.8} {...p}>
    <path d="M9.5 6l6 6-6 6" />
  </Svg>
)

export const HomeIcon = ({ active, ...p }) => (
  <Svg fill={active ? 'currentColor' : 'none'} strokeWidth={active ? 0 : 2} {...p}>
    <path d={HOUSE} />
  </Svg>
)

export const OffersIcon = (p) => (
  <Svg strokeWidth={1.9} {...p}>
    <path d="M3.5 20.5 8 9.5l6.5 6.5z" />
    <path d="M8.2 13.5 10.5 16" />
    <path d="M12.5 11.5c1.6-1.8 3.4-2.2 5.2-1.3" />
    <path d="M11 7.5c.4-1.8-.2-3.2-1.5-4" />
    <path d="M17 3.2v2.6M15.7 4.5h2.6" />
    <path d="M20 12.8v2M19 13.8h2" />
  </Svg>
)

export const FavoritesIcon = (p) => (
  <Svg strokeWidth={1.9} {...p}>
    <path d="M4.8 8h14.4l-1 12.2H5.8z" />
    <path d="M9 8V6.3a3 3 0 0 1 6 0V8" />
    <path
      d="M12 17.6s-3.1-1.8-3.1-3.8a1.6 1.6 0 0 1 3.1-.5 1.6 1.6 0 0 1 3.1.5c0 2-3.1 3.8-3.1 3.8z"
      fill="currentColor"
      strokeWidth={1}
    />
  </Svg>
)

export const AccountIcon = (p) => (
  <Svg strokeWidth={1.9} {...p}>
    <circle cx="10" cy="7.3" r="3.6" />
    <path d="M3.3 20.2c0-3.8 3-6.3 6.7-6.3 1.3 0 2.5.3 3.5.8" />
    <circle cx="17.6" cy="17.4" r="3.9" />
    <path d="M16 17.9c.8.9 2.4.9 3.2 0" strokeWidth={1.5} />
  </Svg>
)

export const BoltIcon = (p) => (
  <Svg fill="currentColor" strokeWidth={0} {...p}>
    <path d="M13.5 2 4.5 13.6h6.3L9.6 22l9.6-12.3h-6.6z" />
  </Svg>
)

export const SpeedBoltIcon = (p) => (
  <Svg {...p}>
    <path d="M14.5 2.5 7.8 12.6h5.4l-1.5 8.9 7.3-11h-5.5z" fill="currentColor" strokeWidth={1.2} />
    <path d="M2.5 8.5h4M1.8 12.5h3.4M3 16.5h3.8" strokeWidth={2} />
  </Svg>
)

export const StarIcon = ({ filled, ...p }) => (
  <Svg fill={filled ? 'currentColor' : 'none'} strokeWidth={filled ? 0 : 2} {...p}>
    <path d={STAR} />
  </Svg>
)

export const TrophyIcon = (p) => (
  <Svg strokeWidth={2.2} {...p}>
    <path d="M7.5 3.5h9v5.2a4.5 4.5 0 0 1-9 0z" />
    <path d="M7.5 5.2H4.3v1.3a3.2 3.2 0 0 0 3.4 3.2M16.5 5.2h3.2v1.3a3.2 3.2 0 0 1-3.4 3.2" />
    <path d="M12 13.3v3.6M8.3 20.5h7.4M9.8 17h4.4" />
  </Svg>
)

export const ClockIcon = (p) => (
  <Svg strokeWidth={2} {...p}>
    <circle cx="12" cy="12" r="8.6" />
    <path d="M12 7.6V12l2.9 1.9" />
  </Svg>
)

export const CrownIcon = (p) => (
  <Svg fill="currentColor" strokeWidth={0} {...p}>
    <path d="M2.5 7.5 7.4 11.6 12 4.5l4.6 7.1 4.9-4.1-2.1 11H4.6z" />
  </Svg>
)

export const SlidersIcon = (p) => (
  <Svg strokeWidth={2.2} {...p}>
    <path d="M3.5 7.5h8.5M17.5 7.5h3" />
    <circle cx="15" cy="7.5" r="2.6" />
    <path d="M3.5 16.5h3M12 16.5h8.5" />
    <circle cx="9.2" cy="16.5" r="2.6" />
  </Svg>
)

export const HeartIcon = (p) => (
  <Svg strokeWidth={2} {...p}>
    <path d="M12 20s-7.5-4.6-7.5-10.2A4.3 4.3 0 0 1 12 7.1a4.3 4.3 0 0 1 7.5 2.7C19.5 15.4 12 20 12 20z" />
  </Svg>
)

export const BadgePercentIcon = (p) => (
  <Svg strokeWidth={2} {...p}>
    <path d="M12 2.6l2.3 1.6 2.8-.1 1 2.6 2.3 1.6-.8 2.7.8 2.7-2.3 1.6-1 2.6-2.8-.1L12 21.4l-2.3-1.6-2.8.1-1-2.6-2.3-1.6.8-2.7-.8-2.7 2.3-1.6 1-2.6 2.8.1z" />
    <path d="M9.4 14.6l5.2-5.2" />
    <circle cx="9.6" cy="9.6" r="0.6" fill="currentColor" />
    <circle cx="14.4" cy="14.4" r="0.6" fill="currentColor" />
  </Svg>
)

export const GridIcon = (p) => (
  <Svg strokeWidth={2.2} {...p}>
    <rect x="3.5" y="3.5" width="7" height="7" rx="2.2" />
    <rect x="13.5" y="3.5" width="7" height="7" rx="2.2" />
    <rect x="3.5" y="13.5" width="7" height="7" rx="2.2" />
    <rect x="13.5" y="13.5" width="7" height="7" rx="2.2" />
  </Svg>
)

export const MoreIcon = (p) => (
  <Svg fill="currentColor" strokeWidth={0} {...p}>
    <circle cx="5" cy="12" r="2.1" />
    <circle cx="12" cy="12" r="2.1" />
    <circle cx="19" cy="12" r="2.1" />
  </Svg>
)

export const BellSlashIcon = (p) => (
  <Svg strokeWidth={2.2} {...p}>
    <path d="M6.5 16.5V11a5.5 5.5 0 0 1 8.8-4.4M17.5 10.5v6H8" />
    <path d="M10 19.5a2.2 2.2 0 0 0 4 0" />
    <path d="M4 4l16 16" />
  </Svg>
)
