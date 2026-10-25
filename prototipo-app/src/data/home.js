import catRestaurants from '../assets/cat-restaurants.webp'
import catTurbo from '../assets/cat-turbo.webp'
import chipGrocery from '../assets/chip-grocery.webp'
import chipPharmacy from '../assets/chip-pharmacy.webp'
import chipRetail from '../assets/chip-retail.webp'
import chipLiquor from '../assets/chip-liquor.webp'
import chipExpress from '../assets/chip-express.webp'
import chipChocolates from '../assets/chip-chocolates.webp'
import chipRappiTravel from '../assets/chip-rappitravel.webp'
import chipLoyalty from '../assets/chip-loyalty.webp'
import chipBenefitsPro from '../assets/chip-benefitspro.webp'
import chipRappiFavorOff from '../assets/chip-rappifavor-off.webp'
import bannerDescuentos from '../assets/banner-descuentos.webp'
import bannerCena from '../assets/banner-cena.webp'

export const CREDITS = {
  logo: chipLoyalty,
  title: '$1.900 en créditos',
  subtitle: 'para tu próximo pedido',
  expiresInMinutes: 116,
}

export const MAIN_TILES = [
  { id: 'restaurants', label: 'Restaurantes', img: catRestaurants, screen: 'restaurants', vertical: 'restaurantes' },
  { id: 'turbo', label: 'Turbo', img: catTurbo, screen: 'turbo', vertical: 'turbo' },
]

// RappiFavor aparece deshabilitado como en la app (la imagen trae el sello «No disponible»); en el prototipo final se
// habilita con su pantalla (`proposalRoute`).
// `route` dice a qué pantalla lleva cada acceso (ver HomeFeed); `service`, el servicio sin catálogo que abre
// (`payload.servicio` de `service_opened`).
export const SHORTCUTS = [
  {
    id: 'grocery',
    label: 'Súper',
    img: chipGrocery,
    vertical: 'supermercado',
    route: ['vertical', { id: 'grocery' }],
  },
  {
    id: 'pharmacy',
    label: 'Farmacia',
    img: chipPharmacy,
    vertical: 'farmacia',
    route: ['vertical', { id: 'pharmacy' }],
  },
  { id: 'retail', label: 'Rappi Mall', img: chipRetail, vertical: 'mall', route: ['vertical', { id: 'retail' }] },
  { id: 'liquor', label: 'Licores', img: chipLiquor, vertical: 'licores', route: ['vertical', { id: 'liquor' }] },
  {
    id: 'express',
    label: 'Express',
    img: chipExpress,
    vertical: 'conveniencia',
    route: ['vertical', { id: 'express' }],
  },
  {
    id: 'chocolates',
    label: 'Chocolates',
    img: chipChocolates,
    vertical: 'chocolateria',
    route: ['vertical', { id: 'chocolates' }],
  },
  { id: 'rappitravel', label: 'RappiTravel', img: chipRappiTravel, route: ['travel'], service: 'rappitravel' },
  { id: 'loyalty', label: 'Lealtad', img: chipLoyalty, route: ['loyalty'] },
  { id: 'benefitspro', label: 'Beneficios Pro', img: chipBenefitsPro },
  {
    id: 'rappifavor',
    label: 'RappiFavor',
    img: chipRappiFavorOff,
    unavailable: true,
    proposalRoute: ['favor'],
    service: 'rappifavor',
    emoji: '🛵',
  },
]

// Cola fija de la fila en el prototipo final: tras los 6 verticales (en el orden del motor), siempre en este orden y
// con Lealtad y Beneficios Pro al final.
const FINAL_TAIL = ['rappitravel', 'rappifavor', 'loyalty', 'benefitspro']

/**
 * La fila de accesos en cada modo. «Rappi hoy» (`final: false`) es la réplica de la app: tal cual. En el prototipo final,
 * los 6 verticales en el orden del motor (`order`: códigos del backend; ignora los desconocidos y los que falten
 * van después en su orden fijo; sin `order`, el orden fijo) y luego `FINAL_TAIL`.
 */
export function orderShortcuts(shortcuts, order, { final }) {
  if (!final) return shortcuts
  const verticals = shortcuts.filter((item) => item.vertical)
  const first = [...new Set(order ?? [])]
    .map((code) => verticals.find((item) => item.vertical === code))
    .filter(Boolean)
  const rest = verticals.filter((item) => !first.includes(item))
  const tail = FINAL_TAIL.map((id) => shortcuts.find((item) => item.id === id)).filter(Boolean)
  return [...first, ...rest, ...tail]
}

// La app muestra 6 banners; en capturas y video solo se ven completos estos dos.
export const PROMOS = [
  { id: 'descuentos', label: 'Descuentos en restaurantes', img: bannerDescuentos, fit: 'top', route: ['restaurants'] },
  { id: 'cena', label: 'Cena con descuento', img: bannerCena, fit: 'cover', route: ['restaurants'] },
]
export const PROMO_START_INDEX = 1
