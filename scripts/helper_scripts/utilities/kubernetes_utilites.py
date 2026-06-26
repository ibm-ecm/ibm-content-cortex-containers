###############################################################################
#
# Licensed Materials - Property of IBM
#
# (C) Copyright IBM Corp. 2024. All Rights Reserved.
#
# US Government Users Restricted Rights - Use, duplication or
# disclosure restricted by GSA ADP Schedule Contract with IBM Corp.
#
###############################################################################

import base64
import io
import tarfile
import warnings
from urllib.parse import urlparse

import urllib3
import yaml
from kubernetes import config, client
from kubernetes.client import ApiException
from kubernetes.stream import stream
from requests.exceptions import ConnectTimeout, ConnectionError
from rich.text import Text
from time import sleep


class KubernetesUtilities:
    def __init__(self, logger=None, require_connection=True):
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self._logger = logger
        self._current_namespace = None
        self._connected = False
        self._require_connection = require_connection

        try:
            config.load_incluster_config()
            self._in_cluster = True
            self._current_namespace = self.get_current_namespace()
            self._connected = True
            if self._logger:
                self._logger.info("Running inside the cluster.")
                self._logger.info(f"Current namespace: {self._current_namespace}")
        except Exception as e:
            self._in_cluster = False
            try:
                config.load_kube_config()
                self._current_context = config.list_kube_config_contexts()[1]
                self._current_namespace = self.get_current_namespace()
                self._connected = True
                if self._logger:
                    self._logger.info("Running outside the cluster.")
                    self._logger.info(f"Current context: {self._current_namespace}")
            except Exception as e:
                self._connected = False
                if self._logger:
                    self._logger.warning(f"No Kubernetes connection available: {e}")
                if require_connection:
                    raise
                # Set defaults when no connection is available
                self._current_context = None

        # Only initialize K8s clients if connected
        if self._connected:
            self._core_v1 = client.CoreV1Api()
            self._apps_v1 = client.AppsV1Api()
            self._policy_v1 = client.PolicyV1Api()
            self._rbac_v1 = client.RbacAuthorizationV1Api()
            self._networking_v1 = client.NetworkingV1Api()
            self._auto_scaling_v2 = client.AutoscalingV2Api()
            self._custom_api = client.CustomObjectsApi()
            self._storage_v1 = client.StorageV1Api()
            self._extensions_v1 = client.ApiextensionsV1Api()
            self._version_v1 = client.VersionApi()
        else:
            # Set to None when not connected
            self._core_v1 = None
            self._apps_v1 = None
            self._policy_v1 = None
            self._rbac_v1 = None
            self._networking_v1 = None
            self._auto_scaling_v2 = None
            self._custom_api = None
            self._storage_v1 = None
            self._extensions_v1 = None
            self._version_v1 = None
            
        self._custom_resource = {}
        self._cr_details = {}
        self._operator_details = {}

        self._resource_type_dict = {}

    @property
    def in_cluster(self):
        return self._in_cluster

    @property
    def connected(self):
        """Returns True if Kubernetes connection is available, False otherwise."""
        return self._connected

    @property
    def current_namespace(self):
        return self._current_namespace

    @property
    def resource_type_dict(self):
        return self._resource_type_dict

    @property
    def custom_resource(self):
        return self._custom_resource

    @property
    def cr_details(self):
        return self._cr_details

    @property
    def core_v1(self):
        return self._core_v1

    @property
    def apps_v1(self):
        return self._apps_v1
    
    @property
    def policy_v1(self):
        return self._policy_v1

    @property
    def networking_v1(self):
        return self._networking_v1

    @property
    def auto_scaling_v2(self):
        return self._auto_scaling_v2

    @property
    def custom_api(self):
        return self._custom_api

    @property
    def extensions_v1(self):
        return self._extensions_v1

    @property
    def version_v1(self):
        return self._version_v1
    
    def check_crd_exists(self, crd_name: str) -> bool:
        """
        Check if a CustomResourceDefinition exists in the cluster.
        
        Args:
            crd_name: Full name of the CRD (e.g., 'fncmclusters.fncm.ibm.com')
            
        Returns:
            True if CRD exists, False otherwise
        """
        try:
            self._extensions_v1.read_custom_resource_definition(name=crd_name)
            self._logger.debug(f"CRD exists: {crd_name}")
            return True
        except ApiException as e:
            if e.status == 404:
                self._logger.debug(f"CRD not found: {crd_name}")
                return False
            self._logger.warning(f"API error checking CRD {crd_name}: {e.reason}")
            return False
        except Exception as e:
            self._logger.error(f"Unexpected error checking CRD {crd_name}: {str(e)}")
            return False
    
    def get_crd_info(self, crd_name: str) -> dict:
        """
        Get detailed information about a CRD.
        
        Args:
            crd_name: Full name of the CRD
            
        Returns:
            Dictionary with CRD information or None if not found
        """
        try:
            crd = self._extensions_v1.read_custom_resource_definition(name=crd_name)
            
            # Safely extract version information
            version = 'unknown'
            if crd.spec and crd.spec.versions and len(crd.spec.versions) > 0:
                version = crd.spec.versions[0].name
            
            # Safely extract managed-by label
            managed_by = 'unknown'
            olm_managed = False
            if crd.metadata and crd.metadata.labels:
                managed_by = crd.metadata.labels.get('app.kubernetes.io/managed-by', 'manual')
                # Check for OLM-specific label
                olm_managed = crd.metadata.labels.get('olm.managed', '').lower() == 'true'
            
            # Check field managers for additional ownership info
            field_managers = []
            if crd.metadata and crd.metadata.managed_fields:
                field_managers = [field.manager for field in crd.metadata.managed_fields if field.manager]
            
            info = {
                'name': crd.metadata.name if crd.metadata else crd_name,
                'group': crd.spec.group if crd.spec else 'unknown',
                'version': version,
                'scope': crd.spec.scope if crd.spec else 'unknown',
                'created': crd.metadata.creation_timestamp if crd.metadata else None,
                'managed_by': managed_by,
                'olm_managed': olm_managed,
                'field_managers': field_managers
            }
            
            self._logger.debug(f"Retrieved CRD info for {crd_name}: {info}")
            return info
            
        except ApiException as e:
            if e.status == 404:
                self._logger.debug(f"CRD not found: {crd_name}")
                return None
            self._logger.warning(f"API error getting CRD info for {crd_name}: {e.reason}")
            return None
        except Exception as e:
            self._logger.error(f"Unexpected error getting CRD info for {crd_name}: {str(e)}")
            return None

    def remove_olm_ownership_from_crd(self, crd_name: str) -> bool:
        """
        Remove OLM ownership from a CRD to allow Helm to take over management.
        This removes the 'olm.managed' label and clears conflicting field managers.
        
        Args:
            crd_name: Full name of the CRD
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Read the current CRD
            crd = self._extensions_v1.read_custom_resource_definition(name=crd_name)
            
            # Remove olm.managed label if present
            if crd.metadata and crd.metadata.labels and 'olm.managed' in crd.metadata.labels:
                self._logger.info(f"Removing 'olm.managed' label from CRD {crd_name}")
                del crd.metadata.labels['olm.managed']
            
            # Clear managed_fields to remove field manager conflicts
            # This allows Helm to become the new field manager without conflicts
            if crd.metadata and crd.metadata.managed_fields:
                self._logger.info(f"Clearing managed_fields from CRD {crd_name} to resolve field manager conflicts")
                crd.metadata.managed_fields = None
            
            # Patch the CRD with the updated metadata
            # Using strategic merge patch to update only metadata
            from kubernetes.client.rest import ApiException
            
            body = {
                "metadata": {
                    "labels": crd.metadata.labels if crd.metadata else {},
                    "managedFields": None
                }
            }
            
            self._extensions_v1.patch_custom_resource_definition(
                name=crd_name,
                body=body
            )
            
            self._logger.info(f"Successfully removed OLM ownership from CRD {crd_name}")
            return True
            
        except ApiException as e:
            self._logger.error(f"API error removing OLM ownership from CRD {crd_name}: {e.reason}")
            return False
        except Exception as e:
            self._logger.error(f"Unexpected error removing OLM ownership from CRD {crd_name}: {str(e)}")
            return False

    # Common function to get current namespace when running in-cluster
    def get_current_namespace(self):
        try:
            # Check if inside or outside the cluster
            if self._in_cluster:
                self._logger.info("Getting namespace from in-cluster service account")
                # Read the namespace from the service account secret
                with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace", "r") as f:
                    namespace = f.read().strip()
                self._logger.info(f"In-cluster namespace: {namespace}")
            else:
                self._logger.info("Not running inside the cluster.")
                namespace = self._current_context['context']['namespace']
                self._logger.info(f"Current context namespace: {namespace}")

            return namespace
        except Exception as e:
            self._logger.info(f"Error getting namespace: {e}")
            return None

    # Function to collect all user-created configmaps
    def calculate_user_configmaps(self, components=list):
        configmaps = set()
        cr = self._custom_resource
        cr_keys = cr["spec"].keys()

        # Collect configmaps from ecm_configuration
        ecm_components = ["cpe", "css", "cmis", "graphql", "es", "tm"]

        if any(e in ecm_components for e in components):
            try:
                for component in ecm_components:
                    section_name = f"{component}_production_setting"
                    if cr["spec"]["ecm_configuration"][component][section_name].get("custom_configmap"):
                        for item in cr["spec"]["ecm_configuration"][component][section_name]["custom_configmap"]:
                            if "name" in item.keys():
                                configmaps.add(item["name"])
                    else:
                        self._logger.info(f"No {component} Configmaps found")
            except Exception as e:
                self._logger.info(f"No ECM Configmaps found")

        # Collect configmaps from ban
        try:
            if "ban" in components:
                if cr["spec"]["navigator_configuration"]["icn_production_setting"].get("custom_configmap"):
                    for item in cr["spec"]["navigator_configuration"]["icn_production_setting"]["custom_configmap"]:
                        if "name" in item.keys():
                            configmaps.add(item["name"])
            else:
                self._logger.info(f"No BAN Configmaps found")
        except Exception as e:
            self._logger.info(f"No BAN Configmaps found")

        # Collect configmaps from ier
        try:
            if "ier" in components:
                if cr["spec"]["ier_configuration"]["ier_production_setting"].get("custom_configmap"):
                    for item in cr["spec"]["ier_configuration"]["ier_production_setting"]["custom_configmap"]:
                        if "name" in item.keys():
                            configmaps.add(item["name"])
            else:
                self._logger.info(f"No IER Configmaps found")
        except Exception as e:
            self._logger.info(f"No IER Configmaps found")

        # Collect configmaps from iccsap
        try:
            if "iccsap" in components:
                if cr["spec"]["iccsap_configuration"]["iccsap_production_setting"].get("custom_configmap"):
                    for item in cr["spec"]["iccsap_configuration"]["iccsap_production_setting"]["custom_configmap"]:
                        if "name" in item.keys():
                            configmaps.add(item["name"])
            else:
                self._logger.info(f"No ICCSAP Configmaps found")
        except Exception as e:
            self._logger.info(f"No ICCSAP Configmaps found")

        # Collect configmaps from ccxmo
        try:
            if "ccxmo" in components:
                if cr["spec"]["ccxmo_configuration"]["ccxmo_production_setting"].get("custom_configmap"):
                    for item in cr["spec"]["ccxmo_configuration"]["ccxmo_production_setting"]["custom_configmap"]:
                        if "name" in item.keys():
                            configmaps.add(item["name"])
            else:
                self._logger.info(f"No CCXMO Configmaps found")
        except Exception as e:
            self._logger.info(f"No CCXMO Configmaps found")

        return list(configmaps)

    # Function to collect all user-created secrets
    def calculate_user_secrets(self, components=list):
        secrets = set()
        cr = self._custom_resource
        cr_keys = cr["spec"].keys()

        # Collect different sections from the CR
        # LDAP Secrets
        # Get all LDAP Sections
        result = filter(lambda x: str(x).startswith("ldap_configuration"), cr_keys)
        ldap_sections = list(result)
        for section in ldap_sections:
            if cr["spec"][section].get("lc_bind_secret"):
                secrets.add(cr["spec"][section]["lc_bind_secret"])

            if cr["spec"][section].get("lc_ldap_ssl_enabled"):
                if cr["spec"][section]["lc_ldap_ssl_enabled"]:
                    secrets.add(cr["spec"][section]["lc_ldap_ssl_secret_name"])

        # DB Secrets
        db_ssl = False
        if cr["spec"]['datasource_configuration'].get("dc_ssl_enabled"):
            if cr["spec"]['datasource_configuration']["dc_ssl_enabled"]:
                db_ssl = True

        if db_ssl:
            for section in cr["spec"]["datasource_configuration"].keys():
                if isinstance(cr["spec"]["datasource_configuration"][section], list):
                    for item in cr["spec"]["datasource_configuration"][section]:
                        if "database_ssl_secret_name" in item.keys():
                            secrets.add(item["database_ssl_secret_name"])
                elif isinstance(cr["spec"]["datasource_configuration"][section], dict):
                    if "database_ssl_secret_name" in cr["spec"]["datasource_configuration"][section].keys():
                        secrets.add(cr["spec"]["datasource_configuration"][section]["database_ssl_secret_name"])

        # ECM Secrets
        ecm_components = ["cpe", "css", "cmis", "graphql", "es", "tm"]
        if any(e in ecm_components for e in components):
            try:
                if cr["spec"]["ecm_configuration"].get("fncm_secret_name"):
                    secrets.add(cr["spec"]["ecm_configuration"].get("fncm_secret_name"))
                else:
                    secrets.add("ibm-fncm-secret")
            except Exception as e:
                self._logger.info(f"No ECM Secret found")
                secrets.add("ibm-fncm-secret")

        # CSS Secrets
        try:
            if "css" in components:
                if cr["spec"]["ecm_configuration"]["css"]["css_production_setting"].get("icc"):
                    if cr["spec"]["ecm_configuration"]["css"]["css_production_setting"]["icc"].get("icc_enabled"):
                        if cr["spec"]["ecm_configuration"]["css"]["css_production_setting"]["icc"]["icc_enabled"]:
                            secrets.add(cr["spec"]["ecm_configuration"]["css"]["css_production_setting"]["icc"][
                                            "icc_secret_name"])
                            secrets.add(cr["spec"]["ecm_configuration"]["css"]["css_production_setting"]["icc"][
                                            "secret_masterkey_name"])
        except Exception as e:
            self._logger.info(f"No ICC Secret found")

        # BAN Secrets
        try:
            if "ban" in components:
                if cr["spec"]["navigator_configuration"].get("ban_secret_name"):
                    secrets.add(cr["spec"]["navigator_configuration"].get("ban_secret_name"))
        except Exception as e:
            self._logger.info(f"No BAN Secret found")
            secrets.add("ibm-ban-secret")

        # IER Secrets
        try:
            if "ier" in components:
                if cr["spec"]["ier_configuration"].get("ier_secret_name"):
                    secrets.add(cr["spec"]["ier_configuration"].get("ier_secret_name"))
                else:
                    secrets.add("ibm-ier-secret")
        except Exception as e:
            self._logger.info(f"No IER Secret found")
            secrets.add("ibm-ier-secret")

        # ICCSAP Secrets
        try:
            if "iccsap" in components:
                if cr["spec"]["iccsap_configuration"].get("iccsap_secret_name"):
                    secrets.add(cr["spec"]["iccsap_configuration"].get("iccsap_secret_name"))
                else:
                    secrets.add("ibm-iccsap-secret")
        except Exception as e:
            self._logger.info(f"No ICCSAP Secret found")
            secrets.add("ibm-iccsap-secret")

        # Trusted Certificates
        try:
            if cr["spec"]["shared_configuration"].get("trusted_certificate_list"):
                for cert_secret in cr["spec"]["shared_configuration"]["trusted_certificate_list"]:
                    secrets.add(cert_secret)
        except Exception as e:
            self._logger.info(f"No trusted certificates found")

        # OIDC Secrets
        try:
            if cr["spec"]["shared_configuration"].get("open_id_connect_providers"):
                for item in cr["spec"]["shared_configuration"]["open_id_connect_providers"]:
                    if "client_oidc_secret" in item.keys():
                        for secret in item["client_oidc_secret"].values():
                            secrets.add(secret)
        except Exception as e:
            self._logger.info(f"No OIDC Secrets found")

        # SCIM Secrets
        try:
            if cr["spec"]["initialize_configuration"].get("scim_configuration"):
                for item in cr["spec"]["initialize_configuration"]["scim_configuration"]:
                    secrets.add(item["scim_secret_name"])
        except Exception as e:
            self._logger.info(f"No SCIM Secrets found")

        return list(secrets)

    # Function to calculate the deployed components
    def calculate_deployed_components(self):
        try:
            components = set()
            cr = self._custom_resource
            cr_keys = cr["spec"].keys()

            # TODO: Validate component names

            # Collect different sections from the CR

            if "content_optional_components" in cr_keys:
                for item, value in cr["spec"]["content_optional_components"].items():
                    if bool(value):
                        components.add(item)

            if "sc_deployment_patterns" in cr["spec"]["shared_configuration"].keys():
                if cr["spec"]["shared_configuration"]["sc_deployment_patterns"].lower() == "content":
                    components.add("cpe")
                    components.add("graphql")
                    components.add("ban")

            if "sc_optional_components" in cr["spec"]["shared_configuration"].keys():
                optional_list = cr["spec"]["shared_configuration"]["sc_optional_components"]
                optional = optional_list.split(",")
                for item in optional:
                    components.add(item)

            # Collect individual components from the CR
            if "ecm_configuration" in cr_keys:
                if "cpe" in cr["spec"]["ecm_configuration"].keys():
                    components.add("cpe")

                if "css" in cr["spec"]["ecm_configuration"].keys():
                    components.add("css")

                if "cmis" in cr["spec"]["ecm_configuration"].keys():
                    components.add("cmis")

                if "graphql" in cr["spec"]["ecm_configuration"].keys():
                    components.add("graphql")

                if "es" in cr["spec"]["ecm_configuration"].keys():
                    components.add("es")

                if "tm" in cr["spec"]["ecm_configuration"].keys():
                    components.add("tm")

            if "navigator_configuration" in cr_keys:
                components.add("ban")

            if "ier_configuration" in cr_keys:
                components.add("ier")

            if "iccsap_configuration" in cr_keys:
                components.add("iccsap")

            return list(components)

        except Exception as e:
            self._logger.exception(f"Exception calculating deployed components: {str(e)}")
            return []
    
    def get_fncm_cluster_cr(self, namespace: str, cr_name: str = None) -> dict:
        """
        Get FNCMCluster Custom Resource from the specified namespace.
        
        Args:
            namespace: Kubernetes namespace to search
            cr_name: Optional specific CR name. If None, returns the first found CR.
            
        Returns:
            Dictionary containing the CR data, or None if not found
        """
        try:
            if not self._connected:
                self._logger.warning("No Kubernetes connection available")
                return None
                
            group = "fncm.ibm.com"
            version = "v1"
            plural = "fncmclusters"
            
            if cr_name:
                # Get specific CR by name
                try:
                    cr = self._custom_api.get_namespaced_custom_object(
                        group=group,
                        version=version,
                        namespace=namespace,
                        plural=plural,
                        name=cr_name
                    )
                    self._logger.info(f"Found FNCMCluster CR: {cr_name} in namespace: {namespace}")
                    return cr
                except ApiException as e:
                    if e.status == 404:
                        self._logger.debug(f"FNCMCluster CR not found: {cr_name}")
                        return None
                    raise
            else:
                # List all CRs in namespace and return first one
                try:
                    cr_list = self._custom_api.list_namespaced_custom_object(
                        group=group,
                        version=version,
                        namespace=namespace,
                        plural=plural
                    )
                    
                    if cr_list and 'items' in cr_list and len(cr_list['items']) > 0:
                        cr = cr_list['items'][0]
                        cr_name = cr.get('metadata', {}).get('name', 'unknown')
                        self._logger.info(f"Found FNCMCluster CR: {cr_name} in namespace: {namespace}")
                        return cr
                    else:
                        self._logger.debug(f"No FNCMCluster CRs found in namespace: {namespace}")
                        return None
                except ApiException as e:
                    if e.status == 404:
                        self._logger.debug(f"FNCMCluster CRD not installed or no CRs in namespace: {namespace}")
                        return None
                    raise
                    
        except Exception as e:
            self._logger.error(f"Error retrieving FNCMCluster CR: {str(e)}")
            return None
    
    def list_fncm_cluster_crs(self, namespace: str) -> list:
        """
        List all FNCMCluster Custom Resources in the specified namespace.
        
        Args:
            namespace: Kubernetes namespace to search
            
        Returns:
            List of CR names, or empty list if none found
        """
        try:
            if not self._connected:
                self._logger.warning("No Kubernetes connection available")
                return []
                
            group = "fncm.ibm.com"
            version = "v1"
            plural = "fncmclusters"
            
            cr_list = self._custom_api.list_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural=plural
            )
            
            if cr_list and 'items' in cr_list:
                names = [item.get('metadata', {}).get('name', '') for item in cr_list['items']]
                names = [n for n in names if n]  # Filter out empty names
                self._logger.info(f"Found {len(names)} FNCMCluster CR(s) in namespace: {namespace}")
                return names
            else:
                self._logger.debug(f"No FNCMCluster CRs found in namespace: {namespace}")
                return []
                
        except ApiException as e:
            if e.status == 404:
                self._logger.debug(f"FNCMCluster CRD not installed or no CRs in namespace: {namespace}")
                return []
            elif e.status == 403:
                # Permission denied - log as warning since this is expected when user lacks permissions
                # The gather script will show a user-friendly message about migration not being available
                self._logger.warning(f"Insufficient permissions to list FNCMCluster CRs in namespace {namespace}: {e.reason}")
                return []
            else:
                # Other API errors - log as error
                self._logger.error(f"API error listing FNCMCluster CRs: {e.reason}")
                return []
        except Exception as e:
            self._logger.error(f"Error listing FNCMCluster CRs: {str(e)}")
            return []
    
    def download_certificate_from_secret(self, secret_name: str, namespace: str, cert_key: str = 'tls.crt') -> str:
        """
        Download certificate from a Kubernetes secret.
        
        Args:
            secret_name: Name of the secret containing the certificate
            namespace: Namespace where the secret exists
            cert_key: Key in the secret data (default: 'tls.crt')
            
        Returns:
            Certificate content as string, or empty string if not found
        """
        try:
            if not self._connected:
                self._logger.warning("No Kubernetes connection available for certificate download")
                return ""
            
            secret = self._core_v1.read_namespaced_secret(
                name=secret_name,
                namespace=namespace
            )
            
            if secret and secret.data:
                # Try the specified key first
                cert_data = secret.data.get(cert_key)
                
                # If not found, try common certificate keys
                if not cert_data:
                    for key in ['tls.crt', 'ca.crt', 'cert', 'certificate']:
                        cert_data = secret.data.get(key)
                        if cert_data:
                            self._logger.info(f"Found certificate in secret {secret_name} under key: {key}")
                            break
                
                if cert_data:
                    # Decode base64 certificate data
                    import base64
                    cert_content = base64.b64decode(cert_data).decode('utf-8')
                    self._logger.info(f"Successfully downloaded certificate from secret: {secret_name}")
                    return cert_content
                else:
                    self._logger.warning(f"No certificate data found in secret: {secret_name}")
                    return ""
            else:
                self._logger.warning(f"Secret {secret_name} has no data")
                return ""
                
        except ApiException as e:
            if e.status == 404:
                self._logger.warning(f"Secret not found: {secret_name}")
            else:
                self._logger.error(f"API error reading secret {secret_name}: {e.reason}")
            return ""
        except Exception as e:
            self._logger.error(f"Error downloading certificate from secret {secret_name}: {str(e)}")
            return ""
    
    def _decode_xor_password(self, encoded_value: str) -> str:
        """
        Decode XOR-encoded password from Liberty format.
        Format: {xor}base64_encoded_value
        """
        if not encoded_value or not encoded_value.startswith('{xor}'):
            return encoded_value
        
        try:
            # Remove {xor} prefix and decode base64
            xor_encoded = encoded_value[5:]
            decoded_bytes = base64.b64decode(xor_encoded)
            
            # XOR decode with Liberty's key
            result = bytearray()
            for byte in decoded_bytes:
                result.append(byte ^ 0x5F)  # Liberty uses 0x5F as XOR key
            
            return result.decode('utf-8')
        except Exception as e:
            self._logger.warning(f"Failed to decode XOR password: {str(e)}")
            return encoded_value
    
    def extract_ai_services_settings_from_fncm_cr(self, cr: dict) -> dict:
        """
        Extract AI Services integration settings from an FNCMCluster CR.
        
        Args:
            cr: FNCMCluster Custom Resource dictionary
            
        Returns:
            Dictionary containing extracted settings for AI Services integration
        """
        try:
            settings = {
                'found': False,
                'namespace': None,
                'cr_name': None,
                'graphql_endpoint': None,
                'graphql_root_ca_secret': None,
                'object_store': None,
                'navigator_url': None,
                'navigator_url_source': None,
                'idp_config': {},
                'has_graphql': False,
                'has_cpe': False,
                'has_ban': False,
                'version': None,
                'version_compatible': False,
                'platform': None,
                'storage_class': None,
                'ingress_enabled': None,
                'ingress_source': None,
                'ingress_hostname': None,
                'ingress_tls_secret': None,
                'ingress_annotations': None,
                'service_type': None,
                'recommendations': []
            }
            
            if not cr:
                return settings
            
            # Extract metadata
            metadata = cr.get('metadata', {})
            settings['cr_name'] = metadata.get('name')
            settings['namespace'] = metadata.get('namespace')
            
            spec = cr.get('spec', {})
            
            # Check for deployed components
            components = set()
            
            # Check shared configuration for deployment pattern
            shared_config = spec.get('shared_configuration', {})
            
            # Extract platform and storage class
            settings['platform'] = shared_config.get('sc_deployment_platform', '')
            settings['storage_class'] = shared_config.get('storage_configuration', {}).get('sc_slow_file_storage_classname', '')
            
            # Extract ingress configuration based on platform
            # For OCP, ingress is not used (routes are used instead)
            # For CNCF/other platforms, check if ingress is enabled
            if settings['platform']:
                if settings['platform'].upper() == 'OCP':
                    settings['ingress_enabled'] = False
                    settings['ingress_source'] = 'Platform (OCP uses Routes)'
                    self._logger.info("Platform is OCP - ingress disabled (uses Routes)")
                else:
                    # For CNCF platforms, check if ingress is configured
                    # Look for ingress configuration in various possible locations
                    ingress_enabled = False
                    ingress_source = 'Not configured'
                    
                    # Check shared_configuration for ingress settings
                    if 'sc_ingress_enable' in shared_config:
                        ingress_enabled = shared_config.get('sc_ingress_enable', False)
                        ingress_source = 'shared_configuration.sc_ingress_enable'
                        self._logger.info(f"Found ingress setting in shared_configuration: {ingress_enabled}")
                    
                    # Check navigator_configuration for ingress
                    nav_config = spec.get('navigator_configuration', {})
                    if nav_config and 'ingress' in nav_config:
                        nav_ingress = nav_config.get('ingress', {})
                        if isinstance(nav_ingress, dict) and nav_ingress.get('enabled') is not None:
                            ingress_enabled = nav_ingress.get('enabled', False)
                            ingress_source = 'navigator_configuration.ingress.enabled'
                            self._logger.info(f"Found ingress setting in navigator_configuration: {ingress_enabled}")
                    
                    # Check ecm_configuration for ingress (GraphQL or CPE)
                    if not ingress_enabled:
                        graphql_config = ecm_config.get('graphql', {})
                        if graphql_config and 'ingress' in graphql_config:
                            graphql_ingress = graphql_config.get('ingress', {})
                            if isinstance(graphql_ingress, dict) and graphql_ingress.get('enabled') is not None:
                                ingress_enabled = graphql_ingress.get('enabled', False)
                                ingress_source = 'ecm_configuration.graphql.ingress.enabled'
                                self._logger.info(f"Found ingress setting in GraphQL configuration: {ingress_enabled}")
                    
                    settings['ingress_enabled'] = ingress_enabled
                    settings['ingress_source'] = ingress_source
                    
                    # Extract additional ingress settings if ingress is enabled
                    if ingress_enabled:
                        # Extract hostname
                        hostname = shared_config.get('sc_deployment_hostname_suffix')
                        if hostname:
                            settings['ingress_hostname'] = hostname
                            self._logger.info(f"Found ingress hostname: {hostname}")
                        
                        # Extract TLS secret name
                        tls_secret = shared_config.get('sc_ingress_tls_secret_name')
                        if tls_secret and tls_secret != '<Required>':
                            settings['ingress_tls_secret'] = tls_secret
                            self._logger.info(f"Found ingress TLS secret: {tls_secret}")
                        
                        # Extract ingress annotations
                        # Annotations in CR can be either strings or dicts, convert to "key: value" string format
                        annotations = shared_config.get('sc_ingress_annotations')
                        if annotations and isinstance(annotations, list) and len(annotations) > 0:
                            converted_annotations = []
                            for annotation in annotations:
                                if isinstance(annotation, dict):
                                    # Convert dict to "key: value" string format
                                    for key, value in annotation.items():
                                        converted_annotations.append(f"{key}: {value}")
                                elif isinstance(annotation, str):
                                    # Already in string format
                                    converted_annotations.append(annotation)
                            
                            if converted_annotations:
                                settings['ingress_annotations'] = converted_annotations
                                self._logger.info(f"Found {len(converted_annotations)} ingress annotations")
                        
                        # Extract service type
                        service_type = shared_config.get('sc_service_type')
                        if service_type:
                            settings['service_type'] = service_type
                            self._logger.info(f"Found service type: {service_type}")
                        
                        self._logger.info(f"Ingress is enabled for CNCF platform (source: {ingress_source})")
                    else:
                        self._logger.info(f"Ingress not enabled or not configured for CNCF platform")
            else:
                # Platform not specified - cannot determine ingress setting
                settings['ingress_enabled'] = None
                settings['ingress_source'] = 'Platform not specified'
                self._logger.warning("Platform not specified in FNCMCluster CR - cannot determine ingress configuration")
            
            if shared_config.get('sc_deployment_patterns', '').lower() == 'content':
                components.add('cpe')
                components.add('graphql')
                components.add('ban')
            
            # Check optional components
            optional_components_str = shared_config.get('sc_optional_components', '')
            if optional_components_str:
                for comp in optional_components_str.split(','):
                    components.add(comp.strip())
            
            # Check ECM configuration
            ecm_config = spec.get('ecm_configuration', {})
            if 'graphql' in ecm_config:
                components.add('graphql')
            if 'cpe' in ecm_config:
                components.add('cpe')
            
            # Check Navigator configuration
            if 'navigator_configuration' in spec:
                components.add('ban')
            
            settings['has_graphql'] = 'graphql' in components
            settings['has_cpe'] = 'cpe' in components
            settings['has_ban'] = 'ban' in components
            
            # Only proceed if we have the necessary components
            if not (settings['has_graphql'] and settings['has_cpe']):
                self._logger.info("FNCMCluster CR does not have required components (GraphQL and CPE) for AI Services")
                return settings
            
            # Check Content Cortex version using appVersion - AI Services requires 26.0.0+
            # The appVersion field is located at spec.appVersion
            app_version = spec.get('appVersion', '')
            
            settings['version'] = app_version if app_version else 'Unknown'
            
            # Parse version and check compatibility (26.0.0 or higher)
            if app_version and app_version != 'Unknown':
                try:
                    # Extract major.minor from version string (ignore patch and any suffixes)
                    version_parts = app_version.strip().split('.')
                    if len(version_parts) >= 2 and version_parts[0] and version_parts[1]:
                        # Parse major and minor, handling any non-numeric suffixes
                        major_str = version_parts[0].split('-')[0].split('_')[0].strip()
                        minor_str = version_parts[1].split('-')[0].split('_')[0].strip()
                        
                        if major_str and minor_str:
                            major = int(major_str)
                            minor = int(minor_str)
                            
                            # Check if version is 26.0 or higher (26.0.0, 26.0.1, 26.1.0, 27.0.0, etc.)
                            if major > 26 or (major == 26 and minor >= 0):
                                settings['version_compatible'] = True
                                self._logger.info(f"Version {app_version} is compatible with AI Services (>= 26.0.0)")
                            else:
                                settings['version_compatible'] = False
                                settings['recommendations'].append({
                                    'type': 'critical',
                                    'message': f'Content Cortex version {app_version} detected. AI Services requires version 26.0.0 or higher.',
                                    'action': 'Upgrade Content Cortex deployment to version 26.0.0 before integrating AI Services'
                                })
                        else:
                            raise ValueError("Empty version components")
                    else:
                        raise ValueError("Insufficient version parts")
                except (ValueError, AttributeError, IndexError) as e:
                    settings['version_compatible'] = False
                    settings['recommendations'].append({
                        'type': 'warning',
                        'message': f'Could not parse version "{app_version}". AI Services requires version 26.0.0 or higher.',
                        'action': 'Verify Content Cortex version is 26.0.0 or higher. Check the appVersion field in your FNCMCluster CR.'
                    })
                    self._logger.warning(f"Version parsing error for '{app_version}': {str(e)}")
            else:
                settings['version_compatible'] = False
                settings['recommendations'].append({
                    'type': 'warning',
                    'message': 'No version information found in FNCMCluster CR. AI Services requires version 26.0.0 or higher.',
                    'action': 'Add appVersion field to shared_configuration in your FNCMCluster CR (e.g., appVersion: "26.0.0")'
                })
                self._logger.warning("No version found in FNCMCluster CR - checked appVersion and sc_deployment_fncm_version")
            
            # Extract GraphQL endpoint and certificate
            if settings['has_graphql']:
                namespace = settings['namespace']
                # Use internal service URL for GraphQL
                settings['graphql_endpoint'] = f"https://content-graphql-svc.{namespace}.svc.cluster.local:9443"
                
                # Extract GraphQL root CA certificate secret name
                # Certificate will be downloaded after property folders are created
                root_ca_secret = shared_config.get('root_ca_secret', '')
                if root_ca_secret:
                    settings['graphql_root_ca_secret'] = root_ca_secret
                    self._logger.info(f"Found GraphQL root CA secret: {root_ca_secret}")
                    settings['recommendations'].append({
                        'type': 'info',
                        'message': f'GraphQL SSL certificate will be automatically downloaded from secret: {root_ca_secret}',
                        'action': f'Certificate will be saved to: propertyFile/{namespace}/ssl-certs/graphql/{root_ca_secret}.crt'
                    })
                else:
                    settings['recommendations'].append({
                        'type': 'warning',
                        'message': 'No root_ca_secret found in Content deployment',
                        'action': 'Manually provide GraphQL SSL certificate in propertyFile/<namespace>/ssl-certs/graphql/'
                    })
            
            # Extract Object Store information
            datasource_config = spec.get('datasource_configuration', {})
            os_datasources = datasource_config.get('dc_os_datasources', [])
            if os_datasources and len(os_datasources) > 0:
                # Use the first object store
                first_os = os_datasources[0]
                settings['object_store'] = first_os.get('dc_os_label', 'OS1')
            else:
                # Default to OS1
                settings['object_store'] = 'OS1'
            
            # Extract Navigator external URL from CR status endpoints or access-info configmap
            if settings['has_ban']:
                nav_url = None
                nav_source = None
                
                # Try to get from CR status endpoints first
                # Look for "Navigator Login URL for FNCM" with scope "External" and type "UI"
                status = cr.get('status', {})
                endpoints = status.get('endpoints', [])
                for endpoint in endpoints:
                    endpoint_name = endpoint.get('name', '')
                    endpoint_scope = endpoint.get('scope', '')
                    endpoint_type = endpoint.get('type', '')
                    
                    # Look for Navigator endpoint with External scope and UI type
                    if ('navigator' in endpoint_name.lower() and
                        endpoint_scope.lower() == 'external' and
                        endpoint_type.lower() == 'ui'):
                        nav_url = endpoint.get('uri', '')
                        nav_source = 'CR Status Endpoints'
                        self._logger.info(f"Found Navigator URL in CR status: {nav_url}")
                        break
                
                # Validate the URL and extract hostname only
                if nav_url:
                    try:
                        parsed = urlparse(nav_url)
                        if not parsed.scheme or not parsed.netloc:
                            self._logger.warning(f"Navigator URL from CR status is not a valid URL: {nav_url}")
                            nav_url = None
                            nav_source = None
                        else:
                            # Extract only scheme and hostname, remove path
                            hostname_url = f"{parsed.scheme}://{parsed.netloc}"
                            nav_url = hostname_url
                            self._logger.info(f"Extracted Navigator hostname: {hostname_url}")
                    except Exception as e:
                        self._logger.warning(f"Error validating Navigator URL: {str(e)}")
                        nav_url = None
                        nav_source = None
                
                # If not found or invalid, try to get from <cr-name>-fncm-access-info configmap
                if not nav_url:
                    try:
                        cr_name = settings['cr_name']
                        configmap_name = f"{cr_name}-fncm-access-info"
                        configmap = self._core_v1.read_namespaced_config_map(
                            name=configmap_name,
                            namespace=settings['namespace']
                        )
                        if configmap and configmap.data:
                            # Look for navigator-access-info key
                            nav_access_info = configmap.data.get('navigator-access-info', '')
                            if nav_access_info:
                                # Extract hostname only
                                try:
                                    parsed = urlparse(nav_access_info)
                                    if parsed.scheme and parsed.netloc:
                                        hostname_url = f"{parsed.scheme}://{parsed.netloc}"
                                        nav_url = hostname_url
                                        self._logger.info(f"Extracted Navigator hostname from configmap: {hostname_url}")
                                    else:
                                        nav_url = nav_access_info
                                except Exception:
                                    nav_url = nav_access_info  # Use original if parsing fails
                                nav_source = f'{configmap_name} ConfigMap'
                                self._logger.info(f"Found Navigator URL in access-info configmap: {nav_url}")
                    except Exception as e:
                        self._logger.debug(f"Could not read {configmap_name} configmap: {str(e)}")
                
                if nav_url:
                    settings['navigator_url'] = nav_url
                    settings['navigator_url_source'] = nav_source
                else:
                    settings['navigator_url'] = '<Required>'
                    settings['navigator_url_source'] = 'Not detected'
                    settings['recommendations'].append({
                        'type': 'warning',
                        'message': 'Navigator external URL could not be automatically detected',
                        'action': 'Manually provide the external Navigator URL in the property file'
                    })
            
            # Extract IDP/OIDC configuration and add audience recommendation
            oidc_providers = shared_config.get('open_id_connect_providers', [])
            if oidc_providers and len(oidc_providers) > 0:
                idp = oidc_providers[0]
                provider_name = idp.get('provider_name', '')
                discovery_url = idp.get('discovery_endpoint_url', '')
                
                # Initialize IDP config with discovery URL
                settings['idp_config'] = {
                    'provider_name': provider_name,
                    'discovery_url': discovery_url,
                    'client_id': '<From Secret>',
                    'client_secret': '<From Secret>',
                    'ssl_enabled': True
                }
                
                # Try to extract client credentials from the OIDC secret
                # The client_oidc_secret structure can be:
                # 1. {'cpe': 'secret-name', 'nav': 'secret-name'} - component-specific secrets
                # 2. {'client_id_secret': 'secret-name', 'client_secret': 'secret-name'} - credential-specific
                # 3. Direct string value
                client_oidc_secret = idp.get('client_oidc_secret', {})
                if client_oidc_secret:
                    self._logger.info(f"Found client_oidc_secret configuration: {client_oidc_secret}")
                    
                    # Get the secret name - try different possible keys
                    secret_name = None
                    if isinstance(client_oidc_secret, dict):
                        # Try component-specific keys first (cpe, nav, graphql, etc.)
                        for key in ['cpe', 'nav', 'graphql', 'client_id_secret', 'client_secret', 'secret_name']:
                            if key in client_oidc_secret:
                                secret_name = client_oidc_secret[key]
                                self._logger.info(f"Found secret name '{secret_name}' under key '{key}'")
                                break
                        
                        # If no specific key found, try to get any value from the dict
                        if not secret_name and client_oidc_secret:
                            secret_name = list(client_oidc_secret.values())[0]
                            self._logger.info(f"Using first secret value: {secret_name}")
                    elif isinstance(client_oidc_secret, str):
                        # Sometimes it might be a direct string
                        secret_name = client_oidc_secret
                        self._logger.info(f"client_oidc_secret is a string: {secret_name}")
                    
                    if secret_name and self._core_v1:
                        self._logger.info(f"Attempting to read OIDC secret: {secret_name} from namespace: {settings['namespace']}")
                        try:
                            secret = self._core_v1.read_namespaced_secret(
                                name=secret_name,
                                namespace=settings['namespace']
                            )
                            
                            self._logger.info(f"Successfully read secret {secret_name}, checking for data...")
                            if secret and secret.data:
                                self._logger.info(f"Secret {secret_name} has data, keys available: {list(secret.data.keys())}")
                                # Extract client_id
                                if 'client_id' in secret.data:
                                    client_id_b64 = secret.data['client_id']
                                    client_id = base64.b64decode(client_id_b64).decode('utf-8')
                                    # Decode XOR if needed
                                    client_id = self._decode_xor_password(client_id)
                                    settings['idp_config']['client_id'] = client_id
                                    self._logger.info(f"Extracted client_id from secret: {secret_name}")
                                
                                # Extract client_secret
                                if 'client_secret' in secret.data:
                                    client_secret_b64 = secret.data['client_secret']
                                    client_secret = base64.b64decode(client_secret_b64).decode('utf-8')
                                    # Decode XOR if needed
                                    client_secret = self._decode_xor_password(client_secret)
                                    settings['idp_config']['client_secret'] = client_secret
                                    self._logger.info(f"Extracted client_secret from secret: {secret_name}")
                                
                                # Store secret name for reference
                                settings['idp_config']['secret_name'] = secret_name
                            else:
                                self._logger.warning(f"Secret {secret_name} exists but has no data or data is None")
                                settings['recommendations'].append({
                                    'type': 'warning',
                                    'message': f'Secret "{secret_name}" exists but contains no data',
                                    'action': 'Verify the secret has client_id and client_secret keys, or manually provide credentials in the IDP property file'
                                })
                        except Exception as e:
                            error_msg = str(e)
                            self._logger.warning(f"Could not read OIDC secret {secret_name}: {error_msg}")
                            
                            # Provide more specific guidance based on error type
                            if "not found" in error_msg.lower() or "404" in error_msg:
                                action = f'The secret "{secret_name}" was not found in namespace "{settings["namespace"]}". Verify the secret name in your FNCMCluster CR or manually provide client_id and client_secret in the IDP property file'
                            elif "forbidden" in error_msg.lower() or "403" in error_msg:
                                action = f'Permission denied reading secret "{secret_name}". Ensure you have proper RBAC permissions or manually provide client_id and client_secret in the IDP property file'
                            else:
                                action = f'Error reading secret "{secret_name}": {error_msg}. Manually provide client_id and client_secret in the IDP property file'
                            
                            settings['recommendations'].append({
                                'type': 'warning',
                                'message': f'Could not automatically extract client credentials from secret: {secret_name}',
                                'action': action
                            })
                    else:
                        if not secret_name:
                            self._logger.warning(f"No secret name found in client_oidc_secret structure: {client_oidc_secret}")
                        if not self._core_v1:
                            self._logger.warning("No Kubernetes core_v1 API client available")
                
                # Validate discovery URL format
                if discovery_url:
                    if not discovery_url.endswith('.well-known/openid-configuration'):
                        settings['recommendations'].append({
                            'type': 'warning',
                            'message': f'Discovery URL may be incomplete: {discovery_url}',
                            'action': 'Verify the discovery URL ends with .well-known/openid-configuration'
                        })
                else:
                    settings['recommendations'].append({
                        'type': 'warning',
                        'message': 'No IDP discovery URL found in FNCMCluster CR',
                        'action': 'Manually provide the IDP discovery endpoint URL'
                    })
                
                # Add recommendation about IDP audience configuration with CR example
                # Use the extracted client_id if available, otherwise use placeholder
                ai_client_id = settings['idp_config'].get('client_id', '<ai-services-client-id>')
                
                # Create YAML snippet for the recommendation
                # Note: audiences is a single string value, not a list
                yaml_snippet = f"""
    open_id_connect_providers:
      - provider_name: {provider_name}
        audiences: {ai_client_id}
        # ... other IDP configuration ..."""
                
                # Customize message based on whether we have the actual client_id
                if settings['idp_config'].get('client_id') and settings['idp_config']['client_id'] != '<From Secret>':
                    action_msg = f'Update your FNCMCluster CR to include the AI Services client ID in the audiences field:\n{yaml_snippet}\n\nNote: Using extracted client_id "{ai_client_id}" from the OIDC secret. If this is not the AI Services client ID, replace it with the correct value.'
                else:
                    action_msg = f'Update your FNCMCluster CR to include the AI Services client ID in the audiences field:\n{yaml_snippet}\n\nReplace <ai-services-client-id> with your actual AI Services OIDC client ID'
                
                settings['recommendations'].append({
                    'type': 'important',
                    'message': f'IDP "{provider_name}" audiences must be configured with the AI Services client ID',
                    'action': action_msg
                })
            else:
                # No IDP configured - this is critical for AI Services integration
                settings['recommendations'].append({
                    'type': 'critical',
                    'message': 'No Identity Provider (IDP) configured in Content deployment. AI Services requires IDP authentication for integration.',
                    'action': 'Configure an Identity Provider in your FNCMCluster CR before integrating AI Services. Add an open_id_connect_providers section with your IDP details (Keycloak, Azure AD, etc.)'
                })
                self._logger.warning("No IDP configuration found in FNCMCluster CR - AI Services requires IDP for integration")
            
            settings['found'] = True
            self._logger.info(f"Successfully extracted AI Services settings from FNCMCluster CR: {settings['cr_name']}")
            
            return settings
            
        except Exception as e:
            self._logger.error(f"Error extracting AI Services settings from FNCMCluster CR: {str(e)}")
            return {
                'found': False,
                'namespace': None,
                'cr_name': None,
                'graphql_endpoint': None,
                'graphql_root_ca_secret': None,
                'object_store': None,
                'navigator_url': None,
                'navigator_url_source': None,
                'idp_config': {},
                'has_graphql': False,
                'has_cpe': False,
                'has_ban': False,
                'version': None,
                'version_compatible': False,
                'recommendations': []
            }

    # Function to check the status of catalog source upgrade rollout
    def check_catalogsource_rollout_status(self, name="ibm-fncm-operator-catalog", namespace=""):
        try:
            catalog_source = self._custom_api.get_namespaced_custom_object(
                group="operators.coreos.com",
                version="v1alpha1",
                namespace=namespace,
                plural="catalogsources",
                name=name
            )
            status = catalog_source.get("status", {})
            connection = status.get("connectionState", {})

            self._logger.info(f"Catalog source '{name}' status: {connection}")

            # Check connection state
            last_observed_state = connection.get("lastObservedState")
            if last_observed_state and last_observed_state.lower() in ["ready", "healthy", "idle"]:
                # Also verify the pod is actually running
                try:
                    pods = self._core_v1.list_namespaced_pod(
                        namespace=namespace,
                        label_selector=f"olm.catalogSource={name}"
                    )
                    if pods.items:
                        for pod in pods.items:
                            if pod.status.phase == "Running":
                                # Check if all containers are ready
                                if pod.status.container_statuses:
                                    all_ready = all(
                                        container.ready for container in pod.status.container_statuses
                                    )
                                    if all_ready:
                                        self._logger.info(f"Catalog pod '{pod.metadata.name}' is running and ready")
                                        return True
                        self._logger.info(f"Catalog pod exists but not all containers are ready")
                        return False
                except Exception as pod_error:
                    self._logger.info(f"Error checking catalog pod status: {pod_error}")
                    # If we can't check pod status but connection state is good, assume it's ready
                    return True

            return False
        except Exception as e:
            self._logger.info(f"Error checking catalog source rollout status: {e}")
            return False

    # Function to check the status of a deployment upgrade rollout
    def check_deployment_rollout_status(self, deployment_name, namespace):
        try:
            deployment = self._apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
            status = deployment.status
            spec = deployment.spec

            self._logger.info(f"Deployment '{deployment_name}' status: {status}\n"
                              f"Replicas Spec: {spec.replicas}")

            if (status.updated_replicas == spec.replicas and
                status.replicas == spec.replicas and
                status.available_replicas == spec.replicas and
                status.observed_generation >= deployment.metadata.generation):
                    return True

            return False
        except Exception as e:
            self._logger.info(f"Error checking deployment rollout status: {e}")
            return False

    # Function to extract storage classes from the CR
    def extract_storage_classes(self):
        try:
            cr = self._custom_resource
            storage_classes = set()

            if "storage_configuration" in cr["spec"]["shared_configuration"].keys():
                storage_classes.add(
                    cr["spec"]["shared_configuration"]["storage_configuration"]["sc_fast_file_storage_classname"])
                storage_classes.add(
                    cr["spec"]["shared_configuration"]["storage_configuration"]["sc_medium_file_storage_classname"])
                storage_classes.add(
                    cr["spec"]["shared_configuration"]["storage_configuration"]["sc_slow_file_storage_classname"])

            return list(storage_classes)
        except Exception as e:
            self._logger.info(f"Error extracting storage classes: {e}")
            return {}

    # Function to read storage classes
    def describe_storage_class(self, storage_class_name):
        try:
            storage_classes = self._storage_v1.read_storage_class(storage_class_name)
            return storage_classes
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the describe_storage_class: {e}")
            return {}

    # Function to parse and extract important info from the CR
    def parse_cr(self):
        try:
            cr = self._custom_resource
            # Extract the important information from the CR

            # TODO: Calculate profile size
            cr_details = {
                "name": cr["metadata"]["name"],
                "namespace": cr["metadata"]["namespace"],
                "platform": cr["spec"]["shared_configuration"]["sc_deployment_platform"],
                "context": cr["spec"]["shared_configuration"]["sc_deployment_context"],
                "appVersion": cr["spec"]["appVersion"]
            }

            # Extract the components from the CR
            components = self.calculate_deployed_components()
            cr_details["components"] = components

            # Equate AppVersion to FNCM Version
            # DBACLD-157604 added the mapping for 24.0.1
            versions = {
                "21.0.3": "5.5.8",
                "22.0.1": "5.5.9",
                "22.0.2": "5.5.10",
                "23.0.1": "5.5.11",
                "23.0.2": "5.5.12",
                "24.0.0": "5.6.0",
                "24.0.1": "5.6.0",
                "25.0.0": "5.7.0"
            }

            # Making sure there is always a version value
            if cr_details["appVersion"] in versions:
                cr_details["version"] = versions[cr_details["appVersion"]]
            else:
                cr_details["version"] = "Unknown"

            cr_details["storage_classes"] = self.extract_storage_classes()

            # Extract User Secrets
            cr_details["user_secrets"] = self.calculate_user_secrets(components)

            # Extract User Configmaps
            cr_details["user_configmaps"] = self.calculate_user_configmaps(components)

            self._cr_details = cr_details
            return cr_details
        except Exception as e:
            self._logger.info(f"Error parsing CR: {e}")
            self._cr_details = cr_details
            return cr_details

    # Function to list the resources deployed by FNCM deployment in a specific namespace
    # Can see to add more resource types
    def list_namespace_resources(
            self, console, namespace, platform, filter="fncmdeploy"
    ):
        try:

            app_v1_resource_types = ["deployment"]
            core_v1_resource_types = [
                "service",
                "config_map",
                "secret",
                "persistent_volume_claim",
            ]
            networking_v1_resource_types = ["ingress", "network_policy"]
            auto_scaling_v2_resource_types = ["horizontal_pod_autoscaler"]
            policy_v1_resource_types = ["pod_disruption_budget"]
            resource_type_dict = {}
            for resource_type in app_v1_resource_types:
                resource_type_dict[resource_type] = []
                try:
                    response = getattr(self._apps_v1, f"list_namespaced_{resource_type}")(namespace=namespace)
                    for item in response.items:
                        if item.metadata.owner_references is not None:
                            if item.metadata.owner_references[0].name == filter:
                                resource_type_dict[resource_type].append(item.metadata.name)
                except client.exceptions.ApiException as e:
                    self._logger.info(f"Error listing {resource_type}: {e}")

            # Routes are only for OCP and CNCF ->
            if platform.lower() != "other":
                try:
                    resource_routes = self._custom_api.get_namespaced_custom_object(group="route.openshift.io",
                                                                                    version="v1",
                                                                                    namespace=namespace,
                                                                                    plural="routes", name="")
                    resource_type_dict["routes"] = []
                    for item in resource_routes["items"]:
                        # Check if owner references exist
                        reference = item["metadata"].get("ownerReferences", None)
                        if reference is not None:
                            if item["metadata"]["ownerReferences"][0]["name"] == filter:
                                resource_type_dict["routes"].append(item["metadata"]["name"])
                except Exception as e:
                    self._logger.info(f"Error listing Routes: {e}")

            for resource_type in core_v1_resource_types:
                resource_type_dict[resource_type] = []
                try:
                    response = getattr(self._core_v1, f"list_namespaced_{resource_type}")(namespace=namespace)
                    for item in response.items:
                        if item.metadata.owner_references is not None:
                            if item.metadata.owner_references[0].name == filter:
                                resource_type_dict[resource_type].append(item.metadata.name)
                        if item.metadata.labels is not None:
                            if 'app.kubernetes.io/instance' in item.metadata.labels.keys():
                                if item.metadata.labels['app.kubernetes.io/instance'] == filter:
                                    resource_type_dict[resource_type].append(item.metadata.name)
                        resource_type_dict[resource_type] = list(set(resource_type_dict[resource_type]))
                except client.exceptions.ApiException as e:
                    self._logger.info(f"Error listing {resource_type}: {e}")

            for resource_type in policy_v1_resource_types:
                resource_type_dict[resource_type] = []
                try:
                    response = getattr(
                        self._policy_v1,
                        f"list_namespaced_{resource_type}"
                    )(namespace=namespace)

                    for item in response.items:
                        if item.metadata.owner_references is not None:
                            if item.metadata.owner_references[0].name == filter:
                                resource_type_dict[resource_type].append(item.metadata.name)

                        if item.metadata.labels is not None:
                            if item.metadata.labels.get("app.kubernetes.io/instance") == filter:
                                resource_type_dict[resource_type].append(item.metadata.name)

                    resource_type_dict[resource_type] = list(
                        set(resource_type_dict[resource_type])
                    )

                except client.exceptions.ApiException as e:
                    self._logger.info(f"Error listing {resource_type}: {e}")

            for resource_type in auto_scaling_v2_resource_types:
                resource_type_dict[resource_type] = []
                try:
                    response = getattr(self._auto_scaling_v2, f"list_namespaced_{resource_type}")(namespace=namespace)
                    for item in response.items:
                        if item.metadata.owner_references is not None:
                            if item.metadata.owner_references[0].name == filter:
                                resource_type_dict[resource_type].append(item.metadata.name)
                except client.exceptions.ApiException as e:
                    self._logger.info(f"Error listing {resource_type}: {e}")

            for resource_type in networking_v1_resource_types:
                resource_type_dict[resource_type] = []
                try:
                    response = getattr(self._networking_v1, f"list_namespaced_{resource_type}")(namespace=namespace)
                    for item in response.items:
                        if item.metadata.owner_references is not None:
                            if item.metadata.owner_references[0].name == filter:
                                resource_type_dict[resource_type].append(item.metadata.name)
                except client.exceptions.ApiException as e:
                    self._logger.info(f"Error listing {resource_type}: {e}")
            
            self._resource_type_dict = resource_type_dict
            return resource_type_dict
        except Exception as e:
            self._logger.info(f"Error in listing resources in namespace function: {e}")
            return None

    # Function to get catalog source details
    def describe_catalogsource(self, name="ibm-fncm-catalog-source", namespace=""):
        # Define the resource group, version, and plural name for the custom resource
        group = "operators.coreos.com"
        version = "v1alpha1"
        plural = "catalogsources"

        try:
            catalog_source = self._custom_api.get_namespaced_custom_object(
                group=group, version=version, namespace=namespace, plural=plural, name=name
            )
            return catalog_source
        except Exception as e:
            self._logger.info(
                f"Error in kubernetes_utilities.py from the get_catalog_source_details function: {e}")
            return {}

    def parse_subscription(self, subscription):
        try:
            if not subscription:
                return {}
            # Extract the important information from the Subscription
            subscription_details = {
                "subscription": subscription["metadata"].get("name", ""),
                "namespace": subscription["metadata"].get("namespace", ""),
                "installedCSV": subscription["status"].get("installedCSV", ""),
                "catalogSource": subscription["spec"].get("source", ""),
                "channel": subscription["spec"].get("channel", ""),
                "sourceNamespace": subscription["spec"].get("sourceNamespace",),
            }

            gnc_namespace = "openshift-marketplace"

            if subscription_details["sourceNamespace"] == gnc_namespace:
                subscription_details["catalogType"] = "Global"
            else:
                subscription_details["catalogType"] = "Private"
            return subscription_details
        except Exception as e:
            self._logger.info(f"Error parsing Subscription: {e}")
            return {}

    def describe_subscription(self, name="", namespace=""):

        # Define the resource group, version, and plural name for the custom resource
        group = "operators.coreos.com"
        version = "v1alpha1"
        plural = "subscriptions"

        try:
            if name == "":
                name = self.get_subscription(namespace)

            subscription = self._custom_api.get_namespaced_custom_object(
                group=group, version=version, namespace=namespace, plural=plural, name=name
            )
            return subscription
        except Exception as e:
            self._logger.info(f"Error in kubernetes_utilities.py from the get_subscription: {e}")
            return {}

    # Function to get subscription name
    def get_subscription(self, namespace):
        try:
            subscriptions = self._custom_api.list_namespaced_custom_object(
                group="operators.coreos.com", version="v1alpha1", namespace=namespace, plural="subscriptions"
            )

            for subscription in subscriptions.get('items', []):
                if "ibm-fncm-operator" in subscription["metadata"]['name']:
                    name = subscription["metadata"]['name']
                    return name

            self._logger.info("Subscription could not be found")
            return None
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the get_subscription: {e}")
            return None

    # Function to delete the subscription of FNCM operator in OCP/ROKS
    def delete_subscription(self, namespace, name):
        # Define the resource group, version, and plural name for the custom resource
        group = "operators.coreos.com"
        version = "v1alpha1"
        plural = "subscriptions"

        try:
            # Delete the custom resource
            self._custom_api.delete_namespaced_custom_object(
                group=group, version=version, namespace=namespace, plural=plural, name=name
            )

            self._logger.info(f"Subscription '{name}' deleted successfully in namespace '{namespace}'.")
            return True
        except client.ApiException as e:
            self._logger.info(f"Error in utilities.py from the delete_subscription: {e}")
            return False

    # This function deletes the csv from the namespace in OCP/ROKS
    def delete_clusterserviceversion(self, csv_name="", namespace=""):

        # Define the resource group, version, and plural name for the custom resource
        group = "operators.coreos.com"
        version = "v1alpha1"
        plural = "clusterserviceversions"
        namespace = namespace
        name = csv_name

        # Specify the name of the ClusterServiceVersion
        name = csv_name

        try:
            # Delete the custom resource using kubectl APIS
            self._custom_api.list_namespaced_custom_object(group=group, version=version, plural=plural,
                                                           namespace=namespace)

            self._custom_api.delete_namespaced_custom_object(
                group=group, version=version, plural=plural, name=name, namespace=namespace
            )
            return True
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the delete_clusterserviceversion: {e}")
            return False

    # This function deletes the role, role binding , service account from the namespace
    def delete_operator_cncf(self, namespace=""):

        name = "ibm-fncm-operator"
        try:
            # Delete the Deployment
            self._apps_v1.delete_namespaced_deployment(name, namespace)

            # Delete the RoleBinding
            self._rbac_v1.delete_namespaced_role_binding(name, namespace)

            # Delete the Role
            self._rbac_v1.delete_namespaced_role(name, namespace)

            # Delete the ServiceAccount
            self._core_v1.delete_namespaced_service_account(name, namespace)

        except Exception as e:
            self._logger.info(f"Error in utilities.py from the delete_operator_cncf: {e}")

    def delete_operator_deployment(self, namespace="", name=""):
        if not name:
            name = "ibm-fncm-operator"
        try:
            # Delete the Deployment
            self._apps_v1.delete_namespaced_deployment(name, namespace)

        except Exception as e:
            self._logger.info(f"Error in utilities.py from the delete_operator_deployment: {e}")

    def delete_secret (self, namespace="", name=""):
        try:
            # Delete the Secret
            self._core_v1.delete_namespaced_secret(name, namespace)
            self._logger.info(f"Secret {name} deleted successfully")

        except Exception as e: 
            self._logger.info(f"Error in utilities.py from the delete_secret: {e}")
            

    def delete_role_binding(self, namespace="", name=""):
        if not name:
            name = "ibm-fncm-operator"
        try:
            # Delete the RoleBinding
            self._rbac_v1.delete_namespaced_role_binding(name, namespace)
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the delete_role_binding: {e}")

    def delete_role(self, namespace="", name=""):
        if not name:
            name = "ibm-fncm-operator"
        try:
            # Delete the Role
            self._rbac_v1.delete_namespaced_role(name, namespace)
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the delete_role: {e}")

    def delete_service_account(self, namespace="", name=""):
        if not name:
            name = "ibm-fncm-operator"
        try:
            # Delete the ServiceAccount
            self._core_v1.delete_namespaced_service_account(name, namespace)
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the delete_service_account: {e}")

    # Function to check the storage class reclaim policy
    def check_storage_class_mode(self):
        try:
            # List all storage classes
            storage_classes = self._storage_v1.list_storage_class()

            # Print the names of the storage classes
            storage_class_return_dict = {}
            for sc in storage_classes.items:
                name = sc.metadata.name
                storage_class_return_dict[name] = sc.reclaim_policy

            return storage_class_return_dict

        except Exception as e:
            self._logger.info(f"Error in utilities.py from the check_storage_class_mode: {e}")

    # Function to check if role is created and if so create the role binding
    def apply_role_binding(self, resource_file, namespace):
        counter = 0
        while True:
            try:
                role = self._rbac_v1.read_namespaced_role(name="ibm-fncm-operator", namespace=namespace)
                if role.metadata.name == 'ibm-fncm-operator':
                    role_binding_applied = self.apply_cluster_resource_files(resource_type="role binding",
                                                                             namespace=namespace,
                                                                             resource_file=resource_file)
                    break
            except client.ApiException as e:
                if e.status == 404:
                    if counter < 3:
                        sleep(5)
                        counter = counter + 1
                    else:
                        role_binding_applied = False
                        break
        return role_binding_applied

    # Get the Kubernetes server version
    def get_kubernetes_version(self):
        try:

            connected = True
            # Get the server version information
            server_version = self._version_v1.get_code(_request_timeout=10)

            if server_version:
                connected = True
                self._logger.info(f"Connected to kubernetes cluster successfully.")
                self._logger.info(f"Kubernetes Server Major Version: {server_version.major}")
                self._logger.info(f"Kubernetes Server Minor Version: {server_version.minor}")
                self._logger.info(f"Kubernetes Server Git Version: {server_version.git_version}")
                self._logger.info(f"Kubernetes Server Platform: {server_version.platform}")

                return server_version.git_version, connected

            else:
                connected = False
                self._logger.info(f"Could not connect to kubernetes cluster.")
                return "Unknown", connected

        except (ConnectTimeout, ConnectionError) as e:
            connected = False
            self._logger.info(f"Could not connect to kubernetes cluster: {e}")
            return "Unknown", connected
        except Exception as e:
            connected = False
            self._logger.info(f"Error in utilities.py from the get_kubernetes_version: {e}")
            return "Unknown", connected

    # Function to apply CRD , cluster role and role binding
    def apply_cluster_resource_files(self, resource_type, resource_file, namespace=None):

        try:
            # Read the resource manifest file
            with open(resource_file, "r") as file:
                resource_manifest = file.read()

            # Deserialize the YAML content into a Python dictionary
            resource_definition = yaml.safe_load(resource_manifest)
            if resource_type.lower() == "operator group":
                resource_definition["apiVersion"] = "operators.coreos.com/v1"

            # Determine the API method based on the resource type
            if resource_type.lower() == "custom resource definition":
                api_method = self._extensions_v1.create_custom_resource_definition
                api_patch_method = self._extensions_v1.patch_custom_resource_definition
            elif resource_type.lower() == "network_policy":
                if namespace:
                    api_method = self._networking_v1.create_namespaced_network_policy
                    api_patch_method = self._networking_v1.patch_namespaced_network_policy
            elif resource_type.lower() == "image policy":
                api_method = self._custom_api.create_cluster_custom_object
                group = "operator.openshift.io"
                version = "v1alpha1"
                plural = "ImageContentSourcePolicy"
                api_patch_method = self._custom_api.patch_namespaced_custom_object
            elif resource_type.lower() == "cluster role binding":
                api_method = self._rbac_v1.create_cluster_role_binding
                api_patch_method = self._rbac_v1.patch_cluster_role_binding
            elif resource_type.lower() == "role binding":
                if namespace:
                    api_method = self._rbac_v1.create_namespaced_role_binding
                    api_patch_method = self._rbac_v1.patch_namespaced_role_binding
            elif resource_type.lower() == "cluster role":
                api_method = self._rbac_v1.create_cluster_role
                api_patch_method = self._rbac_v1.patch_cluster_role
            elif resource_type.lower() == "role":
                if namespace:
                    api_method = self._rbac_v1.create_namespaced_role
                    api_patch_method = self._rbac_v1.patch_namespaced_role
            elif resource_type.lower() == "service account":
                api_method = self._core_v1.create_namespaced_service_account
                api_patch_method = self._core_v1.patch_namespaced_service_account
            elif resource_type.lower() == "catalog source":
                if namespace:
                    api_method = self._custom_api.create_namespaced_custom_object
                    group = "operators.coreos.com"
                    version = "v1alpha1"
                    plural = "catalogsources"
                    api_patch_method = self._custom_api.patch_namespaced_custom_object
            elif resource_type.lower() == "operator group":
                if namespace:
                    api_method = self._custom_api.create_namespaced_custom_object
                    group = "operators.coreos.com"
                    version = "v1"
                    plural = "operatorgroups"
                    api_patch_method = self._custom_api.patch_namespaced_custom_object
            elif resource_type.lower() == "subscription":
                if namespace:
                    api_method = self._custom_api.create_namespaced_custom_object
                    group = "operators.coreos.com"
                    version = "v1alpha1"
                    plural = "subscriptions"
                    api_patch_method = self._custom_api.patch_namespaced_custom_object

            elif resource_type.lower() == "deployment":
                if namespace:
                    api_method = self._apps_v1.create_namespaced_deployment
                    api_patch_method = self._apps_v1.patch_namespaced_deployment

            elif resource_type.lower() == 'pvc':
                if namespace:
                    api_method = self._core_v1.create_namespaced_persistent_volume_claim
                    api_patch_method = self._core_v1.patch_namespaced_persistent_volume_claim

            elif resource_type.lower() == 'secret':
                if namespace:
                    api_method = self._core_v1.create_namespaced_secret
                    api_patch_method = self._core_v1.patch_namespaced_secret
            
            elif resource_type.lower() == 'configmap':
                if namespace:
                    api_method = self._core_v1.create_namespaced_config_map
                    api_patch_method = self._core_v1.patch_namespaced_config_map
            
            elif resource_type.lower() in ['metrics', 'ibmservicemeterdefinition']:
                if namespace:
                    api_method = self._custom_api.create_namespaced_custom_object
                    group = "operator.ibm.com"
                    version = "v1"
                    plural = "ibmservicemeterdefinitions"
                    api_patch_method = self._custom_api.patch_namespaced_custom_object
            
            elif resource_type.lower() == "secretproviderclass":
                if namespace:
                    api_method = self._custom_api.create_namespaced_custom_object
                    group = "secrets-store.csi.x-k8s.io"
                    version = "v1"
                    plural = "secretproviderclasses"
                    api_patch_method = self._custom_api.patch_namespaced_custom_object

            elif resource_type.lower() == "custom resource":
                if namespace:
                    # Determine the group/version/plural from the resource definition
                    api_version = resource_definition.get("apiVersion", "")
                    kind = resource_definition.get("kind", "")
                    
                    # Default to FNCM CR
                    group = "fncm.ibm.com"
                    version = "v1"
                    plural = "fncmclusters"
                    
                    # Check if it's an AI Services CR
                    if "ccxaiservices" in api_version.lower():
                        group = "ccxaiservices.operator.ibm.com"
                        version = "v1"
                        plural = "ccxaiservices"
                    
                    api_method = self._custom_api.create_namespaced_custom_object
                    api_patch_method = self._custom_api.patch_namespaced_custom_object

            else:
                self._logger.info(f"Resource type '{resource_type}' is not supported.")
                return False

            # Create the resource
            if namespace:
                if resource_type.lower() in ["catalog source", "operator group", "subscription", "custom resource", "metrics", "ibmservicemeterdefinition", "secretproviderclass"]:
                    api_response = api_method(body=resource_definition, namespace=namespace, group=group,
                                              version=version, plural=plural)
                else:
                    api_response = api_method(body=resource_definition, namespace=namespace)
            else:
                api_response = api_method(body=resource_definition)

            return True

        except client.ApiException as e:
            if e.status == 409:
                if namespace:
                    if resource_type.lower() in ["catalog source", "operator group", "subscription", "custom resource", "metrics", "ibmservicemeterdefinition", "secretproviderclass"]:
                        api_patch_method(
                            body=resource_definition,
                            name=resource_definition["metadata"]["name"], namespace=namespace, group=group,
                            plural=plural, version=version,
                        )
                    else:
                        api_patch_method(
                            body=resource_definition,
                            name=resource_definition["metadata"]["name"], namespace=namespace,
                        )
                else:
                    api_patch_method(
                        body=resource_definition,
                        name=resource_definition["metadata"]["name"],
                    )
                return True
            else:
                return False
        except Exception as e:
            return False

    def get_node_top(self):
        try:
            node = self.custom_api.list_cluster_custom_object(
                group="metrics.k8s.io", version="v1beta1", plural="nodes", pretty="true"
            )
            return node
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the get_node_top: {e}")
            return {}

    def get_nodes(self):
        try:
            nodes = self.core_v1.list_node()
            return nodes
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the get_nodes: {e}")
            return {}

    def get_events(self, namespace):
        try:
            version_response = self.core_v1.list_namespaced_event(namespace=namespace)
            return version_response
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the get_events: {e}")
            return {}

    def describe_pod(self, pod_name, namespace):
        try:
            pod = self.core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            return pod
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the describe_pod: {e}")
            return {}

    def describe_deployment(self, deployment_name, namespace):
        try:
            deployment = self.apps_v1.read_namespaced_deployment(
                name=deployment_name, namespace=namespace, pretty='true'
            )
            return deployment
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the describe_deployment: {e}")
            return {}

    def describe_configmap(self, configmap_name, namespace):
        try:
            configmap = self.core_v1.read_namespaced_config_map(
                name=configmap_name, namespace=namespace,
            )
            return configmap
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the describe_configmap: {e}")
            return {}

    def describe_pvc(self, pvc_name, namespace):
        try:
            pvc = self.core_v1.read_namespaced_persistent_volume_claim(
                name=pvc_name, namespace=namespace,
            )
            return pvc
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the describe_pvc: {e}")
            return {}

    def describe_service(self, service_name, namespace):
        try:
            service = self.core_v1.read_namespaced_service(
                name=service_name, namespace=namespace,
            )
            return service
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the describe_service: {e}")
            return {}

    def describe_ingress(self, ingress_name, namespace):
        try:
            ingress = self.networking_v1.read_namespaced_ingress(
                name=ingress_name, namespace=namespace,
            )
            return ingress
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the describe_ingress: {e}")
            return {}

    # Function to describe horizontal pod autoscaler
    def describe_hpa(self, hpa_name, namespace):
        try:
            hpa = self.auto_scaling_v2.read_namespaced_horizontal_pod_autoscaler(
                name=hpa_name, namespace=namespace,
            )
            return hpa
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the describe_hpa: {e}")
            return {}
        
    # Function to describe PodDisruptionBudget
    def describe_pdb(self, pdb_name, namespace):
        try:
            pdb = self.policy_v1.read_namespaced_pod_disruption_budget(
                name=pdb_name,
                namespace=namespace,
            )
            return pdb
        except Exception as e:
            self._logger.info(
                f"Error in utilities.py from the describe_pdb: {e}"
            )
            return {}

    def describe_network_policy(self, network_policy_name, namespace):
        try:
            network_policy = self.networking_v1.read_namespaced_network_policy(
                name=network_policy_name, namespace=namespace,
            )
            return network_policy
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the describe_network_policy: {e}")
            return {}
    
    def remove_network_policy_owner_reference(self, progress, network_policy_name, namespace):
        try:
            policy = self.networking_v1.read_namespaced_network_policy(
                name=network_policy_name, namespace=namespace,
            )
            if policy.metadata.owner_references:
                body = {
                    "metadata": {
                        "ownerReferences": None
                    }
                }
                self.networking_v1.patch_namespaced_network_policy(
                    name=policy.metadata.name,
                    namespace=namespace,
                    body=body,
                )
                progress.log(f"Owner references has been removed in  {network_policy_name}")
                progress.log()
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the describe_network_policy: {e}")
            return {}

    def describe_route(self, route_name, namespace):
        try:
            route = self.custom_api.get_namespaced_custom_object(
                "route.openshift.io",
                "v1",
                namespace,
                "routes",
                route_name,
            )
            return route
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the describe_route: {e}")
            return {}

    def describe_secret(self, secret_name, namespace, progress=None):
        try:
            secret = self.core_v1.read_namespaced_secret(
                name=secret_name, namespace=namespace,
            )
            return secret
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the describe_secret: {e}")
            if progress:
                progress.log(Text(f"Secret not found: {secret_name}", style="bold red"))
                progress.log()
            return {}

    # Function to collect container logs
    def get_container_logs(self, pod_name, namespace, container):
        try:
            logs = self.core_v1.read_namespaced_pod_log(name=pod_name, namespace=namespace, container=container)
            return logs
        except Exception as e:
            return ""

    # Function to collect pod metrics
    def get_pod_metrics(self, pod_name, namespace):
        try:
            metrics = self.custom_api.get_namespaced_custom_object(
                group="metrics.k8s.io",
                version="v1beta1",
                namespace=namespace,
                plural="pods",
                name=pod_name,
            )
            return metrics
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the get_pod_metrics: {e}")
            return {}

    # Function to collect pod events
    def get_pod_events(self, pod_name, namespace):
        try:
            field_selector = f'involvedObject.name={pod_name}'
            events = self.core_v1.list_namespaced_event(namespace=namespace, field_selector=field_selector)
            return events
        except Exception as e:
            return ""

    # Function to collect init-container logs
    def get_init_container_logs(self, pod_name, namespace, ini_container):
        try:
            logs = self.core_v1.read_namespaced_pod_log(name=pod_name, namespace=namespace, container=ini_container)
            return logs
        except Exception as e:
            return ""
    # Function to collect logs from all containers in a pod
    def get_pod_logs(self, pod_name, namespace):
        """
        Collect logs from all containers in a pod.
        Returns a dictionary with container names as keys and logs as values.
        """
        try:
            # Get pod details to find all containers
            pod = self.core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            
            all_logs = {}
            
            # Collect logs from all regular containers
            if pod.spec.containers:
                for container in pod.spec.containers:
                    container_name = container.name
                    try:
                        logs = self.core_v1.read_namespaced_pod_log(
                            name=pod_name, 
                            namespace=namespace, 
                            container=container_name
                        )
                        all_logs[container_name] = logs
                    except Exception as e:
                        self._logger.info(f"Could not get logs for container {container_name}: {e}")
                        all_logs[container_name] = f"Error collecting logs: {e}"
            
            return all_logs
            
        except Exception as e:
            self._logger.info(f"Error collecting pod logs for {pod_name}: {e}")
            return {}


    def pod_exec(self, pod_name, namespace, command):
        try:
            self._logger.info(f"Executing command {command} in pod {pod_name}")
            self._logger.info(f"Namespace: {namespace}")
            exec_command = command
            resp = stream(
                self.core_v1.connect_get_namespaced_pod_exec,
                pod_name,
                namespace,
                command=exec_command,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
                _preload_content=False,
            )
            while resp.is_open():
                resp.update(timeout=1)
                if resp.peek_stdout():
                    stdout = resp.read_stdout()
                if resp.peek_stderr():
                    stdout = resp.read_stderr()
            return stdout
        except Exception as e:
            self._logger.info(f"Unable to execute command {e}")

    def create_namespace(self, namespace):
        try:
            # Create a namespace
            body = client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
            self._core_v1.create_namespace(body)
            return True
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the create_namespace: {e}")
            return False

    # Function to get Operator Group details
    def describe_operator_group(self, name, namespace):
        try:
            og = self._custom_api.get_namespaced_custom_object(
                group="operators.coreos.com",
                version="v1",
                namespace=namespace,
                plural="operatorgroups",
                name=name,
            )
            return og
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the describe_operator_group: {e}")
            return {}

    # Function to list all Operator Groups in a namespace
    def list_operator_groups(self, namespace):
        try:
            ogs = self._custom_api.list_namespaced_custom_object(
                group="operators.coreos.com",
                version="v1",
                namespace=namespace,
                plural="operatorgroups"
            )
            return ogs.get('items', [])
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the list_operator_groups: {e}")
            return []


    # Function to get operator group details
    def get_operator_group(self, namespace):
        group = "operators.coreos.com"
        version = "v1"
        plural = "operatorgroups"
        # List Role objects in the specified namespace
        try:
            og = self._custom_api.list_namespaced_custom_object(group=group, version=version, plural=plural,
                                                                namespace=namespace)
            for group in og.get('items', []):
                if "FNCMCluster" in group["metadata"]['annotations']['olm.providedAPIs']:
                    return group["metadata"]['name'], group["metadata"]['annotations']['olm.providedAPIs']

            return ""
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the get_operator_group: {e}")
            return ""

    def get_rolename(self, namespace):
        try:
            roles = self._rbac_v1.list_namespaced_role(namespace=namespace)
            for role in roles.items:
                if "ibm-fncm-operator" in role.metadata.name:
                    name = role.metadata.name
                    return name

            return ""
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the get_rolename: {e}")
            return ""

    def get_rolebinding(self, namespace):
        try:
            rolebindings = self._rbac_v1.list_namespaced_role_binding(namespace=namespace)
            for rolebind in rolebindings.items:
                if "ibm-fncm-operator" in rolebind.metadata.name:
                    name = rolebind.metadata.name
                    return name

            return ""
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the get_rolebinding: {e}")
            return ""

    def get_service_account(self, namespace):
        try:
            service_accounts = self._core_v1.list_namespaced_service_account(namespace=namespace)
            for sa in service_accounts.items:
                if "ibm-fncm-operator" in sa.metadata.name:
                    name = sa.metadata.name
                    return name

            return ""
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the get_service_account: {e}")
            return ""

    def delete_operator_group(self, namespace, name):
        try:
            self._custom_api.delete_namespaced_custom_object(
                group="operators.coreos.com", version="v1", namespace=namespace, plural="operatorgroups", name=name
            )
            self._logger.info(f"Operator Group '{name}' deleted successfully in namespace '{namespace}'.")
            return True
        except client.ApiException as e:
            self._logger.info(f"Error in utilities.py from the delete_subscription: {e}")
            return False


    # Function to check if PVC is bound
    def check_pvc_bound(self, namespace, pvc_name):
        try:
            pvc = self._core_v1.read_namespaced_persistent_volume_claim(name=pvc_name, namespace=namespace)
            if pvc.status.phase == "Bound":
                return True
            else:
                return False
        except client.ApiException as e:
            if e.status == 404:
                return False
            else:
                self._logger.info(f"Error in utilities.py from the check_pvc_bound: {e}")
                return False


    # Function to list all storage classes
    def list_storage_classes(self):
        try:
            storage_classes = self._storage_v1.list_storage_class()

            # Print the names of the storage classes
            storage_classes = [sc.metadata.name for sc in storage_classes.items]
            return storage_classes
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the list_storage_classes: {e}")
            return {}

    def delete_pvc(self, namespace, name):
        try:
            self._core_v1.delete_namespaced_persistent_volume_claim(name=name, namespace=namespace)
            self._logger.info(f"PVC '{name}' deleted successfully in namespace '{namespace}'.")
            return True
        except client.ApiException as e:
            self._logger.info(f"Error in utilities.py from the delete_pvc: {e}")
            return False

    def delete_catalog_source(self, namespace, name):
        try:
            self._custom_api.delete_namespaced_custom_object(
                group="operators.coreos.com", version="v1alpha1", namespace=namespace, plural="catalogsources", name=name
            )
            self._logger.info(f"Catalog Source '{name}' deleted successfully in namespace '{namespace}'.")
            return True
        except client.ApiException as e:
            self._logger.info(f"Error in utilities.py from the delete_catalog_source: {e}")
            return False

    def get_version(self):
        try:
            version_response = self.version_v1.get_code()
            return version_response
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the get_version: {e}")
            return {}
    def check_user_permissions(self, namespace: str = "", skip_olm_permissions: bool = False) -> tuple[bool, list[str], dict]:
        """
        Check if the current user has the required RBAC permissions to deploy operators.
        
        This method verifies that the user can perform all necessary operations:
        - Create/read namespaces
        - Create/manage deployments, services, configmaps, secrets
        - Create/manage custom resource definitions (CRDs)
        - Create/manage operator resources
        - Manage RBAC (roles, rolebindings, serviceaccounts)
        
        Args:
            namespace: Target namespace for deployment (optional)
            skip_olm_permissions: If True, skip OLM-specific permission checks (for Helm deployments)
            
        Returns:
            Tuple of (success: bool, warnings: list[str], metrics: dict)
        """
        warnings = []
        metrics = {
            "cluster_accessible": True,  # Already connected via __init__
            "k8s_version": "Unknown",
            "current_user": "Unknown",
            "permissions": {}
        }
        
        try:
            # Get Kubernetes version
            try:
                version_info = self.get_version()
                if version_info:
                    metrics["k8s_version"] = f"{version_info.major}.{version_info.minor}"
                    self._logger.info(f"Kubernetes version: {metrics['k8s_version']}")
            except Exception as e:
                self._logger.warning(f"Could not retrieve Kubernetes version: {str(e)}")
            
            # Get current user context
            try:
                if not self._in_cluster:
                    contexts, active_context = config.list_kube_config_contexts()
                    if active_context:
                        metrics["current_user"] = active_context.get('context', {}).get('user', 'Unknown')
                        self._logger.info(f"Current user context: {metrics['current_user']}")
                else:
                    metrics["current_user"] = "ServiceAccount (in-cluster)"
                    self._logger.info("Running as service account in-cluster")
            except Exception as e:
                self._logger.warning(f"Could not retrieve user context: {str(e)}")
            
            # Create AuthorizationV1Api for permission checks
            auth_v1 = client.AuthorizationV1Api()
            
            # Define required permissions for operator deployment
            # Format: (resource, verbs, scope, description)
            required_permissions = [
                # Namespace operations
                ("namespaces", ["get", "list", "create"], "cluster", "Manage namespaces"),
                
                # Core resources in namespace
                ("pods", ["get", "list", "watch", "create", "delete"], "namespace", "Manage pods"),
                ("services", ["get", "list", "create", "update", "delete"], "namespace", "Manage services"),
                ("configmaps", ["get", "list", "create", "update", "delete"], "namespace", "Manage configmaps"),
                ("secrets", ["get", "list", "create", "update", "delete"], "namespace", "Manage secrets"),
                ("serviceaccounts", ["get", "list", "create", "update", "delete"], "namespace", "Manage service accounts"),
                ("persistentvolumeclaims", ["get", "list", "create", "delete"], "namespace", "Manage PVCs"),
                
                # Workload resources
                ("deployments", ["get", "list", "create", "update", "delete", "patch"], "namespace", "Manage deployments"),
                ("statefulsets", ["get", "list", "create", "update", "delete"], "namespace", "Manage statefulsets"),
                ("daemonsets", ["get", "list", "create", "update", "delete"], "namespace", "Manage daemonsets"),
                
                # RBAC resources
                ("roles", ["get", "list", "create", "update", "delete"], "namespace", "Manage roles"),
                ("rolebindings", ["get", "list", "create", "update", "delete"], "namespace", "Manage role bindings"),
                ("clusterroles", ["get", "list", "create", "update", "delete"], "cluster", "Manage cluster roles"),
                ("clusterrolebindings", ["get", "list", "create", "update", "delete"], "cluster", "Manage cluster role bindings"),
                
                # CRD and operator resources
                ("customresourcedefinitions", ["get", "list", "create", "update", "delete"], "cluster", "Manage CRDs"),
                ("apiservices", ["get", "list", "create", "update"], "cluster", "Manage API services"),
                
            ]
            
            # Add OLM-specific resources only if not skipping them
            if not skip_olm_permissions:
                required_permissions.extend([
                    ("catalogsources", ["get", "list", "create", "update", "delete"], "namespace", "Manage catalog sources"),
                    ("subscriptions", ["get", "list", "create", "update", "delete"], "namespace", "Manage subscriptions"),
                    ("operatorgroups", ["get", "list", "create", "update", "delete"], "namespace", "Manage operator groups"),
                    ("clusterserviceversions", ["get", "list", "create", "update", "delete"], "namespace", "Manage CSVs"),
                ])
            
            self._logger.info("Checking RBAC permissions for operator deployment...")
            
            # Import rich for progress display
            from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
            from rich.console import Console
            
            failed_permissions = []
            passed_permissions = []
            
            # Create progress bar
            console = Console()
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
                transient=True  # Remove progress bar when complete
            ) as progress:
                task = progress.add_task(
                    "[cyan]Checking RBAC permissions...",
                    total=len(required_permissions)
                )
                
                for resource, verbs, scope, description in required_permissions:
                    # Update progress description
                    progress.update(task, description=f"[cyan]Checking: {description}")
                    
                    permission_key = f"{resource}_{scope}"
                    metrics["permissions"][permission_key] = {
                        "resource": resource,
                        "scope": scope,
                        "description": description,
                        "allowed_verbs": [],
                        "denied_verbs": [],
                        "status": "unknown"
                    }
                    
                    for verb in verbs:
                        try:
                            # Create SelfSubjectAccessReview
                            access_review = client.V1SelfSubjectAccessReview(
                                spec=client.V1SelfSubjectAccessReviewSpec(
                                    resource_attributes=client.V1ResourceAttributes(
                                        namespace=namespace if scope == "namespace" and namespace else None,
                                        verb=verb,
                                        resource=resource,
                                        group="" if resource in ["pods", "services", "configmaps", "secrets",
                                                                 "serviceaccounts", "persistentvolumeclaims",
                                                                 "namespaces"] else
                                               "apps" if resource in ["deployments", "statefulsets", "daemonsets"] else
                                               "rbac.authorization.k8s.io" if resource in ["roles", "rolebindings",
                                                                                            "clusterroles", "clusterrolebindings"] else
                                               "apiextensions.k8s.io" if resource == "customresourcedefinitions" else
                                               "apiregistration.k8s.io" if resource == "apiservices" else
                                               "operators.coreos.com"  # For OLM resources
                                    )
                                )
                            )
                            
                            response = auth_v1.create_self_subject_access_review(access_review)
                            
                            if response.status.allowed:
                                metrics["permissions"][permission_key]["allowed_verbs"].append(verb)
                            else:
                                metrics["permissions"][permission_key]["denied_verbs"].append(verb)
                                
                        except client.rest.ApiException as e:
                            if e.status == 404:
                                # Resource type doesn't exist (e.g., OLM not installed)
                                self._logger.debug(f"Resource type '{resource}' not found - may not be required")
                                metrics["permissions"][permission_key]["status"] = "not_applicable"
                                continue
                            else:
                                self._logger.warning(f"Error checking permission for {verb} on {resource}: {str(e)}")
                                metrics["permissions"][permission_key]["denied_verbs"].append(verb)
                        except Exception as e:
                            self._logger.warning(f"Error checking permission for {verb} on {resource}: {str(e)}")
                            metrics["permissions"][permission_key]["denied_verbs"].append(verb)
                    
                    # Determine overall status for this permission
                    if metrics["permissions"][permission_key]["status"] != "not_applicable":
                        if len(metrics["permissions"][permission_key]["denied_verbs"]) == 0:
                            metrics["permissions"][permission_key]["status"] = "allowed"
                            passed_permissions.append(f"{description} ({resource})")
                            self._logger.info(f"✓ Permission granted: {description}")
                        elif len(metrics["permissions"][permission_key]["allowed_verbs"]) > 0:
                            metrics["permissions"][permission_key]["status"] = "partial"
                            warnings.append(f"⚠️  Partial permissions for {description}: missing {', '.join(metrics['permissions'][permission_key]['denied_verbs'])}")
                            self._logger.warning(f"⚠️  Partial permissions for {description}")
                        else:
                            metrics["permissions"][permission_key]["status"] = "denied"
                            failed_permissions.append(f"{description} ({resource})")
                            self._logger.error(f"✗ Permission denied: {description}")
                    
                    # Advance progress
                    progress.advance(task)
            
            # Determine overall success
            critical_failures = [p for p in metrics["permissions"].values() 
                               if p["status"] == "denied" and p["resource"] in 
                               ["namespaces", "deployments", "pods", "services", "customresourcedefinitions"]]
            
            if critical_failures:
                warnings.insert(0, f"❌ Missing critical permissions: {len(critical_failures)} resource type(s)")
                success = False
            elif failed_permissions:
                warnings.insert(0, f"⚠️  Missing some permissions: {len(failed_permissions)} resource type(s)")
                success = True  # Can proceed with warnings
            else:
                self._logger.info(f"✓ All required permissions verified ({len(passed_permissions)} checks passed)")
                success = True
            
            return success, warnings, metrics
            
        except Exception as e:
            self._logger.error(f"Permission check failed: {str(e)}")
            return False, [f"❌ Permission check failed: {str(e)}"], metrics


    def describe_csv(self, csv_name, namespace):
        try:
            csv = self.custom_api.get_namespaced_custom_object(
                group="operators.coreos.com",
                version="v1alpha1",
                namespace=namespace,
                plural="clusterserviceversions",
                name=csv_name,
            )
            return csv
        except Exception as e:
            self._logger.info(f"Error in utilities.py from the describe_csv: {e}")
            return {}
    def list_csvs_in_namespace(self, namespace):
        """
        List all ClusterServiceVersions in a namespace.
        
        Args:
            namespace: Target namespace
            
        Returns:
            List of CSV objects with name and phase information
        """
        try:
            csvs = self._custom_api.list_namespaced_custom_object(
                group="operators.coreos.com",
                version="v1alpha1",
                namespace=namespace,
                plural="clusterserviceversions"
            )
            
            csv_list = []
            if csvs and "items" in csvs:
                for csv in csvs["items"]:
                    csv_info = {
                        "name": csv["metadata"].get("name", ""),
                        "phase": csv["status"].get("phase", "Unknown") if "status" in csv else "Unknown",
                        "version": csv["spec"].get("version", "Unknown") if "spec" in csv else "Unknown",
                        "displayName": csv["spec"].get("displayName", "") if "spec" in csv else ""
                    }
                    csv_list.append(csv_info)
            
            return csv_list
        except Exception as e:
            self._logger.info(f"Error listing CSVs in namespace {namespace}: {e}")
            return []

    def list_catalog_sources_in_namespace(self, namespace):
        """
        List all CatalogSources in a namespace.
        
        Args:
            namespace: Target namespace
            
        Returns:
            List of CatalogSource objects with name and status information
        """
        try:
            catalogs = self._custom_api.list_namespaced_custom_object(
                group="operators.coreos.com",
                version="v1alpha1",
                namespace=namespace,
                plural="catalogsources"
            )
            
            catalog_list = []
            if catalogs and "items" in catalogs:
                for catalog in catalogs["items"]:
                    catalog_info = {
                        "name": catalog["metadata"].get("name", ""),
                        "namespace": catalog["metadata"].get("namespace", ""),
                        "displayName": catalog["spec"].get("displayName", "") if "spec" in catalog else "",
                        "publisher": catalog["spec"].get("publisher", "") if "spec" in catalog else "",
                        "sourceType": catalog["spec"].get("sourceType", "") if "spec" in catalog else ""
                    }
                    catalog_list.append(catalog_info)
            
            return catalog_list
        except Exception as e:
            self._logger.info(f"Error listing CatalogSources in namespace {namespace}: {e}")
            return []

    def detect_olm_resources(self, namespace, csv_prefixes=None):
        """
        Detect OLM resources (CSVs and CatalogSources) in a namespace.
        
        Args:
            namespace: Target namespace
            csv_prefixes: Optional list of CSV name prefixes to filter by (e.g., ["ibm-licensing-operator"])
                         If provided, only CSVs matching these prefixes will be included
            
        Returns:
            Dictionary with detected CSVs and CatalogSources
        """
        try:
            all_csvs = self.list_csvs_in_namespace(namespace)
            
            # Filter CSVs by prefix if specified
            if csv_prefixes:
                csvs = []
                for csv in all_csvs:
                    csv_name = csv.get("name", "")
                    if any(csv_name.startswith(prefix) for prefix in csv_prefixes):
                        csvs.append(csv)
            else:
                csvs = all_csvs
            
            catalogs = self.list_catalog_sources_in_namespace(namespace)
            
            # Also check common catalog namespaces
            additional_catalogs = []
            for cat_ns in ["openshift-marketplace", "olm"]:
                if cat_ns != namespace:
                    try:
                        additional_catalogs.extend(self.list_catalog_sources_in_namespace(cat_ns))
                    except Exception:
                        pass
            
            return {
                "csvs": csvs,
                "catalogs": catalogs,
                "additional_catalogs": additional_catalogs,
                "has_olm": len(csvs) > 0 or len(catalogs) > 0
            }
        except Exception as e:
            self._logger.error(f"Error detecting OLM resources: {e}")
            return {
                "csvs": [],
                "catalogs": [],
                "additional_catalogs": [],
                "has_olm": False
            }


    def parse_operator_deployment(self, deployment, namespace):
        try:
            # Extract the important information from the Deployment
            name = deployment.metadata.name
            image = deployment.spec.template.spec.containers[0].image
            
            # Extract version from image tag
            # Image format: registry/namespace/image:version or registry/namespace/image@sha256:hash
            version = "unknown"
            if image:
                # Try to extract version from tag (after last :)
                if ':' in image and '@' not in image.split(':')[-1]:
                    # Format: image:version
                    tag = image.split(':')[-1]
                    # Remove any build metadata (e.g., 5.6.0+20240101.123456 -> 5.6.0)
                    version = tag.split('+')[0] if '+' in tag else tag
                elif '@' in image:
                    # Format: image@sha256:hash - try to get version from image name
                    # Some images include version in the name like: operator-5.6.0@sha256:...
                    image_name = image.split('@')[0]
                    if '-' in image_name:
                        parts = image_name.split('-')
                        # Look for version-like pattern (e.g., 5.6.0)
                        for part in reversed(parts):
                            if '.' in part and any(c.isdigit() for c in part):
                                version = part
                                break
            
            operator_deployment_details = {"deployment": name, "namespace": namespace,
                                           "replicas": deployment.spec.replicas,
                                           "image": image,
                                           "version": version,
                                           "pods": self.get_pod_names_for_deployment(namespace, name),
                                           "init_containers": self.get_init_containers_for_deployment(namespace, name),
                                           "type": "YAML",
                                           "release": deployment.spec.template.metadata.labels.get("release", "5.7.0")}

            # Check for OLM installation
            if deployment.metadata.owner_references:
                for owner in deployment.metadata.owner_references:
                    if owner.kind == "ClusterServiceVersion":
                        operator_deployment_details["type"] = "OLM"
            
            # Check for Helm installation
            # Helm adds specific labels and annotations to managed resources
            # Priority: annotations over labels (annotations are more reliable for release name)
            
            # First check annotations for Helm metadata (most reliable)
            if deployment.metadata.annotations:
                if "meta.helm.sh/release-name" in deployment.metadata.annotations:
                    operator_deployment_details["type"] = "HELM"
                    operator_deployment_details["helm_release"] = deployment.metadata.annotations["meta.helm.sh/release-name"]
                    
                    if "meta.helm.sh/release-namespace" in deployment.metadata.annotations:
                        operator_deployment_details["helm_namespace"] = deployment.metadata.annotations["meta.helm.sh/release-namespace"]
            
            # If not found in annotations, check labels
            if operator_deployment_details["type"] != "HELM" and deployment.metadata.labels:
                # Check for Helm-specific labels
                if "app.kubernetes.io/managed-by" in deployment.metadata.labels:
                    if deployment.metadata.labels["app.kubernetes.io/managed-by"] == "Helm":
                        operator_deployment_details["type"] = "HELM"
                        
                        # Extract Helm chart info if available
                        if "helm.sh/chart" in deployment.metadata.labels:
                            operator_deployment_details["helm_chart"] = deployment.metadata.labels["helm.sh/chart"]
                        
                        # Only use instance label if we don't already have helm_release from annotations
                        if "helm_release" not in operator_deployment_details and "app.kubernetes.io/instance" in deployment.metadata.labels:
                            operator_deployment_details["helm_release"] = deployment.metadata.labels["app.kubernetes.io/instance"]

            return operator_deployment_details
        except Exception as e:
            self._logger.info(f"Error in kubernetes_utilities.py from the parse_operator_deployment: {e}")
            return {}

    # function to check if namespace exists
    def check_namespace_exists(self, namespace):
        """
        Check if a namespace exists in the cluster.
        Returns None if no Kubernetes connection is available (graceful degradation).
        """
        if not self._connected:
            if self._logger:
                self._logger.debug(f"No Kubernetes connection available, skipping namespace check for: {namespace}")
            return None  # Return None to indicate check couldn't be performed
        
        try:
            self._core_v1.read_namespace(name=namespace)
            return True
        except client.ApiException as e:
            if e.status == 403:
                if self._in_cluster:
                    if self._logger:
                        self._logger.info("Namespace is where the pod is running")
                    return True
                return False
            if e.status == 404:
                return False
            else:
                print(f"An error occurred: {e}")
                exit(0)

    # Function to describe the role
    def describe_role(self, name, namespace):
        try:
            role = self._rbac_v1.read_namespaced_role(name=name, namespace=namespace)

            return role
        except client.ApiException as e:
            if e.status == 404:
                return False

    # Function to describe the rolebinding
    def describe_role_binding(self, name, namespace):
        try:
            rolebinding = self._rbac_v1.read_namespaced_role_binding(name=name, namespace=namespace)

            return rolebinding
        except client.ApiException as e:
            if e.status == 404:
                return False

    # Function to get the service account
    def describe_service_account(self, name, namespace):
        try:
            service_account = self._core_v1.read_namespaced_service_account(name=name, namespace=namespace)

            return service_account
        except client.ApiException as e:
            if e.status == 404:
                return False

    # Function to collect operator details
    def get_operator_details(self, namespace, deployment_name="ibm-fncm-operator"):
        try:

            operator_details = {}

            # Get the deployment object
            deployment = self._apps_v1.read_namespaced_deployment(deployment_name, namespace)

            if not deployment:
                return {}

            operator_details.update(self.parse_operator_deployment(deployment, namespace))

            # Check if OLM install
            if operator_details["type"] == "OLM":
                # Get the Subscription object
                subscription = self.describe_subscription(namespace=namespace)
                operator_details.update(self.parse_subscription(subscription))

                # Add Operator Group name
                operator_details["operatorGroup"], operator_details["providedAPIs"] = self.get_operator_group(namespace)

            # Add Permissions
            operator_details["role"] = self.get_rolename(namespace)
            operator_details["rolebinding"] = self.get_rolebinding(namespace)
            operator_details["service_account"] = self.get_service_account(namespace)

            self._operator_details = operator_details
            return operator_details

        except Exception as e:
            self._logger.info(f"Operator details: {operator_details}")
            self._logger.info(f"Error in kubernetes_utilities.py from the get_operator_details: {e}")
            return {}


    # Function to copy files or folders from a pod to the local filesystem
    def copy_files_from_pod(self, pod_name, namespace, src_path, dest_path, file_filter=''):
        try:
            exec_command = ["tar", "czf", '-', file_filter, "-C", src_path, '.' ]

            self._logger.info(f"Copying files from pod {pod_name} to {dest_path}")
            self._logger.info(f"Exec command: {exec_command}")

            # Execute the command and get the stream
            resp = stream(
                self.core_v1.connect_get_namespaced_pod_exec,
                pod_name,
                namespace,
                command=exec_command,
                stderr=True,
                stdin=True,
                stdout=True,
                tty=False,
                _preload_content=False,
                binary=True
            )

            self._logger.info(f"Response: {resp}")

            # Read the streamed tar data
            tar_data = b""
            while resp.is_open():
                resp.update(timeout=1)
                if resp.peek_stdout():
                    chunk = resp.read_stdout()
                    tar_data += chunk  # Ensure the chunk is in bytes

            resp.close()

            # Process the tar data (e.g., extract to a local directory)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with io.BytesIO(tar_data) as tar_buffer:
                    with tarfile.open(fileobj=tar_buffer, mode="r") as tar_archive:
                        tar_archive.extractall(path=dest_path)

            return True
        except Exception as e:
            self._logger.info(f"Error in kubernetes_utilities.py from the copy_files_from_pod: {e}")
            return False

    # Function to update the operator group to remove cas.ibm.com/v1 from providedAPIs
    def update_operator_group(self, namespace, operator_group, provided_apis, api_to_remove="FNCMCluster.v1.fncm.ibm.com"):
        # Check if the operator group exists
        if not operator_group:
            self._logger.info("Operator group does not exist, skipping update.")
            return

        # Remove the "cas.ibm.com/v1" API from providedAPIs
        if api_to_remove in provided_apis:
            provided_apis.remove(api_to_remove)

        # Update the operator group with the modified providedAPIs
        self._logger.info(f"Updating operator group '{operator_group}' in namespace '{namespace}' "
                          f"to remove {api_to_remove} from providedAPIs.")

        try:
            og = self.describe_operator_group(name=operator_group, namespace=namespace)
            if not og:
                self._logger.info(f"Operator group '{operator_group}' not found in namespace '{namespace}'.")
                return
            og['metadata']['annotations']['olm.providedAPIs'] = ','.join(provided_apis)
            self._custom_api.patch_namespaced_custom_object(
                group="operators.coreos.com",
                version="v1",
                namespace=namespace,
                plural="operatorgroups",
                name=operator_group,
                body=og
            )
            self._logger.info(f"Operator group '{operator_group}' updated successfully in namespace '{namespace}'.")
        except client.ApiException as e:
            self._logger.info(f"Error updating operator group: {e}")
        except Exception as e:
            self._logger.info(f"Unexpected error while updating operator group: {e}")
            return


    # Function to get CR file from a Content Assistant deployment
    def get_deployment_cr(self, namespace, logger=None):
        # Attempt to list the CR in the specific namespace
        try:
            cr_details = self._custom_api.list_namespaced_custom_object(group="fncm.ibm.com", version="v1",
                                                                        namespace=namespace,
                                                                        plural="fncmclusters")
            cr = cr_details["items"][0]

            if len(cr) == 0:
                return {}
            else:
                self._logger.info("Cleaning up the Custom Resource file before returning it.")
                # Remove unused sections from the CR
                remove_fields = ["creationTimestamp",
                                 "generation",
                                 "resourceVersion",
                                 "uid",
                                 "managedFields"]
                for field in remove_fields:
                    if field in cr["metadata"].keys():
                        del cr["metadata"][field]
                if "annotations" in cr["metadata"].keys():
                    if 'kubectl.kubernetes.io/last-applied-configuration' in cr["metadata"]["annotations"]:
                        del cr["metadata"]["annotations"]['kubectl.kubernetes.io/last-applied-configuration']
                    if not cr["metadata"]["annotations"]:
                        del cr["metadata"]["annotations"]
                self._custom_resource = cr
                self.parse_cr()
                return cr
        except ApiException as e:
            if e.status == 404:
                self._logger.info(f"No Custom Resource file found in '{namespace}'.")
                return {}
        except Exception as e:
            self._logger.info("Error while checking for Custom Resource file : " + str(e))
            return {}
    # Function to get AI Services CR file from deployment
    def get_ai_services_cr(self, namespace, logger=None):
        # Attempt to list the AI Services CR in the specific namespace
        try:
            cr_details = self._custom_api.list_namespaced_custom_object(
                group="ccxaiservices.operator.ibm.com",
                version="v1",
                namespace=namespace,
                plural="ccxaiservices"
            )
            cr = cr_details["items"][0]

            if len(cr) == 0:
                return {}
            else:
                self._logger.info("Cleaning up the AI Services Custom Resource file before returning it.")
                # Remove unused sections from the CR
                remove_fields = ["creationTimestamp",
                                 "generation",
                                 "resourceVersion",
                                 "uid",
                                 "managedFields"]
                for field in remove_fields:
                    if field in cr["metadata"].keys():
                        del cr["metadata"][field]
                if "annotations" in cr["metadata"].keys():
                    if 'kubectl.kubernetes.io/last-applied-configuration' in cr["metadata"]["annotations"]:
                        del cr["metadata"]["annotations"]['kubectl.kubernetes.io/last-applied-configuration']
                    if not cr["metadata"]["annotations"]:
                        del cr["metadata"]["annotations"]
                return cr
        except ApiException as e:
            if e.status == 404:
                self._logger.info(f"No AI Services Custom Resource file found in '{namespace}'.")
                return {}
        except Exception as e:
            self._logger.info("Error while checking for AI Services Custom Resource file : " + str(e))
            return {}


    def scale_operator_deployment(self, namespace, deployment_name, scale="down"):
        try:
            # Retrieve the deployment object
            deployment = self._apps_v1.read_namespaced_deployment(deployment_name, namespace)

            # Patch the deployment object
            self._apps_v1.patch_namespaced_deployment_scale(
                name=deployment.metadata.name,
                namespace=namespace,
                body={"spec": {"replicas": 0}}
            )
            return True
        except Exception as e:
            self._logger.info(f"Error in scaling operator deployment: {e}")
            return False

    # Function to scale down pods
    def scale_pods_in_namespace(self, namespace, deployments, scale="down"):
        if scale == "down":
            try:
                for deployment in deployments:
                    # Scale down each pod to 0 replicas
                    if deployment.metadata.name != "ibm-fncm-operator":
                        self._apps_v1.patch_namespaced_deployment_scale(
                            name=deployment.metadata.name,
                            namespace=namespace,
                            body={"spec": {"replicas": 0}}
                        )

            except Exception as e:
                self._logger.info(f"Error in scaling down pods function: {e}")
        else:
            try:
                # List all pods in the namespace
                deployments = self._apps_v1.list_namespaced_deployment(namespace=namespace).items

                for deployment in deployments:
                    # Scale down each pod to 0 replicas
                    if deployment.metadata.name == "ibm-fncm-operator":
                        self._apps_v1.patch_namespaced_deployment_scale(
                            name=deployment.metadata.name,
                            namespace=namespace,
                            body={"spec": {"replicas": 1}}
                        )

            except Exception as e:
                self._logger.info(f"Error in scaling up pods function: {e}")

    def get_deployments_by_owner_reference(self, namespace, owner_reference_name):

        try:
            # List deployments in the specified namespace
            deployments = self._apps_v1.list_namespaced_deployment(namespace)

            # Filter deployments based on owner reference name
            filtered_deployments = [deployment for deployment in deployments.items
                                    if deployment.metadata.owner_references
                                    and any(
                    owner.name == owner_reference_name for owner in deployment.metadata.owner_references)]

            return filtered_deployments

        except Exception as e:
            self._logger.info(f"Error in get_deployments_by_owner_reference function: {e}")

    # Function to collect init-containers names from a deployment
    def get_init_containers_for_deployment(self, namespace, deployment_name):
        try:
            # Retrieve the deployment object
            deployment = self._apps_v1.read_namespaced_deployment(deployment_name, namespace)
            # Get the init containers for the deployment
            init_containers = deployment.spec.template.spec.init_containers

            if not init_containers:
                return []


            return [container.name for container in init_containers]

        except Exception as e:
            self._logger.info(f"Error getting init-containers for deployment: {e}")

    def get_pods_for_deployment(self, namespace, deployment_name):
        try:
            # Retrieve the deployment object
            deployment = self._apps_v1.read_namespaced_deployment(deployment_name, namespace)
            # Get the label selector for the deployment
            label_selector = ",".join(
                [f"{key}={value}" for key, value in deployment.spec.selector.match_labels.items()])
            # Use the label selector to list pods with matching labels
            pods = self._core_v1.list_namespaced_pod(namespace, label_selector=label_selector)

            return pods.items

        except Exception as e:
            self._logger.info(f"Error getting pods for deployment: {e}")

    # Get pods names for a deployment
    def get_pod_names_for_deployment(self, namespace, deployment_name):

        try:
            # Retrieve the deployment object
            deployment = self._apps_v1.read_namespaced_deployment(deployment_name, namespace)
            # Get the label selector for the deployment
            label_selector = ",".join(
                [f"{key}={value}" for key, value in deployment.spec.selector.match_labels.items()])
            # Use the label selector to list pods with matching labels
            pods = self._core_v1.list_namespaced_pod(namespace, label_selector=label_selector)

            return [pod.metadata.name for pod in pods.items]

        except Exception as e:
            self._logger.info(f"Error getting pods for deployment: {e}")
