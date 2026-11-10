import { AGENT_NAME } from './lib/agentName.js'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Header } from './components/shell/Header.jsx'
import { ProvenanceBanner } from './components/shell/ProvenanceBanner.jsx'
import { SectionNav } from './components/shell/SectionNav.jsx'
import { Tabs } from './components/shell/Tabs.jsx'
import { API_URL, refreshSource, retryConnection, SNAPSHOT_INFO } from './lib/api.js'
import { formatDate } from './lib/format.js'
import { useFallbacks, usePrototypeOffline } from './lib/useAnalytics.js'
import { useMediaQuery } from './lib/useMediaQuery.js'
import { useUrlState } from './lib/useUrlState.js'
import { CustomersView } from './views/customers/CustomersView.jsx'
import { ExperimentsView } from './views/experiments/ExperimentsView.jsx'
import { MochiView } from './views/mochi/MochiView.jsx'
import { OverviewView } from './views/overview/OverviewView.jsx'

// Cuatro vistas: tres alrededor de 4 preguntas (el porqué, en docs/decisiones.md), el Resumen para la gerencia y RappiAds
// y un detalle para cada público, y al final los experimentos del MVP: cómo leer cada comparación antes de decidir con
// ella.
// `sections`: los títulos de sección de cada vista (sus ids), para "En esta vista".
export const VIEWS = [
  {
    id: 'resumen',
    label: 'Resumen',
    View: OverviewView,
    sections: [
      { id: 'que-decidir', label: 'Qué decidir' },
      { id: 'como-va', label: 'Cómo va' },
    ],
  },
  {
    id: 'clientes',
    label: 'Retención y venta cruzada',
    short: 'Clientes',
    View: CustomersView,
    sections: [
      { id: 'venta-cruzada', label: 'Dónde está la venta cruzada' },
      { id: 'pro', label: 'Pro y sin Pro' },
      { id: 'perdiendo', label: 'A quién estamos perdiendo' },
    ],
  },
  {
    id: 'mochi',
    label: `${AGENT_NAME} y búsquedas`,
    short: AGENT_NAME,
    View: MochiView,
    sections: [
      { id: 'ofertas', label: `Lo que ofrece ${AGENT_NAME}` },
      { id: 'presencia', label: `¿${AGENT_NAME} molesta?` },
      { id: 'listas', label: 'Qué se ve y qué se toca' },
      { id: 'busquedas', label: 'Qué buscan y no encuentran' },
    ],
  },
  {
    id: 'experimentos',
    label: 'Experimentos',
    View: ExperimentsView,
    sections: [{ id: 'experimentos', label: 'Experimentos del MVP' }],
  },
]
const VIEW_IDS = VIEWS.map((view) => view.id)

// "Ver cómo funciona": solo en el panel en un solo HTML (el modo panel-html de `npm run panel:html`); se decide por el
// modo del armado y no por una variable de entorno, que podría colarse en un build normal.
const DemoTour = import.meta.env.MODE === 'panel-html' ? lazy(() => import('./demo/DemoTour.jsx')) : null

