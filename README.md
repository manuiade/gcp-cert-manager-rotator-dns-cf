# Google Cloud Certificate Manager Certificate rotation with Terraform and DNS Authorization with Cloudflare Registrar


## Scenario description

Since GCP managed certificates are immutable, adding/removing a new domain requires to create a new managed certificate.

The first 100 certificates are free, then they cost $0.20 per month per certificate (https://cloud.google.com/certificate-manager/pricing).

But since each certificate can contain up to 100 domains, a rotation procedure could be performed where:

- we define in any state a domain list A and apply the Terraform code

- for each domain a DNS authorization is created and the corresponding CNAME record on Cloudflare (Terraform also creates the A record pointing to the load balancer)

- for every 100 domains a new certificate will be provisioned

- the procedure waits until all the new certificates are in active state

- once all new certificates are active, new certificate map entries are created per domain (or update) to pointing ONLY to the certificate containing the domain

- for cleaning up, old certificates, certificate map entries, dns authorizations and CNAME records are deleted


## Content of this repo

This repo contains the following resources to setup the scenario (using Terraform):

- backend bucket with a static content to show load balancer is working

- dedicated service account and custom role with minimum set of permissions required to perform the certificate manager rotation

- gcp global external http/s load balancer setup

- cloud function (with source code) used to perform the steps described in the above section

Updating the domain list in the *terraform.tfvars* file and launching Terraform will ensure that the cloud function env variables will be updated with the new domain list and the cloud scheduler job which triggers the cf will automatically starts the certificate rotation procedure.


## Requirements

You will need the following resources in order to test this repo:

- A GCP Project with an active billing account

- A user/service account with at least Editor role on the GCP project in order to create the required resources

- Terraform >=1.1.0 on your laptop

- gcloud > 365.0 on your laptop

- a personal domain with Cloudflare as DNS registrar to add A records and CNAME records

- a Cloudflare API Token used by the cloud function to perform actions on zone and records (create, delete records)


## Launch steps

### Set project

```
gcloud compute set project <PROJECT_ID>
```

### Ensure required APIs are enabled

```
gcloud services enable compute.googleapis.com logging.googleapis.com cloudfunctions.googleapis.com pubsub.googleapis.com cloudbuild.googleapis.com cloudscheduler.googleapis.com certificatemanager.googleapis.com
```

### Execute Terraform

Rename *terraform.tfvars.template* to *terraform.tfvars* and enter the required values, then launch Terraform:

```
terraform init
terraform plan -out plan.out
terraform apply plan.out
```

<b> Terraform will create a Secret Manager resource (cloudflare-api-token) containing a first empty version. You must upload a new version containing the Cloudflare API Token that will be used by the cloud function procedure </b>

### Try to add new domain to the domain_list variable, relaunch terraform and wait for certificates to be rotated.


## Cleanup

### TF resources
```
terraform destroy
```

### Other resources

Note that the certificates manager resources are created by the Cloud Function, thus you have to delete them manually:

```
gcloud certificate-manager maps entries delete <CERT_MAP_ENTRY_NAME> --map <CERT_MAP_NAME>
gcloud certificate-manager certificates delete <CERT_NAME>
gcloud certificate-manager dns-authorizations delete <DNS_AUTH_NAME>
```