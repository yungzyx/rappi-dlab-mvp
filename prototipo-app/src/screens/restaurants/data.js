import rcatTurbo from '../../assets/rcat-turbo.webp'
import rcatPizza from '../../assets/rcat-pizza.webp'
import rcatBurger from '../../assets/rcat-burger.webp'
import rcatCulinaria from '../../assets/rcat-culinaria.webp'
import promoWraps from '../../assets/promo-wraps.webp'
import promoBurger from '../../assets/promo-hamburguesa.webp'

export const FILTERS = [
  { id: 'sort', label: 'Ordenar', kind: 'menu' },
  { id: 'top', label: 'Destacados', icon: 'trophy', kind: 'toggle' },
  { id: 'fast', label: '35 min', icon: 'bolt', kind: 'toggle' },
  { id: 'rating', label: '+ 4,5', icon: 'star', kind: 'toggle' },
]

// "Experiencia Culinaria" queda cortada en el borde de la captura; se recorta igual.
// `cuisine`: la cocina de la API (`/catalog/restaurants?cuisine=`) que filtra la lista; sin ella, la categoría abre el buscador.
export const CATEGORIES = [
  { id: 'turbo', label: 'Turbo Restaurantes', img: rcatTurbo, query: 'turbo' },
  { id: 'pizzas', label: 'Pizzas', img: rcatPizza, cuisine: 'Pizzas' },
  { id: 'hamburguesa', label: 'Hamburguesa', img: rcatBurger, cuisine: 'Hamburguesa' },
  {
    id: 'culinaria',
    label: 'Experiencia Culinaria',
    img: rcatCulinaria,
    partial: true,
    cuisine: 'Experiencias Culinarias',
  },
]

// Promociones genéricas de ejemplo, sin marcas: no son tiendas del catálogo y no abren ninguna.
export const BANNERS = [
  { id: 'wraps', title: 'Hasta 40% de descuento', place: 'en wraps y bowls seleccionados', img: promoWraps },
  { id: 'hamburguesas', title: 'Hasta 30% de descuento', place: 'en hamburguesas para la cena', img: promoBurger },
]