export default function App() {
  const [{ view, source }, setUrlState] = useUrlState(VIEW_IDS)
  const fallbacks = useFallbacks()
  const prototypeOffline = usePrototypeOffline()
  const [reloadKey, setReloadKey] = useState(0)
  const main = useRef(null)
  const top = useRef(null)
  const nav = useRef(null)
  const anchor = useRef(null)
  // Desde 1024 px: barra superior fija y navegación lateral; en angosto, la navegación es una tira fija arriba.
  const wide = useMediaQuery('(min-width: 1024px)')
  const { View, sections } = VIEWS.find((item) => item.id === view)

  // La altura de lo fijo arriba (la franja de procedencia puede ocupar dos líneas o sumar avisos), para el CSS.
  useEffect(() => {
    const element = top.current
    if (!element || typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(() =>
      document.documentElement.style.setProperty('--top-h', `${element.offsetHeight}px`),
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  /** Cambia de vista; con `section` (el id del título de una sección), llega a esa sección y le pasa el foco. */
  const selectView = (id, section) => {
    // En la misma vista el efecto de abajo no vuelve a correr: se lleva a la sección aquí mismo.
    if (section && id === view) {
      const target = document.getElementById(section)
      target?.scrollIntoView?.({ block: 'start' })
      target?.focus({ preventScroll: true })
      return
    }
    setUrlState((state) => ({ ...state, view: id }))
    if (section) {
      anchor.current = { id: section, focus: true }
      return
    }
    // Al cambiar de vista desde abajo, se vuelve al comienzo del contenido (bajo lo que queda fijo arriba).
    const fixed = wide ? top.current.offsetHeight : nav.current.offsetHeight
    const start = main.current.getBoundingClientRect().top + window.scrollY - fixed
    if (window.scrollY > start) window.scrollTo({ top: start })
  }

  // También tras recargar los datos: la demostración vuelve a pintar la vista y lleva a la sección que cambió. Lo que
  // está más arriba puede seguir cargando y empujar la sección hacia abajo: se vuelve a llevar arriba cuando termina
  // (hasta ~2 s; si la persona se mueve antes, no se la interrumpe).
  // El enlace de una decisión pasa el foco al título; la demostración solo desplaza (el foco sigue en su tarjeta).
  useEffect(() => {
    const pending = anchor.current
    anchor.current = null
    const target = pending && document.getElementById(pending.id)
    if (!target) return undefined
    target.scrollIntoView?.({ block: 'start' })
    if (pending.focus) target.focus({ preventScroll: true })
    let frames = 0
    let frame
    const settle = () => {
      if (pending.focus && document.activeElement !== target) return
      if (main.current?.querySelector('.state--loading') && frames < 120) {
        frames += 1
        frame = requestAnimationFrame(settle)
      } else if (frames > 0) target.scrollIntoView?.({ block: 'start' })
    }
    frame = requestAnimationFrame(settle)
    return () => cancelAnimationFrame(frame)
  }, [view, reloadKey])

  const retry = () => {
    retryConnection()
    setReloadKey((key) => key + 1)
  }

  // Vuelve a pedir la fuente elegida (lo nuevo del prototipo) sin recargar la página ni repetir la otra fuente.
  const refresh = () => {
    refreshSource(source)
    setReloadKey((key) => key + 1)
  }

  return (
    <div className="app">
      <div className="app-top" ref={top}>
        <Header
          source={source}
          reloadKey={reloadKey}
          fallbacks={fallbacks}
          prototypeOffline={prototypeOffline}
          onSourceChange={(next) => setUrlState((state) => ({ ...state, source: next }))}
          onRefresh={refresh}
        />
        <ProvenanceBanner source={source} fallbacks={fallbacks} prototypeOffline={prototypeOffline} onRetry={retry} />
      </div>
      <div className="app-body">
        <div className="sidenav" ref={nav}>
          <div className="sidenav-inner">
            <Tabs views={VIEWS} active={view} onSelect={selectView} orientation={wide ? 'vertical' : 'horizontal'} />
            <SectionNav sections={sections} onSelect={(section) => selectView(view, section)} />
          </div>
        </div>
        <div className="app-main">
          <main ref={main} id={`panel-${view}`} role="tabpanel" aria-labelledby={`tab-${view}`} className="app-content">
            <View key={`${view}-${source}-${reloadKey}`} source={source} onNavigate={selectView} />
          </main>
          <footer className="site-footer">
            <div className="site-footer-inner">
              {SNAPSHOT_INFO ? (
                // El archivo suelto no lleva la presentación ni habla con una API.
                <p>
                  Definiciones de cada métrica: <span className="mono">docs/diseno-ia.md §5</span>. Datos grabados el{' '}
                  {formatDate(SNAPSHOT_INFO.fecha)} desde la API de rappi-ia sobre una copia de la base (
                  {SNAPSHOT_INFO.base}).
                </p>
              ) : (
                <p>
                  Definiciones de cada métrica: <span className="mono">docs/diseno-ia.md §5</span>. Datos de la API de
                  rappi-ia en <span className="mono">{API_URL}</span>.{' '}
                  <a href={`${import.meta.env.BASE_URL}presentacion.html`}>Presentación de la propuesta</a>.
                </p>
              )}
              <p>Prototipo dLab con Rappi · demo, no es un producto oficial de Rappi.</p>
              <p>
                Personas con id seudónimo; las listas por persona nunca muestran conceptos sensibles. Ninguna palanca se
                escala sin un grupo de control (A/B con holdout).
              </p>
            </div>
          </footer>
        </div>
      </div>
      {DemoTour && (
        <Suspense fallback={null}>
          <DemoTour
            onShow={(target) => {
              // El recorrido es del prototipo: lleva a esa fuente y a la sección que cambia; al cerrar, solo repinta.
              if (target) {
                anchor.current = { id: target.section, focus: false }
                setUrlState({ view: target.view, source: 'prototype' })
              }
              setReloadKey((key) => key + 1)
            }}
          />
        </Suspense>
      )}
    </div>
  )
}
