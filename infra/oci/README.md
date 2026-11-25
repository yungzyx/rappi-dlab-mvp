# Infraestructura en Oracle Cloud (Terraform)

Crea el servidor del MVP en Oracle Cloud Infrastructure (OCI) dentro del nivel **Always Free**: una máquina ARM Ampere A1 (4 OCPU y 24 GB), una red con solo la web abierta, y una IP pública reservada. El despliegue de la app sobre esa máquina sigue en [docs/despliegue.md](../../docs/despliegue.md).

| Archivo | Qué crea |
|---|---|
| `network.tf` | VCN, gateway a internet, tabla de rutas, subred pública y lista de seguridad: 80 y 443 abiertos, 22 solo desde `admin_cidrs` |
| `compute.tf` | La máquina `VM.Standard.A1.Flex` con Ubuntu 24.04 (aarch64) y la IP pública reservada, que sobrevive a recrear la máquina |
| `cloud-init.yaml` | El primer arranque: Docker Engine con compose, 80 y 443 abiertos en el iptables de la imagen, `/opt/rappi` y `/etc/rappi` |
| `budget.tf` | Opcional: presupuesto de 1 USD al mes con alerta por correo (`budget_alert_email`) |
| `reintentar-capacidad.sh` | Reintenta crear la máquina cuando OCI responde «Out of host capacity» |

## Requisitos

- Una cuenta de OCI con **Pay As You Go** (sigue sin costo dentro de Always Free y evita que una máquina con poco uso se reclame), con la región principal donde va el servidor.
- La CLI de OCI y Terraform 1.6 o más nuevo (`brew install oci-cli hashicorp/tap/terraform`).
- Una llave SSH para el servidor: `ssh-keygen -t ed25519 -f ~/.ssh/rappi_oci`.

## Uso

```bash
oci session authenticate --region sa-santiago-1 --profile-name RAPPI   # abre el navegador; sin llaves de API
cd infra/oci
cp terraform.tfvars.example terraform.tfvars                         # tenancy_ocid y admin_cidrs
terraform init
terraform plan
terraform apply          # o ./reintentar-capacidad.sh si no hay capacidad
terraform output         # IP, comando SSH y un nombre <ip>.sslip.io para Caddy
```

La sesión de la CLI dura una hora: `oci session refresh --profile RAPPI` la renueva (hasta 24 h). El estado de Terraform (`terraform.tfstate`) y `terraform.tfvars` quedan fuera de git: tienen los OCID y las IP de la cuenta.

## Decisiones

- **Sesión de la CLI y no llaves de API:** nada que robar en el equipo.
- **IP reservada:** el DNS (o el nombre sslip.io) no cambia si se recrea la máquina.
- **`ignore_changes` en la imagen y el cloud-init:** una imagen nueva de Ubuntu no recrea la máquina (con la base adentro); se actualiza con `apt` (`unattended-upgrades` queda activo).
- **SSH solo desde `admin_cidrs`:** la web es lo único abierto a internet, y está detrás de la puerta de Caddy. Si cambia la IP de quien administra, se actualiza la variable y `terraform apply` (no hace falta SSH para eso).

## Estado

Sin probar contra una máquina real: al 25-11-2026 `terraform validate` pasa, pero OCI no tuvo capacidad para la A1 en `sa-santiago-1` y el servidor no se llegó a crear. La red y el presupuesto sí se crearon. El primer `terraform apply` que saque la máquina es también la primera prueba del `cloud-init.yaml`.
