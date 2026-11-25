data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

# La última imagen de Ubuntu 24.04 para ARM (aarch64) compatible con la forma A1.
data "oci_core_images" "ubuntu_arm" {
  compartment_id           = local.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "24.04"
  shape                    = "VM.Standard.A1.Flex"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

resource "oci_core_instance" "mvp" {
  compartment_id      = local.compartment_ocid
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[0].name
  display_name        = var.name
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = var.ocpus
    memory_in_gbs = var.memory_gb
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu_arm.images[0].id
    boot_volume_size_in_gbs = var.boot_volume_gb
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.public.id
    assign_public_ip = false # la IP pública es la reservada de abajo: sobrevive a recrear la máquina
    hostname_label   = "mvp"
  }

  metadata = {
    ssh_authorized_keys = trimspace(file(pathexpand(var.ssh_public_key_path)))
    user_data           = base64encode(file("${path.module}/cloud-init.yaml"))
  }

  lifecycle {
    # Una imagen nueva de Ubuntu no debe recrear la máquina (y borrar la base); se actualiza con apt.
    ignore_changes = [source_details[0].source_id, metadata["user_data"]]
  }
}

data "oci_core_vnic_attachments" "mvp" {
  compartment_id = local.compartment_ocid
  instance_id    = oci_core_instance.mvp.id
}

data "oci_core_private_ips" "mvp" {
  vnic_id = data.oci_core_vnic_attachments.mvp.vnic_attachments[0].vnic_id
}

resource "oci_core_public_ip" "mvp" {
  compartment_id = local.compartment_ocid
  display_name   = "${var.name}-ip"
  lifetime       = "RESERVED"
  private_ip_id  = data.oci_core_private_ips.mvp.private_ips[0].id
}
