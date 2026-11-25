# Alerta si la cuenta gasta algo: todo lo de este Terraform cabe en Always Free, así que cualquier cobro es una sorpresa.
resource "oci_budget_budget" "guard" {
  count          = var.budget_alert_email == "" ? 0 : 1
  compartment_id = var.tenancy_ocid
  target_type    = "COMPARTMENT"
  targets        = [var.tenancy_ocid]
  amount         = 1
  reset_period   = "MONTHLY"
  display_name   = "${var.name}-presupuesto"
  description    = "Alerta si la cuenta pasa de 1 USD al mes"
}

resource "oci_budget_alert_rule" "guard" {
  count          = var.budget_alert_email == "" ? 0 : 1
  budget_id      = oci_budget_budget.guard[0].id
  type           = "ACTUAL"
  threshold      = 1
  threshold_type = "ABSOLUTE"
  display_name   = "gasto-real"
  recipients     = var.budget_alert_email
  message        = "La cuenta de OCI de ${var.name} tiene gasto real: revisa qué recurso salió de Always Free."
}
