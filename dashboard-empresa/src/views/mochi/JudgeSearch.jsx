import { useCallback, useEffect, useState } from 'react'
import { SectionHead } from '../../components/SectionHead.jsx'
import { ErrorState, LoadingState } from '../../components/States.jsx'
import { formatNumber } from '../../lib/format.js'
import { plural, verticalLabel } from '../../lib/labels.js'
import './judging.css'
import { JUDGE_PATTERN, loadPairs, nextUnjudged, saveJudgment, shortcutLevel, VERDICTS } from './judging.js'

// El rótulo se recuerda en este navegador (una comodidad: los juicios viven en la base, no aquí).
const JUDGE_KEY = 'panel-juez-busqueda'

function storedJudge() {
  try {
    return window.localStorage.getItem(JUDGE_KEY) || null // uno vacío (de antes) se vuelve a pedir
  } catch {
    return null
  }
}

function storeJudge(judge) {
  try {
    window.localStorage.setItem(JUDGE_KEY, judge)
  } catch {
    // sin almacenamiento (ventana privada): se vuelve a pedir el rótulo la próxima vez
  }
}

const NO_PAIRS = [] // estable entre renders: la lista vacía mientras carga
const verdictLabel = (level) => VERDICTS.find((verdict) => verdict.level === level)?.label

/** El rótulo de quien juzga: "J1", nunca un nombre ni un correo. */
function JudgeForm({ initial, onStart }) {
  const [value, setValue] = useState(initial ?? '')
  const valid = JUDGE_PATTERN.test(value.trim())
  const bad = !valid && value.trim() !== '' // vacío: todavía no hay nada que corregir, pero no se empieza
  return (
    <form
      className="judge-form"
      onSubmit={(event) => {
        event.preventDefault()
        if (valid) onStart(value.trim())
      }}
    >
      <label htmlFor="judge-label">Rótulo del juez</label>
      <input
        id="judge-label"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        maxLength={16}
        autoComplete="off"
        spellCheck={false}
        aria-describedby="judge-label-help"
        aria-invalid={bad}
      />
      <p id="judge-label-help" className={bad ? 'judge-form-help judge-form-help--bad' : 'judge-form-help'}>
        {bad
          ? 'Solo letras sin tilde, números, - y _ (hasta 16), sin espacios ni @.'
          : 'Como J1 o J2, para separar a dos personas que juzgan. Nunca tu nombre ni tu correo.'}
      </p>
      <button type="submit" className="text-button text-button--go" disabled={!valid}>
        Empezar
      </button>
    </form>
  )
}

/**
 * Lo que se mostró: la consulta y el resultado, sin el método, la posición ni otro juicio. La muestra guarda solo el id
 * del resultado: nombre, tienda, precio y foto son los de hoy en el catálogo de esta base, y la tarjeta lo dice.
 */
function PairCard({ pair }) {
  const [broken, setBroken] = useState(false)
  const details = [pair.presentacion, pair.categoria].filter(Boolean).join(' · ')
  return (
    <div className="judge-pair">
      <p className="judge-query-label">
        Alguien buscó en <strong>{verticalLabel(pair.vertical)}</strong>
      </p>
      <p className="judge-query">"{pair.consulta}"</p>
      <div className="judge-result">
        <div className="judge-photo" aria-hidden="true">
          {pair.imagen && !broken ? (
            <img src={pair.imagen} alt="" width="96" height="96" loading="lazy" onError={() => setBroken(true)} />
          ) : (
            <span>Sin foto</span>
          )}
        </div>
        <div className="judge-result-text">
          <p className="judge-result-label">y le mostramos (como está hoy en el catálogo)</p>
          <p className="judge-name">{pair.nombre}</p>
          {details && <p className="judge-meta">{details}</p>}
          <p className="judge-meta">
            {pair.tienda ?? 'Sin tienda con precio vigente'}
            {pair.precio !== null && pair.precio !== undefined && <> · ${formatNumber(pair.precio)}</>}
          </p>
        </div>
      </div>
    </div>
  )
}

