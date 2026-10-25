/**
 * Texto para comparar: sin tildes ni ñ (pañales = panales, como `tsv_unaccent` de la búsqueda de rappi-ia), en
 * minúsculas, sin emojis ni signos. Es también la clave de las búsquedas y preguntas grabadas en la muestra.
 */
export const normalize = (text) =>
  (text ?? '')
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()

/**
 * La clave de un seguimiento grabado (`npm run demo:snapshot`, conversation.js): el mensaje y el turno anterior, sin lo
 * ya mostrado.
 */
export const followKey = (previous, message) =>
  [
    normalize(message),
    normalize(previous?.query),
    previous?.vertical ?? '',
    previous?.occasion ?? '',
    previous?.price_max ?? '',
    previous?.people ?? '',
    previous?.order ?? '',
  ].join('|')
