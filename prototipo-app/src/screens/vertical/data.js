// Lo que no es catálogo de las verticales abiertas desde los accesos de la Home (capturas de la app iOS del 26-09-2026,
// no versionadas): título y filas de categorías. Las tiendas y los productos salen de la API (`/catalog`).
const v = import.meta.glob('../../assets/v/*.webp', { eager: true, import: 'default' })
const a = (name) => v[`../../assets/v/${name}.webp`]

// Cada categoría es `[etiqueta, consulta]`: tocarla busca esa consulta en el catálogo, con la vertical de la pantalla.
function catRow(prefix, items, partialLast = false) {
  return items.map(([label, query], i) => ({
    id: `${prefix}-${i}`,
    label,
    query,
    img: a(`${prefix}-cat${i}`),
    partial: partialLast && i === items.length - 1,
  }))
}

export const VERTICALS = {
  grocery: {
    title: 'Súper',
    categoryRows: [
      catRow(
        'gro',
        [
          ['Despensa', 'despensa'],
          ['Express', 'snacks'],
          ['Frutas y verduras', 'frutas y verduras'],
          ['Carnes y pescados', 'carnes y pescados'],
          ['Farmacia', 'medicamentos'],
        ],
        true,
      ),
    ],
  },

  pharmacy: {
    title: 'Farmacia',
    categoryRows: [
      catRow(
        'pha',
        [
          ['Belleza', 'belleza'],
          ['Salud sexual', 'salud sexual'],
          ['Analgésicos', 'analgésicos'],
          ['Vitaminas y suplementos', 'vitaminas'],
          ['Primeros auxilios', 'primeros auxilios'],
        ],
        true,
      ),
      catRow(
        'pha2',
        [
          ['Cuidado personal', 'cuidado personal'],
          ['Resfrío y alergias', 'resfrío y alergias'],
          ['Salud digestiva', 'salud digestiva'],
          ['Cuidado del bebé', 'cuidado del bebé'],
          ['Salud visual', 'salud visual'],
        ],
        true,
      ),
    ],
  },

  retail: {
    title: 'Rappi Mall',
    scrollCategories: true,
    categoryRows: [
      catRow('ret', [
        ['Belleza y salud', 'belleza'],
        ['Librería y oficina', 'útiles de oficina'],
        ['Moda', 'ropa'],
        ['Herramientas y jardín', 'herramientas y jardín'],
        ['Sex shop', 'sex shop'],
      ]),
      catRow('ret2', [
        ['Tecnología', 'tecnología'],
        ['Hogar y decoración', 'decoración del hogar'],
        ['Flores y plantas', 'flores y plantas'],
        ['Bebés y niños', 'accesorios para bebé'],
        ['Fiestas', 'fiesta'],
      ]),
    ],
  },

  liquor: {
    title: 'Licores',
    scrollCategories: true,
    categoryRows: [
      catRow('liq', [
        ['Cervezas y sidras', 'cerveza'],
        ['Vinos', 'vino'],
        ['Destilados', 'licores'],
        ['Bebidas y mixers', 'bebidas'],
        ['Listos para tomar', 'cócteles'],
      ]),
    ],
  },

  express: {
    title: 'Express',
    categoryRows: [
      catRow(
        'exp',
        [
          ['Especialidades', 'productos especiales'],
          ['Almacén', 'mercado'],
          ['Kiosco', 'kiosco'],
          ['Mascotas', 'mascotas'],
          ['Carnes', 'carne'],
        ],
        true,
      ),
    ],
  },

  chocolates: {
    title: 'Chocolates',
    categoryRows: [],
  },
}
