import { useState } from 'react'
import { placeList } from '../../api/attribution'
import { restaurants as loadRestaurants } from '../../api/catalog'
import { useApi } from '../../api/useApi'
import BackButton from '../../components/BackButton'
import Carousel, { Dots } from '../../components/Carousel'
import HScroll from '../../components/HScroll'
import OfflineNotice from '../../components/OfflineNotice'
import Sheet from '../../components/Sheet'
import { useToast } from '../../components/Toast'
import { HOURS_SOURCE_NOTE, isClosed } from '../../components/storeHours'
import {
  BadgePercentIcon,
  BoltIcon,
  ChevronDown,
  SearchIcon,
  SlidersIcon,
  StarIcon,
  TrophyIcon,
} from '../../components/Icons'
import { useOpenSearch } from '../../hooks/useOpenSearch'
import { useAddress } from '../../state/AddressContext'
import { RestaurantCard } from '../home/StoreCards'
import { BANNERS, CATEGORIES, DEFAULT_SORT, FILTERS, SORTS, TOP_RULE } from './data'
import './restaurants.css'

const FILTER_ICONS = {
  trophy: () => <TrophyIcon size={17} />,
  bolt: () => <BoltIcon size={17} />,
  star: (active) => <StarIcon size={17} filled={active} />,
  percent: () => <BadgePercentIcon size={17} />,
}

/** Los parámetros de la API de los filtros encendidos (`FILTERS[].query`). */
const filterQuery = (active) =>
  FILTERS.filter((filter) => active.has(filter.id)).reduce((query, filter) => ({ ...query, ...filter.query }), {})

export default function RestaurantsScreen({ back, push }) {
  const toast = useToast()
  const address = useAddress()
  const openSearch = useOpenSearch(push)
  const [activeFilters, setActiveFilters] = useState(() => new Set())
  const [bannerIndex, setBannerIndex] = useState(0)
  const [cuisine, setCuisine] = useState(null) // la cocina que filtra la lista, o ninguna
  const [sort, setSort] = useState(DEFAULT_SORT)
  const [sorting, setSorting] = useState(false) // la hoja de "Ordenar"
  const filters = [...activeFilters].sort().join(',')
  const list = useApi(
    () => loadRestaurants({ sort, cuisine, ...filterQuery(activeFilters) }),
    [cuisine, sort, filters], // `filters` resume el Set (que cambia de identidad en cada toque)
  )
  // Cada restaurante con su lugar en la lista: abrirlo dice de qué lista y posición salió.
  const shown = list.data ? placeList(list.data, { surface: 'restaurants', origin: 'lista' }) : null
  const anyClosed = shown?.some((restaurant) => isClosed(restaurant.hours))
  const sortTitle = SORTS.find((option) => option.id === sort)?.title

  const toggleFilter = (id) =>
    setActiveFilters((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  return (
    <div className="screen restaurants">
      <header className="rest-header">
        <BackButton className="round-button" onClick={back} />
        <button type="button" className="rest-address tap" onClick={address.openSheet}>
          {address.selected.line}
          <ChevronDown size={17} />
        </button>
      </header>

      <div className="rest-search-wrap">
        <button type="button" className="search-bar tap" onClick={() => openSearch('restaurants')}>
          <SearchIcon size={21} />
          <span className="search-hint">Busca platos o restaurantes</span>
        </button>
      </div>

      <HScroll className="rest-filters">
        <button
          type="button"
          className="filter-chip filter-chip--icon tap"
          aria-label="Filtros"
          onClick={() => toast()}
        >
          <SlidersIcon size={19} />
        </button>
        {FILTERS.map((filter) => {
          const isActive = activeFilters.has(filter.id)
          const onClick = filter.kind === 'toggle' ? () => toggleFilter(filter.id) : () => setSorting(true)
          return (
            <button
              key={filter.id}
              type="button"
              className={isActive ? 'filter-chip is-active tap' : 'filter-chip tap'}
              aria-pressed={filter.kind === 'toggle' ? isActive : undefined}
              onClick={onClick}
            >
              {filter.icon && FILTER_ICONS[filter.icon](isActive)}
              {filter.label}
              {filter.kind === 'menu' && <ChevronDown size={15} />}
            </button>
          )
        })}
      </HScroll>

      <div className="rest-categories">
        {CATEGORIES.map((cat) => {
          // Una cocina filtra la lista (tocarla otra vez la quita); las demás abren el buscador.
          const isActive = cat.cuisine === cuisine
          const onClick = cat.cuisine
            ? () => setCuisine(isActive ? null : cat.cuisine)
            : () => push('search', { query: cat.query, vertical: 'restaurants' })
          return (
            <button
              key={cat.id}
              type="button"
              className={isActive ? 'rest-category is-active tap' : 'rest-category tap'}
              aria-pressed={cat.cuisine ? isActive : undefined}
              onClick={onClick}
            >
              <span className={cat.partial ? 'rest-category-img is-partial' : 'rest-category-img'}>
                <img src={cat.img} alt="" loading="lazy" />
              </span>
              <span className="rest-category-label">{cat.label}</span>
            </button>
          )
        })}
      </div>

      <Carousel className="rest-banners" autoplayMs={4500} onIndexChange={setBannerIndex}>
        {BANNERS.map((banner) => (
          <button key={banner.id} type="button" className="rest-banner" onClick={() => toast()}>
            <span className="rest-banner-text">
              <strong>{banner.title}</strong>
              <span>{banner.place}</span>
            </span>
            <img className="rest-banner-photo" src={banner.img} alt="" draggable="false" loading="lazy" />
          </button>
        ))}
      </Carousel>
      <Dots count={BANNERS.length} active={bannerIndex} className="rest-banner-dots" />

      <h2 className="section-title rest-title">{cuisine ?? sortTitle}</h2>
      <p className="rest-real-note">Menús y precios reales de Rappi Chile</p>
      {activeFilters.has('top') && <p className="rest-real-note">{TOP_RULE}</p>}
      {anyClosed && <p className="rest-real-note">Los cerrados van al final. {HOURS_SOURCE_NOTE.horario}</p>}
      {list.error && <OfflineNotice onRetry={list.retry} />}
      {!list.data && !list.error && <div className="rest-skeleton" aria-hidden="true" />}
      {list.data?.length === 0 && (
        <p className="rest-empty">
          {activeFilters.size > 0
            ? 'Ningún restaurante del catálogo calza con estos filtros.'
            : cuisine
              ? 'Todavía no hay restaurantes de esta cocina en el catálogo.'
              : 'Todavía no hay restaurantes en el catálogo.'}
        </p>
      )}
      {shown?.length > 0 && (
        <div className="rest-list">
          {shown.map((restaurant) => (
            // Abre su menú: el id dice cuál sucursal es (dos pueden llamarse igual).
            <RestaurantCard
              key={restaurant.id}
              store={restaurant}
              onClick={() => push('store', { store: restaurant })}
              impression
            />
          ))}
        </div>
      )}

      <Sheet open={sorting} onClose={() => setSorting(false)} title="Ordenar por">
        <ul className="rest-sorts">
          {SORTS.map((option) => (
            <li key={option.id}>
              <button
                type="button"
                className={option.id === sort ? 'rest-sort is-active tap' : 'rest-sort tap'}
                aria-pressed={option.id === sort}
                onClick={() => {
                  setSort(option.id)
                  setSorting(false)
                }}
              >
                <strong>{option.label}</strong>
                <small>{option.hint}</small>
              </button>
            </li>
          ))}
        </ul>
      </Sheet>
    </div>
  )
}
