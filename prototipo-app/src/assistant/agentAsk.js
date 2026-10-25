// Preguntarle al agente por un producto: lo que se le pide al buscador con el agente y el tipo con que viaja al arrastrarlo.

export const AGENT_DRAG_TYPE = 'application/x-agent-producto'

export const askAbout = (product) => `¿Con qué acompaño ${product.name}?`
