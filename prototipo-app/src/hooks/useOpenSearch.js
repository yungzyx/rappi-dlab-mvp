import { useAssistant } from '../state/AssistantContext'
import { useDemo } from '../state/DemoContext'

/**
 * Abre el buscador que corresponde al modo de demo: en el prototipo final, el del agente; en «Rappi hoy», el plano.
 * `vertical`: la de la pantalla desde la que se abre el buscador plano (el panel del agente toma la de la pantalla actual).
 * `query`: texto con el que arranca el buscador (una categoría de la vertical).
 */
export function useOpenSearch(push) {
  const assistant = useAssistant()
  const demo = useDemo()
  return (vertical, query) => {
    if (demo.isFinal) assistant.open(query ? { search: query } : {})
    else push('search', { ...(query ? { query } : {}), ...(vertical ? { vertical } : {}) })
  }
}
