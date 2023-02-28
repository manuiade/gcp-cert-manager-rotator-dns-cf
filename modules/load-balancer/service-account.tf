//-----------------------------------------------------------------------------
// custom-sa.tf - creates dedicated service account storing its JSON keys in
// GCP secret manager
//-----------------------------------------------------------------------------

// Dedicated service account for certificate rotation (used by CF and Scheduler)
resource "google_service_account" "cert_rotator_sa" {
  account_id = var.service_account
  display_name = "Dedicated Service Account for manage certificate rotation"
  project      = var.project_id
}

// Custom role with minimum permission required to manage ssl certificates and LB
resource "google_project_iam_custom_role" "cert_manager_rotator_custom_role" {
  role_id     = "cert_manager_rotator_custom_role"
  title       = "cert_manager_rotator_custom_role"
  permissions = local.cert_manager_rotator_custom_role_permissions
  project     = var.project_id
}

// IAM custom role assigned to service account
resource "google_project_iam_member" "cert_manager_rotator_sa_iam" {
  project = var.project_id
  role    = google_project_iam_custom_role.cert_manager_rotator_custom_role.id
  member  = format("serviceAccount:%s", google_service_account.cert_rotator_sa.email)
}

# Permissions on the service account used for calling the cloud function v2
resource "google_project_iam_member" "f2_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = format("serviceAccount:%s", google_service_account.cert_rotator_sa.email)
}
