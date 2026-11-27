// Copia de las reglas de rappi-ia/src/rappi_ia/safety.py (sin Claude: la demo sin conexión no llama a nadie). Lo que
// se escribe en el buscador o a Mochi, antes de buscar: "crisis" (quitarse la vida: la línea *4141, sin productos),
// "bloqueado" (drogas ilegales, manipular a Mochi, dañar a otro: nada) u "ok".
import { normalize } from './text'

export const CRISIS_TEXT =
  'Si estás pasando por un momento difícil, no estás solo ni sola 🧡. Llama gratis al *4141, la Línea de ' +
  'Prevención del Suicidio del Minsal (todos los días, a toda hora). Si es una emergencia, llama al SAMU (131).'
export const BLOCKED_TEXT = 'Eso no lo busco 🙅. Toca una idea o busca otra cosa.'

// safety.py: CRISIS_WORDS; offers/guards.py: ILLEGAL_DRUG_WORDS (palabra entera, sin tildes).
const CRISIS_WORDS = [
  'matarme',
  'suicidarme',
  'suicidio',
  'suicida',
  'quiero morir',
  'quiero morirme',
  'me quiero morir',
  'no quiero vivir',
  'quitarme la vida',
  'hacerme dano',
  'cortarme las venas',
  'autolesion',
  'autolesionarme',
]
const DRUG_WORDS = [
  'droga',
  'drogas',
  'marihuana',
  'marijuana',
  'cannabis',
  'cocaina',
  'pasta base',
  'extasis',
  'lsd',
  'metanfetamina',
  'heroina',
  'ketamina',
  'tusi',
  'hachis',
  'porro',
  'porros',
  'weed',
]
// safety.py: _INJECTION y _VIOLENCE.
const INJECTION =
  /\b(?:ignore|ignora|ignorar|olvida|olvidate de)\b.{0,30}\b(?:instructions?|instrucciones|reglas|prompt)\b|\bsystem prompt\b|\bprompt del sistema\b|\bjailbreak\b|\bmodo desarrollador\b|\bdeveloper mode\b/
const VIOLENCE = /\b(?:matar|asesinar|envenenar)\s+(?:a|al)\b|\bcomo\s+(?:matar|asesinar|envenenar)\b/

const says = (said, words) => words.some((word) => ` ${said} `.includes(` ${word} `))

/** 'ok', 'crisis' o 'bloqueado', como `rules_verdict` de safety.py. */
export function judge(text) {
  const said = normalize(text)
  if (says(said, CRISIS_WORDS)) return 'crisis'
  if (says(said, DRUG_WORDS) || INJECTION.test(said) || VIOLENCE.test(said)) return 'bloqueado'
  return 'ok'
}

/** La respuesta de /search a lo que el juez detiene (app.py: _stopped). */
export function stoppedSearch(q, vertical, kind) {
  const empty = { unmet: true, unmet_reason: kind, corrected_query: null, preferences_notice: null, request_id: null }
  if (vertical) return { vertical, products: [], ...empty }
  return { query: q, groups: [], ...empty, places: { stores: [], restaurants: [] }, whim_allowed: false }
}

/** La de /agent/ask (rappi_agent.py: _reply con el veredicto): el texto, sin productos ni ideas debajo. */
export function stoppedAnswer(kind, query) {
  return {
    text: kind === 'crisis' ? CRISIS_TEXT : BLOCKED_TEXT,
    products: [],
    vertical: null,
    prototype_vertical: null,
    intent: {
      kind: 'ayuda',
      confidence: 1,
      vertical: null,
      concepts: [],
      occasion: null,
      price_max: null,
      query,
      symptom: true,
    },
    reason: null,
    suggestion: null,
    actions: [],
    tags: [],
    stores: [],
    unmet: false,
    unmet_reason: null,
    age_notice: false,
    conversation: null,
  }
}
