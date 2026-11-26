// Copia de rappi-ia/src/rappi_ia/events/store.py (redact): la demo sin conexión guarda las consultas con los datos
// personales tapados, como la API. Sus casos de prueba son los del backend (redact.test.js lee test_privacy.py).
// Diferencia: `\w` de JavaScript es solo ASCII (en Python, Unicode); los nombres ya traen sus tildes a mano.

const DASH = '[-‐‑‒–—]'
const EMAIL = /[\w.+-]+\s?@\s?[\w-]+(?:\.[\w-]+)+/g
const RUT = new RegExp(String.raw`(?<!\d)(\d{1,2})[.\s]?(\d{3})[.\s]?(\d{3})\s*${DASH}\s*([\dkK])(?!\w)`, 'g')
const CARD = /(?<!\d)(?:\d[\s-]?){12,18}\d(?!\d)/g
// Teléfono chileno: celular 9 + 8 dígitos o fijo (código de área + 7-8 dígitos), con +56 opcional.
const PHONE = /(?<![\d$])(?:\+?\s?56[\s.-]*)?(?:9[\s.-]*\d{4}[\s.-]*\d{4}|\d{1,2}[\s.-]*\d{3,4}[\s.-]*\d{4})(?!\d)/g
const STREET_TYPES = String.raw`(?:calle|av(?:da)?\.?|avenida|pasaje|psje\.?|pje\.?|camino|ruta)`
const TAIL = String.raw`(?:\s*(?:depto|dpto|departamento|of|oficina|casa)\.?\s*\w+)?`
const ADDRESS = new RegExp(
  String.raw`\b${STREET_TYPES}\s+(?<name>[^\d,;\n]{2,40}?)\s*(?:n[°º]\.?\s*|#\s*)?\d{1,5}\b${TAIL}`,
  'gi',
)
// Sin tipo de calle: solo con una frase que anuncia la dirección ("vivo en Los Leones 123").
const ADDRESS_CONTEXT = new RegExp(
  String.raw`(?<intro>vivo en|mi direcci[oó]n(?: es)?|despacho a|entregar en|env[ií]a(?:lo)? a|manda(?:lo)? a|estoy en` +
    String.raw`|queda en)\s+[^\d,;\n]{2,40}?\s*(?:n[°º]\.?\s*|#\s*)?\d{1,5}\b${TAIL}`,
  'gi',
)
// Un nombre propio tras "me llamo" o "mi nombre es" (con mayúscula: "me llamo la atención" no es un nombre).
const NAME = /(?<intro>me llamo|mi nombre es)\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+){0,2}/g
const NOT_A_STREET = new Set('para de la el los las con sin y a en por que un una'.split(' '))

const rutValid = (body, check) => {
  let total = 0
  let factor = 2
  for (const digit of [...body].reverse()) {
    total += Number(digit) * factor
    factor = factor === 7 ? 2 : factor + 1
  }
  const expected = 11 - (total % 11)
  return check.toUpperCase() === ({ 10: 'K', 11: '0' }[expected] ?? String(expected))
}

const luhn = (number) => {
  const digits = number.replace(/\D/g, '').split('').map(Number)
  const sum = [...digits].reverse().reduce((acc, d, i) => acc + (i % 2 === 0 ? d : d * 2 > 9 ? d * 2 - 9 : d * 2), 0)
  return digits.length >= 13 && digits.length <= 19 && sum % 10 === 0
}

// "calle para 4" no es una dirección: el nombre de la calle debe tener alguna palabra que no sea de relleno.
const street = (match, ...rest) => {
  const { name } = rest.at(-1)
  return name
    .toLowerCase()
    .split(/\s+/)
    .some((word) => word && !NOT_A_STREET.has(word))
    ? '[dirección]'
    : match
}

/** Quita correo, RUT (válido), tarjetas (Luhn), teléfonos chilenos, nombres y direcciones antes de guardar una consulta. */
export function redact(text) {
  if (text == null) return text
  return text
    .replace(EMAIL, '[correo]')
    .replace(RUT, (match, a, b, c, check) => (rutValid(a + b + c, check) ? '[rut]' : match))
    .replace(CARD, (match) => (luhn(match) ? '[tarjeta]' : match))
    .replace(PHONE, '[teléfono]')
    .replace(ADDRESS, street)
    .replace(NAME, (...args) => `${args.at(-1).intro} [nombre]`)
    .replace(ADDRESS_CONTEXT, (...args) => `${args.at(-1).intro} [dirección]`)
}
