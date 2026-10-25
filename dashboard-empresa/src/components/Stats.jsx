/** Cifras de una sección como lista de definiciones: [{ label, value, note? }]. */
export function Stats({ items }) {
  return (
    <dl className="stats">
      {items.map((item) => (
        <div key={item.label}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
          {item.note && <p>{item.note}</p>}
        </div>
      ))}
    </dl>
  )
}
