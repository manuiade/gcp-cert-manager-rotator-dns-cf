from google.cloud import certificate_manager_v1
from googleapiclient import discovery
import os
import time
import requests
import json
import tldextract

# Parse and adjust variables

# Passed by Terraform and used to indicate the number of domains per certificate
CHUNK_SIZE=int(os.environ.get('_CHUNK_SIZE', 'Environment variable does not exist'))

project_id = os.environ.get('_PROJECT_ID', 'Environment variable does not exist')
gcp_region = os.environ.get('_GCP_REGION', 'Environment variable does not exist')
cs_job_id = os.environ.get('_CS_JOB_ID', 'Environment variable does not exist')

# Created by Terraform
certificate_map = os.environ.get('_CERTIFICATE_MAP', 'Environment variable does not exist')

# Passed by Terraform and used to establish certificate domains
new_domains_list = os.environ.get('_NEW_DOMAINS_LIST', 'Environment variable does not exist')
new_domains_list = new_domains_list.split(",")

# DNS Authorizations names to create for each domain
new_dns_auths_list = [dns.replace('.', '-') for dns in new_domains_list]
new_dns_auths_list_self_link = [ "projects/{project_id}/locations/global/dnsAuthorizations/{dns}"
				.format(project_id=project_id,dns=dns) for dns in new_dns_auths_list]

# Certificate map entry names to create for each domain
new_cme_list = [cme.replace('.', '-') for cme in new_domains_list]

# Passed by Terraform
new_certs_list = os.environ.get('_NEW_CERTS_LIST', 'Environment variable does not exist')
new_certs_list = new_certs_list.split(",")

# Passed by Terraform, any certificate that must be kept in the certificat map entry
fixed_certs_list = os.environ.get('_FIXED_CERTS_LIST', 'Environment variable does not exist')
fixed_certs_list = fixed_certs_list.split(",")

# Passed by Terraform, any DNS Authorizations that must be kept in the certificate manager project
fixed_dns_auths_list = os.environ.get('_FIXED_DNS_AUTHS_LIST', 'Environment variable does not exist')
fixed_dns_auths_list = fixed_dns_auths_list.split(",")

# Passed by Terraform, any certificate map entry that must be kept in the certificate manager project
fixed_cme_list = os.environ.get('_FIXED_CME_LIST', 'Environment variable does not exist')
fixed_cme_list = fixed_cme_list.split(",")

# Split domain list for multiple certificates (since there is a maximun number of domains per certificate)
chunked_domain_list = [new_domains_list[x:x+CHUNK_SIZE] for x in range(0, len(new_domains_list), CHUNK_SIZE)]

# Split dns authorization lists to use only the CHUNK_SIZE for each certificate and respective domains
chunked_dns_auth_list = [new_dns_auths_list_self_link[x:x+CHUNK_SIZE] for x in range(0, len(new_dns_auths_list_self_link), CHUNK_SIZE)]

# Split cme lists to use only the CHUNK_SIZE for each certificate and respective domains
chunked_cme_list = [new_cme_list[x:x+CHUNK_SIZE] for x in range(0, len(new_cme_list), CHUNK_SIZE)]


#To manage in secret
cloudflare_api_token= os.environ.get('_CLOUDFLARE_API_TOKEN', 'Environment variable does not exist')

service = discovery.build('compute', 'v1')
client = certificate_manager_v1.CertificateManagerClient()

# Returns the list of all the DNS Authorizations on the project
def get_current_map_entries():
	request = certificate_manager_v1.ListCertificateMapEntriesRequest(
        parent="projects/{project_id}/locations/global/certificateMaps/{cert_map}".format(project_id=project_id, cert_map=certificate_map)
    )
	response = client.list_certificate_map_entries(request=request)
	map_entries = [map_entry.name.split("/")[7] for map_entry in response.certificate_map_entries]
	return map_entries

# Returns the list of all the DNS Authorizations on the project
def get_current_dns_auths():
	request = certificate_manager_v1.ListDnsAuthorizationsRequest(
        parent="projects/{project_id}/locations/global".format(project_id=project_id)
    )
	response = client.list_dns_authorizations(request=request)
	dns_auths = [dns_auth.name.split("/")[5] for dns_auth in response.dns_authorizations]
	return dns_auths

