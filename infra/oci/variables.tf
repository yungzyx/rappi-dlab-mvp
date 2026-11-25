variable "oci_profile" {
  description = "Perfil de ~/.oci/config creado con `oci session authenticate`."
  type        = string
  default     = "RAPPI"
}

variable "region" {
  description = "Región de OCI. Los recursos Always Free existen solo en la región principal de la cuenta."
  type        = string
  default     = "sa-santiago-1"
}

variable "tenancy_ocid" {
  description = "OCID de la cuenta (tenancy). Está en ~/.oci/config, en la línea tenancy= del perfil."
  type        = string
}

variable "compartment_ocid" {
  description = "Compartimento donde se crean los recursos. Vacío: la raíz de la cuenta."
  type        = string
  default     = ""
}

variable "name" {
  description = "Prefijo de los nombres de los recursos."
  type        = string
  default     = "rappi-dlab-mvp"
}

variable "ssh_public_key_path" {
  description = "Llave pública que podrá entrar por SSH como ubuntu."
  type        = string
  default     = "~/.ssh/rappi_oci.pub"
}

variable "admin_cidrs" {
  description = "Redes que pueden entrar por SSH (puerto 22). La web (80 y 443) queda abierta a todos, detrás de la puerta de Caddy."
  type        = list(string)
}

# Always Free de Ampere A1: hasta 4 OCPU y 24 GB en total por cuenta, y 200 GB de disco en bloques.
variable "ocpus" {
  description = "OCPU de la máquina Ampere A1 (gratis hasta 4)."
  type        = number
  default     = 4
}

variable "memory_gb" {
  description = "Memoria en GB (gratis hasta 24)."
  type        = number
  default     = 24
}

variable "boot_volume_gb" {
  description = "Disco de arranque en GB (gratis hasta 200 en total)."
  type        = number
  default     = 100
}

variable "budget_alert_email" {
  description = "Correo para la alerta de presupuesto (1 USD al mes). Vacío: sin presupuesto."
  type        = string
  default     = ""
}
