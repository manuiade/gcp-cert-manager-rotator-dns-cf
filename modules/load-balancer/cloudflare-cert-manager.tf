//-----------------------------------------------------------------------------
// cloudflare-cert-manager.tf - creates all the infrastructure components to
//dynamically rotate ssl certificates based on new domains definition of
// cert manager and creates the corresponding CNAME on cloudflare
//-----------------------------------------------------------------------------

data "google_project" "project" {
  project_id = var.project_id
}

// Obtain the top level domain for the zone id
data "cloudflare_zone" "zone_id" {
  for_each = toset(var.domain_list)
  name     = join(".", ["${element(split(".", each.key), length(split(".", each.key)) - 2)}", "${element(split(".", each.key), length(split(".", each.key)) - 1)}"])
}

// Certificate map for subsequent certificate entries
resource "google_certificate_manager_certificate_map" "cmap" {
  name = "${var.load_balancer}-cert-map"
  // description = ""
  project = var.project_id
}


resource "cloudflare_record" "a_record" {
  for_each = toset(var.domain_list)

  allow_overwrite = false
  zone_id         = data.cloudflare_zone.zone_id["${each.key}"].id
  name            = replace(each.key, ".${join(".", ["${element(split(".", each.key), length(split(".", each.key)) - 2)}", "${element(split(".", each.key), length(split(".", each.key)) - 1)}"])}", "")
  value           = google_compute_global_address.global_ipv4.address
  type            = "A"
  proxied         = false
  ttl             = 60
}

// Create a secret manager vault to store cloudflare API Token (add new version)
resource "google_secret_manager_secret" "cloudflare_api_token" {
  secret_id = "cloudflare-api-token"
  project   = var.project_id
  replication {
    automatic = true
  }
}

resource "google_secret_manager_secret_iam_member" "function_sa_access" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.cloudflare_api_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = format("serviceAccount:%s", google_service_account.cert_rotator_sa.email)
}

resource "google_secret_manager_secret_version" "cloudflare_api_token" {
  secret      = google_secret_manager_secret.cloudflare_api_token.id
  enabled     = true
  secret_data = "changeme"
}

// Create the bucket hosting the Cloud Function source code for SSL rotation
resource "google_storage_bucket" "source_code_bucket" {
  name                        = "${var.project_id}-ssl-rot-bucket"
  location                    = "EU"
  force_destroy               = true
  project                     = var.project_id
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
}

// Upload source code to GCS bucket
resource "google_storage_bucket_object" "cert_manager_rotator_source_code" {
  bucket = google_storage_bucket.source_code_bucket.name
  name   = "source-code/cert-manager-rotator-code.zip"
  source = "${path.module}/../../static/cert-manager-rotator-code/cert-manager-rotator-code.zip"
}

// Creates/updates the cloud function based on the last domain and ssl certificates list
resource "google_cloudfunctions2_function" "cert_manager_rotator_function" {
  name     = "cert-manager-rotator"
  project  = var.project_id
  location = var.gcp_region
  build_config {
    runtime     = "python39"
    entry_point = "rotate_certs"
    source {
      storage_source {
        bucket = google_storage_bucket.source_code_bucket.name
        object = google_storage_bucket_object.cert_manager_rotator_source_code.output_name
      }
    }
  }

  service_config {
    timeout_seconds                  = 1500
    available_memory                 = "512M"
    max_instance_request_concurrency = 1
    environment_variables = {
      "_PROJECT_ID" : "${var.project_id}",
      "_GCP_REGION" : "${var.gcp_region}",
      "_CS_JOB_ID" : "cert-manager-${local.cs_job_id}",
      "_CHUNK_SIZE" : "${local.chunk_size}",
      "_CERTIFICATE_MAP" : google_certificate_manager_certificate_map.cmap.name,
      "_NEW_DOMAINS_LIST" : "${local.new_domains_list}",
      "_NEW_CERTS_LIST" : "${local.new_certs_list}",
      "_FIXED_CERTS_LIST" : ""
      "_FIXED_DNS_AUTHS_LIST" : "",
      "_FIXED_CME_LIST" : ""
    }
    max_instance_count    = 1
    min_instance_count    = 0
    service_account_email = google_service_account.cert_rotator_sa.email
    ingress_settings      = "ALLOW_ALL"
    secret_environment_variables {
      key        = "_CLOUDFLARE_API_TOKEN"
      project_id = data.google_project.project.number
      secret     = split("/", google_secret_manager_secret.cloudflare_api_token.id)[3]
      version    = "latest"
    }
  }
}

// Grant SA invoke permission to cloud function
resource "google_cloudfunctions2_function_iam_member" "cert_manager_rotator_function_invoke" {
  project        = var.project_id
  location       = var.gcp_region
  cloud_function = google_cloudfunctions2_function.cert_manager_rotator_function.name
  role           = "roles/cloudfunctions.invoker"
  member         = format("serviceAccount:%s", google_service_account.cert_rotator_sa.email)
}

// Creates/update the Cloud Scheduler Job which periodically calls the Function for the certificate rotation
resource "google_cloud_scheduler_job" "cert_manager_rotator_job" {
  name      = "cert-manager-${local.cs_job_id}"
  schedule  = "*/30 * * * *"
  time_zone = "Europe/Rome"
  project   = var.project_id
  region    = var.gcp_region
  http_target {
    http_method = "GET"
    uri         = google_cloudfunctions2_function.cert_manager_rotator_function.service_config[0].uri
    oidc_token {
      service_account_email = google_service_account.cert_rotator_sa.email
    }
  }
}