function Judging({ judge, onChangeJudge }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [attempt, setAttempt] = useState(0)
  const [judgments, setJudgments] = useState({})
  const [index, setIndex] = useState(0)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)
  const [announcement, setAnnouncement] = useState('')

  useEffect(() => {
    let current = true
    loadPairs(judge).then(
      (body) => {
        if (!current) return
        const given = Object.fromEntries(body.pares.filter((p) => p.juicio !== null).map((p) => [p.id, p.juicio]))
        setData(body)
        setJudgments(given)
        setIndex(Math.max(nextUnjudged(body.pares, given), 0)) // se retoma donde quedó
      },
      (reason) => current && setError(reason.message),
    )
    return () => {
      current = false
    }
  }, [judge, attempt])

  const pairs = data?.pares ?? NO_PAIRS
  const pair = pairs[index]
  const judged = Object.keys(judgments).length
  const done = pairs.length > 0 && judged === pairs.length

  const judgeCurrent = useCallback(
    async (level) => {
      if (!pair || saving) return
      setSaving(true)
      setSaveError(null)
      try {
        await saveJudgment(pair.id, level, judge)
        const next = { ...judgments, [pair.id]: level }
        setJudgments(next)
        const count = Object.keys(next).length
        setAnnouncement(`Guardado: ${verdictLabel(level)}. ${count} de ${pairs.length}.`)
        const following = nextUnjudged(pairs, next, index + 1)
        if (following !== -1) setIndex(following)
      } catch (reason) {
        setSaveError(`No se guardó: ${reason.message}`)
      } finally {
        setSaving(false)
      }
    },
    [pair, saving, judge, judgments, pairs, index],
  )

  useEffect(() => {
    if (!pair) return undefined
    const onKey = (event) => {
      const level = shortcutLevel(event)
      if (level === null) return
      event.preventDefault()
      judgeCurrent(level)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pair, judgeCurrent])

  if (error) {
    return (
      <ErrorState
        message={error}
        onRetry={() => {
          setError(null)
          setAttempt((n) => n + 1)
        }}
      />
    )
  }
  if (!data) return <LoadingState />

  const current = pair ? judgments[pair.id] : undefined
  return (
    <div className="judge">
      <div className="judge-bar">
        <p className="judge-who">
          Juzgando como <strong>{judge}</strong>{' '}
          <button type="button" className="link-button" onClick={onChangeJudge}>
            Cambiar
          </button>
        </p>
        <div className="judge-progress">
          <span>
            {formatNumber(judged)} de {formatNumber(pairs.length)} {plural(pairs.length, 'par', 'pares')} juzgados
          </span>
          <progress value={judged} max={Math.max(pairs.length, 1)} aria-label="Pares juzgados" />
        </div>
      </div>
      {data.fuera_del_catalogo > 0 && (
        <p className="judge-note">
          {formatNumber(data.fuera_del_catalogo)} de los {formatNumber(data.muestra)} pares de la muestra no se pueden
          juzgar aquí: su producto no está en el catálogo de esta base.
        </p>
      )}
      <p className="visually-hidden" role="status" aria-live="polite">
        {announcement}
      </p>

      {done && (
        <div className="state">
          <strong>Juzgaste los {formatNumber(pairs.length)} pares.</strong>
          <p>
            El κ contra el juez por concepto sale con{' '}
            <span className="mono">rappi-ia eval-human --desde-base --juez {judge}</span>. Puedes seguir revisando:
            volver a juzgar un par reemplaza su juicio.
          </p>
        </div>
      )}

      {pair ? (
        <div className="panel judge-card">
          <div className="panel-body">
            <p className="judge-count">
              Par {formatNumber(index + 1)} de {formatNumber(pairs.length)}
              {current !== undefined && <> · lo juzgaste "{verdictLabel(current)}"</>}
            </p>
            <PairCard key={pair.id} pair={pair} />
            <div className="judge-verdicts" role="group" aria-label="¿Sirve este resultado para esa búsqueda?">
              {VERDICTS.map((verdict) => (
                <button
                  key={verdict.level}
                  type="button"
                  className={`judge-verdict judge-verdict--${verdict.level}`}
                  aria-pressed={current === verdict.level}
                  aria-keyshortcuts={String(verdict.level)}
                  aria-describedby={`judge-hint-${verdict.level}`}
                  disabled={saving}
                  onClick={() => judgeCurrent(verdict.level)}
                >
                  <span className="judge-verdict-label">{verdict.label}</span>
                  <kbd aria-hidden="true">{verdict.level}</kbd>
                  <span id={`judge-hint-${verdict.level}`} className="judge-verdict-hint">
                    {verdict.hint}
                  </span>
                </button>
              ))}
            </div>
            {saveError && (
              <p className="judge-error" role="alert">
                {saveError}
              </p>
            )}
            <div className="judge-nav">
              {/* Mientras se guarda, el par no cambia: al terminar se avanza (o se avisa el error) desde ese par. */}
              <button
                type="button"
                className="text-button"
                disabled={saving || index === 0}
                onClick={() => setIndex((n) => Math.max(n - 1, 0))}
              >
                Anterior
              </button>
              <button
                type="button"
                className="text-button"
                disabled={saving || index >= pairs.length - 1}
                onClick={() => setIndex((n) => Math.min(n + 1, pairs.length - 1))}
              >
                Saltar
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div className="state">
          <strong>No hay pares para juzgar en esta base.</strong>
        </div>
      )}
    </div>
  )
}

/**
 * "Juzgar la búsqueda": la muestra de 200 pares (consulta, resultado) de la evaluación, uno a la vez y a ciegas. El
 * juicio se guarda en la base al tocar un botón (o con las teclas 2, 1 y 0) y `rappi-ia eval-human --desde-base` lo
 * compara con el juez por concepto. No depende de la fuente: es el catálogo real.
 */
export function JudgeSearch() {
  const [judge, setJudge] = useState(storedJudge)
  const [editing, setEditing] = useState(judge === null)
  return (
    <section className="section" aria-labelledby="juzgar">
      <SectionHead
        id="juzgar"
        title="Juzgar la búsqueda"
        meta="Catálogo real · juicio de personas"
        help={
          <>
            <p>
              Cada par es una búsqueda en una vertical y un resultado que la app mostró. Piensa en quien escribió esa
              búsqueda: ¿le sirve? No se muestra en qué posición salió, con qué método ni qué dijo otro juez.
            </p>
            <p>
              Atajos: 2 "Sirve", 1 "A medias", 0 "No sirve". Se guarda al tocar y se puede retomar otro día; volver a
              juzgar un par reemplaza su juicio.
            </p>
          </>
        }
      />
      {editing ? (
        <JudgeForm
          initial={judge}
          onStart={(label) => {
            storeJudge(label)
            setJudge(label)
            setEditing(false)
          }}
        />
      ) : (
        <Judging key={judge} judge={judge} onChangeJudge={() => setEditing(true)} />
      )}
    </section>
  )
}
