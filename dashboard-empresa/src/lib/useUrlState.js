import { useCallback, useEffect, useState } from 'react'

// La vista, la fuente y la subpestaña viven en la URL (?vista=clientes&fuente=prototipo&seccion=pro) para compartir un
// enlace exacto. La primera subpestaña de cada vista no se escribe: así los enlaces de antes siguen abriendo lo mismo.
const SOURCE_PARAMS = { synthetic: 'simulados', prototype: 'prototipo' }

/** Un estado válido: una vista conocida (si no, la primera) y una subpestaña de esa vista (si no, su primera). */
function resolve(state, views) {
  const view = views.find((item) => item.id === state.view) ?? views[0]
  const section = view.tabs.some((tab) => tab.id === state.section) ? state.section : view.tabs[0].id
  return { view: view.id, source: state.source, section }
}

function readUrlState(search, views) {
  const params = new URLSearchParams(search)
  const source = params.get('fuente') === SOURCE_PARAMS.prototype ? 'prototype' : 'synthetic'
  return resolve({ view: params.get('vista'), source, section: params.get('seccion') }, views)
}

/** `views`: las vistas del panel, cada una con su `id` y sus `tabs` (la primera, la de por defecto). */
export function useUrlState(views) {
  const [state, setRawState] = useState(() => readUrlState(window.location.search, views))

  // Cambiar de vista sin decir la subpestaña lleva a la primera de esa vista.
  const setState = useCallback(
    (update) => setRawState((previous) => resolve(typeof update === 'function' ? update(previous) : update, views)),
    [views],
  )

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    params.set('vista', state.view)
    params.set('fuente', SOURCE_PARAMS[state.source])
    const first = views.find((item) => item.id === state.view).tabs[0].id
    if (state.section === first) params.delete('seccion')
    else params.set('seccion', state.section)
    window.history.replaceState(null, '', `?${params}${window.location.hash}`)
  }, [state, views])

  return [state, setState]
}
