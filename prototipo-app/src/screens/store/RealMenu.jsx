import { useEffect, useRef, useState } from 'react'
import ProductRow from '../../components/ProductRow'

// Espacio que ocupan las pestañas fijas: una sección cuenta como "activa" al pasar bajo ellas.
const TABS_OFFSET = 112

/**
 * Menú de un restaurante (`menu(id)` de la API): pestañas de sección fijas arriba que siguen el scroll
 * y llevan a cada sección al tocarlas. `scrollRef` es el contenedor con scroll de la página de tienda.
 */
export default function RealMenu({ sections, scrollRef }) {
  const [active, setActive] = useState(0)
  const sectionRefs = useRef([])
  const tabRefs = useRef([])

  const topOf = (index) => {
    const container = scrollRef.current
    const section = sectionRefs.current[index]
    return section.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop
  }

  useEffect(() => {
    const container = scrollRef.current
    if (!container) return undefined
    const onScroll = () => {
      const y = container.scrollTop + TABS_OFFSET
      let current = 0
      sectionRefs.current.forEach((_, i) => {
        if (topOf(i) <= y) current = i
      })
      setActive(current)
    }
    container.addEventListener('scroll', onScroll, { passive: true })
    return () => container.removeEventListener('scroll', onScroll)
    // topOf solo lee refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scrollRef])

  // La pestaña activa se mantiene visible en la fila de pestañas.
  useEffect(() => {
    tabRefs.current[active]?.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' })
  }, [active])

  const goTo = (index) => scrollRef.current.scrollTo({ top: topOf(index) - TABS_OFFSET + 8, behavior: 'smooth' })

  return (
    <>
      <nav className="menu-tabs" aria-label="Secciones del menú">
        {sections.map((section, i) => (
          <button
            key={`${i}-${section.name}`}
            ref={(el) => {
              tabRefs.current[i] = el
            }}
            type="button"
            className={i === active ? 'menu-tab is-active' : 'menu-tab'}
            aria-current={i === active ? 'true' : undefined}
            onClick={() => goTo(i)}
          >
            {section.name}
          </button>
        ))}
      </nav>
      {sections.map((section, i) => (
        <section
          key={`${i}-${section.name}`}
          ref={(el) => {
            sectionRefs.current[i] = el
          }}
          className="menu-section"
        >
          <h2>{section.name}</h2>
          <ul className="store-products">
            {section.items.map((item) => (
              <ProductRow key={item.id} product={item} showDescription />
            ))}
          </ul>
        </section>
      ))}
      <p className="menu-source">Menú y precios reales de Rappi Chile (scraper). Las fotos se cargan desde Rappi.</p>
    </>
  )
}