# Returns Cloudflare zone id given its top level domain name
def get_zone_id(dns_tld):
	zone_url = "https://api.cloudflare.com/client/v4/zones/?name={dns_tld}".format(dns_tld=dns_tld)
	headers = {"Authorization": "Bearer {cloudflare_api_token}".format(cloudflare_api_token=cloudflare_api_token), "Content-Type": "application/json"}
	zone = requests.get(zone_url, headers=headers).json()
	return zone["result"][0]['id']

# Returns Cloudflare record_id id given its zone_id and name
def get_record_id(zone_id, record_name):
	record_url = "https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?name={record_name}".format(zone_id=zone_id, record_name=record_name)
	headers = {"Authorization": "Bearer {cloudflare_api_token}".format(cloudflare_api_token=cloudflare_api_token), "Content-Type": "application/json"}
	record = requests.get(record_url, headers=headers).json()
	return record["result"][0]['id']

# Return the list of the current managed certificates
def get_current_certs():
	request = certificate_manager_v1.ListCertificatesRequest(
    	parent="projects/{project_id}/locations/global".format(project_id=project_id)
    )
	response = client.list_certificates(request=request)
	certificates = [cert.name.split("/")[5] for cert in response.certificates]
	return certificates




# For each new domain creates the DNS Authorization resource (if not exists) and the corresponding CNAME record on cloudflare
def create_dns_auths():
	current_dns_auths = get_current_dns_auths()
	# Here domain is test.example.com and corresponding dns_auth is test-example-com, the DNS Auth resource name
	for domain, dns_auth in zip(new_domains_list, new_dns_auths_list):

		if dns_auth not in current_dns_auths:
			print("Creating the new DNS Authorization {}..".format(dns_auth))
			dns_authorization = certificate_manager_v1.types.DnsAuthorization(
				name = "projects/{project_id}/locations/global/dnsAuthorizations/{dns_auth}".format(project_id=project_id, dns_auth=dns_auth),
				domain = domain
			)
			request = certificate_manager_v1.CreateDnsAuthorizationRequest(
        		parent="projects/{project_id}/locations/global".format(project_id=project_id),
        		dns_authorization_id=dns_auth,
        		dns_authorization=dns_authorization,
    		)
			client.create_dns_authorization(request=request)

		else:
			print("DNS Authorization {} already exists".format(dns_auth))

	# A subsequent iterarion is done because it may take a few second to create each DNS Authorization and get from them
	# the data needed to create the CNAME record, so they are created all previously and then pause the execution for a 
	# small amount of period to ensure each entry has the required values
	time.sleep(5)

	# Same iteration cycle as before, used to create the CNAME record for each DNS Authorization
	for domain, dns_auth in zip(new_domains_list, new_dns_auths_list):
		# Get the TLD for getting the zone_id of cloudflare
		dns_tld = tldextract.extract(domain)
		dns_tld = "{}.{}".format(dns_tld.domain, dns_tld.suffix)
		if dns_auth not in current_dns_auths:
			zone_id = get_zone_id(dns_tld)
			# Get for the created DNS Authorization request data used to create the CNAME record on Cloudflare
			request = certificate_manager_v1.GetDnsAuthorizationRequest(
        		name="projects/{project_id}/locations/global/dnsAuthorizations/{dns_auth}".format(project_id=project_id, dns_auth=dns_auth),
    		)
			response = client.get_dns_authorization(request=request)

			# Make the POST request to Cloudflare creating the CNAME record
			zone_url = "https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records".format(zone_id=zone_id)
			headers = {"Authorization": "Bearer {cloudflare_api_token}".format(cloudflare_api_token=cloudflare_api_token), "Content-Type": "application/json"}
			body = json.dumps({"type": response.dns_resource_record.type_, "name": response.dns_resource_record.name, "content": response.dns_resource_record.data, "ttl": 1})
			try:
				print("Creating the CNAME record for DNS auth {} on Cloudflare..".format(dns_auth))
				response = requests.post(zone_url, headers=headers, data=body)
				response.raise_for_status()
			except requests.exceptions.HTTPError as e:
				print(e)
	return


