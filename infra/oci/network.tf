locals {
  compartment_ocid = var.compartment_ocid != "" ? var.compartment_ocid : var.tenancy_ocid
}

resource "oci_core_vcn" "main" {
  compartment_id = local.compartment_ocid
  display_name   = "${var.name}-vcn"
  cidr_blocks    = ["10.0.0.0/16"]
  dns_label      = "rappimvp"
}

resource "oci_core_internet_gateway" "main" {
  compartment_id = local.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  display_name   = "${var.name}-igw"
}

resource "oci_core_route_table" "public" {
  compartment_id = local.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  display_name   = "${var.name}-rt"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.main.id
  }
}

# Solo entra la web (80 y 443) desde cualquier lado y SSH desde las redes de admin_cidrs. Sale todo.
resource "oci_core_security_list" "public" {
  compartment_id = local.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  display_name   = "${var.name}-sl"

  egress_security_rules {
    destination = "0.0.0.0/0"
    protocol    = "all"
  }

  dynamic "ingress_security_rules" {
    for_each = var.admin_cidrs
    content {
      description = "SSH de administración"
      protocol    = "6"
      source      = ingress_security_rules.value
      tcp_options {
        min = 22
        max = 22
      }
    }
  }

  dynamic "ingress_security_rules" {
    for_each = [80, 443]
    content {
      description = "Web (Caddy)"
      protocol    = "6"
      source      = "0.0.0.0/0"
      tcp_options {
        min = ingress_security_rules.value
        max = ingress_security_rules.value
      }
    }
  }

  # Descubrimiento del MTU de la ruta: sin esto, algunas conexiones grandes se cuelgan.
  ingress_security_rules {
    description = "ICMP fragmentación necesaria"
    protocol    = "1"
    source      = "0.0.0.0/0"
    icmp_options {
      type = 3
      code = 4
    }
  }
}

resource "oci_core_subnet" "public" {
  compartment_id    = local.compartment_ocid
  vcn_id            = oci_core_vcn.main.id
  display_name      = "${var.name}-subnet"
  cidr_block        = "10.0.1.0/24"
  dns_label         = "publica"
  route_table_id    = oci_core_route_table.public.id
  security_list_ids = [oci_core_security_list.public.id]
}
