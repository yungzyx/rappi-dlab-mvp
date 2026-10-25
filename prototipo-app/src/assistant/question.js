// Si lo escrito en el buscador parece una pregunta para Mochi y no el nombre de un producto: entonces Enter le pregunta
// a Mochi (y su fila va resaltada); si no, Enter busca como siempre. Tocar «Pregúntale a Mochi» pregunta siempre.

const strip = (text) =>
  text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^\w$\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()

// Cómo empieza una pregunta o un pedido abierto («algo dulce», «tengo hambre», «qué llevo para…»). «como» solo como
// pregunta («cómo preparo…»): «como agua para chocolate» es un libro.
const LEADS =
  /^(?:que|cual|cuales|como (?:se|hago|preparo|puedo|funciona)|cuanto|cuanta|cuantos|cuantas|donde|con que|algo|alguna|tengo|me|se me|recomiendame|sugiereme|sorprendeme|ayudame|hola|dame algo|cosas para|ideas para|(?:quiero|necesito|busco|hay) (?:algo|cosas|ideas))\b/
// Una cantidad de personas o un presupuesto («asado para 6», «somos 10», «con 8 mil»). Un nombre de producto largo
// («leche descremada sin lactosa colun») sigue siendo una búsqueda: Enter busca y la fila de arriba pregunta.
const PEOPLE = /\b(?:somos|personas?)\b|\bpara (?:\d{1,2}|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)$/
const BUDGET = /\$|\d\s*(?:lucas|mil)\b/

export function looksLikeQuestion(text) {
  const raw = text.trim()
  if (!raw) return false
  if (raw.startsWith('¿') || raw.endsWith('?')) return true
  const plain = strip(raw)
  return LEADS.test(plain) || PEOPLE.test(plain) || BUDGET.test(plain)
}
