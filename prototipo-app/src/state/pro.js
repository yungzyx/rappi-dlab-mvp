import { useSyncExternalStore } from 'react'
import { loadStored, saveStored } from './storage'

// Si la persona de la demo es Rappi Pro (por defecto, no). Vive en el navegador como el resto del prototipo: «Olvidar»
// lo borra y una persona del «Panel de la demo» trae el suyo (api/offline/personas.js). El checkout lo usa para el envío
// gratis y el descuento en servicio, y cada pedido se lo dice a la API (`POST /orders`, `pro`).
export const PRO_KEY = 'rappi-proto-pro'
const listeners = new Set()

export const readPro = () => loadStored(PRO_KEY, (value) => typeof value === 'boolean', false)

/** Cambia la marca Pro (el interruptor de la demo en Cuenta) y avisa a las pantallas que la leen. */
export function setPro(value) {
  saveStored(PRO_KEY, Boolean(value))
  listeners.forEach((listener) => listener())
}

const subscribe = (listener) => {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** `true` si la persona es Rappi Pro. */
export const usePro = () => useSyncExternalStore(subscribe, readPro)
