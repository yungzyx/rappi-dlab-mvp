// La foto de cada destino de la idea para RappiTravel (`viaje.id` de la API, offers/destinos.toml) y su crédito
// (licencia Unsplash). Japón, Colombia e Italia son las de la primera demo de los perfiles de gusto; México, del
// 14-11-2026, también de Unsplash. Un destino sin foto aquí se muestra sin ella.

import colombia from '../assets/viajes/colombia.jpg'
import italia from '../assets/viajes/italia.jpg'
import japon from '../assets/viajes/japon.jpg'
import mexico from '../assets/viajes/mexico.jpg'

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
  mexico: {
    img: mexico,
    credit: 'Foto: Alma Agencia D / Unsplash',
    creditUrl: 'https://unsplash.com/photos/two-tacos-on-a-plate-with-a-lime-wedge-n5jDzmKMT8w',
  },
}
