import { AGENT_NAME } from './lib/agentName.js'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Header } from './components/shell/Header.jsx'
import { PageHeader } from './components/shell/PageHeader.jsx'
import { ConnectionNotices, ProvenanceBanner } from './components/shell/ProvenanceBanner.jsx'
import { SourceSwitch } from './components/shell/SourceSwitch.jsx'
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
// `tabs`: las subpestañas de cada vista (?seccion=, la primera por defecto), cada una con los ids de los títulos de sus
// secciones. Una vista con una sola no muestra subpestañas.
export const VIEWS = [
  {
    id: 'resumen',
    label: 'Resumen',
    icon: 'dashboard',
    View: OverviewView,
    tabs: [{ id: 'resumen', label: 'Resumen', sections: ['como-va', 'que-decidir'] }],
  },
  {
    id: 'clientes',
    label: 'Retención y venta cruzada',
    short: 'Clientes',
    icon: 'users',
    View: CustomersView,
    tabs: [
      { id: 'venta-cruzada', label: 'Venta cruzada', sections: ['venta-cruzada'] },
      { id: 'pro', label: 'Pro y sin Pro', sections: ['pro'] },
      { id: 'perdiendo', label: 'En riesgo', sections: ['perdiendo'] },
    ],
  },
  {
    id: 'mochi',
    label: `${AGENT_NAME} y búsquedas`,
    short: AGENT_NAME,
    icon: 'search',
    View: MochiView,
    tabs: [
      { id: 'ofertas', label: 'Ofertas', sections: ['ofertas', 'presencia'] },
      { id: 'listas', label: 'Listas y embudo', sections: ['listas'] },
      { id: 'busquedas', label: 'Búsquedas', sections: ['busquedas'] },
    ],
  },
  {
    id: 'experimentos',
    label: 'Experimentos',
    icon: 'columns',
    View: ExperimentsView,
    tabs: [
      { id: 'experimentos', label: 'Experimentos', sections: ['hipotesis', 'valor-meta', 'adopcion', 'experimentos'] },
    ],
  },
]

/** La subpestaña de la vista `viewId` que tiene la sección `sectionId`; si ninguna la tiene, la primera. */
export const tabOf = (viewId, sectionId) => {
  const { tabs } = VIEWS.find((item) => item.id === viewId)
  return (tabs.find((tab) => tab.sections.includes(sectionId)) ?? tabs[0]).id
}

// "Ver cómo funciona": solo en el panel en un solo HTML (el modo panel-html de `npm run panel:html`); se decide por el
// modo del armado y no por una variable de entorno, que podría colarse en un build normal.
const DemoTour = import.meta.env.MODE === 'panel-html' ? lazy(() => import('./demo/DemoTour.jsx')) : null

export default function App() {
  const [{ view, source, section }, setUrlState] = useUrlState(VIEWS)
  const fallbacks = useFallbacks()
  const prototypeOffline = usePrototypeOffline()
  const [reloadKey, setReloadKey] = useState(0)
  const main = useRef(null)
  const top = useRef(null)
  const nav = useRef(null)
  const anchor = useRef(null)
  // Desde 1200 px: barra lateral con la marca, la fuente y las vistas, y la franja de procedencia fija arriba del
  // contenido; más angosto, las vistas son una tira fija arriba y la franja queda fija bajo ella.
  const wide = useMediaQuery('(min-width: 1200px)')
  const { View, label, tabs } = VIEWS.find((item) => item.id === view)

  // La altura de la franja de procedencia (en angosto ocupa dos líneas), para el CSS.
  useEffect(() => {
    const element = top.current
    if (!element || typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(() =>
      document.documentElement.style.setProperty('--top-h', `${element.offsetHeight}px`),
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  /** Vuelve al comienzo del contenido (bajo lo que queda fijo arriba) si se está más abajo. */
  const toContentStart = () => {
    const fixed = wide ? top.current.offsetHeight : nav.current.offsetHeight + top.current.offsetHeight
    const start = main.current.getBoundingClientRect().top + window.scrollY - fixed
    if (window.scrollY > start) window.scrollTo({ top: start })
  }

  /**
   * Cambia de vista; con `section` (el id del título de una sección), abre su subpestaña, llega a esa sección y le pasa
   * el foco. Sin `section`, la primera subpestaña de la vista.
   */
  const selectView = (id, target) => {
    if (target) {
      const tab = tabOf(id, target)
      // Ya a la vista: el efecto de abajo no vuelve a correr; se lleva a la sección aquí mismo.
      if (id === view && tab === section) {
        const heading = document.getElementById(target)
        heading?.scrollIntoView?.({ block: 'start' })
        heading?.focus({ preventScroll: true })
        return
      }
      anchor.current = { id: target, focus: true }
      setUrlState((state) => ({ ...state, view: id, section: tab }))
      return
    }
    setUrlState((state) => ({ ...state, view: id, section: null }))
    toContentStart()
  }

  /** Cambia de subpestaña dentro de la vista; el foco sigue en su botón. */
  const selectTab = (tab) => {
    setUrlState((state) => ({ ...state, section: tab }))
    toContentStart()
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
  }, [view, section, reloadKey])

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
      <div className="sidebar">
        <Header />
        <div className="app-source">
          <SourceSwitch value={source} onChange={(next) => setUrlState((state) => ({ ...state, source: next }))} />
        </div>
        <div className="sidenav" ref={nav}>
          <Tabs views={VIEWS} active={view} onSelect={selectView} orientation={wide ? 'vertical' : 'horizontal'} />
        </div>
      </div>
      <div className="app-main">
        <div className="app-top" ref={top}>
          <ProvenanceBanner source={source} />
        </div>
        <ConnectionNotices source={source} fallbacks={fallbacks} prototypeOffline={prototypeOffline} onRetry={retry} />
        <main ref={main} id={`panel-${view}`} role="tabpanel" aria-labelledby={`tab-${view}`} className="app-content">
          <PageHeader
            title={label}
            source={source}
            reloadKey={reloadKey}
            fallbacks={fallbacks}
            prototypeOffline={prototypeOffline}
            onRefresh={refresh}
            tabs={tabs}
            tab={section}
            onTab={selectTab}
          />
          <View key={`${view}-${source}-${reloadKey}`} source={source} tab={section} onNavigate={selectView} />
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
      {DemoTour && (
        <Suspense fallback={null}>
          <DemoTour
            onShow={(target) => {
              // El recorrido es del prototipo: lleva a esa fuente y a la sección que cambia; al cerrar, solo repinta.
              if (target) {
                anchor.current = { id: target.section, focus: false }
                setUrlState({ view: target.view, source: 'prototype', section: tabOf(target.view, target.section) })
              }
              setReloadKey((key) => key + 1)
            }}
          />
        </Suspense>
      )}
    </div>
  )
}
