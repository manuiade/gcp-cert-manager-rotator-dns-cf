//-----------------------------------------------------------------------------
// locals.tf - format variables for easier use in resource attributes
//-----------------------------------------------------------------------------

locals {

  // Required permissions for cloud function in order to perform cert rotation
  cert_rotator_custom_role_permissions = [
    "compute.targetHttpsProxies.get",
    "compute.targetHttpsProxies.list",
    "compute.targetHttpsProxies.setSslCertificates",
    "compute.sslCertificates.create",
    "compute.sslCertificates.delete",
    "compute.sslCertificates.get",
    "compute.sslCertificates.list",
    "cloudscheduler.jobs.pause"
  ]

  cert_manager_rotator_custom_role_permissions = [
    "certificatemanager.certmapentries.get",
    "certificatemanager.certmapentries.list",
    "certificatemanager.certmapentries.update",
    "certificatemanager.certmapentries.create",
    "certificatemanager.certmapentries.delete",
    "certificatemanager.certmaps.list",
    "certificatemanager.certmaps.get",
    "certificatemanager.certs.create",
    "certificatemanager.certs.delete",
    "certificatemanager.certs.get",
    "certificatemanager.certs.list",
    "certificatemanager.certs.use",
    "certificatemanager.dnsauthorizations.use",
    "certificatemanager.dnsauthorizations.list",
    "certificatemanager.dnsauthorizations.get",
    "certificatemanager.dnsauthorizations.create",
    "certificatemanager.dnsauthorizations.delete",
    "cloudscheduler.jobs.pause"
  ]

  chunk_size = 100 // Max domains supported by a GCP-managed SSL certificate

  cs_job_id = "check-ssl-${sha1(join("", var.domain_list))}"

  chunked_new_domain_list = chunklist(var.domain_list, local.chunk_size)

  new_certs = flatten([
    for c in local.chunked_new_domain_list : "ssl-${sha1(join("", c))}"
  ])

  new_certs_list = join(",", local.new_certs)
  new_domains_list   = join(",", var.domain_list)
}