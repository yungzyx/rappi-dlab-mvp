import { useEffect, useRef, useState } from 'react'
import { EMOTIONS, useMochiMood } from '../../state/mochiMood'
import './mascot.css'

// Cuánto se inclina el agente hacia el mouse, como si lo mirara.
const LOOK_MAX_DEG = 5

// Los ánimos que no son el reposo: mientras se ven, pasar el mouse no le cambia la pose (sería otra cosa que decir).
const FEELINGS = new Set(['thinking', 'sleepy', ...Object.keys(EMOTIONS)])
const SPARKS = 8

/**
 * Los adornos de cada ánimo, hechos con CSS (mascot.css): tres puntos que laten al pensar, chispas al celebrar, una gota
 * al preocuparse, un "!" al sorprenderse y "z z" al dormir. Sin texto: los dibuja el CSS.
 */
function Adornment({ mood }) {
  if (mood === 'thinking')
    return (
      <span className="mascot-fx mascot-fx--dots">
        <i />
        <i />
        <i />
      </span>
    )
  if (mood === 'celebrate')
    return (
      <span className="mascot-fx mascot-fx--sparks">
        {Array.from({ length: SPARKS }, (_, i) => (
          <i key={i} style={{ '--spark-turn': `${(360 / SPARKS) * i + 22}deg` }} />
        ))}
      </span>
    )
  if (mood === 'worried')
    return (
      <span className="mascot-fx mascot-fx--drop">
        <i />
      </span>
    )
  if (mood === 'surprised')
    return (
      <span className="mascot-fx mascot-fx--bang">
        <i />
      </span>
    )
  if (mood === 'sleepy')
    return (
      <span className="mascot-fx mascot-fx--zz">
        <i />
        <i />
      </span>
    )
  return null
}

/**
 * La mascota del asistente: la mochila Rappi con bigote. Sus 4 poses están en una sola imagen
 * (frontal, feliz, tímido, saltando) y el ánimo elige cuál se ve y cómo se mueve.
 * mood: 'idle' | 'wave' | 'listen' | 'thinking' | 'talk' | 'jump' (salta una vez y queda feliz) | 'sleepy' | 'worried'
 * o una de las emociones de state/mochiMood.js. `badge` lo pone en un círculo, como un avatar.
 * `live`: la mascota que acompaña a la persona (la de la Home, la flotante, la del buscador con Mochi) también sigue el
 * ánimo de state/mochiMood.js: piensa mientras algo carga (manda sobre todo) y, salvo dormida (`mood="sleepy"`), muestra
 * la emoción breve que esté corriendo.
 */
export default function Mascot({ size = 56, mood = 'idle', badge = false, live = false, className = '' }) {
  const [booping, setBooping] = useState(false)
  const ref = useRef(null)
  const feeling = useMochiMood()

  // Si el salto se corta (p. ej. el agente se oculta a mitad), vuelve a su pose en vez de quedar pegado en el salto.
  useEffect(() => {
    const el = ref.current
    const cancel = (event) => event.animationName === 'mascot-boop' && setBooping(false)
    el.addEventListener('animationcancel', cancel)
    return () => el.removeEventListener('animationcancel', cancel)
  }, [])

  let shown = mood
  // Cada emoción vuelve a montar el cuerpo y sus adornos (su llave): la misma emoción dos veces corre dos veces.
  let take = 'base'
  if (live && feeling.thinking) shown = 'thinking'
  else if (live && feeling.emotion && mood !== 'sleepy') {
    shown = feeling.emotion
    take = `emotion-${feeling.id}`
  }

  const look = (event) => {
    if (event.pointerType !== 'mouse') return
    const box = event.currentTarget.getBoundingClientRect()
    const deg = Math.max(-LOOK_MAX_DEG, Math.min(LOOK_MAX_DEG, (event.clientX - box.left - box.width / 2) / 8))
    event.currentTarget.style.setProperty('--mascot-look', `${deg}deg`)
  }

  const classes = [
    'mascot',
    `mascot--${shown}`,
    FEELINGS.has(shown) && 'is-feeling',
    badge && 'mascot--badge',
    booping && 'mascot--boop',
    className,
  ]

  return (
    <span
      ref={ref}
      className={classes.filter(Boolean).join(' ')}
      style={{ width: size, height: size * (badge ? 1 : 1.2), '--mascot-size': `${size}px` }}
      aria-hidden="true"
      data-mood={shown}
      onPointerMove={look}
      onPointerLeave={(event) => event.currentTarget.style.setProperty('--mascot-look', '0deg')}
      onPointerDown={() => setBooping(true)}
      onAnimationEnd={(event) => event.animationName === 'mascot-boop' && setBooping(false)}
    >
      <span className="mascot-shadow" />
      <span key={take} className="mascot-body">
        <span className="mascot-sprite" />
      </span>
      <Adornment key={`fx-${take}`} mood={shown} />
    </span>
  )
}
