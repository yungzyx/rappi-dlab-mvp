import { Help } from './Help.jsx'

/** Cifras de una sección como lista de definiciones: [{ label, value, note?, help? }]. */
export function Stats({ items }) {
  return (
    <dl className="stats">
      {items.map((item) => (
        <div key={item.label}>
          {item.help ? (
            <dt>
              <span>{item.label}</span>
              <Help label={item.label}>{item.help}</Help>
            </dt>
          ) : (
            <dt>{item.label}</dt>
          )}
          <dd>{item.value}</dd>
          {item.note && <p>{item.note}</p>}
        </div>
      ))}
    </dl>
  )
}
