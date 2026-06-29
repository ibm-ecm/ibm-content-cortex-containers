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
import inspect
import os
from urllib.parse import urlparse

import toml

from ..gather.gather import GatherOptions
from ..utilities.prerequisites_utilites import gather_var


# Class for silent option for all deployment scripts i.e deployoperator, cleanupdeployment, upgradeOperator , loadimages
class SilentGatherOptions(GatherOptions):
    # Default path for env file
    _envfile_path = os.path.join(os.getcwd(), "silent_config",
                                 "silent_install_cleandeployment.toml")
    _error_list = []

    def __init__(self, logger, envfile_path=_envfile_path, script_type="cleanup", dev=False, tls_verify=True):

        super().__init__(logger=logger, console=None, script_type=script_type, dev=dev)

        self._envfile_path = envfile_path
        # Setting it to true so the gather class can accordingly skip the menu based questions
        self._silent_mode = True
        self._tls_verify = tls_verify
        try:
            self._envfile = toml.loads(open(self._envfile_path, encoding="utf-8").read())
        except Exception as e:
            self._logger.exception(
                f"Exception from silent.py script - error loading {self._envfile_path} file -  {str(e)}")

    # method to output all variables to dict
    def to_dict(self):
        return {
            "namespace": self._namespace,
            "private_catalog": self._private_catalog,
            "private_registry": self._private_registry,
            "private_registry_host": self._private_registry_host,
            "private_registry_port": self._private_registry_port,
            "private_registry_full_server": self._private_registry_full_server,
            "private_registry_username": self._private_registry_username,
            "private_registry_password": self._private_registry_password,
            "private_registry_ssl_enabled": self._private_registry_ssl_enabled,
            "private_registry_ssl_cert": self._private_registry_ssl_cert,
            "entitlement_key": self._entitlement_key,
            "components": self._components,
            "accept_license": self._accept_license,
            "sensitive_collect": self._sensitive_collect,
            "error_list": self._error_list
        }


    def silent_parse_mustgather_operator_file(self):
        self.silent_namespace()
        self.silent_collect_sensitive_info()
        self.silent_mustgather_components()

        collect_content = self._envfile.get("COLLECT_CONTENT_OPERATOR", True)
        collect_ai_services = self._envfile.get("COLLECT_AI_SERVICES_OPERATOR", False)

        self._selected_operators = []
        if collect_content:
            self._selected_operators.append("content")
        if collect_ai_services:
            self._selected_operators.append("ai-services")

        if not self._selected_operators:
            self._error_list.append(
                f"ERROR in {self._envfile_path}: at least one of COLLECT_CONTENT_OPERATOR or "
                f"COLLECT_AI_SERVICES_OPERATOR must be true")

        self.error_check()


    # method to parse the file
    def parse_envfile(self):
        try:
            self.silent_namespace()

            # self.error_check()

        except Exception as e:
            self._logger.exception(
                f"Exception from silent.py script in {inspect.currentframe().f_code.co_name} function -  {str(e)}")

    # Function to read namespace information from toml file
    def silent_namespace(self):
        namespace = self._envfile.get("NAMESPACE")
        super().collect_namespace(namespace)
        self._namespace = super().namespace

    def silent_license_model(self, version_data=None):
        license = self._envfile.get("LICENSE_ACCEPT")
        super().collect_license_model(version_data, license)
        self._accept_license = super().accept_license

    def silent_collect_sensitive_info(self):
        collected_sensitive = gather_var(key="COLLECT_SENSITIVE_DATA", _logger=self._logger, _envfile=self._envfile, _error_list=self._error_list)
        super().collect_sensitive_data(collected_sensitive)
        self._sensitive_collect = super().sensitive_collect

    def silent_mustgather_components(self):
        cpe = gather_var(key="CPE", _logger=self._logger, _envfile=self._envfile, _error_list=self._error_list)
        graphql = gather_var(key="GRAPHQL", _logger=self._logger, _envfile=self._envfile,
                             _error_list=self._error_list)
        ban = gather_var(key="BAN", _logger=self._logger, _envfile=self._envfile, _error_list=self._error_list)
        cmis = gather_var(key="CMIS", _logger=self._logger, _envfile=self._envfile, _error_list=self._error_list)
        css = gather_var(key="CSS", _logger=self._logger, _envfile=self._envfile, _error_list=self._error_list)
        tm = gather_var(key="TM", _logger=self._logger, _envfile=self._envfile, _error_list=self._error_list)
        es = gather_var(key="ES", _logger=self._logger, _envfile=self._envfile, _error_list=self._error_list)
        ier = gather_var(key="IER", _logger=self._logger, _envfile=self._envfile, _error_list=self._error_list)
        iccsap = gather_var(key="ICCSAP", _logger=self._logger, _envfile=self._envfile,
                            _error_list=self._error_list)
        ccxmo = gather_var(key="CCXMO", _logger=self._logger, _envfile=self._envfile,
                           _error_list=self._error_list)
        coremcp = gather_var(key="COREMCP", _logger=self._logger, _envfile=self._envfile,
                             _error_list=self._error_list)
        reasoning = gather_var(key="REASONING", _logger=self._logger, _envfile=self._envfile,
                               _error_list=self._error_list)

        if cpe is not None and cpe is True:
            super().components.add("cpe")
        if graphql is not None and graphql is True:
            super().components.add("graphql")
        if ban is not None and ban is True:
            super().components.add("ban")
        if cmis is not None and cmis is True:
            super().components.add("cmis")
        if css is not None and css is True:
            super().components.add("css")
        if tm is not None and tm is True:
            super().components.add("tm")
        if es is not None and es is True:
            super().components.add("es")
        if ier is not None and ier is True:
            super().components.add("ier")
        if iccsap is not None and iccsap is True:
            super().components.add("iccsap")
        if ccxmo is not None and ccxmo is True:
            super().components.add("ccxmo")
        if coremcp is not None and coremcp is True:
            super().components.add("coremcp")
        if reasoning is not None and reasoning is True:
            super().components.add("reasoning")

    def silent_parse_upgrade_variables(self):
        self.silent_namespace()

        self._selected_license = self._envfile.get("LICENSE")
        if not self._selected_license:
            self._error_list.append(
                f"ERROR with LICENSE in silent mode configuration {self._envfile_path} file - Field Cannot be Empty")
            self.error_check()

        self._apply_cr = self._envfile.get("APPLY_CR", True)

    # Function to parse private registry info from silent install file
    def silent_parse_private_registry_info(self):

        private_reg_hostname_full = self._envfile.get("PRIVATE_REGISTRY_URL")
        # Parse the remaining private registry url
        # Split hostname into scheme, server, context and port using urlparse
        if "://" not in private_reg_hostname_full:
            private_reg_hostname_full_shema = "//" + private_reg_hostname_full
        else:
            private_reg_hostname_full_shema = private_reg_hostname_full

        private_reg_parts = urlparse(private_reg_hostname_full_shema, scheme="https")

        self._private_registry_host = private_reg_parts.hostname

        # If no port is provided, default to 443 for https and 80 for http
        # Use 443 if no schema is provided
        private_reg_scheme = private_reg_parts.scheme
        if private_reg_parts.port is None:
            if private_reg_parts.scheme == "http":
                self._private_registry_port = 80
            else:
                self._private_registry_port = 443
        else:
            self._private_registry_port = private_reg_parts.port

        # Store registry server WITHOUT protocol for Docker/Skopeo compatibility
        # Docker registries expect format: hostname:port/path, NOT https://hostname:port/path
        # Note: Omit standard ports (80 for HTTP, 443 for HTTPS) as Docker/Skopeo don't require them
        
        # Build base registry address (hostname or hostname:port)
        base_registry = self._private_registry_host
        # Only add port if it's not a standard port
        if private_reg_scheme == "https" and self._private_registry_port != 443:
            base_registry = f"{base_registry}:{self._private_registry_port}"
        elif private_reg_scheme == "http" and self._private_registry_port != 80:
            base_registry = f"{base_registry}:{self._private_registry_port}"
        elif private_reg_scheme not in ["http", "https"]:
            # For other schemes or when scheme is not set, always include port
            base_registry = f"{base_registry}:{self._private_registry_port}"
        
        # Add path if present
        if private_reg_parts.path != "":
            self._private_registry_path = private_reg_parts.path.lstrip('/')
            self._private_registry_full_server = f"{base_registry}/{self._private_registry_path}"
        else:
            self._private_registry_full_server = base_registry
        
        self._logger.info(f"Private registry server (for Docker/Skopeo): {self._private_registry_full_server}")

        self._private_registry_username = self._envfile.get("PRIVATE_REGISTRY_USERNAME")
        self._private_registry_password = self._envfile.get("PRIVATE_REGISTRY_PASSWORD")
        if self._private_registry_full_server == "" or self._private_registry_full_server is None:
            self._error_list.append(
                f"ERROR with PRIVATE REGISTRY URL in silent mode configuration {self._envfile_path} file - Field Cannot be Empty")

        if self._private_registry_username == "" or self._private_registry_full_server is None:
            self._error_list.append(
                f"ERROR with PRIVATE REGISTRY USER in silent mode configuration {self._envfile_path} file - Field Cannot be Empty")

        if self._private_registry_password == "" or self._private_registry_full_server is None:
            self._error_list.append(
                f"ERROR with PRIVATE REGISTRY PASSWORD in silent mode configuration {self._envfile_path} file -  Field Cannot be Empty")
        self._private_registry_ssl_enabled = self._envfile.get("PRIVATE_REGISTRY_SSL_ENABLED")
        if self._private_registry_ssl_enabled:
            if not self._tls_verify:
                self._private_registry_ssl_cert = self._envfile.get("PRIVATE_REGISTRY_SSL_CRT_PATH")
                if self._private_registry_ssl_cert == "" or self._private_registry_full_server is None:
                    self._error_list.append(
                        f"ERROR with PRIVATE REGISTRY SSL CRT PATH in silent mode configuration {self._envfile_path} file -  Field Cannot be Empty if SSL is Enabled")


    # method to parse load images silent install file
    def silent_parse_load_images_file(self):
        private_registry = self._envfile.get("PRIVATE_REGISTRY", False)
        self._private_registry = private_registry

        if private_registry:
            self.silent_parse_private_registry_info()

            if self._error_list:
                self.error_check()
            else:
                self.collect_verify_private_registry()
        else:
            self._entitlement_key = self._envfile.get("ENTITLEMENT_KEY")
            if not self._entitlement_key:
                self._error_list.append(
                    f"ERROR with ENTITLEMENT KEY in silent mode configuration {self._envfile_path} file - Field Cannot be Empty")
                self.error_check()
            else:
                self.collect_verify_entitlement_key()


    def silent_parse_deploy_operator_file(self, validate=True, version_data=None):
        self.silent_license_model(version_data)
        self._entitlement_key = self._envfile.get("ENTITLEMENT_KEY")
        private_registry = self._envfile.get("PRIVATE_REGISTRY", False)
        self._private_registry = private_registry

        if private_registry:
            self.silent_parse_private_registry_info()

            if self._error_list:
                self.error_check()
            else:
                self.collect_verify_private_registry()
        else:
            if self._entitlement_key == "" or self._entitlement_key is None:
                self._error_list.append(
                    f"ERROR with ENTITLEMENT KEY in silent mode configuration {self._envfile_path} file -  Field Cannot be Empty if a private registry is not used")
                self.error_check()
            else:
                if validate:
                    self.collect_verify_entitlement_key()
        self.silent_namespace()

        # Parse multi-operator configuration with defaults
        self._parse_multi_operator_config()
    
    def _parse_multi_operator_config(self):
        """Parse multi-operator deployment configuration from silent file."""
        from ..utilities.operator_config import OperatorType
        
        # Parse deployment mode (default: multi-operator)
        deployment_mode = self._envfile.get("DEPLOYMENT_MODE", "multi-operator")
        
        # Parse parallel deployment settings (defaults: enabled with 3 workers)
        self._parallel_deployment = self._envfile.get("PARALLEL_DEPLOYMENT", True)
        self._max_parallel_workers = self._envfile.get("MAX_PARALLEL_WORKERS", 3)
        
        # Validate max_parallel_workers
        if not isinstance(self._max_parallel_workers, int) or self._max_parallel_workers < 1 or self._max_parallel_workers > 10:
            self._logger.warning(f"Invalid MAX_PARALLEL_WORKERS value: {self._max_parallel_workers}. Using default: 3")
            self._max_parallel_workers = 3
        
        # All four operators are now installed by default
        # No user configuration needed - all operators are required
        self._selected_operators = [
            OperatorType.CONTENT,
            OperatorType.AI_SERVICES,
            OperatorType.LICENSE_ADVISOR,
            OperatorType.USAGE_METERING
        ]
        
        self._logger.info(f"Multi-operator configuration parsed:")
        self._logger.info(f"  - Deployment mode: {deployment_mode}")
        self._logger.info(f"  - Parallel deployment: {self._parallel_deployment}")
        self._logger.info(f"  - Max parallel workers: {self._max_parallel_workers}")
        self._logger.info(f"  - Selected operators: {[op.value for op in self._selected_operators]}")

    def silent_print_deployment_options(self):

        self._logger.info("namespace-", self._namespace)
        self._logger.info("podman present-", super()._podman_available)
        self._logger.info("oc logged in", super()._ocp_logged_in)
        return_dict = {
            "namespace": self._namespace,
            "podman present": super()._podman_available,
            "Cluster connection": super()._ocp_logged_in
        }

    def error_check(self):
        if len(self._error_list) > 0:
            for error in self._error_list:
                self._logger.error(error)
            exit()
