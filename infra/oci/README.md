# Infraestructura en Oracle Cloud (Terraform)

Crea el servidor del MVP en Oracle Cloud Infrastructure (OCI) dentro del nivel **Always Free**: una máquina ARM Ampere A1 (4 OCPU y 24 GB), una red con solo la web abierta, y una IP pública reservada. El despliegue de la app sobre esa máquina sigue en [docs/despliegue.md](../../docs/despliegue.md).

| Archivo | Qué crea |
|---|---|
| `network.tf` | VCN, gateway a internet, tabla de rutas, subred pública y lista de seguridad: 80 y 443 abiertos, 22 solo desde `admin_cidrs` |
| `compute.tf` | La máquina `VM.Standard.A1.Flex` con Ubuntu 24.04 (aarch64) y la IP pública reservada, que sobrevive a recrear la máquina |
| `cloud-init.yaml` | El primer arranque: Docker Engine con compose, 80 y 443 abiertos en el iptables de la imagen, `/opt/rappi` y `/etc/rappi`. Se detiene en el primer error (reintenta lo que usa la red o apt hasta 10 minutos) y deja `/var/lib/cloud/instance/rappi-listo` solo si Docker y compose responden |
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

## Límite de la cuenta

No todas las cuentas tienen 4 OCPU y 24 GB de A1: hay cuentas con 2 OCPU y 12 GB (OCI responde "400-LimitExceeded" al pedir más). Para ver el de una cuenta:

```bash
oci limits value list -c <tenancy_ocid> --service-name compute --name standard-a1-core-regional-count \
  --profile RAPPI --auth security_token --region sa-santiago-1
```

Con un límite menor, `ocpus` y `memory_gb` van en `terraform.tfvars` (ver el ejemplo); `reintentar-capacidad.sh` ya prueba 2 OCPU y 12 GB cuando la forma completa choca con el límite.

## Estado

Sin probar contra una máquina real: `terraform validate` pasa, pero OCI no tuvo capacidad para la A1 en `sa-santiago-1` y la máquina no se llegó a crear (la red y el presupuesto, sí). El primer `terraform apply` que la cree es también la primera prueba del `cloud-init.yaml`: si `cloud-init status` da error, el detalle está en `/var/log/cloud-init-output.log`. El CI no corre `terraform validate` (se revisa a mano).
