// Restricciones al pagar, como en la app de Rappi (RappiUI:ageConfirmationTitle, RappiCart:clMedicalPrescriptionLaw):
// - Edad: con un producto +18 (`ageRestricted`) se pregunta una vez "¿Eres mayor de edad?" y se recuerda en la sesión
//   del navegador. Sin documento ni fecha de nacimiento: es una demo.
// - Receta: con productos de Farmacia se avisa que pueden necesitar receta y se pide marcar "la tengo". No se sube nada.
//   La base no marca qué producto la exige: el aviso va con toda canasta de Farmacia.
const AGE_KEY = 'rappi-proto-age-ok'
let confirmedInMemory = false // sin almacenamiento (modo privado), vale para esta pestaña

export function ageConfirmed() {
  try {
    return sessionStorage.getItem(AGE_KEY) === '1' || confirmedInMemory
  } catch {
    return confirmedInMemory
  }
}

export function confirmAge() {
  confirmedInMemory = true
  try {
    sessionStorage.setItem(AGE_KEY, '1')
  } catch {
    // Sin almacenamiento: queda en memoria.
  }
}

/** Solo para los tests: olvida la confirmación de esta pestaña. */
export const forgetAge = () => {
  confirmedInMemory = false
}

/** Si alguna línea del carro es +18. */
export const hasAgeRestricted = (items) => items.some(({ product }) => product.ageRestricted)

/** Si la canasta (por tienda) es de Farmacia. */
export const needsPrescription = (basket) => basket.vertical === 'farmacia'
