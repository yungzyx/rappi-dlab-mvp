// La foto de cada destino de la idea para RappiTravel (`viaje.id` de la API, offers/destinos.toml), con su crédito.
// Son las de la demo del Comité 2 (rama demo/prototipo-sushi). Un destino sin foto aquí se muestra sin ella.

import colombia from '../assets/viajes/colombia.jpg'
import italia from '../assets/viajes/italia.jpg'
import japon from '../assets/viajes/japon.jpg'

export const TRIP_PHOTOS = {
  japon: {
    img: japon,
    alt: 'Torii naranjos en Kioto',
    credit: 'Foto: David Emrich en Unsplash (licencia Unsplash)',
    creditUrl: 'https://unsplash.com/photos/torii-gates-in-kyoto-EJvGBYjrwEA',
  },
  colombia: {
    img: colombia,
    alt: 'Palmas de cera en el Valle del Cocora, Salento, Colombia',
    credit: 'Foto: Nicole Arango Lang en Unsplash (licencia Unsplash)',
    creditUrl: 'https://unsplash.com/photos/FYIPrgZqBBA',
  },
  italia: {
    img: italia,
    alt: 'Pizza napoletana en un horno de leña',
    credit: 'Foto: Fabrizio Pullara en Unsplash (licencia Unsplash)',
    creditUrl: 'https://unsplash.com/photos/pizza-baking-in-wood-fired-oven-vHRFraV4U00',
  },
}
