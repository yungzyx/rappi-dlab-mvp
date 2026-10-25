output "public_ip" {
  description = "IP pública reservada del servidor."
  value       = oci_core_public_ip.mvp.ip_address
}

output "ssh" {
  description = "Comando para entrar al servidor."
  value       = "ssh -i ${replace(pathexpand(var.ssh_public_key_path), ".pub", "")} ubuntu@${oci_core_public_ip.mvp.ip_address}"
}

output "sslip_domain" {
  description = "Nombre gratis que apunta a la IP (sirve como DOMAIN de Caddy mientras no haya un dominio propio)."
  value       = "${replace(oci_core_public_ip.mvp.ip_address, ".", "-")}.sslip.io"
}

output "image" {
  description = "Imagen de Ubuntu con la que se creó la máquina."
  value       = data.oci_core_images.ubuntu_arm.images[0].display_name
}
