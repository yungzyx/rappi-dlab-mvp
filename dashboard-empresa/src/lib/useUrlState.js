import { useEffect, useState } from 'react'

// La vista y la fuente viven en la URL (?vista=clientes&fuente=prototipo) para compartir un enlace exacto.
const SOURCE_PARAMS = { synthetic: 'simulados', prototype: 'prototipo' }

function readUrlState(search, viewIds) {
  const params = new URLSearchParams(search)
  const requested = params.get('vista')
  const view = viewIds.includes(requested) ? requested : viewIds[0]
  const source = params.get('fuente') === SOURCE_PARAMS.prototype ? 'prototype' : 'synthetic'
  return { view, source }
}

export function useUrlState(viewIds) {
  const [state, setState] = useState(() => readUrlState(window.location.search, viewIds))

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    params.set('vista', state.view)
    params.set('fuente', SOURCE_PARAMS[state.source])
    window.history.replaceState(null, '', `?${params}${window.location.hash}`)
  }, [state])

  return [state, setState]
}
