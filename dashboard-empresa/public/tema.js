// Aplica el tema elegido antes de pintar, para no mostrar un destello del otro tema. Es un archivo (no un script en
// línea) para que la CSP del servidor (script-src 'self') lo deje correr; se carga sin `defer` ni `type="module"`.
try {
  const theme = localStorage.getItem('panel-empresa:tema')
  if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme
} catch {
  // Sin almacenamiento se sigue al sistema.
}
