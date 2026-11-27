// Aplica el tema elegido antes de pintar, para no mostrar un destello del otro tema. Es un archivo (no un script en
// línea) para que la CSP del servidor (script-src 'self') lo deje correr; se carga sin `defer` ni `type="module"`.
// ?tema=claro u ?tema=oscuro en la dirección (p. ej. el QR de una presentación) lo fija como el botón (src/lib/useTheme.js).
const fromUrl = { claro: 'light', oscuro: 'dark' }[new URLSearchParams(location.search).get('tema')]
if (fromUrl) document.documentElement.dataset.theme = fromUrl
try {
  if (fromUrl) localStorage.setItem('panel-empresa:tema', fromUrl)
  const theme = localStorage.getItem('panel-empresa:tema')
  if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme
} catch {
  // Sin almacenamiento se sigue al sistema (o al de la dirección).
}
// Aplicado, se saca de la dirección: si no, el botón de tema no duraba (cada recarga volvía al de la dirección) y un
// enlace copiado lo arrastraba.
if (fromUrl) {
  const url = new URL(location.href)
  url.searchParams.delete('tema')
  history.replaceState(history.state, '', url)
}
