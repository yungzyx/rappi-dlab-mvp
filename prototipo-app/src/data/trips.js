// La foto de cada destino de la idea para RappiTravel (`viaje.id` de la API, offers/destinos.toml) y su crédito
// (licencia Unsplash). Son las de la demo del Comité 2 (rama demo/prototipo-sushi). Un destino sin foto aquí se
// muestra sin ella.

import colombia from '../assets/viajes/colombia.jpg'
import italia from '../assets/viajes/italia.jpg'
import japon from '../assets/viajes/japon.jpg'

export const TRIP_PHOTOS = {
  japon: {
    img: japon,
    credit: 'Foto: David Emrich / Unsplash',
    creditUrl: 'https://unsplash.com/photos/torii-gates-in-kyoto-EJvGBYjrwEA',
  },
  colombia: {
    img: colombia,
    credit: 'Foto: Nicole Arango Lang / Unsplash',
    creditUrl: 'https://unsplash.com/photos/FYIPrgZqBBA',
  },
  italia: {
    img: italia,
    credit: 'Foto: Fabrizio Pullara / Unsplash',
    creditUrl: 'https://unsplash.com/photos/pizza-baking-in-wood-fired-oven-vHRFraV4U00',
  },
}