# For each certificates (and its chunked domain list) creates a new managed certificate
def create_new_certs():
	current_certs_list = get_current_certs()

	# Creates the required managed certificate, pointing each one to the indexed list of domains.
	# For example if we have certificates c1 and c2 with a chunk size of 100, each certificate may have max 100 domains.
	# So this iteration ensure that c1 points to the first 100 domains and relative dns authorizations, the second to the next 100 and so on
	for index, cert in enumerate(new_certs_list):
		if cert not in current_certs_list :
			print("Creating the new SSL certificate {}..".format(cert))
			certificate = certificate_manager_v1.types.Certificate(
				name = "projects/{project_id}/locations/global/certificates/{cert}".format(project_id=project_id, cert=cert),
				managed = certificate_manager_v1.types.Certificate.ManagedCertificate(
					domains=chunked_domain_list[index],
					dns_authorizations=chunked_dns_auth_list[index]			
				)
			)
			request = certificate_manager_v1.CreateCertificateRequest(
				parent="projects/{project_id}/locations/global".format(project_id=project_id),
				certificate_id=cert,
				certificate=certificate
			)
			client.create_certificate(request=request)
		else:
			print("Certificate {} already exists..".format(cert))


# For each new certificate added, check if ACTIVE or not. If at least one new certificate is not ACTIVE nothing happens.
# If all certificates are ACTIVE then apply the rotation strategy.
# The strategy is the following:
# 1 -  Check if any new certificate is NOT ACTIVE, and if so return False and terminate the process
# 2 -  If all new certificates are ACTIVE start the rotation process
# 3 -  Create (if not exists) a new certificate map entry for each domain and referencing ONLY the certificate containing
#      the corresponding domain (this behaviour is ensured iterating through the chunked list of domains)
# 3a - If the map already exists it already has a domain, it is just updated pointing to the corresponding new active certificate
# 4  - All certificate map entries are collected, and for each one not specified on the new list or the fixed list, they are removed
# 5  - All certificates are collected, and for each one not specified on the new list or the fixed list, they are removed
# 6  - All DNS authorizations are collected, and for each one not specified on the new list or the fixed, list
#      they are removed alongside the corresponding CNAME records on Cloudflare
def check_certificates_status():

	NEW_CERTS_ACTIVE = 1

	# For each new certificate to provision, if status is not ACTIVE exit from the execution
	for cert in new_certs_list:
		request = certificate_manager_v1.GetCertificateRequest(name="projects/{project_id}/locations/global/certificates/{cert}"
				   .format(project_id=project_id,cert=cert))
		certificate = client.get_certificate(request=request)
		if certificate.managed.state is not certificate_manager_v1.types.Certificate.ManagedCertificate.State.ACTIVE:
			NEW_CERTS_ACTIVE = 0

	if NEW_CERTS_ACTIVE == 0:
		print("Some new certs are still provisioning...")
		return False

	# If all new certificates are active update the certificate map entry to use only them
	print("Rotating certificates in all certificate map entries..")

	current_cme = get_current_map_entries()

	for index, cert in enumerate(new_certs_list):
		for domain, cme in zip(chunked_domain_list[index], chunked_cme_list[index]):
			if cme not in current_cme:
				print("Creating the new certificate map entry {} for new domain {}..".format(cme, domain))
				certificate_map_entry = certificate_manager_v1.CertificateMapEntry(
					name = "projects/{project_id}/locations/global/certificateMaps/{certificate_map}/certificateMapEntries/{cme}"
						.format(project_id=project_id,certificate_map=certificate_map,cme=cme),
					certificates = ["projects/{project_id}/locations/global/certificates/{cert}".format(project_id=project_id,cert=cert)],
					hostname = domain
				)
				request = certificate_manager_v1.CreateCertificateMapEntryRequest(
					parent = "projects/{project_id}/locations/global/certificateMaps/{certificate_map}"
					.format(project_id=project_id,certificate_map=certificate_map),
    		    	certificate_map_entry = certificate_map_entry,
					certificate_map_entry_id = cme
				
				)
				client.create_certificate_map_entry(request=request)

			else:
				print("Pointing existing certificate {} map entry to new active certificate..".format(cme))
				certificate_map_entry = certificate_manager_v1.CertificateMapEntry(
					name = "projects/{project_id}/locations/global/certificateMaps/{certificate_map}/certificateMapEntries/{cme}"
						.format(project_id=project_id,certificate_map=certificate_map,cme=cme),
					certificates = ["projects/{project_id}/locations/global/certificates/{cert}".format(project_id=project_id,cert=cert)]
				)
				request = certificate_manager_v1.UpdateCertificateMapEntryRequest(
    		    	certificate_map_entry = certificate_map_entry,
					update_mask = "certificates"
				)
				client.update_certificate_map_entry(request=request)

	# Certificate map entries to delete
	old_cme_list = get_current_map_entries()
	old_cme_list = [cme for cme in old_cme_list if cme not in fixed_cme_list and cme not in new_cme_list]

	# Certificate to delete
	old_certs_list = get_current_certs()
	old_certs_list = [cert for cert in old_certs_list if cert not in fixed_certs_list and cert not in new_certs_list]

	# DNS Authorizations to delete
	old_dns_auths_list = get_current_dns_auths()
	old_dns_auths_list = [dns for dns in old_dns_auths_list if dns not in fixed_dns_auths_list and dns not in new_dns_auths_list]

	# Delete old cme
	for cme in old_cme_list:
		print("Deleting old certificate map entry {}..".format(cme))
		request = certificate_manager_v1.DeleteCertificateMapEntryRequest(
			name = "projects/{project_id}/locations/global/certificateMaps/{certificate_map}/certificateMapEntries/{cme}"
						.format(project_id=project_id,certificate_map=certificate_map,cme=cme)
		)
		client.delete_certificate_map_entry(request=request)
		
	# Wait some time to ensure all certificate map entries are correctly removed and referenced certificates may be removed without errors
	time.sleep(60)
	
	# Delete old certificates and DNS Authorizations
	for cert in old_certs_list:
		print("Deleting old certificate {}..".format(cert))
		request = certificate_manager_v1.DeleteCertificateRequest(
			name="projects/{project_id}/locations/global/certificates/{cert}".format(project_id=project_id, cert=cert)
		)
		client.delete_certificate(request=request)
		

	for dns in old_dns_auths_list:
		dns_name = dns.replace('-', '.')
		dns_tld = tldextract.extract(dns_name)
		dns_tld = "{}.{}".format(dns_tld.domain, dns_tld.suffix)
		zone_id = get_zone_id(dns_tld)
		
		print("Deleting old DNS Authorization {}..".format(dns))
		request = certificate_manager_v1.GetDnsAuthorizationRequest(
        	name="projects/{project_id}/locations/global/dnsAuthorizations/{dns}".format(project_id=project_id, dns=dns),
    	)
		response = client.get_dns_authorization(request=request)

		record_id = get_record_id(zone_id, response.dns_resource_record.name[:-1])

		record_url = "https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}".format(zone_id=zone_id,record_id=record_id)
		headers = {"Authorization": "Bearer {cloudflare_api_token}".format(cloudflare_api_token=cloudflare_api_token), "Content-Type": "application/json"}
		try:
			print("Deleting CNAME record for domain {} on Cloudflare..".format(dns_name))
			response = requests.delete(record_url, headers=headers)
			response.raise_for_status()
		except requests.exceptions.HTTPError as e:
			print(e)

		request = certificate_manager_v1.DeleteDnsAuthorizationRequest(
        	name="projects/{project_id}/locations/global/dnsAuthorizations/{dns}".format(project_id=project_id, dns=dns),
		)
		client.delete_dns_authorization(request=request)

		# Wait some time to not exceed the Cloudflare API rate limits
		time.sleep(2)

	return True


# Cloud Scheduler job is paused since it is not required to check again for certificate status in this rotation cycle
def pause_cloud_scheduler():
	service = discovery.build('cloudscheduler', 'v1')
	cs_job = "projects/{project_id}/locations/{gcp_region}/jobs/{job_id}".format(
			project_id=project_id, gcp_region=gcp_region, job_id=cs_job_id)

	pause_job_request_body = {}
	request = service.projects().locations().jobs().pause(name=cs_job, body=pause_job_request_body)
	request.execute()
	print("Paused cloud scheduler job..")


def rotate_certs(request):
	create_dns_auths()
	create_new_certs()
	if check_certificates_status():
		print("Certificate rotated.. pausing Cloud Scheduler job..")
		#pause_cloud_scheduler()
	else:
		print("Certificates not rotated..")

	return "All done.."