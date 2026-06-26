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

"""
AI Services Artifact Generator

This module generates Kubernetes artifacts for IBM Content Cortex AI Services:
- Custom Resource (CR) for CCXAIServices
- Secret for WatsonX credentials
- ConfigMap for AI Services configuration
"""

import base64
import json
import os
from logging import Logger
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import jinja2
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree
from rich.text import Text
from ruamel.yaml import YAML, CommentedMap
from ruamel.yaml.scalarstring import SingleQuotedScalarString

from ..utilities.prerequisites_utilites import collect_visible_files, split_pem


class GenerateAIServices:
    """
    Generator class for AI Services Kubernetes artifacts.
    
    Generates:
    - CCXAIServices Custom Resource (CR)
    - WatsonX credentials secret
    - AI Services configuration ConfigMap
    """

    def __init__(
        self,
        aiservices_properties: Dict,
        deployment_properties: Dict,
        idp_properties: Dict,
        db_properties: Dict,
        aiservices_integration_properties: Optional[Dict] = None,
        ingress_properties: Optional[Dict] = None,
        egress_properties: Optional[Dict] = None,
        namespace: str = "",
        logger: Optional[Logger] = None,
        console: Optional[Console] = None
    ):
        """
        Initialize the AI Services artifact generator.

        Args:
            aiservices_properties: Dictionary containing AI Services configuration
            deployment_properties: Dictionary containing deployment configuration
            idp_properties: Dictionary containing IDP/OIDC configuration
            db_properties: Dictionary containing database configuration
            aiservices_integration_properties: Dictionary containing integration configuration
            ingress_properties: Dictionary containing ingress configuration
            egress_properties: Dictionary containing egress configuration
            namespace: Kubernetes namespace for deployment
            logger: Optional logger instance
            console: Optional console instance
        """
        self._logger = logger
        self._console = console or Console()
        self._aiservices_properties = aiservices_properties
        self._deployment_properties = deployment_properties
        self._idp_properties = idp_properties
        self._db_properties = db_properties
        self._aiservices_integration_properties = aiservices_integration_properties or {}
        self._ingress_properties = ingress_properties or {}
        self._egress_properties = egress_properties or {}
        self._namespace = namespace
        
        # Get the provider section from nested structure
        self._provider_section = self._get_provider_section()
        
        # Integration properties are at the root level (no section header)
        self._integration_section = self._aiservices_integration_properties

        # Version from deployment properties
        self.ccx_version = self._deployment_properties.get("CCX_Version", "26.0.0")
        
        # Vault configuration
        self._vault_enabled = self._deployment_properties.get("VAULT_ENABLED", False)
        self._vault_url = self._deployment_properties.get("VAULT_URL", "")
        self._vault_path = self._deployment_properties.get("VAULT_PATH", "")
        self._vault_role = self._deployment_properties.get("VAULT_ROLE", "")
        self._vault_cert_path = self._deployment_properties.get("VAULT_CERT_PATH", "")
        
        # Track generated files
        self._generated_files: List[Tuple[str, Path, int]] = []
        
        # Setup paths - following same structure as content generator
        self._generate_folder = Path.cwd() / "generatedFiles" / self._namespace
        self._generate_folder.mkdir(parents=True, exist_ok=True)
        
        # Create folders based on vault configuration
        if self._vault_enabled:
            # Vault secrets folders (must be after _generate_folder is set)
            self._vault_folder = self._generate_folder / "vault"
            self._vault_json_folder = self._vault_folder / "json-data"
            self._vault_spc_folder = self._vault_folder / "secret-provider-classes"
            self._vault_folder.mkdir(parents=True, exist_ok=True)
            self._vault_json_folder.mkdir(parents=True, exist_ok=True)
            self._vault_spc_folder.mkdir(parents=True, exist_ok=True)
            
            # Define paths but don't create K8s secret folders when vault is enabled
            self._secrets_folder = self._generate_folder / "secrets"
            self._ssl_secrets_folder = self._generate_folder / "ssl"
        else:
            # Create K8s secret folders only when vault is NOT enabled
            self._secrets_folder = self._generate_folder / "secrets"
            self._secrets_folder.mkdir(parents=True, exist_ok=True)
            
            self._ssl_secrets_folder = self._generate_folder / "ssl"
            self._ssl_secrets_folder.mkdir(parents=True, exist_ok=True)
        
        # ConfigMaps folder (always created, independent of vault)
        self._configmaps_folder = self._generate_folder / "configmaps"
        self._configmaps_folder.mkdir(parents=True, exist_ok=True)
        
        # SSL certificate input folders (always defined, independent of vault)
        self._ssl_cert_folder = Path.cwd() / "propertyFile" / self._namespace / "ssl-certs"
        self._graphql_ssl_folder = self._ssl_cert_folder / "graphql"
        
        # Temp folder for certificate processing
        self._tmp_dir = Path.cwd() / "helper_scripts" / "generate" / "tmp"
        self._tmp_dir.mkdir(parents=True, exist_ok=True)

        # CR template paths
        cr_templates_base = (
            Path.cwd() / "helper_scripts" / "generate" / "cr_templates" /
            self.ccx_version / "ai-services"
        )
        self._base_template = cr_templates_base / "base.yaml"
        self._ingress_template = cr_templates_base / "ingress.yaml"
        self._egress_template = cr_templates_base / "egress.yaml"

        # Jinja2 template setup
        self._template_folder = Path.cwd() / "helper_scripts" / "generate" / "templates"
        self._template_loader = jinja2.FileSystemLoader(str(self._template_folder))
        self._template_env = jinja2.Environment(
            loader=self._template_loader,
            trim_blocks=True,
            lstrip_blocks=True
        )

        # Output file paths - organized into subdirectories
        self._generated_cr = self._generate_folder / "ibm_ai_services_cr_production.yaml"
        self._generated_watsonx_secret = self._secrets_folder / "ibm-ai-services-secret.yaml"
        self._generated_oidc_secret = self._secrets_folder / "ibm-ai-services-oidc-secret.yaml"
        self._generated_providers_secret = self._secrets_folder / "ibm-providers-config-secret.yaml"
        self._generated_configmap = self._configmaps_folder / "ibm-ai-services-integration-config.yaml"

        # YAML handler
        self._yaml = YAML()
        self._yaml.preserve_quotes = True
        self._yaml.representer.ignore_aliases = lambda *args: True

    def _log_info(self, message: str):
        """Log info message if logger is available."""
        if self._logger:
            self._logger.info(message)
        else:
            print(f"INFO: {message}")

    def _log_error(self, message: str):
        """Log error message if logger is available."""
        if self._logger:
            self._logger.error(message)
        else:
            print(f"ERROR: {message}")

    def _render_secretproviderclass_template(
        self,
        secret_name: str,
        secret_keys: List[str],
        secret_store_type: str = "secret",
        owned_by: str = "ai-services-operator"
    ) -> str:
        """
        Render SecretProviderClass template for Vault integration.
        
        Args:
            secret_name: Name of the secret
            secret_keys: List of keys in the secret
            secret_store_type: Type of secret ("secret" or "certificate")
            owned_by: Operator that owns this secret
            
        Returns:
            Rendered YAML string
        """
        template = self._template_env.get_template('secretproviderclass.j2')
        
        # Build objects list for Vault
        objects = []
        for key in secret_keys:
            objects.append({
                'objectName': key,
                'secretPath': f"{self._vault_path}/{secret_name}",
                'secretKey': key
            })
        
        rendered = template.render(
            secret_name=secret_name,
            vault_url=self._vault_url,
            vault_role=self._vault_role,
            vault_cert_path=self._vault_cert_path,
            objects=objects,
            secret_store_type=secret_store_type,
            owned_by=owned_by
        )
        
        return rendered

    def _create_vault_json(self, secret_name: str, secret_data: Dict[str, str]) -> bool:
        """
        Create JSON file with secret data for Vault import.
        Adds a _comment metadata field to document the secret.
        
        Args:
            secret_name: Name of the secret
            secret_data: Dictionary of secret key-value pairs (plain text, not base64)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            json_file = self._vault_json_folder / f"{secret_name}.json"
            
            # Add _comment metadata field to the beginning of the JSON
            json_with_comment = {
                "_comment": f"Vault secret data for: {secret_name}. Import to path: {self._vault_path}/{secret_name}"
            }
            # Add all secret data after the comment
            json_with_comment.update(secret_data)
            
            with open(json_file, 'w') as f:
                json.dump(json_with_comment, f, indent=2)
            
            self._log_info(f"Vault JSON created: {json_file}")
            return True
            
        except Exception as e:
            self._log_error(f"Error creating Vault JSON for {secret_name}: {str(e)}")
            return False

        """Log error message if logger is available."""
        if self._logger:
            self._logger.error(message)
        else:
            print(f"ERROR: {message}")

    def _encode_base64(self, value: str) -> str:
        """
        Encode a string value to base64.

        Args:
            value: String to encode

        Returns:
            Base64 encoded string
        """
        return base64.b64encode(value.encode()).decode()

    def _load_cr_template(self, filepath: Path) -> CommentedMap:
        """
        Load a YAML CR template file.

        Args:
            filepath: Path to the YAML template file

        Returns:
            Loaded YAML data as CommentedMap
        """
        with open(filepath, 'r') as file:
            return self._yaml.load(file)

    def _write_yaml(self, data: CommentedMap, filepath: Path):
        """
        Write YAML data to a file.

        Args:
            data: YAML data to write
            filepath: Output file path
        """
        with open(filepath, 'w') as file:
            self._yaml.dump(data, file)

    def _get_provider_section(self) -> Optional[Dict]:
        """
        Get the first AI provider section from properties.
        Supports both legacy (AI_PROVIDER) and new multi-provider (PROVIDER_) formats.
        
        Returns:
            Provider section dictionary or None if not found
        """
        for key in self._aiservices_properties.keys():
            if key.startswith("AI_PROVIDER") or key.startswith("PROVIDER_"):
                return self._aiservices_properties[key]
        return None
    def _get_object_store_names(self) -> str:
        """
        Get object store symbolic names for AI Services integration.
        
        Priority order:
        1. If deploying with Content (db_properties exist), use object store names from db_properties
        2. If deploying standalone, try to extract from deployed Content CR in the cluster
        3. Fall back to OBJECT_STORE from integration properties
        4. Default to "OS1" if nothing else is available
        
        Returns:
            Comma-separated string of object store symbolic names (e.g., "OS1,OS2,OS3")
        """
        try:
            # Case 1: Deploying with Content - get from db_properties
            if self._db_properties:
                os_list = []
                for key in self._db_properties.keys():
                    if key.startswith("OS") and key != "OS_NUMBER":
                        os_label = self._db_properties[key].get("OS_LABEL", "")
                        if os_label:
                            os_list.append(os_label)
                
                if os_list:
                    object_stores = ",".join(os_list)
                    self._log_info(f"Using object stores from Content deployment: {object_stores}")
                    return object_stores
            
            # Case 2: Deploying standalone - try to extract from deployed Content CR
            try:
                from kubernetes import client, config
                from kubernetes.client.rest import ApiException
                
                # Load kubeconfig
                try:
                    config.load_kube_config()
                except:
                    config.load_incluster_config()
                
                # Create custom objects API client
                custom_api = client.CustomObjectsApi()
                
                # Try to get the FNCMCluster CR from the namespace
                try:
                    cr = custom_api.get_namespaced_custom_object(
                        group="fncm.ibm.com",
                        version="v1",
                        namespace=self._namespace,
                        plural="fncmclusters",
                        name="fncm-cluster"  # Default CR name
                    )
                    
                    # Extract object store names from the CR
                    os_list = []
                    # Type ignore for dynamic Kubernetes object structure
                    spec = cr.get("spec", {})  # type: ignore
                    init_config = spec.get("initialize_configuration", {}) if isinstance(spec, dict) else {}
                    ic_obj_store = init_config.get("ic_obj_store_creation", {}) if isinstance(init_config, dict) else {}
                    object_stores_config = ic_obj_store.get("object_stores", []) if isinstance(ic_obj_store, dict) else []
                    
                    for os_config in object_stores_config:
                        symb_name = os_config.get("oc_cpe_obj_store_symb_name", "")
                        if symb_name:
                            os_list.append(symb_name)
                    
                    if os_list:
                        object_stores = ",".join(os_list)
                        self._log_info(f"Extracted object stores from deployed Content CR: {object_stores}")
                        return object_stores
                    else:
                        self._log_info("No object stores found in deployed Content CR")
                
                except ApiException as e:
                    if e.status == 404:
                        self._log_info("No Content CR found in cluster (404 - not found)")
                    else:
                        self._log_info(f"Could not access Content CR: {e.reason}")
                except Exception as e:
                    self._log_info(f"Error reading Content CR: {str(e)}")
            
            except ImportError:
                self._log_info("Kubernetes client not available for CR extraction")
            except Exception as e:
                self._log_info(f"Could not extract object stores from cluster: {str(e)}")
            
            # Case 3: Use OBJECT_STORE from integration properties
            if self._integration_section:
                object_store = self._integration_section.get("OBJECT_STORE", "")
                if object_store:
                    self._log_info(f"Using object store from integration properties: {object_store}")
                    return object_store
            
            # Case 4: Default fallback
            self._log_info("Using default object store: os")
            return "os"
        
        except Exception as e:
            self._log_error(f"Error determining object store names: {str(e)}")
            # Return safe default
            return "os"


    def _validate_properties(self) -> bool:
        """
        Validate required AI Services properties.
        Supports both legacy (AI_PROVIDER) and new multi-provider (PROVIDER_) formats.

        Returns:
            True if all required properties are present, False otherwise
        """
        if not self._provider_section:
            self._log_error("No AI_PROVIDER section found in properties")
            return False
        
        # Check if this is new multi-provider format (has PROVIDER_ID)
        is_multi_provider = "PROVIDER_ID" in self._provider_section
        
        if is_multi_provider:
            # New multi-provider format validation
            required_fields = [
                "PROVIDER_ID",
                "PROVIDER_TYPE",
                "PROVIDER_URL",
                "ENABLED"
            ]
            
            missing_fields = []
            for field in required_fields:
                if field not in self._provider_section:
                    missing_fields.append(field)
                elif field != "ENABLED" and not self._provider_section[field]:
                    missing_fields.append(field)
            
            if missing_fields:
                self._log_error(
                    f"Missing required AI Services properties: {', '.join(missing_fields)}"
                )
                return False
            
            # For multi-provider, detailed validation is done by ReadPropAIServices
            # This is just a basic check for CR/secret generation
            return True
        else:
            # Legacy format validation
            required_fields = [
                "AI_PROVIDER_LABEL",
                "DEPLOYMENT_TYPE",
                "SERVICE_ENDPOINT",
                "API_KEY"
            ]

            missing_fields = []
            for field in required_fields:
                if field not in self._provider_section:
                    missing_fields.append(field)
                elif not self._provider_section[field]:
                    missing_fields.append(field)

            if missing_fields:
                self._log_error(
                    f"Missing required AI Services properties: {', '.join(missing_fields)}"
                )
                return False

            # Validate that at least one of SPACE_ID or PROJECT_ID is provided for SaaS
            deployment_type = self._provider_section["DEPLOYMENT_TYPE"]
            if deployment_type.lower() == "saas":
                space_id = self._provider_section.get("SPACE_ID", "")
                project_id = self._provider_section.get("PROJECT_ID", "")
                
                if not space_id and not project_id:
                    self._log_error(
                        "For SaaS deployment, at least one of SPACE_ID or "
                        "PROJECT_ID must be provided"
                    )
                    return False

            return True

    def _populate_ingress_section(self, cr_data: CommentedMap) -> None:
        """
        Populate the ingress section of the AI Services CR from ingress properties.
        Similar to Content CR ingress population logic.
        
        Args:
            cr_data: The CR data to update
        """
        if not self._ingress_properties:
            # Remove ingress parameters if no ingress properties
            ingress_params = ["sc_service_type", "sc_ingress_enable", "sc_ingress_tls_secret_name",
                            "sc_deployment_hostname_suffix", "sc_ingress_annotations"]
            shared_config = cr_data["spec"]["shared_configuration"]
            for param in ingress_params:
                if param in shared_config:
                    shared_config.pop(param)
            return
        
        # Load ingress template
        if not self._ingress_template.exists():
            self._log_error(f"Ingress template not found: {self._ingress_template}")
            return
            
        ingress_dict = self._load_cr_template(self._ingress_template)
        ingress_config = ingress_dict["spec"]["shared_configuration"]
        
        # Set service type
        if "SERVICE_TYPE" in self._ingress_properties:
            ingress_config["sc_service_type"] = self._ingress_properties["SERVICE_TYPE"]
        
        # Set ingress enabled
        if "INGRESS_ENABLED" in self._ingress_properties:
            ingress_config["sc_ingress_enable"] = self._ingress_properties["INGRESS_ENABLED"]
        
        # Set TLS secret if TLS is enabled
        if self._ingress_properties.get("INGRESS_TLS_ENABLED", False):
            if "INGRESS_TLS_SECRET_NAME" in self._ingress_properties:
                tls_secret = self._ingress_properties["INGRESS_TLS_SECRET_NAME"]
                if tls_secret and tls_secret.lower() != "<optional>":
                    ingress_config["sc_ingress_tls_secret_name"] = tls_secret
                else:
                    ingress_config.pop("sc_ingress_tls_secret_name", None)
            else:
                ingress_config.pop("sc_ingress_tls_secret_name", None)
        else:
            ingress_config.pop("sc_ingress_tls_secret_name", None)
        
        # Set ingress annotations as a dictionary (object), not an array
        # AI Services CRD expects type: object with additionalProperties
        ingress_config["sc_ingress_annotations"] = {}
        if "INGRESS_ANNOTATIONS" in self._ingress_properties and self._ingress_properties["INGRESS_ANNOTATIONS"]:
            for item in self._ingress_properties["INGRESS_ANNOTATIONS"]:
                # Parse "key: value" format
                if ":" in item:
                    item_key = item.split(":", 1)[0].strip()
                    item_value = item.split(":", 1)[1].strip().strip('"').strip("'")
                    # Add directly to dictionary, not as array element
                    ingress_config["sc_ingress_annotations"][item_key] = item_value
        
        # Set hostname suffix
        if "INGRESS_HOSTNAME" in self._ingress_properties:
            hostname = self._ingress_properties["INGRESS_HOSTNAME"]
            # Remove protocol if present
            from urllib.parse import urlparse
            parsed = urlparse(hostname if "://" in hostname else f"http://{hostname}")
            hostname_clean = parsed.hostname or hostname
            ingress_config["sc_deployment_hostname_suffix"] = hostname_clean.lower()
        
        # Update CR with ingress configuration
        cr_data["spec"]["shared_configuration"].update(ingress_config)
        self._log_info("Ingress configuration populated in AI Services CR")
    
    def _populate_egress_section(self, cr_data: CommentedMap) -> None:
        """
        Populate the egress section of the AI Services CR from deployment properties.
        Similar to Content CR egress population logic.
        
        Args:
            cr_data: The CR data to update
        """
        # Only populate egress for CNCF/standard Kubernetes deployments.
        # OCP uses Routes and should not include sc_egress_configuration here.
        platform = self._deployment_properties.get("PLATFORM", "OCP")
        
        if platform == "OCP":
            return
        
        # Load egress template
        if not self._egress_template.exists():
            self._log_error(f"Egress template not found: {self._egress_template}")
            return
            
        egress_dict = self._load_cr_template(self._egress_template)
        egress_config = egress_dict["spec"]["shared_configuration"]["sc_egress_configuration"]
        
        # Populate egress configuration for non-OCP platforms
        if platform != "OCP":
            if "K8_API_NAMESPACE" in self._deployment_properties:
                egress_config["sc_api_namespace"] = self._deployment_properties["K8_API_NAMESPACE"]
            else:
                egress_config.pop("sc_api_namespace", None)
            
            if "K8_API_PORT" in self._deployment_properties:
                egress_config["sc_api_port"] = self._deployment_properties["K8_API_PORT"]
            else:
                egress_config.pop("sc_api_port", None)
            
            if "K8_DNS_NAMESPACE" in self._deployment_properties:
                egress_config["sc_dns_namespace"] = self._deployment_properties["K8_DNS_NAMESPACE"]
            else:
                egress_config.pop("sc_dns_namespace", None)
            
            if "K8_DNS_PORT" in self._deployment_properties:
                egress_config["sc_dns_port"] = self._deployment_properties["K8_DNS_PORT"]
            else:
                egress_config.pop("sc_dns_port", None)
        
        # Only update CR if egress configuration has content
        if egress_config:
            cr_data["spec"]["shared_configuration"].update(egress_dict["spec"]["shared_configuration"])
            self._log_info("Egress configuration populated in AI Services CR")

    def generate_cr(self) -> bool:
        """
        Generate the AI Services Custom Resource (CR) YAML file.

        Returns:
            True if generation was successful, False otherwise
        """
        try:
            self._log_info("Generating AI Services Custom Resource")

            if not self._validate_properties():
                return False
            
            # After validation, provider_section is guaranteed to be not None
            assert self._provider_section is not None

            # Load base template
            if not self._base_template.exists():
                self._log_error(f"Base template not found: {self._base_template}")
                return False

            cr_data = self._load_cr_template(self._base_template)

            # Update license acceptance
            cr_data['spec']['license']['accept'] = True

            # Update shared configuration
            shared_config = cr_data['spec']['shared_configuration']
            
            # Set deployment platform
            platform = self._deployment_properties.get("PLATFORM", "OCP")
            shared_config['sc_deployment_platform'] = platform

            # Set storage class
            storage_class = self._deployment_properties.get(
                "SLOW_FILE_STORAGE_CLASSNAME",
                "<Required>"
            )
            shared_config['storage_configuration']['sc_slow_file_storage_classname'] = storage_class

            # Set image repository if using private registry
            if self._deployment_properties.get("PRIVATE_REGISTRY", False):
                registry_url = self._deployment_properties.get("PRIVATE_REGISTRY_URL", "")
                if registry_url:
                    shared_config['sc_image_repository'] = registry_url

            # Set deployment profile size
            profile_size = self._deployment_properties.get("DEPLOYMENT_PROFILE_SIZE", "small")
            shared_config['sc_deployment_profile_size'] = profile_size

            # Set license model from deployment properties
            license_model = self._deployment_properties.get("LICENSE", "FNCM.PVUNonProd")
            shared_config['sc_ccx_license_model'] = license_model

            # Add vault configuration if enabled
            if self._vault_enabled:
                if 'sc_vault_configuration' not in shared_config:
                    shared_config['sc_vault_configuration'] = CommentedMap()
                shared_config['sc_vault_configuration']['enable_external_secret_store'] = True

            # Add Redis configuration if enabled
            enable_redis = self._provider_section.get("ENABLE_REDIS", "false")
            if enable_redis.lower() == "true":
                if 'redis_configuration' not in cr_data['spec']:
                    cr_data['spec']['redis_configuration'] = CommentedMap()
                cr_data['spec']['redis_configuration']['enabled'] = True
            
            # Set network policies generation flag
            generate_network_policies = self._deployment_properties.get('GENERATE_NETWORK_POLICIES', False)
            shared_config['sc_generate_sample_network_policies'] = generate_network_policies
            
            # Populate egress configuration if needed
            if self._deployment_properties.get('RESTRICTED_INTERNET_ACCESS', False) or generate_network_policies:
                self._log_info("Populating egress configuration")
                self._populate_egress_section(cr_data)
            
            # Populate ingress configuration
            self._log_info("Populating ingress configuration")
            self._populate_ingress_section(cr_data)

            # Write the CR to file
            self._write_yaml(cr_data, self._generated_cr)
            self._log_info(f"AI Services CR generated: {self._generated_cr}")

            return True

        except Exception as e:
            self._log_error(f"Error generating AI Services CR: {str(e)}")
            return False

    def generate_watsonx_secret(self) -> bool:
        """
        Generate the WatsonX credentials secret YAML file.
        If Vault is enabled, also generates SecretProviderClass and JSON for Vault import.

        Returns:
            True if generation was successful, False otherwise
        """
        try:
            self._log_info("Generating WatsonX credentials secret")

            if not self._validate_properties():
                return False
            
            # After validation, provider_section is guaranteed to be not None
            assert self._provider_section is not None

            # Get API key
            api_key = self._provider_section["API_KEY"]
            
            # Check if API key is already base64 encoded (has {Base64} prefix)
            if api_key.startswith("{Base64}"):
                # Remove prefix and use the encoded value
                api_key_encoded = api_key[8:]
                # Decode for plain text version (for Vault JSON)
                api_key_plain = base64.b64decode(api_key_encoded).decode('utf-8')
            else:
                # Use plain text and encode it
                api_key_plain = api_key
                api_key_encoded = self._encode_base64(api_key)

            secret_name = "ibm-ai-services-secret"
            
            # If Vault is enabled, generate ONLY SecretProviderClass and JSON
            if self._vault_enabled:
                self._log_info(f"Vault enabled - generating SecretProviderClass for {secret_name}")
                
                # Generate SecretProviderClass
                secret_keys = ["WATSONX_API_KEY"]
                spc_yaml = self._render_secretproviderclass_template(
                    secret_name=secret_name,
                    secret_keys=secret_keys,
                    secret_store_type="secret",
                    owned_by="ai-services-operator"
                )
                
                spc_file = self._vault_spc_folder / f"{secret_name}.yaml"
                with open(spc_file, 'w') as f:
                    f.write(spc_yaml)
                
                self._log_info(f"SecretProviderClass generated: {spc_file}")
                
                # Generate Vault JSON (plain text values)
                vault_data = {
                    "WATSONX_API_KEY": api_key_plain
                }
                self._create_vault_json(secret_name, vault_data)
            else:
                # Create standard Kubernetes Secret only when vault is NOT enabled
                # Prepare secret data (base64 encoded for K8s secret)
                secret_data = {
                    "WATSONX_API_KEY": api_key_encoded
                }

                # Render secret template
                template = self._template_env.get_template('secret.j2')
                rendered_secret = template.render(
                    secret_name=secret_name,
                    values=secret_data
                )

                # Write secret to file
                with open(self._generated_watsonx_secret, 'w') as f:
                    f.write(rendered_secret)

                self._log_info(f"WatsonX secret generated: {self._generated_watsonx_secret}")

            return True

        except Exception as e:
            self._log_error(f"Error generating WatsonX secret: {str(e)}")
            return False

    def generate_oidc_secret(self) -> bool:
        """
        Generate the OIDC credentials secret YAML file.
        If Vault is enabled, also generates SecretProviderClass and JSON for Vault import.

        Returns:
            True if generation was successful, False otherwise
        """
        try:
            self._log_info("Generating OIDC credentials secret")

            # Check if IDP properties are available
            if not self._idp_properties or "_idp_ids" not in self._idp_properties:
                self._log_info("No IDP configuration found, skipping OIDC secret generation")
                return True

            # Get the first IDP configuration
            idp_ids = self._idp_properties.get("_idp_ids", [])
            if not idp_ids:
                self._log_info("No IDP IDs found, skipping OIDC secret generation")
                return True

            idp_id = idp_ids[0]  # Use first IDP
            idp_config = self._idp_properties.get(idp_id, {})

            # Get OIDC credentials
            client_id = idp_config.get("CLIENT_ID", "")
            client_secret = idp_config.get("CLIENT_SECRET", "")

            if not client_id or not client_secret:
                self._log_info("OIDC credentials not configured, skipping OIDC secret generation")
                return True

            # Encode credentials
            client_id_encoded = self._encode_base64(client_id)
            client_secret_encoded = self._encode_base64(client_secret)

            secret_name = "ibm-ai-services-oidc-secret"
            
            # If Vault is enabled, generate ONLY SecretProviderClass and JSON
            if self._vault_enabled:
                self._log_info(f"Vault enabled - generating SecretProviderClass for {secret_name}")
                
                # Generate SecretProviderClass
                secret_keys = ["client_id", "client_secret"]
                spc_yaml = self._render_secretproviderclass_template(
                    secret_name=secret_name,
                    secret_keys=secret_keys,
                    secret_store_type="secret",
                    owned_by="ai-services-operator"
                )
                
                spc_file = self._vault_spc_folder / f"{secret_name}.yaml"
                with open(spc_file, 'w') as f:
                    f.write(spc_yaml)
                
                self._log_info(f"SecretProviderClass generated: {spc_file}")
                
                # Generate Vault JSON (plain text values)
                vault_data = {
                    "client_id": client_id,
                    "client_secret": client_secret
                }
                self._create_vault_json(secret_name, vault_data)
            else:
                # Create standard Kubernetes Secret only when vault is NOT enabled
                # Prepare secret data (base64 encoded for K8s secret)
                secret_data = {
                    "client_id": client_id_encoded,
                    "client_secret": client_secret_encoded
                }

                # Render secret template
                template = self._template_env.get_template('secret.j2')
                rendered_secret = template.render(
                    secret_name=secret_name,
                    values=secret_data
                )

                # Write secret to file
                with open(self._generated_oidc_secret, 'w') as f:
                    f.write(rendered_secret)

                self._log_info(f"OIDC secret generated: {self._generated_oidc_secret}")

            return True

        except Exception as e:
            self._log_error(f"Error generating OIDC secret: {str(e)}")
            return False

    def generate_graphql_ssl_secret(self) -> Optional[str]:
        """
        Generate GraphQL SSL certificate secret if certificate is provided.
        If Vault is enabled, also generates SecretProviderClass and JSON for Vault import.
        
        Returns:
            Secret name if generated, None if no certificate found or on error
            
        Note:
            - If AI Services is deployed WITH Content (db_properties exist), returns 'content-root-ca'
            - If AI Services is deployed ALONE, generates 'ibm-graphql-ssl-secret' from graphql SSL folder
        """
        try:
            # Check if Content is deployed (db_properties exist)
            content_deployed = bool(self._db_properties)
            
            if content_deployed:
                # AI Services deployed WITH Content - use Content's root CA
                self._log_info("Content deployment detected - using content-root-ca for GraphQL SSL")
                return "content-root-ca"
            
            # AI Services deployed ALONE - generate GraphQL SSL secret from graphql folder
            # Check if GraphQL SSL certificate folder exists
            if not self._graphql_ssl_folder.exists():
                self._log_info("No GraphQL SSL certificate folder found, skipping secret generation")
                return None
            
            # Collect certificate files
            ssl_certs = collect_visible_files(str(self._graphql_ssl_folder))
            if not ssl_certs:
                self._log_info("No GraphQL SSL certificates found, skipping secret generation")
                return None
            
            self._log_info(f"Found GraphQL SSL certificates: {ssl_certs}")
            
            # Process certificates
            cert_data = ""
            for i, cert_file in enumerate(ssl_certs):
                if any(ext in cert_file for ext in [".crt", ".cer", ".pem", ".cert", ".key", ".arm"]):
                    cert_path = self._graphql_ssl_folder / cert_file
                    
                    # Split PEM file if it contains multiple certificates
                    cert_list = split_pem(
                        self._logger,
                        str(cert_path),
                        str(self._tmp_dir),
                        f'graphql-cert-{i}'
                    )
                    
                    # Read and concatenate all certificates
                    for cert in cert_list:
                        self._log_info(f"Reading certificate: {cert}")
                        with open(cert, "r") as f:
                            cert_data += f.read() + '\n'
            
            if not cert_data:
                self._log_info("No valid certificate data found")
                return None
            
            # Generate secret name
            secret_name = "ibm-graphql-ssl-secret"
            
            # If Vault is enabled, generate ONLY SecretProviderClass and JSON
            if self._vault_enabled:
                self._log_info(f"Vault enabled - generating SecretProviderClass for {secret_name}")
                
                # Generate SecretProviderClass
                secret_keys = ["tls.crt"]
                spc_yaml = self._render_secretproviderclass_template(
                    secret_name=secret_name,
                    secret_keys=secret_keys,
                    secret_store_type="certificate",
                    owned_by="ai-services-operator"
                )
                
                spc_file = self._vault_spc_folder / f"{secret_name}.yaml"
                with open(spc_file, 'w') as f:
                    f.write(spc_yaml)
                
                self._log_info(f"SecretProviderClass generated: {spc_file}")
                
                # Generate Vault JSON (plain text certificate)
                vault_data = {
                    "tls.crt": cert_data
                }
                self._create_vault_json(secret_name, vault_data)
            else:
                # Create standard Kubernetes Secret only when vault is NOT enabled
                # Encode certificate data to base64
                encoded_cert = base64.b64encode(cert_data.encode()).decode('utf-8')
                
                # Prepare secret data (base64 encoded for K8s secret)
                secret_data = {
                    'tls.crt': encoded_cert
                }
                
                # Render secret using data template (base64-encoded)
                template = self._template_env.get_template('secret.j2')
                rendered_secret = template.render(
                    secret_name=secret_name,
                    values=secret_data
                )
                
                # Write secret to SSL folder
                secret_file = self._ssl_secrets_folder / f"{secret_name}.yaml"
                with open(secret_file, 'w') as f:
                    f.write(rendered_secret)
                
                self._log_info(f"GraphQL SSL secret generated: {secret_file}")
                
                # Track generated file
                line_count = len(rendered_secret.splitlines())
                self._generated_files.append(("GraphQL SSL Secret", secret_file, line_count))
            
            return secret_name
            
        except Exception as e:
            self._log_error(f"Error generating GraphQL SSL secret: {str(e)}")
            import traceback
            self._log_error(traceback.format_exc())
            return None

    def generate_lwe_provider_ssl_secrets(self) -> List[Tuple[str, str]]:
        """
        Generate SSL certificate secrets for LWE (Lightweight Engine) providers.
        
        Returns:
            List of tuples containing (provider_id, secret_name) for each generated secret
        """
        generated_secrets = []
        
        try:
            # Check if we have multi-provider configuration
            provider_sections = {}
            for key in self._aiservices_properties.keys():
                if key.startswith("PROVIDER_"):
                    provider_sections[key] = self._aiservices_properties[key]
            
            if not provider_sections:
                self._log_info("No multi-provider configuration found, skipping LWE SSL secret generation")
                return generated_secrets
            
            # Process each provider
            for provider_key in sorted(provider_sections.keys()):
                provider = provider_sections[provider_key]
                
                # Skip disabled providers
                enabled = provider.get("ENABLED", "true")
                if isinstance(enabled, str):
                    enabled = enabled.lower() == "true"
                
                if not enabled:
                    continue
                
                provider_id = provider.get("PROVIDER_ID", "")
                provider_type = provider.get("PROVIDER_TYPE", "").lower()
                provider_url = provider.get("PROVIDER_URL", "")
                
                # Only process LWE providers with HTTPS URLs
                if provider_type != "watsonx_lwe":
                    continue
                
                if not provider_url or not provider_url.startswith("https://") or provider_url == "<Required>":
                    self._log_info(f"Skipping SSL secret for provider {provider_id}: no HTTPS URL configured")
                    continue
                
                # Expected SSL folder name: ai-provider-<provider_id_lowercase>
                ssl_folder_name = f"ai-provider-{provider_id.lower()}"
                provider_ssl_folder = self._ssl_cert_folder / ssl_folder_name
                
                # Check if SSL certificate folder exists
                if not provider_ssl_folder.exists():
                    self._log_info(f"No SSL certificate folder found for provider {provider_id}: {provider_ssl_folder}")
                    continue
                
                # Collect certificate files
                ssl_certs = collect_visible_files(str(provider_ssl_folder))
                if not ssl_certs:
                    self._log_info(f"No SSL certificates found for provider {provider_id}")
                    continue
                
                self._log_info(f"Found SSL certificates for provider {provider_id}: {ssl_certs}")
                
                # Process certificates
                cert_data = ""
                for i, cert_file in enumerate(ssl_certs):
                    if any(ext in cert_file for ext in [".crt", ".cer", ".pem", ".cert", ".key", ".arm"]):
                        cert_path = provider_ssl_folder / cert_file
                        
                        # Split PEM file if it contains multiple certificates
                        cert_list = split_pem(
                            self._logger,
                            str(cert_path),
                            str(self._tmp_dir),
                            f'{provider_id}-cert-{i}'
                        )
                        
                        # Read and concatenate all certificates
                        for cert in cert_list:
                            self._log_info(f"Reading certificate: {cert}")
                            with open(cert, "r") as f:
                                cert_data += f.read() + '\n'
                
                if not cert_data:
                    self._log_info(f"No valid certificate data found for provider {provider_id}")
                    continue
                
                # Encode certificate data to base64
                encoded_cert = base64.b64encode(cert_data.encode()).decode('utf-8')
                
                # Prepare secret data
                secret_data = {
                    'tls.crt': encoded_cert
                }
                
                # Generate secret name: ibm-<provider_id>-ssl-secret
                secret_name = f"ibm-{provider_id.lower()}-ssl-secret"
                
                # Render secret using data template (base64-encoded)
                template = self._template_env.get_template('secret.j2')
                rendered_secret = template.render(
                    secret_name=secret_name,
                    values=secret_data
                )
                
                # Write secret to SSL folder
                secret_file = self._ssl_secrets_folder / f"{secret_name}.yaml"
                with open(secret_file, 'w') as f:
                    f.write(rendered_secret)
                
                self._log_info(f"LWE provider SSL secret generated: {secret_file}")
                
                # Track generated file
                line_count = len(rendered_secret.splitlines())
                self._generated_files.append((f"LWE Provider SSL Secret ({provider_id})", secret_file, line_count))
                
                # Add to list of generated secrets
                generated_secrets.append((provider_id, secret_name))
            
            return generated_secrets
            
        except Exception as e:
            self._log_error(f"Error generating LWE provider SSL secrets: {str(e)}")
            import traceback
            self._log_error(traceback.format_exc())
            return generated_secrets

    def generate_providers_config_secret(self) -> bool:
        """
        Generate the providers configuration secret containing providers_config.json.
        
        This secret contains the multi-provider configuration in JSON format with:
        - active_llm: The key of the currently active model (provider_id-model_id)
        - llms: Dictionary of all configured providers and their models
        
        Returns:
            True if generation was successful, False otherwise
        """
        try:
            self._log_info("Generating providers configuration secret")
            
            # Check if we have multi-provider configuration (PROVIDER_1, PROVIDER_2, etc.)
            provider_sections = {}
            for key in self._aiservices_properties.keys():
                if key.startswith("PROVIDER_"):
                    provider_sections[key] = self._aiservices_properties[key]
            
            if not provider_sections:
                self._log_info("No multi-provider configuration found, skipping providers config secret")
                return True
            
            # Generate LWE provider SSL secrets first and get the mapping
            lwe_ssl_secrets_map = {}
            lwe_ssl_secrets = self.generate_lwe_provider_ssl_secrets()
            for provider_id, secret_name in lwe_ssl_secrets:
                lwe_ssl_secrets_map[provider_id] = secret_name
                self._log_info(f"LWE provider '{provider_id}' has SSL secret: {secret_name}")
            
            # Build the providers_config.json structure
            providers_config = {
                "active_llm": "",
                "llms": {}
            }
            
            # Track default models for validation
            default_models = []
            enabled_provider_count = 0
            
            # Process each provider
            for provider_key in sorted(provider_sections.keys()):
                provider = provider_sections[provider_key]
                
                # Skip disabled providers - handle TOML string booleans
                enabled = provider.get("ENABLED", "true")
                if isinstance(enabled, str):
                    enabled = enabled.lower() == "true"
                
                if not enabled:
                    self._log_info(f"Skipping disabled provider: {provider_key}")
                    continue
                
                enabled_provider_count += 1
                
                provider_id = provider.get("PROVIDER_ID", "")
                provider_type = provider.get("PROVIDER_TYPE", "")
                provider_url = provider.get("PROVIDER_URL", "")
                
                if not provider_id or not provider_type:
                    continue
                
                # Get models for this provider
                models = provider.get("models", [])
                if not models:
                    continue
                
                # Process each model
                for model in models:
                    model_id = model.get("MODEL", "")
                    
                    # Handle TOML string booleans for DEFAULT
                    is_default = model.get("DEFAULT", "false")
                    if isinstance(is_default, str):
                        is_default = is_default.lower() == "true"
                    
                    if not model_id:
                        continue
                    
                    # Create unique key: provider_id-model_id
                    llm_key = f"{provider_id}-{model_id.replace('/', '-')}"
                    
                    # Build provider-specific configuration
                    if provider_type == "watsonx_saas":
                        llm_config = {
                            "provider": "watsonx",
                            "deployment_mode": "saas",
                            "url": provider_url,
                            "space_id": provider.get("SPACE_ID", ""),
                            "api_key": provider.get("API_KEY", ""),
                            "model": model_id,
                            "max_completion_tokens": model.get("MAX_COMPLETION_TOKENS", 0),
                            "temperature": model.get("TEMPERATURE", 0.0),
                            "context_window_token_limit": model.get("CONTEXT_WINDOW_TOKEN_LIMIT", 0)
                        }
                    
                    elif provider_type == "watsonx_lwe":
                        llm_config = {
                            "provider": "watsonx",
                            "deployment_mode": "lightweight",
                            "url": provider_url,
                            "instance_id": provider.get("INSTANCE_ID", "openshift"),
                            "username": provider.get("USERNAME", ""),
                            "api_key": provider.get("API_KEY", ""),
                            "version": provider.get("VERSION", "5.4"),
                            "model": model_id,
                            "max_completion_tokens": model.get("MAX_COMPLETION_TOKENS", 0),
                            "temperature": model.get("TEMPERATURE", 0.0),
                            "context_window_token_limit": model.get("CONTEXT_WINDOW_TOKEN_LIMIT", 0)
                        }
                        
                        # Add SSL configuration if certificate exists for this provider
                        if provider_id in lwe_ssl_secrets_map:
                            ssl_secret_name = lwe_ssl_secrets_map[provider_id]
                            llm_config["verify_ssl"] = f"/etc/certs/{provider_id}/tls.crt"
                            llm_config["ssl_secret_name"] = ssl_secret_name
                            self._log_info(f"Provider '{provider_id}' configured with SSL: verify_ssl={llm_config['verify_ssl']}, ssl_secret_name={ssl_secret_name}")
                        else:
                            llm_config["verify_ssl"] = False
                            self._log_info(f"Provider '{provider_id}' configured without SSL verification")
                    
                    elif provider_type == "microsoft_foundry":
                        llm_config = {
                            "provider": "azure",
                            "endpoint": provider_url,
                            "model": model_id,
                            "api_key": provider.get("API_KEY", ""),
                            "use_entra_id": model.get("USE_ENTRA_ID", False),
                            "max_completion_tokens": model.get("MAX_COMPLETION_TOKENS", 16384),
                            "temperature": model.get("TEMPERATURE", 1.0),
                            "timeout": model.get("TIMEOUT", 60),
                            "api_version": model.get("API_VERSION", "2024-12-01-preview"),
                            "context_window_token_limit": model.get("CONTEXT_WINDOW_TOKEN_LIMIT", 0)
                        }
                        
                        # Add reasoning_effort if model is o3-mini
                        if "o3-mini" in model_id.lower():
                            llm_config["reasoning_effort"] = "medium"
                    
                    else:
                        self._log_error(f"Unknown provider type: {provider_type}")
                        continue
                    
                    # Add to llms dictionary
                    providers_config["llms"][llm_key] = llm_config
                    
                    # Track default models
                    if is_default:
                        default_models.append(llm_key)
                        # Set as active (will be validated below)
                        if not providers_config["active_llm"]:
                            providers_config["active_llm"] = llm_key
            
            # Validate configuration
            if enabled_provider_count == 0:
                self._log_error("No enabled providers found. At least one provider must be enabled.")
                return False
            
            if not providers_config["llms"]:
                self._log_error("No valid models found in enabled providers")
                return False
            
            # Validate exactly one default model
            if len(default_models) == 0:
                self._log_error("No default model specified. Exactly one model across all enabled providers must be marked as DEFAULT=true.")
                return False
            
            if len(default_models) > 1:
                self._log_error(f"Multiple default models found: {', '.join(default_models)}. Only one model across all enabled providers can be marked as DEFAULT=true.")
                return False
            
            # Log the active model
            self._log_info(f"Active LLM set to: {providers_config['active_llm']}")
            
            # Convert to JSON string
            import json
            providers_json = json.dumps(providers_config, indent=2)
            
            secret_name = "ibm-providers-config-secret"
            
            # If Vault is enabled, create ONLY SecretProviderClass and JSON
            if self._vault_enabled:
                self._log_info(f"Vault enabled - generating SecretProviderClass for {secret_name}")
                
                # Generate SecretProviderClass
                secret_keys = ["providers_config.json"]
                spc_yaml = self._render_secretproviderclass_template(
                    secret_name=secret_name,
                    secret_keys=secret_keys,
                    secret_store_type="secret",
                    owned_by="ai-services-operator"
                )
                
                spc_file = self._vault_spc_folder / f"{secret_name}.yaml"
                with open(spc_file, 'w') as f:
                    f.write(spc_yaml)
                
                self._log_info(f"SecretProviderClass generated: {spc_file}")
                
                # Generate Vault JSON (plain text JSON string)
                vault_data = {
                    "providers_config.json": providers_json
                }
                self._create_vault_json(secret_name, vault_data)
            else:
                # Create standard Kubernetes Secret only when vault is NOT enabled
                # Prepare secret data as string (not base64 encoded)
                secret_data = {
                    "providers_config.json": providers_json
                }
                
                # Render secret template using string_secret.j2 for stringData
                template = self._template_env.get_template('string_secret.j2')
                rendered_secret = template.render(
                    secret_name=secret_name,
                    values=secret_data
                )
                
                # Write secret to file
                providers_secret_path = self._secrets_folder / f"{secret_name}.yaml"
                with open(providers_secret_path, 'w') as f:
                    f.write(rendered_secret)
                
                self._log_info(f"Providers config secret generated: {providers_secret_path}")
                
                # Track the generated file
                self._generated_providers_secret = providers_secret_path
            
            return True
        
        except Exception as e:
            self._log_error(f"Error generating providers config secret: {str(e)}")
            import traceback
            self._log_error(traceback.format_exc())
            return False


    def generate_configmap(self, graphql_secret_name: Optional[str] = None) -> bool:
        """
        Generate the AI Services configuration ConfigMap YAML file.
        
        Args:
            graphql_secret_name: Name of the GraphQL SSL secret to use:
                - 'content-root-ca' if AI Services is deployed WITH Content
                - 'ibm-graphql-ssl-secret' if AI Services is deployed ALONE (from graphql SSL folder)
                - None if no GraphQL SSL configuration is available

        Returns:
            True if generation was successful, False otherwise
        """
        try:
            self._log_info("Generating AI Services ConfigMap")
            
            # Ensure provider section exists
            if not self._provider_section:
                self._log_error("No AI_PROVIDER section found in properties")
                return False

            # Prepare ConfigMap data
            config_data = CommentedMap()

            # Note: WatsonX provider configuration (DEPLOYMENT_TYPE, SERVICE_ENDPOINT, SPACE_ID)
            # is now stored in the ibm-providers-config-secret instead of this ConfigMap

            # JWT and OIDC configuration from IDP properties
            jwt_issuer = ""
            jwt_jws_url = ""
            jwt_audience = ""
            oidc_auth_server = ""
            oidc_config_url = ""
            oidc_client_secret = ""
            
            if self._idp_properties and "_idp_ids" in self._idp_properties:
                idp_ids = self._idp_properties.get("_idp_ids", [])
                if idp_ids:
                    idp_id = idp_ids[0]  # Use first IDP
                    idp_config = self._idp_properties.get(idp_id, {})

                    # Get IDP endpoints
                    discovery_endpoint = idp_config.get("DISCOVERY_ENDPOINT", "")
                    oidc_config_url = discovery_endpoint
                    
                    # JWT issuer from IDP configuration
                    jwt_issuer = idp_config.get("ISSUER", "")
                    
                    # JWT JWS URL from JWKS endpoint
                    jwt_jws_url = idp_config.get("JWKS_ENDPOINT", "")
                    
                    # Set JWT audience to the same value as CLIENT_ID
                    jwt_audience = idp_config.get("CLIENT_ID", "")
                    
                    # Extract auth server from discovery endpoint (remove .well-known path)
                    if discovery_endpoint:
                        oidc_auth_server = discovery_endpoint.replace("/.well-known/openid-configuration", "")
                        # Add /protocol/openid-connect/auth for the auth endpoint
                        if not oidc_auth_server.endswith("/protocol/openid-connect/auth"):
                            oidc_auth_server = oidc_auth_server + "/protocol/openid-connect/auth"
                    
                    # Client secret reference (stored in secret)
                    oidc_client_secret = "ibm-ai-services-oidc-secret"
            
            # Add integration properties if available
            if self._integration_section:
                # Map integration properties to ConfigMap keys (using lowercase with underscores)
                # Wrap all string values with SingleQuotedScalarString for single-quote formatting
                graphql_endpoint = self._integration_section.get("GRAPHQL_ENDPOINT", "")
                # Ensure graphql_url includes the full path
                if graphql_endpoint and not graphql_endpoint.endswith("/content-services-graphql/graphql"):
                    graphql_endpoint = graphql_endpoint + "/content-services-graphql/graphql"
                config_data["graphql_url"] = SingleQuotedScalarString(graphql_endpoint)
                
                # Use GraphQL SSL secret name if provided
                # This will be either:
                # - 'content-root-ca' when deployed with Content
                # - 'ibm-graphql-ssl-secret' when deployed standalone with graphql SSL folder
                if graphql_secret_name:
                    config_data["graphql_cert_secret"] = SingleQuotedScalarString(graphql_secret_name)
                    self._log_info(f"Using GraphQL SSL secret: {graphql_secret_name}")
                
                auth_mode = self._integration_section.get("AUTH_MODE", "dual")
                config_data["auth_mode"] = SingleQuotedScalarString(auth_mode)
                
                # Get object store names - either from integration properties or from deployed Content CR
                object_stores = self._get_object_store_names()
                config_data["object_stores"] = SingleQuotedScalarString(object_stores)
                
                # Add cors_allowed_origins with the navigator external URL (for CORS configuration)
                navigator_url = self._integration_section.get("NAVIGATOR_EXTERNAL_URL", "")
                if navigator_url:
                    config_data["cors_allowed_origins"] = SingleQuotedScalarString(navigator_url)
                
                # Add JWT configuration (all wrapped with SingleQuotedScalarString)
                config_data["jwt_algorithm"] = SingleQuotedScalarString("RS256")
                config_data["jwt_audience"] = SingleQuotedScalarString(jwt_audience)
                config_data["jwt_issuer"] = SingleQuotedScalarString(jwt_issuer)
                config_data["jwt_jws_url"] = SingleQuotedScalarString(jwt_jws_url)
                config_data["jwt_public_key_secret"] = SingleQuotedScalarString("ibm-idp-public-key-secret")
                config_data["jwt_required_scopes"] = SingleQuotedScalarString("openid,profile,email")
                
                # Add OIDC properties with lowercase keys (all wrapped with SingleQuotedScalarString)
                config_data["oidc_auth_server"] = SingleQuotedScalarString(oidc_auth_server)
                config_data["oidc_config_url"] = SingleQuotedScalarString(oidc_config_url)
                config_data["oidc_client_secret"] = SingleQuotedScalarString(oidc_client_secret)
                config_data["oidc_ssl_secret"] = SingleQuotedScalarString("ibm-idp-ssl-secret")

            # Create ConfigMap structure using CommentedMap
            configmap = CommentedMap()
            configmap['apiVersion'] = 'v1'
            configmap['kind'] = 'ConfigMap'
            configmap['metadata'] = CommentedMap()
            configmap['metadata']['name'] = 'ibm-ai-services-integration-config'
            configmap['metadata']['labels'] = CommentedMap()
            configmap['metadata']['labels']['ccx.ibm.com/backup-type'] = 'mandatory'
            configmap['metadata']['labels']['app.kubernetes.io/name'] = 'ibm-ai-services'
            configmap['metadata']['labels']['app.kubernetes.io/instance'] = 'ai-services'
            configmap['metadata']['labels']['app.kubernetes.io/managed-by'] = 'ibm-ai-services'
            configmap['data'] = config_data

            # Write ConfigMap to file
            self._write_yaml(configmap, self._generated_configmap)
            self._log_info(f"AI Services ConfigMap generated: {self._generated_configmap}")

            return True

        except Exception as e:
            self._log_error(f"Error generating AI Services ConfigMap: {str(e)}")
            return False

    def generate_idp_secret(self) -> bool:
        """
        Generate the IDP credentials secret by calling GenerateSecrets.
        
        Returns:
            True if generation was successful, False otherwise
        """
        try:
            if not self._idp_properties:
                self._log_info("No IDP properties found, skipping IDP secret generation")
                return True
            
            content_enabled = any([
                self._deployment_properties.get("BAN", False),
                self._deployment_properties.get("CPE", False),
                self._deployment_properties.get("CMIS", False),
                self._deployment_properties.get("GRAPHQL", False)
            ])

            if not content_enabled:
                self._log_info(
                    "Skipping IDP credentials secret generation for AI Services-only deployment; "
                    "ibm-idp-oidc-secret is only required when Content is included"
                )
                return True

            self._log_info("Generating IDP credentials secret")
            
            # Import GenerateSecrets class
            from .generate_secrets import GenerateSecrets
            
            # Create GenerateSecrets instance with deployment properties for vault configuration
            secrets_generator = GenerateSecrets(
                namespace=self._namespace,
                idp_properties=self._idp_properties,
                deployment_properties=self._deployment_properties,
                logger=self._logger
            )
            
            # Generate the IDP secret
            secrets_generator.create_idp_secret()
            
            self._log_info("IDP credentials secret generated successfully")
            
            # Track the generated file(s) - there may be multiple IDP secrets
            for idp_id in self._idp_properties.get('_idp_ids', []):
                secret_name = f"ibm-{idp_id.lower()}-oidc-secret"
                secret_path = self._secrets_folder / f"{secret_name}.yaml"
                if secret_path.exists():
                    self._track_generated_file(secret_path)
            
            return True
            
        except Exception as e:
            self._log_error(f"Error generating IDP secret: {str(e)}")
            return False

    def generate_idp_public_key_secret(self) -> bool:
        """
        Generate the IDP public key secret by calling GenerateSecrets.
        
        Returns:
            True if generation was successful, False otherwise
        """
        try:
            if not self._idp_properties:
                self._log_info("No IDP properties found, skipping IDP public key secret generation")
                return True
            
            self._log_info("Generating IDP public key secret")
            
            # Import GenerateSecrets class
            from .generate_secrets import GenerateSecrets
            
            # Create GenerateSecrets instance with deployment properties for vault configuration
            secrets_generator = GenerateSecrets(
                namespace=self._namespace,
                idp_properties=self._idp_properties,
                deployment_properties=self._deployment_properties,
                logger=self._logger
            )
            
            # Generate the IDP public key secret
            result = secrets_generator.create_idp_public_key_secret()
            
            if result:
                self._log_info("IDP public key secret generated successfully")
                # Track the generated file
                secret_path = self._ssl_secrets_folder / "ibm-idp-public-key-secret.yaml"
                if secret_path.exists():
                    self._track_generated_file(secret_path)
            else:
                self._log_error(
                    "Unable to generate IDP public key secret from the configured JWKS endpoint. "
                    "Verify the IDP URL is reachable from this machine and that the JWKS endpoint is correct."
                )
            
            return result
            
        except Exception as e:
            self._log_error(f"Error generating IDP public key secret: {str(e)}")
            return False

    def generate_idp_ssl_secret(self) -> bool:
        """
        Generate the IDP SSL certificate secret by calling GenerateSecrets.
        
        Returns:
            True if generation was successful, False otherwise
        """
        try:
            if not self._idp_properties:
                self._log_info("No IDP properties found, skipping IDP SSL secret generation")
                return True
            
            self._log_info("Generating IDP SSL certificate secret")
            
            # Import GenerateSecrets class
            from .generate_secrets import GenerateSecrets
            
            # Create GenerateSecrets instance with deployment properties for vault configuration
            secrets_generator = GenerateSecrets(
                namespace=self._namespace,
                idp_properties=self._idp_properties,
                deployment_properties=self._deployment_properties,
                logger=self._logger
            )
            
            # Generate the IDP SSL secrets
            secrets_generator.create_idp_ssl_secrets()
            
            self._log_info("IDP SSL certificate secret generated successfully")
            
            # Track the generated file
            secret_path = self._ssl_secrets_folder / "ibm-idp-ssl-secret.yaml"
            if secret_path.exists():
                self._track_generated_file(secret_path)
            
            return True
            
        except Exception as e:
            self._log_error(f"Error generating IDP SSL secret: {str(e)}")
            return False

    def _track_generated_file(self, file_path: Path) -> None:
        """Track a generated file with its size."""
        if file_path.exists():
            size = file_path.stat().st_size
            # Get relative path from generate folder
            try:
                rel_path = file_path.relative_to(self._generate_folder)
            except ValueError:
                rel_path = file_path
            self._generated_files.append((file_path.name, rel_path, size))
    
    def _display_generation_summary(self) -> None:
        """Display modern generation summary with rich formatting."""
        # Create file tree
        tree = Tree(
            f"[bold cyan]📁 {self._generate_folder.name}[/bold cyan]",
            guide_style="bright_black"
        )
        
        # Group files by directory
        dirs: Dict[str, List[Tuple[str, int]]] = {}
        for name, rel_path, size in self._generated_files:
            parent = str(rel_path.parent) if rel_path.parent != Path('.') else "root"
            if parent not in dirs:
                dirs[parent] = []
            dirs[parent].append((name, size))
        
        # Add files to tree
        for dir_name in sorted(dirs.keys()):
            if dir_name == "root":
                dir_node = tree
            else:
                dir_node = tree.add(f"[cyan]📂 {dir_name}[/cyan]")
            
            for name, size in sorted(dirs[dir_name]):
                size_str = self._format_file_size(size)
                dir_node.add(f"[green]📄 {name}[/green] [dim]({size_str})[/dim]")
        
        # Create summary panel
        summary = Text()
        summary.append("✓ ", style="bold green")
        summary.append("All AI Services artifacts generated successfully!\n\n", style="bold white")
        summary.append(f"Output Directory: ", style="white")
        summary.append(f"{self._generate_folder}\n", style="cyan")
        summary.append(f"Total Files: ", style="white")
        summary.append(f"{len(self._generated_files)}", style="bold cyan")
        
        # Display panels
        self._console.print()
        self._console.print(Panel(
            summary,
            title="[bold green]Files Generated Successfully[/bold green]",
            border_style="green",
            padding=(1, 2)
        ))
        
        self._console.print()
        self._console.print(Panel(
            tree,
            title="[bold cyan]Generated Files Structure[/bold cyan]",
            border_style="cyan",
            padding=(1, 2)
        ))
        
        # Next steps
        next_steps = Text()
        next_steps.append("1. ", style="bold white")
        next_steps.append("Review the Generated files:\n", style="white")
        next_steps.append("   - Database SQL files\n", style="dim white")
        next_steps.append("   - Deployment Secrets\n", style="dim white")
        next_steps.append("   - SSL Certs in yaml format\n", style="dim white")
        next_steps.append("   - Custom Resource (CR) file\n\n", style="dim white")
        
        next_steps.append("2. ", style="bold white")
        next_steps.append("Use the SQL files to create the databases\n\n", style="white")
        
        next_steps.append("3. ", style="bold white")
        next_steps.append("Run the following command to validate:\n\n", style="white")
        next_steps.append("   python3 prerequisites.py validate\n", style="bold cyan")
        
        self._console.print()
        self._console.print(Panel(
            next_steps,
            title="[bold yellow]Next Steps[/bold yellow]",
            border_style="yellow",
            padding=(1, 2)
        ))
        self._console.print()
    
    def _format_file_size(self, size: int) -> str:
        """Format file size in human-readable format."""
        if size < 1024:
            return f"{size} bytes"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"

    def generate_all(self) -> bool:
        """
        Generate all AI Services artifacts (CR, Secrets, ConfigMap).

        Returns:
            True if all artifacts were generated successfully, False otherwise
        """
        self._console.print("\n[bold cyan]Generating AI Services Kubernetes Artifacts...[/bold cyan]\n")

        success = True
        self._generated_files = []

        # Generate CR
        if self.generate_cr():
            self._track_generated_file(self._generated_cr)
        else:
            success = False

        # Generate OIDC Secret
        if self.generate_oidc_secret():
            if self._generated_oidc_secret.exists():
                self._track_generated_file(self._generated_oidc_secret)
        else:
            success = False

        # Generate Providers Config Secret (multi-provider configuration)
        if self.generate_providers_config_secret():
            if self._generated_providers_secret.exists():
                self._track_generated_file(self._generated_providers_secret)
        else:
            # This is optional - don't fail if not using multi-provider config
            pass

        # Generate GraphQL SSL Secret (if certificate is provided)
        graphql_secret_name = self.generate_graphql_ssl_secret()
        if graphql_secret_name:
            self._log_info(f"GraphQL SSL secret will be used: {graphql_secret_name}")
        
        # Note: LWE Provider SSL Secrets are now generated inside generate_providers_config_secret()
        # to ensure the SSL secret names are available when building the providers config JSON

        # Generate IDP Secret only when Content is included
        if self.generate_idp_secret():
            self._log_info("IDP secret generation step completed")
        else:
            self._log_error("Failed to generate IDP secret")
            success = False

        # Generate IDP Public Key Secret (required for JWT validation)
        if self.generate_idp_public_key_secret():
            self._log_info("IDP public key secret generated successfully")
        else:
            self._log_error(
                "Skipping IDP public key secret generation because the JWKS endpoint could not be reached "
                "or did not return a usable signing key"
            )
        
        # Generate IDP SSL Secret (required for OIDC SSL verification)
        if self.generate_idp_ssl_secret():
            self._log_info("IDP SSL secret generated successfully")
        else:
            self._log_error("Failed to generate IDP SSL secret")
            success = False

        # Generate ConfigMap (pass GraphQL secret name if generated)
        if self.generate_configmap(graphql_secret_name=graphql_secret_name):
            self._track_generated_file(self._generated_configmap)
        else:
            success = False

        # Don't display AI Services-specific summary here
        # The overall generate_generate_results() will show all files including AI Services
        if not success:
            self._console.print("\n[bold red]✗ Some AI Services artifacts failed to generate[/bold red]\n")

        return success

# Made with Bob
