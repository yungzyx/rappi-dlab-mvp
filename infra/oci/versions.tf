terraform {
  required_version = ">= 1.6"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 6.0"
    }
  }
}

# Autenticación con una sesión de la CLI de OCI (`oci session authenticate --profile-name <perfil>`): no hay llaves
# de API guardadas en el equipo, la sesión dura una hora y se renueva con `oci session refresh --profile <perfil>`.
provider "oci" {
  auth                = "SecurityToken"
  config_file_profile = var.oci_profile
  region              = var.region
}
