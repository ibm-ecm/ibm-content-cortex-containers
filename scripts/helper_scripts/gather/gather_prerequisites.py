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
import os
import sys
from enum import Enum
from urllib.parse import urlparse

import requests
import xmltodict
from kubernetes import config
from rich import print
from rich.panel import Panel
from rich.text import Text
import questionary
from questionary import Style

from ..utilities.interface import clear
from ..utilities.kubernetes_utilites import KubernetesUtilities

requests.packages.urllib3.disable_warnings()


# create a class to gather all deployment options from the user for the prerequisite scripts
class GatherPrereqOptions:
    
    # Inner Class to take care of FNCM version.
    class Version:
        CCXVersion = Enum(
            value='CCXVersion',
            names=[("26.0.0", 1)]
        )

        def __init__(self, ccx_version: CCXVersion):
            self._ccx_version = ccx_version

    # Create an inner class to gather ldap info from the user
    class Ldap:
        ldapTypes = Enum(
            value='LdapType',
            names=[
                ('Microsoft Active Directory', 1),
                ('IBM Security Verify Directory', 2),
                ('NetIQ eDirectory', 3),
                ('Oracle Internet Directory', 4),
                ('Oracle Directory Server Enterprise Edition', 5),
                ('Oracle Unified Directory', 6),
                ('CA eTrust', 7)
            ]
        )

        def __init__(self, ldap_type: ldapTypes, ldap_ssl: bool, ldap_id: str = None):
            self._type = ldap_type
            self._ssl = ldap_ssl
            self._ldap_id = ldap_id

        # Create a function to display the ldap info
        def display(self):
            print("Type:", self._type.name)
            print("SSL Enabled:", self._ssl)
            print("LDAP ID:", self._ldap_id)

        # Create a function to return the ldap info as a dictionary
        def to_dict(self):
            return {
                "type": self._type.name,
                "ssl": self._ssl,
                "id": self._ldap_id
            }

    # Create an inner class to gather ldap info from the user
    class Idp:
        def __init__(self, discovery_enabled: bool, idp_id: str = None, discovery_url: str = None):
            self._discovery_url = discovery_url
            self._discovery_enabled = discovery_enabled
            self._idp_id = idp_id
            self._validation_method = "introspect"
            self._introspect_url = "<Required>"
            self._userinfo_url = "<Required>"
            self._token_url = "<Required>"
            self._revoke_url = "<Required>"
            self._issuer = "<Required>"
            self._client_id = "<Required>"
            self._client_secret = "<Required>"
            self._jwks_url = "<Required>"
            self._user_identifier = "sub"
            self._unique_user_identifier = "sub"
            self._user_identifier_to_sub = "sub"
            self._ssl_enabled = True

        # Create a function to parse the json return from discovery url
        def parse_discovery_url(self):
            try:
                # Create a variable to hold the url
                url = self._discovery_url

                # Check if the url is valid
                if url is None:
                    return False
                else:
                    if url.endswith(".well-known/openid-configuration"):
                        # Create a variable to hold the json
                        json = requests.get(url, timeout=5, verify=False).json()

                        # Check if the json is valid
                        if json is None:
                            return False
                        else:
                            # Check if the json contains the required fields
                            if "introspection_endpoint" in json:
                                self._introspect_url = json["introspection_endpoint"]
                                self._validation_method = "introspect"

                                if "preferred_username" in json["claims_supported"]:
                                    self._user_identifier = "preferred_username"

                            elif "userinfo_endpoint" in json:
                                self._userinfo_url = json["userinfo_endpoint"]
                                self._validation_method = "userinfo"

                                if "email" in json["claims_supported"]:
                                    self._user_identifier = "email"

                            else:
                                return False

                            if "token_endpoint" in json:
                                self._token_url = json["token_endpoint"]

                            if "revocation_endpoint" in json:
                                self._revoke_url = json["revocation_endpoint"]

                            if "issuer" in json:
                                self._issuer = json["issuer"]

                            if "jwks_uri" in json:
                                self._jwks_url = json["jwks_uri"]

                            # Check if the discovery url is https scheme
                            if urlparse(url).scheme == "https":
                                self._ssl_enabled = True
                            else:
                                self._ssl_enabled = False

                            return True

                    else:
                        return False
            except Exception as e:
                print(f"Exception from parse_discovery_url function - {str(e)}")
                return False

        # Create a function to display the ldap info
        def display(self):
            print("Discovery URL:", self._discovery_url)
            print("Discovery Enabled:", self._discovery_enabled)
            print("IDP ID:", self._idp_id)

        # Create a function to return the ldap info as a dictionary
        def to_dict(self):
            return {
                "discovery_url": self._discovery_url,
                "discovery_enabled": self._discovery_enabled,
                "id": self._idp_id,
                "validation_method": self._validation_method,
                "introspect_url": self._introspect_url,
                "userinfo_url": self._userinfo_url,
                "jwks_url": self._jwks_url,
                "token_url": self._token_url,
                "revoke_url": self._revoke_url,
                "issuer": self._issuer,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "user_identifier": self._user_identifier,
                "unique_user_identifier": self._unique_user_identifier,
                "user_identifier_to_sub": self._user_identifier_to_sub,
                "ssl_enabled": self._ssl_enabled
            }

    # Create an enum for all the database types
    class DatabaseType(Enum):
        db2 = 1
        db2HADR = 2
        oracle = 5
        sqlserver = 3
        postgresql = 4
        # Adding DB2 RDS and DB2 RDS HADR to the list of database types the user can select from ( only from 5.7.0)
        db2rds = 6
        db2rdsHADR = 7

    class AuthType(Enum):
        LDAP = 1
        LDAP_IDP = 2
        SCIM_IDP = 3

    # Create an enum for all the license types
    class LicenseModel(Enum):
        ESS = 1
        CP4BA = 2

    # Create an enum for CP4BA license metrics
    class LicenseMetricCP4BA(Enum):
        NonProd = 1
        Prod = 2
        User = 3

    # Create an enum for Essentials license metrics
    class LicenseMetricESS(Enum):
        AR = 1   # IBM Content Cortex Restricted - Authorized
        PR = 2   # IBM Content Cortex Restricted - Eligible Participant
        ER = 3   # IBM Content Cortex Restricted - Employee
        AU = 4   # IBM Content Cortex Essentials - Authorized User
        EP = 5   # IBM Content Cortex Essentials - Eligible Participants
        EE = 6   # IBM Content Cortex Essentials - Employee

    # Create an enum for all optional components
    class OptionalComponents(Enum):
        cpe = 1
        graphql = 2
        ban = 3
        css = 4
        cmis = 5
        tm = 6
        es = 7
        ier = 8
        iccsap = 9
        ccxmo = 10

    # Create an enum for WatsonX deployment types
    class WatsonXType(Enum):
        SAAS = 1
        LWE = 2
    
    # Create an enum for AI Model Provider types
    class ModelProviderType(Enum):
        WATSONX_SAAS = 1
        WATSONX_LWE = 2
        MICROSOFT_FOUNDRY = 3
        # Future providers can be added here:
        # OPENAI = 4
        # AZURE_OPENAI = 5

    # Create an enum for all platform types
    class Platform(Enum):
        OCP = 1
        other = 2

    def __init__(self, logger, console, require_k8s_connection=False):
        self._optional_components = set()
        self._ldap_info = []
        self._ldap_number = 0
        self._db_type = None
        self._db_ssl = False
        self._idp_info = []
        self._idp_number = 0
        self._os_number = 1
        self._content_initialize = False
        self._content_verification = False
        self._platform = self.Platform(1).name
        self._license_model = None
        self._ingress = False
        self._logger = logger
        self._console = console
        self._ssl_directory_list = []
        self._ccx_version = "26.0.0"
        self._sendmail_support = False
        self._icc_support = False
        self._tm_custom_groups = False
        self._egress_support = False
        self._np_support = False
        self._fips_support = False
        self._auth_type = self.AuthType(1).name
        self._namespace = None
        self._current_namespace = None
        self._script_type = 'gather'
        # Allow caller to specify if K8s connection is required (e.g., validate mode needs it)
        self._k = KubernetesUtilities(self._logger, require_connection=require_k8s_connection)
        self._watsonx_type = None
        self._model_providers = []  # List of model provider configurations
        self._model_provider_count = 1  # Default to 1 provider
        self._fncm_migration_settings = None  # Settings migrated from existing FNCMCluster CR
        self._vault_enabled = False  # Vault secret management enabled
        self._vault_url = None  # Vault server URL

    # Create a function to gather all deployment options from the user
    @property
    def license_model(self):
        return self._license_model

    @property
    def namespace(self):
        return self._namespace

    @property
    def ccx_version(self):
        return self._ccx_version

    @property
    def egress_support(self):
        return self._egress_support

    @property
    def np_support(self):
        return self._np_support

    @property
    def fips_support(self):
        return self._fips_support

    @property
    def db_ssl(self):
        return self._db_ssl

    @property
    def sendmail_support(self):
        return self._sendmail_support

    @property
    def icc_support(self):
        return self._icc_support

    @property
    def tm_custom_groups(self):
        return self._tm_custom_groups

    @property
    def optional_components(self):
        return self._optional_components

    @optional_components.setter
    def optional_components(self, value):
        self._optional_components = value

    @property
    def auth_type(self):
        return self._auth_type

    @auth_type.setter
    def auth_type(self, value):
        self._auth_type = value

    @property
    def ldap_info(self):
        return self._ldap_info

    @ldap_info.setter
    def ldap_info(self, value):
        self._ldap_info = value

    @property
    def idp_info(self):
        return self._idp_info

    @idp_info.setter
    def idp_info(self, value):
        self._idp_info = value

    @property
    def idp_number(self):
        return self._idp_number

    @property
    def db_type(self):
        return self._db_type

    @db_type.setter
    def db_type(self, value):
        self._db_type = value

    @property
    def os_number(self):
        return self._os_number

    @os_number.setter
    def os_number(self, value):
        self._os_number = value

    @property
    def content_initialize(self):
        return self._content_initialize

    @content_initialize.setter
    def content_initialize(self, value):
        self._content_initialize = value

    @property
    def content_verification(self):
        return self._content_verification

    @content_verification.setter
    def content_verification(self, value):
        self._content_verification = value

    @property
    def vault_enabled(self):
        return self._vault_enabled
    
    @vault_enabled.setter
    def vault_enabled(self, value):
        self._vault_enabled = value
    
    @property
    def vault_url(self):
        return self._vault_url
    
    @vault_url.setter
    def vault_url(self, value):
        self._vault_url = value

    @property
    def platform(self):
        return self._platform

    @platform.setter
    def platform(self, value):
        self._platform = value
    
    @property
    def fncm_migration_settings(self):
        """Return the migrated settings from FNCMCluster CR if available."""
        return getattr(self, '_fncm_migration_settings', None)

    @property
    def ingress(self):
        return self._ingress

    @ingress.setter
    def ingress(self, value):
        self._ingress = value

    # Create a method to return the ssl directory list
    @property
    def ssl_directory_list(self):
        return self._ssl_directory_list

    # Create a property to return the ldap number
    @property
    def ldap_number(self):
        return self._ldap_number

    @ldap_number.setter
    def ldap_number(self, value):
        self._ldap_number = value

    @property
    def watsonx_type(self):
        return self._watsonx_type

    @watsonx_type.setter
    def watsonx_type(self, value):
        self._watsonx_type = value
    
    @property
    def model_providers(self):
        return self._model_providers
    
    @model_providers.setter
    def model_providers(self, value):
        self._model_providers = value
    
    @property
    def model_provider_count(self):
        return self._model_provider_count
    
    @model_provider_count.setter
    def model_provider_count(self, value):
        self._model_provider_count = value

    def collect_namespace(self, namespace=None):
        # namespace parameter is none when silent mode is NOT selected, hence the conditions to skip conditions if silent mode is selected
        try:
            self._logger.info("Gathering namespace information")
            if namespace is None:
                try:
                    if self._k.connected:
                        self._current_namespace = self._k.current_namespace
                        self._logger.info(f"Current namespace from kubeconfig: {self._current_namespace}")
                    else:
                        self._current_namespace = None
                        self._logger.info("No Kubernetes connection available, namespace check skipped")
                except Exception as e:
                    self._current_namespace = None
                    self._logger.info(f"Gathering namespace information failed: {e}")

            if self._platform in ["OCP"]:
                invalid_namespaces = ["services", "default", "calico-system", "ibm-cert-store", "ibm-observe",
                                      "ibm-system", "ibm-odf-validation-webhook"]
                invalid_namespace_to_start_with = ["openshift-", "kube-"]
            else:
                invalid_namespaces = ["services", "default", "calico-system"]
                invalid_namespace_to_start_with = ["kube-"]

            while True:
                if namespace is None:
                    # Enhanced namespace prompt with context
                    namespace_info = Text()
                    namespace_info.append("📦 Kubernetes Namespace Configuration\n\n", style="bold cyan")
                    namespace_info.append("The namespace isolates your IBM Content Cortex deployment resources.\n", style="white")
                    if self._current_namespace:
                        namespace_info.append(f"\n💡 Current namespace detected: ", style="yellow")
                        namespace_info.append(f"{self._current_namespace}", style="bold green")
                    
                    print(Panel(
                        namespace_info,
                        title="[bold white]Namespace Selection[/bold white]",
                        border_style="cyan",
                        padding=(1, 2)
                    ))
                    print()
                    
                    answer = questionary.text(
                        "Enter your namespace:",
                        default=self._current_namespace if self._current_namespace else "",
                        style=Style([
                            ('qmark', 'fg:cyan bold'),
                            ('question', 'bold'),
                            ('answer', 'fg:cyan bold'),
                        ])
                    ).ask()
                    
                    if answer is None:  # User cancelled (Ctrl+C)
                        print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                        sys.exit(0)
                    # Skip namespace existence check for gather and generate modes
                    if self._script_type not in ("deploy", "gather", "generate"):
                        namespace_exists = self._k.check_namespace_exists(namespace=answer)
                        # namespace_exists can be True, False, or None (when no K8s connection)
                        if namespace_exists is False:
                            print()
                            print(Panel.fit(f"Namespace '{answer}' does not exist.\n"
                                            f"Enter a valid namespace for script to proceed.", style="bold red"))
                            print()
                            continue
                        elif namespace_exists is None:
                            # No K8s connection, show warning but allow to proceed
                            print()
                            print(Panel.fit(f"⚠️  Warning: Cannot verify namespace '{answer}' (no Kubernetes connection).\n"
                                            f"Proceeding without validation.", style="bold yellow"))
                            print()
                else:
                    # silent install check for namespace will not loop more than once if invalid namespace is provided
                    # Skip namespace existence check for gather and generate modes
                    if self._script_type not in ("deploy", "gather", "generate"):
                        self._logger.info(f"Checking if namespace: {namespace} exists.")
                        namespace_exists = self._k.check_namespace_exists(namespace=namespace)
                        # namespace_exists can be True, False, or None (when no K8s connection)
                        if namespace_exists is False:
                            self._logger.debug(f"Namespace '{namespace}' does not exist.")
                            print()
                            print(Panel.fit(f"Namespace '{namespace}' does not exist.\n"
                                            f"Enter a valid namespace for script to proceed.", style="bold red"))
                            print()
                            exit(1)
                        elif namespace_exists is None:
                            # No K8s connection, log warning but allow to proceed
                            self._logger.warning(f"Cannot verify namespace '{namespace}' (no Kubernetes connection). Proceeding without validation.")
                            print()
                            print(Panel.fit(f"⚠️  Warning: Cannot verify namespace '{namespace}' (no Kubernetes connection).\n"
                                            f"Proceeding without validation.", style="bold yellow"))
                            print()
                    answer = namespace

                answer = answer.strip()
                # Start of namespace validation
                # Check if the answer is not empty after stripping whitespace
                if answer == '':
                    self._logger.debug(f"Namespace cannot be empty. Please try again")
                    print()
                    print("[prompt.invalid]Namespace cannot be empty. Please try again")
                    print()
                    if namespace is None:
                        continue
                    else:
                        exit(0)

                # Check if the answer is not in the list of invalid namespaces
                if any(answer in value for value in invalid_namespaces):
                    invalid_msg = ""
                    for value in invalid_namespaces:
                        invalid_msg += f"- {value}\n"
                    invalid_msg.strip()

                    print()
                    print(f"[prompt.invalid]Namespace cannot be any of the following. Please try again.\n{invalid_msg}")
                    print()
                    self._logger.debug(f"Namespace cannot be any of the following: {invalid_msg}")
                    if namespace is None:
                        continue
                    else:
                        exit(0)

                if any(answer.startswith(value) for value in invalid_namespace_to_start_with):
                    invalid_msg = ""
                    for value in invalid_namespace_to_start_with:
                        invalid_msg += f"- {value}\n"
                    invalid_msg = invalid_msg.strip()
                    print()
                    print(
                        f"[prompt.invalid]Namespace cannot start with any of the following. Please try again.\n{invalid_msg}")
                    print()
                    self._logger.debug(f"Namespace cannot start with any of the following: {invalid_msg}")
                    if namespace is None:
                        continue
                    else:
                        exit(0)

                # Check if namespace is only numbers
                if answer.isnumeric():
                    print()
                    print("[prompt.invalid]Namespace cannot be a number. Please try again.")
                    print()
                    self._logger.debug(f"Namespace cannot be a number. Please try again.")
                    if namespace is None:
                        continue
                    else:
                        exit(0)

                # Check if namespace is more than 1 word
                if " " in answer:
                    print()
                    print("[prompt.invalid]Namespace cannot contain spaces. Use '-'. Please try again.")
                    print()
                    if namespace is None:
                        continue
                    else:
                        exit(0)

                # Check if namespace has an underscore
                if "_" in answer:
                    print()
                    print("[prompt.invalid]Namespace cannot contain '_'. Use '-'. Please try again.")
                    print()
                    self._logger.debug(f"Namespace cannot be a number. Please try again.")
                    if namespace is None:
                        continue
                    else:
                        exit(0)

                # for all scripts using this function other than deploy operator we need to check if namespace exists
                self._namespace = answer
                self._logger.info(f"Namespace entered: {self._namespace}")
                break

        except Exception as e:
            self._logger.exception(
                f"Exception from gathering deployment details in collect namespace function -  {str(e)}")


    def parse_db_files(self, path, db_files):
        try:
            db_type = set()
            for idx, db_file in enumerate(db_files):
                # open the ldap file
                with open(os.path.join(path, db_file)) as fd:
                    # parse the ldap file
                    db_dict = xmltodict.parse(fd.read())

                    db_type.add(db_dict['configuration']['@implementorid'])
            result = 0
            if len(db_type) > 1:
                print(
                    "Multiple database types found in the database files.  Please check the database files and try again.")
                exit(1)
            else:
                xml_type = list(db_type)[0]
                if xml_type == "mssql":
                    result = 3
                elif xml_type in ["oracle", "oracle_ssl", "oracle_rac"]:
                    result = 5
                elif xml_type == "db2":
                    result = 1
                elif xml_type == "db2hadr":
                    result = 2
                else:
                    print("Unknown DB type")
                self._db_type = self.DatabaseType(result).name



        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in parse_db_files function -  {str(e)}")

    def parse_ldap_files(self, path, ldap_files):
        try:
            result = 0
            for idx, ldap_file in enumerate(ldap_files):
                # open the ldap file
                with open(os.path.join(path, ldap_file)) as fd:

                    # Determine the LDAP ID
                    if idx == 0:
                        ldap_id = "ldap"
                    else:
                        ldap_id = f"ldap{idx + 1}"

                    # parse the ldap file
                    ldap_dict = xmltodict.parse(fd.read())
                    # Determine LDAP type
                    xml_type = ldap_dict['configuration']['@implementorid']
                    if "tivoli" in xml_type:
                        result = 2
                    # Need to search the string for .ad to support federated.ad and standalone.ad
                    elif any(x in xml_type for x in ["adam", "activedirectory", ".ad"]):
                        result = 1
                    elif "ca" in xml_type:
                        result = 7
                    elif "edirectory" in xml_type:
                        result = 3
                    elif "oid" in xml_type:
                        result = 4
                    elif any(x in xml_type for x in ["oracledirectoryse","sunjavads"]):
                        result = 5
                    else:
                        print(Text(f"Unable to parse XML file: {ldap_file}\n"
                                   f"Unknown LDAP type", style='bold red'))

                    # Determine if SSL is enabled
                    for prop in ldap_dict['configuration']['property']:
                        if prop['@name'] == "SSLEnabled":
                            if prop['value'] == "true":
                                ssl = True
                                self._ssl_directory_list.append(ldap_id)
                            else:
                                ssl = False
                            break
                        else:
                            ssl = False

                    # Add the ldap info to the ldap_info list
                    self.ldap_info.append(
                        self.Ldap(
                            self.Ldap.ldapTypes(result),
                            ssl,
                            ldap_id
                        )
                    )
        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in parse_ldap_files function -  {str(e)}")

    # Create a function to parse optional components
    def __parse_optional_components__(self, choices=None):
        try:
            if choices is None:
                print("No optional components chosen")
            else:
                # loop through choices and add to optional components list based on Enum value
                for choice in choices:
                    self.optional_components.add(self.OptionalComponents(choice).name)

            return self.optional_components

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in set_optional_components function -  {str(e)}")
    
    def collect_networkpolicy_info(self):
        try:
            # Enhanced network policy prompt
            netpol_info = Text()
            netpol_info.append("🔒 Network Policy Configuration\n\n", style="bold cyan")
            netpol_info.append("Network Policies control network traffic to and from pods in your cluster.\n\n", style="white")
            netpol_info.append("What Network Policies Provide:\n", style="bold yellow")
            netpol_info.append("  ✓ Pod-to-pod traffic control\n", style="green")
            netpol_info.append("  ✓ Ingress and egress rules\n", style="green")
            netpol_info.append("  ✓ Enhanced security isolation\n", style="green")
            netpol_info.append("  ✓ Compliance with security policies\n\n", style="green")
            netpol_info.append("Important Notes:\n", style="bold yellow")
            netpol_info.append("  • Network Policies are NOT installed automatically\n", style="white")
            netpol_info.append("  • Templates are generated for manual application\n", style="white")
            netpol_info.append("  • Both egress and ingress templates provided\n\n", style="white")
            netpol_info.append("💡 Recommendation: ", style="bold yellow")
            netpol_info.append("Enable for production environments requiring strict network controls.", style="white")
            
            print(Panel(
                netpol_info,
                title="[bold white]Network Policy Templates[/bold white]",
                border_style="cyan",
                padding=(1, 2)
            ))
            print()
            
            result = questionary.confirm(
                "Do you want to generate Network Policies templates for your deployment?",
                default=False,
                style=Style([
                    ('qmark', 'fg:cyan bold'),
                    ('question', 'bold'),
                    ('answer', 'fg:cyan bold'),
                ])
            ).ask()
            
            if result is None:  # User cancelled
                print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                sys.exit(0)
            if result:
                self._np_support = True

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in FNCM S collect version function -  {str(e)}")

    # Create a function to check if the dsicovery url is valid
    def check_discovery_url(self, url: str):
        try:

            # Check if the url is valid
            if url is None:
                return False
            else:
                if url.endswith(".well-known/openid-configuration"):
                    return True
                else:
                    return False
        except Exception as e:
            print(f"Exception from check_discovery_url function - {str(e)}")
            return False

    # Create a function to gather optional components from the user
    def collect_auth_type(self):
        try:
            # Check if we have migrated IDP settings from FNCMCluster CR
            if hasattr(self, '_fncm_migration_settings') and self._fncm_migration_settings:
                idp_config = self._fncm_migration_settings.get('idp_config', {})
                if idp_config and idp_config.get('discovery_url'):
                    # Use migrated IDP configuration - set auth type to LDAP + IDP
                    self._auth_type = "LDAP_IDP"
                    print(f"\n[green]✓ Using LDAP + IDP authentication from Content deployment[/green]")
                    return
            
            # Check if AI Services is selected - it requires IDP authentication
            ai_services_selected = self.has_ai_services_operator()
            content_selected = self.has_content_operator()
            both_selected = ai_services_selected and content_selected
            
            # Modern UI with rich panel and detailed description
            auth_info = Text()
            auth_info.append("🔐 Authentication Configuration\n\n", style="bold cyan")
            auth_info.append("Your authentication type determines how users authenticate and where their identities are stored.\n\n", style="white")
            
            if ai_services_selected:
                auth_info.append("⚠️  ", style="bold yellow")
                auth_info.append("AI Services Requirement: ", style="bold yellow")
                auth_info.append("Identity Provider (IDP) authentication is required for AI Services.\n", style="yellow")
                auth_info.append("LDAP-only authentication is not supported with AI Services.\n\n", style="yellow")
            
            # Add IDP consistency warning if both operators are selected
            if both_selected:
                auth_info.append("⚠️  ", style="bold red")
                auth_info.append("Important - IDP Configuration Consistency:\n", style="bold red")
                auth_info.append("When deploying both AI Services and Content, the IDP configuration ", style="white")
                auth_info.append("MUST match ", style="bold red")
                auth_info.append("across both deployments.\n", style="white")
                auth_info.append("AI Services tokens are passed to Content services for authentication.\n", style="dim white")
                auth_info.append("Ensure: same IDP provider, client ID, client secret, and discovery URL.\n\n", style="dim white")
            
            auth_info.append("Available Options:\n", style="bold yellow")
            
            if not ai_services_selected:
                auth_info.append("  • ", style="cyan")
                auth_info.append("LDAP", style="bold green")
                auth_info.append(" - Traditional directory-based authentication\n", style="white")
            
            auth_info.append("  • ", style="cyan")
            auth_info.append("LDAP + IDP", style="bold green")
            auth_info.append(" - Combines LDAP with Identity Provider for enhanced security\n", style="white")
            auth_info.append("  • ", style="cyan")
            auth_info.append("SCIM + IDP", style="bold green")
            auth_info.append(" - Modern cloud-native identity management with SCIM protocol\n", style="white")
            
            print(Panel(
                auth_info,
                title="[bold white]Authentication Type Selection[/bold white]",
                border_style="cyan",
                padding=(1, 2)
            ))
            print()

            # Build choices based on whether AI Services is selected
            choices = []
            if not ai_services_selected:
                choices.append(questionary.Choice("LDAP", value=1))
            choices.append(questionary.Choice("LDAP + IDP", value=2))
            choices.append(questionary.Choice("SCIM + IDP", value=3))

            result = questionary.select(
                "Select an Authentication Type:",
                choices=choices,
                style=Style([
                    ('qmark', 'fg:cyan bold'),
                    ('question', 'bold'),
                    ('answer', 'fg:cyan bold'),
                    ('pointer', 'fg:cyan bold'),
                    ('highlighted', 'fg:cyan'),
                    ('selected', 'fg:green bold')
                ])
            ).ask()
            
            if result is None:  # User cancelled
                print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                sys.exit(0)

            self._auth_type = self.AuthType(result).name

        except Exception as e:
            # Create log for exception
            self._logger.exception(
                f"Exception from gather script in auth_type function -  {str(e)}")

    # Create a function to gather optional components from the user
    def collect_optional_components(self):
        try:
            # Only collect components if Content operator is selected
            if not self.has_content_operator():
                self._logger.info("Skipping component selection - Content operator not selected")
                return
            
            # Enhanced component selection panel
            component_info = Text()
            component_info.append("📦 Component Selection\n\n", style="bold cyan")
            component_info.append("Select the IBM Content Cortex components you want to deploy.\n\n", style="white")
            
            component_info.append("Core Components:\n", style="bold yellow")
            component_info.append("  • ", style="white")
            component_info.append("CPE", style="bold green")
            component_info.append(" - Content Platform Engine (required for most components)\n", style="white")
            component_info.append("  • ", style="white")
            component_info.append("GraphQL", style="bold green")
            component_info.append(" - Modern API for content operations\n", style="white")
            component_info.append("  • ", style="white")
            component_info.append("Navigator", style="bold green")
            component_info.append(" - Web-based content management interface\n\n", style="white")
            
            component_info.append("Additional Services:\n", style="bold yellow")
            component_info.append("  • ", style="white")
            component_info.append("CSS", style="bold green")
            component_info.append(" - Content Search Services\n", style="white")
            component_info.append("  • ", style="white")
            component_info.append("CMIS", style="bold green")
            component_info.append(" - Content Management Interoperability Services\n", style="white")
            component_info.append("  • ", style="white")
            component_info.append("Task Manager", style="bold green")
            component_info.append(" - Workflow and task management\n", style="white")
            component_info.append("  • ", style="white")
            component_info.append("External Share", style="bold green")
            component_info.append(" - Secure external content sharing\n", style="white")
            component_info.append("  • ", style="white")
            component_info.append("IER", style="bold green")
            component_info.append(" - IBM Enterprise Records\n", style="white")
            component_info.append("  • ", style="white")
            component_info.append("ICCSAP", style="bold green")
            component_info.append(" - Content Collector for SAP\n", style="white")
            component_info.append("  • ", style="white")
            component_info.append("CCXMO", style="bold green")
            component_info.append(" - Content Cortex for Microsoft Office\n\n", style="white")
            
            component_info.append("💡 Note: ", style="bold yellow")
            component_info.append("Some components have dependencies that will be validated.", style="white")
            
            print(Panel(
                component_info,
                title="[bold white]Component Configuration[/bold white]",
                border_style="cyan",
                padding=(1, 2)
            ))
            print()

            # Component mapping for validation
            component_map = {
                'CPE': 1,
                'GraphQL': 2,
                'Navigator': 3,
                'CSS': 4,
                'CMIS': 5,
                'Task Manager': 6,
                'External Share': 7,
                'IER': 8,
                'ICCSAP': 9,
                'CCXMO': 10
            }

            while True:
                # Use questionary checkbox for multi-select
                selected_components = questionary.checkbox(
                    'Select IBM Content Cortex components (use Space to select, Enter to confirm):',
                    choices=[
                        questionary.Choice('CPE - Content Platform Engine', value='CPE', checked=True),
                        questionary.Choice('GraphQL - Modern API for content operations', value='GraphQL', checked=True),
                        questionary.Choice('Navigator - Web-based content management', value='Navigator', checked=True),
                        questionary.Choice('CSS - Content Search Services', value='CSS'),
                        questionary.Choice('CMIS - Content Management Interoperability', value='CMIS'),
                        questionary.Choice('Task Manager - Workflow and task management', value='Task Manager'),
                        questionary.Choice('External Share - Secure external sharing', value='External Share'),
                        questionary.Choice('IER - IBM Enterprise Records', value='IER'),
                        questionary.Choice('ICCSAP - Content Collector for SAP', value='ICCSAP'),
                        questionary.Choice('CCXMO - Content Cortex for Microsoft Office', value='CCXMO'),
                    ],
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                        ('pointer', 'fg:cyan bold'),
                        ('highlighted', 'fg:cyan bold'),
                        ('selected', 'fg:green'),
                        ('checkbox', 'fg:cyan'),
                        ('checkbox-selected', 'fg:green bold'),
                    ])
                ).ask()
                
                if selected_components is None:  # User cancelled
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                
                # Convert selected component names to numbers
                choices = {component_map[comp] for comp in selected_components}
                
                # Validate dependencies
                validation_passed = True
                
                if any(item in [2, 4, 5] for item in choices) and (1 not in choices):
                    print("\n[red]✗ IBM Content Platform Engine (CPE) is required to deploy GraphQL, CSS, or CMIS.[/red]")
                    validation_passed = False

                if 6 in choices and 3 not in choices:
                    print("\n[red]✗ IBM Content Navigator is required to deploy Task Manager.[/red]")
                    validation_passed = False

                if 7 in choices and not {3, 1}.issubset(choices):
                    print("\n[red]✗ IBM Content Navigator and CPE are required to deploy External Share.[/red]")
                    validation_passed = False

                if 8 in choices and not {3, 1}.issubset(choices):
                    print("\n[red]✗ IBM Content Navigator and CPE are required to deploy IER.[/red]")
                    validation_passed = False

                if 9 in choices and not {3, 1}.issubset(choices):
                    print("\n[red]✗ IBM Content Navigator and CPE are required to deploy ICCSAP.[/red]")
                    validation_passed = False

                if 10 in choices and 3 not in choices:
                    print("\n[red]✗ IBM Content Navigator is required to deploy CCXMO.[/red]")
                    validation_passed = False
                
                if validation_passed:
                    break
                else:
                    print("\n[yellow]Please adjust your selection to meet the dependencies.[/yellow]\n")

            if any(item in [3, 4, 6] for item in choices):
                print()
                
                # Enhanced component options panel
                options_info = Text()
                options_info.append("⚙️  Additional Component Features\n\n", style="bold cyan")
                options_info.append("Configure optional features for your selected components.\n\n", style="white")
                
                if 3 in choices:
                    options_info.append("Navigator Options:\n", style="bold yellow")
                    options_info.append("  • ", style="white")
                    options_info.append("Java SendMail", style="bold green")
                    options_info.append(" - Enable email capabilities for Navigator\n", style="white")
                
                if 4 in choices:
                    if 3 in choices:
                        options_info.append("\n", style="white")
                    options_info.append("CSS Options:\n", style="bold yellow")
                    options_info.append("  • ", style="white")
                    options_info.append("Content Collector", style="bold green")
                    options_info.append(" - Enable content collection for search indexing\n", style="white")
                
                if 6 in choices:
                    if 3 in choices or 4 in choices:
                        options_info.append("\n", style="white")
                    options_info.append("Task Manager Options:\n", style="bold yellow")
                    options_info.append("  • ", style="white")
                    options_info.append("Custom Groups/Users", style="bold green")
                    options_info.append(" - Configure custom security groups and users\n", style="white")
                
                options_info.append("\n💡 Tip: ", style="bold yellow")
                options_info.append("These features can be enabled now or configured later.", style="white")
                
                print(Panel(
                    options_info,
                    title="[bold white]Component Feature Configuration[/bold white]",
                    border_style="cyan",
                    padding=(1, 2)
                ))
                print()

            if 3 in choices:
                sendmailresult = questionary.confirm(
                    "Add Java SendMail support for IBM Content Navigator?",
                    default=False,
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                    ])
                ).ask()
                
                if sendmailresult is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                if sendmailresult:
                    self._sendmail_support = True
            if 4 in choices:
                print()
                iccresult = questionary.confirm(
                    "Add IBM Content Collector support for IBM Content Search Services?",
                    default=False,
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                    ])
                ).ask()
                
                if iccresult is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                if iccresult:
                    self._icc_support = True
            if 6 in choices:
                print()
                tmresult = questionary.confirm(
                    "Add custom groups and users for IBM Task Manager?",
                    default=False,
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                    ])
                ).ask()
                
                if tmresult is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                if tmresult:
                    self._tm_custom_groups = True

            self.__parse_optional_components__(choices)
        except Exception as e:
            # Create log for exception
            self._logger.exception(
                f"Exception from gather script in optional_components_menu function -  {str(e)}")

    # Create a function to gather init and verify content from the user
    def collect_init_verify_content(self):
        try:
            if "cpe" in self._optional_components:
                # Enhanced initialization panel
                init_info = Text()
                init_info.append("🚀 Content Initialization\n\n", style="bold cyan")
                init_info.append("Content initialization is recommended for new deployments and automates the setup process.\n\n", style="white")
                
                init_info.append("Initialization Steps:\n", style="bold yellow")
                init_info.append("  ✓ ", style="green")
                init_info.append("Creation of the P8 domain\n", style="white")
                init_info.append("  ✓ ", style="green")
                init_info.append("Creation of the directory services\n", style="white")
                init_info.append("  ✓ ", style="green")
                init_info.append("Assignments of users/groups to the P8 domain and object store(s)\n", style="white")
                init_info.append("  ✓ ", style="green")
                init_info.append("Creation of the object store(s)\n", style="white")
                init_info.append("  ✓ ", style="green")
                init_info.append("Creation/addition of add-ons for each object store\n", style="white")
                init_info.append("  ✓ ", style="green")
                init_info.append("Optional enablement of Process Engine Workflow\n", style="white")
                init_info.append("  ✓ ", style="green")
                init_info.append("Creation of Content Search Services servers and CBR configuration\n", style="white")
                init_info.append("  ✓ ", style="green")
                init_info.append("Creation of Navigator desktop\n\n", style="white")
                
                init_info.append("💡 Recommendation: ", style="bold yellow")
                init_info.append("Enable for new deployments to automate initial configuration.", style="white")
                
                print(Panel(
                    init_info,
                    title="[bold white]Initialize and Verify Content[/bold white]",
                    border_style="cyan",
                    padding=(1, 2)
                ))
                print()

                self._content_initialize = questionary.confirm(
                    "Do you want to initialize content?",
                    default=False,
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                    ])
                ).ask()
                
                if self._content_initialize is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)

                print()
                
                # Enhanced verification panel
                verify_info = Text()
                verify_info.append("✅ Content Verification\n\n", style="bold cyan")
                verify_info.append("Verification ensures that FNCM and BAN components are functioning correctly.\n\n", style="white")
                
                verify_info.append("Verification Tests:\n", style="bold yellow")
                verify_info.append("  ✓ ", style="green")
                verify_info.append("Creation of a CPE folder & CPE document\n", style="white")
                verify_info.append("  ✓ ", style="green")
                verify_info.append("CBR search functionality\n", style="white")
                verify_info.append("  ✓ ", style="green")
                verify_info.append("Process Engine Workflow configuration\n", style="white")
                verify_info.append("  ✓ ", style="green")
                verify_info.append("BAN desktop validation\n\n", style="white")
                
                verify_info.append("💡 Note: ", style="bold yellow")
                verify_info.append("Verification is recommended after initialization to confirm proper deployment.", style="white")
                
                print(Panel(
                    verify_info,
                    title="[bold white]Content Verification[/bold white]",
                    border_style="cyan",
                    padding=(1, 2)
                ))
                print()

                if self._content_initialize:
                    self._content_verification = questionary.confirm(
                        "Do you want to verify content?",
                        default=False,
                        style=Style([
                            ('qmark', 'fg:cyan bold'),
                            ('question', 'bold'),
                            ('answer', 'fg:cyan bold'),
                        ])
                    ).ask()
                    
                    if self._content_verification is None:
                        print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                        sys.exit(0)
            else:
                self._content_initialize = False
                self._content_verification = False

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in check_init_verify function -  {str(e)}")

    # Create a function to gather os number from the user
    def collect_os_number(self):
        try:
            # only ask in 5.5.8 or in releases above that if cpe graphql is selected
            if "cpe" in self._optional_components:
                print()
                
                # Enhanced object store panel
                os_info = Text()
                os_info.append("📦 Object Store Configuration\n\n", style="bold cyan")
                os_info.append("Object stores are repositories for storing and managing content in IBM Content Platform Engine.\n\n", style="white")
                
                if "ier" in self._optional_components:
                    os_info.append("Requirements:\n", style="bold yellow")
                    os_info.append("  • ", style="white")
                    os_info.append("Content Platform Engine", style="bold green")
                    os_info.append(" - Requires at least 1 object store\n", style="white")
                    os_info.append("  • ", style="white")
                    os_info.append("Enterprise Records", style="bold green")
                    os_info.append(" - Requires at least 2 object stores:\n", style="white")
                    os_info.append("    - ", style="white")
                    os_info.append("ROS", style="bold cyan")
                    os_info.append(" (Record Object Store) - Stores records and metadata\n", style="white")
                    os_info.append("    - ", style="white")
                    os_info.append("FPOS", style="bold cyan")
                    os_info.append(" (File Plan Object Store) - Stores file plan structure\n\n", style="white")
                    os_info.append("💡 Note: ", style="bold yellow")
                    os_info.append("Enterprise Records deployments require a minimum of 2 object stores.", style="white")
                    default = 2
                else:
                    os_info.append("Requirements:\n", style="bold yellow")
                    os_info.append("  • ", style="white")
                    os_info.append("Content Platform Engine", style="bold green")
                    os_info.append(" - Requires at least 1 object store\n\n", style="white")
                    os_info.append("💡 Tip: ", style="bold yellow")
                    os_info.append("You can deploy multiple object stores to organize content by department, project, or security requirements.", style="white")
                    default = 1
                
                print(Panel(
                    os_info,
                    title="[bold white]Object Store Planning[/bold white]",
                    border_style="cyan",
                    padding=(1, 2)
                ))
                print()
                
                while True:
                    result_str = questionary.text(
                        "How many Object Stores do you want to deploy?",
                        default=str(default),
                        validate=lambda text: text.isdigit() and int(text) >= default,
                        style=Style([
                            ('qmark', 'fg:cyan bold'),
                            ('question', 'bold'),
                            ('answer', 'fg:cyan bold'),
                        ])
                    ).ask()
                    
                    if result_str is None:
                        print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                        sys.exit(0)
                        
                    result = int(result_str)
                    if result >= default:
                        self._os_number = result
                        break
                    print(f"[prompt.invalid]Number of Object Stores must be equal or greater than [[b]{default}[/b]]")

        except Exception as e:
            self._logger.exception(
                f'Exception from gather script in object_store_menu function -  {str(e)}')

    # Create a function to gather db info from the user
    def collect_db_info(self):
        self.collect_db_type()
        self.collect_os_number()
        self.collect_db_ssl_info()

    # Create a private function to collect db ssl info from the user
    def collect_db_ssl_info(self):
        # Enhanced database SSL prompt
        db_ssl_info = Text()
        db_ssl_info.append("🔒 Database SSL Configuration\n\n", style="bold cyan")
        db_ssl_info.append("SSL/TLS encryption secures database connections and protects data in transit.\n\n", style="white")
        db_ssl_info.append("Benefits:\n", style="bold yellow")
        db_ssl_info.append("  ✓ Encrypted data transmission\n", style="green")
        db_ssl_info.append("  ✓ Protection against eavesdropping\n", style="green")
        db_ssl_info.append("  ✓ Enhanced security compliance\n\n", style="green")
        db_ssl_info.append("Note: ", style="bold yellow")
        db_ssl_info.append("You'll need to provide SSL certificates if enabled.", style="white")
        
        print(Panel(
            db_ssl_info,
            title="[bold white]Database SSL/TLS Encryption[/bold white]",
            border_style="cyan",
            padding=(1, 2)
        ))
        print()
        
        self._db_ssl = questionary.confirm(
            "Do you want to enable SSL for your database selection?",
            default=False,
            style=Style([
                ('qmark', 'fg:cyan bold'),
                ('question', 'bold'),
                ('answer', 'fg:cyan bold'),
            ])
        ).ask()
        
        if self._db_ssl is None:
            print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
            sys.exit(0)

        if self._db_ssl:
            # if we are using 5.5.8 no custom component deployments so existing logic for this case
            if "cpe" in self._optional_components:
                self._ssl_directory_list.append("gcd")
            if "ban" in self._optional_components:
                self._ssl_directory_list.append("icn")
            for i in range(self._os_number):
                if i == 0:
                    self._ssl_directory_list.append("os")
                else:
                    self._ssl_directory_list.append(f"os{i + 1}")
        
        # Add GraphQL SSL folder only if AI Services operator is selected WITHOUT Content operator
        # When both are deployed together, they share the same GraphQL endpoint
        if self.has_ai_services_operator() and not self.has_content_operator():
            self._ssl_directory_list.append("graphql")

    # Function to collect the fncm version
    def collect_ccx_version(self):
        try:
            # Enhanced version selection prompt
            version_info = Text()
            version_info.append("📦 IBM Content Cortex Version Selection\n\n", style="bold cyan")
            version_info.append("Select the version you want to deploy. Each version includes:\n\n", style="white")
            version_info.append("  • New features and capabilities\n", style="white")
            version_info.append("  • Security updates and patches\n", style="white")
            version_info.append("  • Performance improvements\n\n", style="white")
            version_info.append("💡 Tip: ", style="bold yellow")
            version_info.append("Choose the latest version for the newest features and fixes.", style="white")
            
            print(Panel(
                version_info,
                title="[bold white]Version Configuration[/bold white]",
                border_style="cyan",
                padding=(1, 2)
            ))
            print()
            
            result = questionary.select(
                "Which version of IBM Content Cortex do you want to deploy?",
                choices=[
                    questionary.Choice("5.5.8", value=1),
                    questionary.Choice("5.5.11", value=2),
                    questionary.Choice("5.5.12", value=3),
                    questionary.Choice("5.6.0", value=4),
                    questionary.Choice("5.7.0", value=5)
                ],
                style=Style([
                    ('qmark', 'fg:cyan bold'),
                    ('question', 'bold'),
                    ('answer', 'fg:cyan bold'),
                    ('pointer', 'fg:cyan bold'),
                    ('highlighted', 'fg:cyan'),
                    ('selected', 'fg:green bold')
                ])
            ).ask()
            
            if result is None:
                print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                sys.exit(0)

            self._ccx_version = self.Version.CCXVersion(result).name


        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in IBM Content Cortex collect version function -  {str(e)}")

    # Function to collect FIPS related info
    def collect_fips_info(self):
        try:
            # Enhanced FIPS prompt
            fips_info = Text()
            fips_info.append("🛡️ FIPS 140-2 Compliance Configuration\n\n", style="bold cyan")
            fips_info.append("Federal Information Processing Standard (FIPS) 140-2 ensures cryptographic modules meet government security requirements.\n\n", style="white")
            fips_info.append("When to enable:\n", style="bold yellow")
            fips_info.append("  • Government or regulated industry deployments\n", style="white")
            fips_info.append("  • Strict security compliance requirements\n", style="white")
            fips_info.append("  • Environments requiring validated cryptography\n\n", style="white")
            fips_info.append("⚠️  Important: ", style="bold red")
            fips_info.append("FIPS mode requires FIPS-enabled platform and may impact performance.", style="yellow")
            
            print(Panel(
                fips_info,
                title="[bold white]FIPS 140-2 Security Standard[/bold white]",
                border_style="cyan",
                padding=(1, 2)
            ))
            print()
            
            result = questionary.confirm(
                "Do you want to configure a FIPS enabled deployment?",
                default=False,
                style=Style([
                    ('qmark', 'fg:cyan bold'),
                    ('question', 'bold'),
                    ('answer', 'fg:cyan bold'),
                ])
            ).ask()
            
            if result is None:
                print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                sys.exit(0)
            if result:
                self._fips_support = True

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in FNCM S collect version function -  {str(e)}")

    # Function to collect secret management configuration
    def collect_secret_management(self):
        """Collect secret management type (Kubernetes Secrets vs Vault). Vault URL is configured in property file."""
        try:
            # Enhanced secret management prompt
            secret_info = Text()
            secret_info.append("🔐 Secret Management Configuration\n\n", style="bold cyan")
            secret_info.append("Choose how secrets will be managed for your Content Cortex deployment.\n\n", style="white")
            
            secret_info.append("Available Options:\n", style="bold yellow")
            secret_info.append("  • ", style="cyan")
            secret_info.append("Kubernetes Secrets", style="bold green")
            secret_info.append(" - Native Kubernetes secret management\n", style="white")
            secret_info.append("    ", style="white")
            secret_info.append("Secrets stored directly in Kubernetes etcd\n", style="dim white")
            secret_info.append("    ", style="white")
            secret_info.append("Simple setup, no additional infrastructure required\n\n", style="dim white")
            
            secret_info.append("  • ", style="cyan")
            secret_info.append("HashiCorp Vault", style="bold green")
            secret_info.append(" - External secret management with Vault\n", style="white")
            secret_info.append("    ", style="white")
            secret_info.append("Centralized secret management and rotation\n", style="dim white")
            secret_info.append("    ", style="white")
            secret_info.append("Enhanced security with audit logging\n", style="dim white")
            secret_info.append("    ", style="white")
            secret_info.append("Requires Vault server and CSI driver setup\n\n", style="dim white")
            
            secret_info.append("💡 Note: ", style="bold yellow")
            secret_info.append("If you select Vault, you will need to configure the Vault URL in the deployment property file.", style="white")
            
            print(Panel(
                secret_info,
                title="[bold white]Secret Management Selection[/bold white]",
                border_style="cyan",
                padding=(1, 2)
            ))
            print()
            
            result = questionary.select(
                "Select secret management method:",
                choices=[
                    questionary.Choice("Kubernetes Secrets", value=1),
                    questionary.Choice("HashiCorp Vault", value=2)
                ],
                style=Style([
                    ('qmark', 'fg:cyan bold'),
                    ('question', 'bold'),
                    ('answer', 'fg:cyan bold'),
                    ('pointer', 'fg:cyan bold'),
                    ('highlighted', 'fg:cyan'),
                    ('selected', 'fg:green bold')
                ])
            ).ask()
            
            if result is None:
                print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                sys.exit(0)
            
            if result == 1:
                self._vault_enabled = False
                self._vault_url = None
                self._logger.info("Secret management: Kubernetes Secrets")
            else:
                self._vault_enabled = True
                self._vault_url = None  # Will be set from property file
                self._logger.info("Secret management: HashiCorp Vault")
                
                # Display configuration note
                print()
                note = Text()
                note.append("ℹ️  Vault Configuration Required\n\n", style="bold cyan")
                note.append("You have selected HashiCorp Vault for secret management.\n\n", style="white")
                note.append("Next Steps:\n", style="bold yellow")
                note.append("  1. Complete the gather process\n", style="white")
                note.append("  2. Edit ", style="white")
                note.append("propertyFile/<namespace>/ccx-deployment.toml\n", style="cyan")
                note.append("  3. Set ", style="white")
                note.append("VAULT_URL", style="bold cyan")
                note.append(" to your Vault server URL\n", style="white")
                note.append("  4. Ensure Vault CSI driver is installed and configured\n", style="white")
                note.append("  5. Store secrets in Vault before running generate mode\n", style="white")
                
                print(Panel(
                    note,
                    title="[bold white]Configuration Instructions[/bold white]",
                    border_style="yellow",
                    padding=(1, 2)
                ))
                print()
        
        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_secret_management function - {str(e)}")

    # Function to collect WatsonX deployment type
    def collect_watsonx_type(self):
        """Collect WatsonX deployment type (SaaS or Lightweight Engine)."""
        try:
            # Enhanced WatsonX type selection prompt
            watsonx_info = Text()
            watsonx_info.append("🤖 WatsonX Deployment Type\n\n", style="bold cyan")
            watsonx_info.append("Select the type of WatsonX deployment you are using for AI Services.\n\n", style="white")
            
            watsonx_info.append("Deployment Options:\n", style="bold yellow")
            watsonx_info.append("  • ", style="cyan")
            watsonx_info.append("WatsonX.ai SaaS", style="bold green")
            watsonx_info.append(" - Cloud-based IBM WatsonX service\n", style="white")
            watsonx_info.append("    ", style="white")
            watsonx_info.append("Requires: API Key and Space ID (or Project ID)\n\n", style="dim white")
            
            watsonx_info.append("  • ", style="cyan")
            watsonx_info.append("WatsonX.ai Lightweight Engine (WLE)", style="bold green")
            watsonx_info.append(" - On-premise deployment\n", style="white")
            watsonx_info.append("    ", style="white")
            watsonx_info.append("Requires: Username and API Key\n\n", style="dim white")
            
            watsonx_info.append("💡 Note: ", style="bold yellow")
            watsonx_info.append("The credential requirements differ based on your deployment type.", style="white")
            
            print(Panel(
                watsonx_info,
                title="[bold white]WatsonX Configuration[/bold white]",
                border_style="cyan",
                padding=(1, 2)
            ))
            print()
            
            result = questionary.select(
                "Which WatsonX deployment type are you using?",
                choices=[
                    questionary.Choice("WatsonX.ai SaaS", value=1),
                    questionary.Choice("WatsonX.ai Lightweight Engine (WLE)", value=2)
                ],
                style=Style([
                    ('qmark', 'fg:cyan bold'),
                    ('question', 'bold'),
                    ('answer', 'fg:cyan bold'),
                    ('pointer', 'fg:cyan bold'),
                    ('highlighted', 'fg:cyan'),
                    ('selected', 'fg:green bold')
                ])
            ).ask()
            
            if result is None:
                print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                sys.exit(0)

            self._watsonx_type = self.WatsonXType(result).name
            self._logger.info(f"WatsonX deployment type selected: {self._watsonx_type}")

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_watsonx_type function - {str(e)}")
    # Function to collect model provider information
    def collect_model_providers(self):
        """Collect information about AI model providers (number and types)."""
        try:
            # Enhanced model provider configuration prompt
            provider_info = Text()
            provider_info.append("🤖 AI Model Provider Configuration\n\n", style="bold cyan")
            provider_info.append("Configure the AI model providers for your Content Cortex deployment.\n\n", style="white")
            
            provider_info.append("What are Model Providers?\n", style="bold yellow")
            provider_info.append("Model providers are AI services that power intelligent features in Content Cortex.\n", style="white")
            provider_info.append("You can configure multiple providers for redundancy or to use different models.\n\n", style="white")
            
            provider_info.append("Supported Provider Types:\n", style="bold yellow")
            provider_info.append("  • ", style="cyan")
            provider_info.append("WatsonX.ai SaaS", style="bold green")
            provider_info.append(" - IBM's cloud-based AI platform\n", style="white")
            provider_info.append("  • ", style="cyan")
            provider_info.append("WatsonX.ai Lightweight Engine (WLE)", style="bold green")
            provider_info.append(" - On-premise AI deployment\n", style="white")
            provider_info.append("  • ", style="cyan")
            provider_info.append("Microsoft Foundry", style="bold green")
            provider_info.append(" - Microsoft's Azure AI platform (https://ai.azure.com/)\n\n", style="white")
            
            provider_info.append("💡 Recommendation: ", style="bold yellow")
            provider_info.append("Start with 1 provider for initial deployment. Additional providers can be added later.", style="white")
            
            print(Panel(
                provider_info,
                title="[bold white]Model Provider Setup[/bold white]",
                border_style="cyan",
                padding=(1, 2)
            ))
            print()
            
            # Ask for number of providers
            while True:
                result_str = questionary.text(
                    "How many AI model providers do you want to configure?",
                    default="1",
                    validate=lambda text: text.isdigit() and int(text) >= 1 and int(text) <= 5,
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                    ])
                ).ask()
                
                if result_str is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                    
                result = int(result_str)
                if 1 <= result <= 5:
                    self._model_provider_count = result
                    self._logger.info(f"Number of model providers: {self._model_provider_count}")
                    break
                print("[prompt.invalid]Number of providers must be between 1 and 5")
            
            print()
            
            # Collect type for each provider
            self._model_providers = []
            for i in range(self._model_provider_count):
                provider_num = i + 1
                
                # Enhanced provider type selection
                type_info = Text()
                type_info.append(f"🔧 Provider {provider_num} Configuration\n\n", style="bold cyan")
                type_info.append(f"Select the deployment type for model provider #{provider_num}.\n\n", style="white")
                
                type_info.append("Deployment Options:\n", style="bold yellow")
                type_info.append("  • ", style="cyan")
                type_info.append("WatsonX.ai SaaS", style="bold green")
                type_info.append(" - Cloud-based service\n", style="white")
                type_info.append("    ", style="white")
                type_info.append("Requires: API Key, Space ID or Project ID\n\n", style="dim white")
                
                type_info.append("  • ", style="cyan")
                type_info.append("WatsonX.ai Lightweight Engine (WLE)", style="bold green")
                type_info.append(" - On-premise deployment\n", style="white")
                type_info.append("    ", style="white")
                type_info.append("Requires: Username, API Key\n\n", style="dim white")
                
                type_info.append("  • ", style="cyan")
                type_info.append("Microsoft Foundry", style="bold green")
                type_info.append(" - Microsoft Azure AI platform\n", style="white")
                type_info.append("    ", style="white")
                type_info.append("Requires: API Key, Endpoint URL\n", style="dim white")
                
                print(Panel(
                    type_info,
                    title=f"[bold white]Provider {provider_num} Type Selection[/bold white]",
                    border_style="cyan",
                    padding=(1, 2)
                ))
                print()
                
                provider_type = questionary.select(
                    f"Select the type for provider #{provider_num}:",
                    choices=[
                        questionary.Choice("WatsonX.ai SaaS", value=self.ModelProviderType.WATSONX_SAAS),
                        questionary.Choice("WatsonX.ai Lightweight Engine (WLE)", value=self.ModelProviderType.WATSONX_LWE),
                        questionary.Choice("Microsoft Foundry", value=self.ModelProviderType.MICROSOFT_FOUNDRY)
                    ],
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                        ('pointer', 'fg:cyan bold'),
                        ('highlighted', 'fg:cyan'),
                        ('selected', 'fg:green bold')
                    ])
                ).ask()
                
                if provider_type is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                
                self._model_providers.append({
                    'provider_number': provider_num,
                    'provider_type': provider_type.name,
                    'provider_type_value': provider_type.value
                })
                
                self._logger.info(f"Provider {provider_num} type: {provider_type.name}")
                print()
            
            # Set the watsonx_type based on the first provider for backward compatibility
            if self._model_providers:
                first_provider_type = self._model_providers[0]['provider_type']
                if first_provider_type == 'WATSONX_SAAS':
                    self._watsonx_type = self.WatsonXType.SAAS.name
                elif first_provider_type == 'WATSONX_LWE':
                    self._watsonx_type = self.WatsonXType.LWE.name
                self._logger.info(f"WatsonX type set to: {self._watsonx_type} (based on first provider)")
            
            # Display summary
            summary = Text()
            summary.append("✅ Model Provider Configuration Summary\n\n", style="bold green")
            summary.append(f"Total Providers: ", style="bold white")
            summary.append(f"{self._model_provider_count}\n\n", style="bold cyan")
            
            for provider in self._model_providers:
                summary.append(f"Provider {provider['provider_number']}: ", style="bold white")
                # Map provider type to display name
                if provider['provider_type'] == 'WATSONX_SAAS':
                    provider_type_display = "WatsonX.ai SaaS"
                elif provider['provider_type'] == 'WATSONX_LWE':
                    provider_type_display = "WatsonX.ai Lightweight Engine (WLE)"
                elif provider['provider_type'] == 'MICROSOFT_FOUNDRY':
                    provider_type_display = "Microsoft Foundry"
                else:
                    provider_type_display = provider['provider_type']  # Fallback
                summary.append(f"{provider_type_display}\n", style="cyan")
            
            print(Panel(
                summary,
                title="[bold white]Configuration Complete[/bold white]",
                border_style="green",
                padding=(1, 2)
            ))
            print()

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_model_providers function - {str(e)}")
    
    def check_and_migrate_from_fncm_deployment(self):
        """
        Check if an FNCMCluster deployment exists in the namespace and offer to migrate settings.
        This is specifically for AI Services setup when Content operator is already deployed.
        """
        try:
            # Only check if we have AI Services operator selected and namespace is set
            if not self.has_ai_services_operator() or not self._namespace:
                return False
            
            # Check if Kubernetes connection is available
            if not self._k.connected:
                self._logger.warning("No Kubernetes connection available - Content migration function disabled")
                self._display_migration_disabled_warning("No Kubernetes connection available")
                return False
            
            # Check for existing FNCMCluster CRs in the namespace
            # Note: This will return empty list if there's a permission error (Forbidden)
            # The list_fncm_cluster_crs method logs errors (including "Forbidden") but returns empty list
            cr_names = self._k.list_fncm_cluster_crs(self._namespace)
            
            # If no CRs found, it could be due to:
            # 1. No FNCMCluster deployments exist (normal case)
            # 2. Permission error (Forbidden) - user logged out or insufficient permissions
            # 3. CRD not installed
            if not cr_names or len(cr_names) == 0:
                self._logger.info(f"No FNCMCluster deployments found or inaccessible in namespace: {self._namespace}")
                # Show informational message about migration not being available
                # This covers both "no CRs" and "permission denied" scenarios gracefully
                info_panel = Text()
                info_panel.append("ℹ️  Content Migration Not Available\n\n", style="bold cyan")
                info_panel.append("No existing FNCMCluster deployments detected in namespace ", style="white")
                info_panel.append(f"{self._namespace}\n\n", style="bold cyan")
                info_panel.append("This could mean:\n", style="bold yellow")
                info_panel.append("  • No Content deployment exists yet (normal for new deployments)\n", style="dim white")
                info_panel.append("  • Insufficient permissions to list FNCMCluster resources\n", style="dim white")
                info_panel.append("  • FNCMCluster CRD not installed in the cluster\n\n", style="dim white")
                info_panel.append("Impact:\n", style="bold yellow")
                info_panel.append("  • AI Services will be configured manually\n", style="white")
                info_panel.append("  • You'll need to provide GraphQL endpoint, Object Store, and IDP settings\n\n", style="white")
                info_panel.append("Continuing with manual configuration...", style="bold white")
                
                print(Panel(
                    info_panel,
                    title="[bold cyan]ℹ️  Migration Information[/bold cyan]",
                    border_style="cyan",
                    padding=(1, 2)
                ))
                print()
                
                return False
            
            # Display information about existing deployment
            migration_info = Text()
            migration_info.append("🔍 Existing Content Deployment Detected\n\n", style="bold cyan")
            migration_info.append(f"Found {len(cr_names)} FNCMCluster deployment(s) in namespace ", style="white")
            migration_info.append(f"{self._namespace}\n\n", style="bold cyan")
            
            if len(cr_names) == 1:
                migration_info.append(f"Deployment: ", style="bold yellow")
                migration_info.append(f"{cr_names[0]}\n\n", style="cyan")
            else:
                migration_info.append("Deployments:\n", style="bold yellow")
                for name in cr_names:
                    migration_info.append(f"  • {name}\n", style="cyan")
                migration_info.append("\n", style="white")
            
            migration_info.append("💡 AI Services Integration\n\n", style="bold yellow")
            migration_info.append("AI Services can integrate with your existing Content deployment.\n", style="white")
            migration_info.append("Settings can be automatically extracted from the FNCMCluster CR:\n\n", style="white")
            migration_info.append("  ✓ ", style="green")
            migration_info.append("GraphQL endpoint configuration\n", style="white")
            migration_info.append("  ✓ ", style="green")
            migration_info.append("Object Store selection\n", style="white")
            migration_info.append("  ✓ ", style="green")
            migration_info.append("IDP/OIDC configuration\n", style="white")
            migration_info.append("  ✓ ", style="green")
            migration_info.append("Platform selection (OCP/CNCF)\n", style="white")
            migration_info.append("  ✓ ", style="green")
            migration_info.append("Storage class configuration\n", style="white")
            migration_info.append("  ✓ ", style="green")
            migration_info.append("Navigator URL (may need manual input)\n\n", style="white")
            
            migration_info.append("⚠️  Note: ", style="bold red")
            migration_info.append("This will skip some configuration questions and use settings from the existing deployment.", style="yellow")
            
            print(Panel(
                migration_info,
                title="[bold white]Content Deployment Migration[/bold white]",
                border_style="cyan",
                padding=(1, 2)
            ))
            print()
            
            # Ask user if they want to migrate settings
            migrate = questionary.confirm(
                "Do you want to use settings from the existing Content deployment?",
                default=True,
                style=Style([
                    ('qmark', 'fg:cyan bold'),
                    ('question', 'bold'),
                    ('answer', 'fg:cyan bold'),
                ])
            ).ask()
            
            if migrate is None:
                print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                sys.exit(0)
            
            if not migrate:
                self._logger.info("User chose not to migrate settings from existing deployment")
                return False
            
            # Select which CR to use if multiple exist
            cr_name = None
            if len(cr_names) == 1:
                cr_name = cr_names[0]
            else:
                print()
                cr_name = questionary.select(
                    "Select the FNCMCluster deployment to migrate settings from:",
                    choices=[questionary.Choice(name, value=name) for name in cr_names],
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                        ('pointer', 'fg:cyan bold'),
                        ('highlighted', 'fg:cyan'),
                        ('selected', 'fg:green bold')
                    ])
                ).ask()
                
                if cr_name is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
            
            # Retrieve the CR
            cr = self._k.get_fncm_cluster_cr(self._namespace, cr_name)
            if not cr:
                print(f"\n[red]✗ Failed to retrieve FNCMCluster CR: {cr_name}[/red]")
                return False
            
            # Extract settings
            settings = self._k.extract_ai_services_settings_from_fncm_cr(cr)
            
            if not settings['found']:
                print("\n[yellow]⚠ Could not extract AI Services settings from the deployment[/yellow]")
                print("[yellow]  The deployment may not have the required components (GraphQL and CPE)[/yellow]")
                return False
            
            # Store the migrated settings
            self._fncm_migration_settings = settings
            
            # Display the migrated settings summary
            self._display_migration_summary(settings)
            
            return True
            
        except Exception as e:
            self._logger.exception(f"Exception checking for FNCMCluster deployment migration: {str(e)}")
            print(f"\n[red]✗ Error checking for existing deployment: {str(e)}[/red]")
            return False
    
    def _display_migration_disabled_warning(self, reason: str):
        """Display a warning panel when content migration is disabled."""
        warning_panel = Text()
        warning_panel.append("⚠️  Kubernetes Access Issue\n\n", style="bold yellow")
        warning_panel.append("Content Migration Function: ", style="bold white")
        warning_panel.append("DISABLED\n\n", style="bold red")
        warning_panel.append(f"Reason: {reason}\n\n", style="yellow")
        warning_panel.append("The content migration function requires cluster access to:\n", style="white")
        warning_panel.append("  • Detect existing FNCMCluster deployments\n", style="dim white")
        warning_panel.append("  • Extract Custom Resource (CR) configuration\n", style="dim white")
        warning_panel.append("  • Retrieve required secrets for AI Services integration\n\n", style="dim white")
        warning_panel.append("Impact:\n", style="bold yellow")
        warning_panel.append("  ✗ Cannot automatically migrate settings from existing Content deployment\n", style="red")
        warning_panel.append("  ✗ Cannot retrieve GraphQL endpoint and certificates\n", style="red")
        warning_panel.append("  ✗ Cannot extract Object Store and IDP configuration\n\n", style="red")
        warning_panel.append("💡 To restore content migration function:\n", style="bold cyan")
        warning_panel.append("  1. Ensure you have a valid kubeconfig file\n", style="white")
        warning_panel.append("  2. Verify cluster connectivity (kubectl cluster-info)\n", style="white")
        warning_panel.append("  3. Confirm access to the target namespace (kubectl auth can-i list fncmclusters)\n", style="white")
        warning_panel.append("  4. Re-run the gather command with proper cluster access\n\n", style="white")
        warning_panel.append("Continuing with manual configuration...", style="bold white")
        
        print(Panel(
            warning_panel,
            title="[bold red]⚠️  Content Migration Disabled[/bold red]",
            border_style="red",
            padding=(1, 2)
        ))
        print()
    
    def _display_migration_summary(self, settings: dict):
        """Display a summary panel of the migrated settings from FNCMCluster CR."""
        try:
            summary = Text()
            summary.append("✅ Settings Migrated Successfully\n\n", style="bold green")
            
            summary.append("Source Deployment:\n", style="bold yellow")
            summary.append(f"  CR Name: ", style="white")
            summary.append(f"{settings['cr_name']}\n", style="cyan")
            summary.append(f"  Namespace: ", style="white")
            summary.append(f"{settings['namespace']}\n", style="cyan")
            
            # Version information
            summary.append(f"  Version: ", style="white")
            version = settings.get('version', 'Unknown')
            if settings.get('version_compatible'):
                summary.append(f"{version} ", style="green")
                summary.append("✓ Compatible\n", style="bold green")
            else:
                summary.append(f"{version} ", style="red")
                summary.append("⚠ Incompatible\n", style="bold red")
            
            # Platform
            summary.append(f"  Platform: ", style="white")
            platform = settings.get('platform', 'Unknown')
            if platform and platform != 'Unknown':
                summary.append(f"{platform}\n", style="cyan")
            else:
                summary.append("<Not specified>\n", style="dim")
            
            # Ingress Configuration
            summary.append(f"  Ingress: ", style="white")
            ingress_enabled = settings.get('ingress_enabled')
            ingress_source = settings.get('ingress_source', 'Unknown')
            if ingress_enabled is not None:
                if ingress_enabled:
                    summary.append("Enabled\n", style="green")
                else:
                    summary.append("Disabled\n", style="cyan")
                summary.append(f"    Source: ", style="dim white")
                summary.append(f"{ingress_source}\n", style="dim cyan")
                
                # Show additional ingress settings if available
                ingress_hostname = settings.get('ingress_hostname')
                if ingress_hostname:
                    summary.append(f"    Hostname: ", style="dim white")
                    summary.append(f"{ingress_hostname}\n", style="dim cyan")
                
                ingress_tls_secret = settings.get('ingress_tls_secret')
                if ingress_tls_secret:
                    summary.append(f"    TLS Secret: ", style="dim white")
                    summary.append(f"{ingress_tls_secret}\n", style="dim cyan")
                
                ingress_annotations = settings.get('ingress_annotations')
                if ingress_annotations and isinstance(ingress_annotations, list):
                    summary.append(f"    Annotations: ", style="dim white")
                    summary.append(f"{len(ingress_annotations)} annotation(s)\n", style="dim cyan")
                
                service_type = settings.get('service_type')
                if service_type:
                    summary.append(f"    Service Type: ", style="dim white")
                    summary.append(f"{service_type}\n", style="dim cyan")
            else:
                summary.append("<Not detected>\n", style="dim")
                if ingress_source and ingress_source != 'Unknown':
                    summary.append(f"    Reason: ", style="dim white")
                    summary.append(f"{ingress_source}\n", style="dim yellow")
            
            # Storage Class
            summary.append(f"  Storage Class: ", style="white")
            storage_class = settings.get('storage_class', 'Unknown')
            if storage_class and storage_class != 'Unknown':
                summary.append(f"{storage_class}\n", style="cyan")
            else:
                summary.append("<Not specified>\n", style="dim")
            
            summary.append("\n", style="white")
            summary.append("Extracted Configuration:\n", style="bold yellow")
            
            # Platform and Ingress (grouped together as they're related)
            summary.append(f"  Platform: ", style="white")
            if platform and platform != 'Unknown':
                summary.append(f"{platform}", style="cyan")
                # Show ingress status inline with platform
                ingress_enabled = settings.get('ingress_enabled')
                if ingress_enabled is not None:
                    if platform.upper() == 'OCP':
                        summary.append(" (Routes)\n", style="dim cyan")
                    else:
                        ingress_status = "Ingress Enabled" if ingress_enabled else "Ingress Disabled"
                        ingress_color = "green" if ingress_enabled else "yellow"
                        summary.append(f" ({ingress_status})\n", style=ingress_color)
                else:
                    summary.append("\n", style="white")
            else:
                summary.append("<Not specified>\n", style="dim")
            
            # GraphQL Endpoint
            summary.append(f"  GraphQL Endpoint: ", style="white")
            if settings['graphql_endpoint']:
                summary.append(f"{settings['graphql_endpoint']}\n", style="green")
                # Show certificate secret if available
                if settings.get('graphql_root_ca_secret'):
                    summary.append(f"    Certificate Secret: ", style="dim white")
                    summary.append(f"{settings['graphql_root_ca_secret']}\n", style="cyan")
            else:
                summary.append("<Not configured>\n", style="dim")
            
            # Object Store
            summary.append(f"  Object Store: ", style="white")
            if settings['object_store']:
                summary.append(f"{settings['object_store']}\n", style="green")
            else:
                summary.append("<Not configured>\n", style="dim")
            
            # Navigator URL
            summary.append(f"  Navigator URL: ", style="white")
            nav_url = settings.get('navigator_url', '<Required>')
            nav_source = settings.get('navigator_url_source', 'Not detected')
            if nav_url and nav_url != '<Required>':
                summary.append(f"{nav_url}\n", style="green")
                summary.append(f"    Source: ", style="dim white")
                summary.append(f"{nav_source}\n", style="dim cyan")
            else:
                summary.append("<Requires manual input>\n", style="yellow")
                summary.append(f"    Source: ", style="dim white")
                summary.append(f"{nav_source}\n", style="dim yellow")
            
            # IDP Configuration
            summary.append(f"  IDP Configuration: ", style="white")
            idp_config = settings.get('idp_config', {})
            if idp_config and idp_config.get('provider_name'):
                summary.append(f"Configured ({idp_config['provider_name']})\n", style="green")
                
                # Show discovery URL
                if idp_config.get('discovery_url'):
                    summary.append(f"    Discovery URL: ", style="dim white")
                    discovery_url = idp_config['discovery_url']
                    # Validate if it ends with the expected path
                    if discovery_url.endswith('.well-known/openid-configuration'):
                        summary.append(f"{discovery_url}\n", style="dim green")
                    else:
                        summary.append(f"{discovery_url} ", style="dim yellow")
                        summary.append("⚠ May be incomplete\n", style="dim yellow")
                
                # Show client credentials status
                client_id = idp_config.get('client_id', '<From Secret>')
                client_secret = idp_config.get('client_secret', '<From Secret>')
                
                summary.append(f"    Client ID: ", style="dim white")
                if client_id and client_id != '<From Secret>':
                    summary.append(f"✓ Extracted\n", style="dim green")
                else:
                    summary.append(f"⚠ Requires manual input\n", style="dim yellow")
                
                summary.append(f"    Client Secret: ", style="dim white")
                if client_secret and client_secret != '<From Secret>':
                    summary.append(f"✓ Extracted\n", style="dim green")
                else:
                    summary.append(f"⚠ Requires manual input\n", style="dim yellow")
                
                # Show secret name if available
                if idp_config.get('secret_name'):
                    summary.append(f"    Secret Name: ", style="dim white")
                    summary.append(f"{idp_config['secret_name']}\n", style="dim cyan")
            else:
                summary.append("<Not configured>\n", style="dim")
            
            summary.append("\n", style="white")
            summary.append("Components Detected:\n", style="bold yellow")
            summary.append(f"  CPE: ", style="white")
            summary.append("✓\n" if settings['has_cpe'] else "✗\n", style="green" if settings['has_cpe'] else "red")
            summary.append(f"  GraphQL: ", style="white")
            summary.append("✓\n" if settings['has_graphql'] else "✗\n", style="green" if settings['has_graphql'] else "red")
            summary.append(f"  Navigator: ", style="white")
            summary.append("✓\n" if settings['has_ban'] else "✗\n", style="green" if settings['has_ban'] else "red")
            
            # Display recommendations if any
            recommendations = settings.get('recommendations', [])
            if recommendations:
                summary.append("\n", style="white")
                summary.append("📋 Recommendations:\n", style="bold yellow")
                for rec in recommendations:
                    rec_type = rec.get('type', 'info')
                    message = rec.get('message', '')
                    action = rec.get('action', '')
                    
                    # Choose icon and color based on type
                    if rec_type == 'critical':
                        icon = "🔴"
                        style_color = "bold red"
                    elif rec_type == 'warning':
                        icon = "⚠️ "
                        style_color = "yellow"
                    elif rec_type == 'important':
                        icon = "❗"
                        style_color = "bold yellow"
                    else:  # info
                        icon = "ℹ️ "
                        style_color = "cyan"
                    
                    summary.append(f"\n  {icon} ", style=style_color)
                    summary.append(f"{message}\n", style="white")
                    if action:
                        summary.append(f"     Action: ", style="dim white")
                        summary.append(f"{action}\n", style="dim cyan")
            
            summary.append("\n", style="white")
            summary.append("💡 Next Steps:\n", style="bold yellow")
            summary.append("  • Property files will be pre-filled with these settings\n", style="white")
            if not settings.get('version_compatible'):
                summary.append("  • Upgrade Content Cortex to version 26.0.0 before proceeding\n", style="yellow")
            if settings.get('navigator_url') == '<Required>':
                summary.append("  • Provide Navigator external URL in property file\n", style="white")
            summary.append("  • Review and adjust settings in the generate phase\n", style="white")
            
            print(Panel(
                summary,
                title="[bold white]Migration Summary[/bold white]",
                border_style="green",
                padding=(1, 2)
            ))
            print()
            
            # Confirm to continue
            confirm = questionary.confirm(
                "Continue with these migrated settings?",
                default=True,
                style=Style([
                    ('qmark', 'fg:cyan bold'),
                    ('question', 'bold'),
                    ('answer', 'fg:cyan bold'),
                ])
            ).ask()
            
            if confirm is None or not confirm:
                print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                sys.exit(0)
            
        except Exception as e:
            self._logger.exception(f"Exception displaying migration summary: {str(e)}")
    
    @property
    def fncm_migration_settings(self):
        """Get the migrated settings from FNCMCluster CR."""
        return self._fncm_migration_settings

    # Create a function to gather db_type from the user
    def collect_license_model(self, version_data):
        try:

            self._ccx_version = version_data.get("VERSION", '26.0.0')
            display = version_data.get("DISPLAY", '26.0.0')

            # Enhanced license agreement prompt
            fncm_license_url = "https://ibm.biz/CPE_CCX_License_26_0_0"
            cpe_notices_url = "http://ibm.biz/CCX_Notices_26_0_0"
            ier_license_url = "https://ibm.biz/ier_license_521"
            iccsap_license_url = "https://ibm.biz/iccsap_license_4002"
            cp4ba_license_url = "https://ibm.biz/cp4ba_license_2600"
            
            license_info = Text()
            license_info.append(f"📦 Detected Version: ", style="bold cyan")
            license_info.append(f"{display}\n\n", style="bold green")
            license_info.append("📜 International Program License Agreement\n\n", style="bold cyan")
            license_info.append("Please review the license agreements before proceeding:\n\n", style="white")
            license_info.append("📄 IBM Content Cortex:\n", style="bold yellow")
            license_info.append(f"   {fncm_license_url}\n\n", style="link " + fncm_license_url)
            license_info.append("📄 Software Notices:\n", style="bold yellow")
            license_info.append(f"   {cpe_notices_url}\n\n", style="link " + cpe_notices_url)
            license_info.append("📄 IBM Enterprise Records:\n", style="bold yellow")
            license_info.append(f"   {ier_license_url}\n\n", style="link " + ier_license_url)
            license_info.append("📄 IBM Content Collector for SAP:\n", style="bold yellow")
            license_info.append(f"   {iccsap_license_url}\n\n", style="link " + iccsap_license_url)
            license_info.append("📄 IBM Cloud Pak for Business Automation:\n", style="bold yellow")
            license_info.append(f"   {cp4ba_license_url}\n\n", style="link " + cp4ba_license_url)
            license_info.append("⚠️  You must accept the license to continue deployment.", style="bold red")
            
            print(Panel(
                license_info,
                title="[bold white]License Agreement Required[/bold white]",
                border_style="white",
                padding=(1, 2)
            ))
            print()

            # Second Panel: Data Collection Notice
            agreement_text = Text()
            agreement_text.append("⚠ ", style="bold yellow")
            agreement_text.append("You are about to accept the IBM Content Cortex License Agreement\n\n", style="bold white")
            
            agreement_text.append("📊 ", style="bold cyan")
            agreement_text.append("Data collection will be enabled by default\n", style="white")
            agreement_text.append("📄 ", style="bold cyan")
            agreement_text.append("Review full license terms in the License Information document\n\n", style="white")
            
            agreement_text.append("By accepting the license, you agree and understand that by default the program collects certain data and metrics regarding deployment and usage. ", style="white")
            agreement_text.append("For more information, please consult the License Information for IBM Content Cortex.", style="bold white")
            
            print(Panel(
                agreement_text,
                title="[bold yellow]⚠ LICENSE AGREEMENT REQUIRED ⚠[/bold yellow]",
                border_style="yellow",
                padding=(1, 2)
            ))
            print()
            
            # Third Panel: License Terms
            terms_text = Text()
            terms_text.append("📋 ", style="bold cyan")
            terms_text.append("License Agreement Acceptance\n\n", style="bold white")
            
            terms_text.append("By accepting, you agree to:\n", style="white")
            terms_text.append("  • Comply with all license terms and conditions\n", style="white")
            terms_text.append("  • Use the software within entitled scope\n", style="white")
            terms_text.append("  • Maintain proper license documentation\n\n", style="white")
            
            terms_text.append("⚠ ", style="bold yellow")
            terms_text.append("Required: ", style="bold yellow")
            terms_text.append("You must accept to proceed with deployment.", style="white")
            
            print(Panel(
                terms_text,
                title="[bold white]License Terms[/bold white]",
                border_style="white",
                padding=(1, 2)
            ))
            print()

            self._accept_license = questionary.confirm(
                "Do you accept the International Program License?",
                default=False,
                style=Style([
                    ('qmark', 'fg:yellow bold'),
                    ('question', 'bold'),
                    ('answer', 'fg:green bold'),
                ])
            ).ask()
            
            if self._accept_license is None:
                print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                sys.exit(0)

            if not self._accept_license:
                print("\n[prompt.invalid]You must accept the International Program License to continue.")
                exit(1)

            # Enhanced license type selection
            license_type_info = Text()
            license_type_info.append("🏷️ License Type Selection\n\n", style="bold cyan")
            license_type_info.append("Choose the license model that matches your entitlement:\n\n", style="white")
            license_type_info.append("  • ", style="cyan")
            license_type_info.append("Essentials", style="bold green")
            license_type_info.append(" - IBM Content Cortex Essentials license\n", style="white")
            license_type_info.append("  • ", style="cyan")
            license_type_info.append("CP4BA", style="bold green")
            license_type_info.append(" - Cloud Pak for Business Automation license\n", style="white")
            
            print(Panel(
                license_type_info,
                title="[bold white]License Model Configuration[/bold white]",
                border_style="cyan",
                padding=(1, 2)
            ))
            print()
            
            license_type_result = questionary.select(
                "Select a License Type:",
                choices=[
                    questionary.Choice("Essentials", value=1),
                    questionary.Choice("CP4BA", value=2)
                ],
                style=Style([
                    ('qmark', 'fg:cyan bold'),
                    ('question', 'bold'),
                    ('answer', 'fg:cyan bold'),
                    ('pointer', 'fg:cyan bold'),
                    ('highlighted', 'fg:cyan'),
                    ('selected', 'fg:green bold')
                ])
            ).ask()
            
            if license_type_result is None:
                print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                sys.exit(0)

            model = self.LicenseModel(license_type_result).name

            if license_type_result == 2:  # CP4BA
                metric_result = questionary.select(
                    "Select a License Metric:",
                    choices=[
                        questionary.Choice("NonProd", value=1),
                        questionary.Choice("Prod", value=2),
                        questionary.Choice("User", value=3)
                    ],
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                        ('pointer', 'fg:cyan bold'),
                        ('highlighted', 'fg:cyan'),
                        ('selected', 'fg:green bold')
                    ])
                ).ask()
                
                if metric_result is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                    
                metric = self.LicenseMetricCP4BA(metric_result).name
            else:  # ESS
                metric_result = questionary.select(
                    "Select a License Metric:",
                    choices=[
                        questionary.Choice("IBM Content Cortex Restricted - Authorized", value=1),
                        questionary.Choice("IBM Content Cortex Restricted - Eligible Participant", value=2),
                        questionary.Choice("IBM Content Cortex Restricted - Employee", value=3),
                        questionary.Choice("IBM Content Cortex Essentials - Authorized User", value=4),
                        questionary.Choice("IBM Content Cortex Essentials - Eligible Participants", value=5),
                        questionary.Choice("IBM Content Cortex Essentials - Employee", value=6)
                    ],
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                        ('pointer', 'fg:cyan bold'),
                        ('highlighted', 'fg:cyan'),
                        ('selected', 'fg:green bold')
                    ])
                ).ask()
                
                if metric_result is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)

                metric = self.LicenseMetricESS(metric_result).name

            # Map the license model to the property file format
            license_mapping = {
                "ESS.AR": "CCx.AR",
                "ESS.PR": "CCx.PR",
                "ESS.AU": "CCx.Ess.AU",
                "ESS.EP": "CCx.Ess.EP",
                "ESS.EE": "CCx.EE",
                "ESS.ER": "CCx.ER",
                "CP4BA.NonProd": "CP4BA.NonProd",
                "CP4BA.Prod": "CP4BA.Prod",
                "CP4BA.User": "CP4BA.User"
            }
            
            combined_license = f"{model}.{metric}"
            self._license_model = license_mapping.get(combined_license, combined_license)

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in license model function -  {str(e)}")

    # Create a function to gather db_type from the user
    def collect_db_type(self):
        try:
            # Enhanced database selection panel
            db_info = Text()
            db_info.append("🗄️  Database Configuration\n\n", style="bold cyan")
            db_info.append("Select the database platform for your IBM Content Cortex deployment.\n\n", style="white")
            
            db_info.append("Enterprise Databases:\n", style="bold yellow")
            db_info.append("  • ", style="white")
            db_info.append("IBM Db2", style="bold green")
            db_info.append(" - IBM's enterprise relational database\n", style="white")
            db_info.append("  • ", style="white")
            db_info.append("IBM Db2 HADR", style="bold green")
            db_info.append(" - High Availability Disaster Recovery configuration\n", style="white")
            db_info.append("  • ", style="white")
            db_info.append("Oracle", style="bold green")
            db_info.append(" - Oracle Database for enterprise workloads\n", style="white")
            db_info.append("  • ", style="white")
            db_info.append("Microsoft SQL Server", style="bold green")
            db_info.append(" - Microsoft's relational database platform\n\n", style="white")
            
            db_info.append("Cloud Databases:\n", style="bold yellow")
            db_info.append("  • ", style="white")
            db_info.append("PostgreSQL", style="bold green")
            db_info.append(" - Open-source relational database\n", style="white")
            db_info.append("  • ", style="white")
            db_info.append("IBM Db2 RDS", style="bold green")
            db_info.append(" - AWS RDS managed Db2 service\n", style="white")
            db_info.append("  • ", style="white")
            db_info.append("IBM Db2 RDS HADR", style="bold green")
            db_info.append(" - AWS RDS Db2 with high availability\n\n", style="white")
            
            db_info.append("💡 Recommendation: ", style="bold yellow")
            db_info.append("Choose HADR configurations for production environments requiring high availability.", style="white")
            
            print(Panel(
                db_info,
                title="[bold white]Database Platform Selection[/bold white]",
                border_style="cyan",
                padding=(1, 2)
            ))
            print()
            
            result = questionary.select(
                "Select a Database Type:",
                choices=[
                    questionary.Choice("IBM Db2", value=1),
                    questionary.Choice("IBM Db2 HADR", value=2),
                    questionary.Choice("Microsoft SQL Server", value=3),
                    questionary.Choice("PostgreSQL", value=4),
                    questionary.Choice("Oracle", value=5),
                    questionary.Choice("IBM Db2 RDS", value=6),
                    questionary.Choice("IBM Db2 RDS HADR", value=7)
                ],
                style=Style([
                    ('qmark', 'fg:cyan bold'),
                    ('question', 'bold'),
                    ('answer', 'fg:cyan bold'),
                    ('pointer', 'fg:cyan bold'),
                    ('highlighted', 'fg:cyan'),
                    ('selected', 'fg:green bold')
                ])
            ).ask()
            
            if result is None:
                print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                sys.exit(0)

            self._db_type = self.DatabaseType(result).name


        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect DB function -  {str(e)}")

    # Create a function to gather operators from the user
    def collect_operators(self):
        """Collect which deployment type(s) to configure - Content and/or AI Services."""
        try:
            # Enhanced deployment type selection prompt
            deployment_info = Text()
            deployment_info.append("🚀 Deployment Type Selection\n\n", style="bold cyan")
            deployment_info.append("Select which operator(s) you want to configure:\n\n", style="white")
            deployment_info.append("Deployment Options:\n", style="bold yellow")
            deployment_info.append("  • ", style="cyan")
            deployment_info.append("Content", style="bold green")
            deployment_info.append(" - IBM Content Cortex\n", style="white")
            deployment_info.append("    ", style="white")
            deployment_info.append("Configure Content operator with CPE, GraphQL, Navigator, CSS, CMIS, etc.\n\n", style="dim white")
            deployment_info.append("  • ", style="cyan")
            deployment_info.append("AI Services", style="bold green")
            deployment_info.append(" - IBM Content Cortex AI Services\n", style="white")
            deployment_info.append("    ", style="white")
            deployment_info.append("Configure AI Services operator with Agent and MCP integration\n\n", style="dim white")
            deployment_info.append("💡 Note: ", style="bold yellow")
            deployment_info.append("You can configure property files for one or both operators.", style="white")
            
            print(Panel(
                deployment_info,
                title="[bold white]Deployment Configuration[/bold white]",
                border_style="cyan",
                padding=(1, 2)
            ))
            
            custom_style = Style([
                ('qmark', 'fg:cyan bold'),
                ('question', 'fg:white bold'),
                ('answer', 'fg:green bold'),
                ('pointer', 'fg:cyan bold'),
                ('highlighted', 'fg:cyan bold'),
                ('selected', 'fg:green bold'),
                ('separator', 'fg:cyan'),
                ('instruction', 'fg:white'),
                ('checkbox', 'fg:cyan bold'),
                ('checkbox-selected', 'fg:green bold'),
            ])
            
            selected_operators = questionary.checkbox(
                "Which deployment type(s) do you want to configure? (Use arrow keys and space to select)",
                choices=[
                    questionary.Choice("Content", checked=True),
                    questionary.Choice("AI Services", checked=False)
                ],
                style=custom_style
            ).ask()
            
            # Store selected operators for later use
            self._selected_operators = selected_operators if selected_operators else ["Content"]
            self._logger.info(f"Selected operators: {', '.join(self._selected_operators)}")
            
            # For backward compatibility, set deployment_type
            if len(self._selected_operators) == 2:
                self._deployment_type = "Both"
            elif "AI Services" in self._selected_operators:
                self._deployment_type = "AI Services"
            else:
                self._deployment_type = "Content"
            
        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_operators function - {str(e)}")
    
    @property
    def deployment_type(self):
        """Get the selected deployment type."""
        return getattr(self, '_deployment_type', 'Content')  # Default to Content for backward compatibility
    
    @property
    def selected_operators(self):
        """Get the list of selected operators."""
        return getattr(self, '_selected_operators', ['Content'])  # Default to Content for backward compatibility
    
    def has_content_operator(self):
        """Check if Content operator is selected."""
        return "Content" in self.selected_operators
    
    def has_ai_services_operator(self):
        """Check if AI Services operator is selected."""
        return "AI Services" in self.selected_operators
    
    # Create a function to gather ingress info from the user
    def collect_ingress(self):
        """Collect platform and ingress configuration."""
        try:
            # Check if we have migrated settings from FNCMCluster CR
            if hasattr(self, '_fncm_migration_settings') and self._fncm_migration_settings:
                migrated_platform = self._fncm_migration_settings.get('platform', '')
                migrated_ingress = self._fncm_migration_settings.get('ingress_enabled')
                ingress_source = self._fncm_migration_settings.get('ingress_source', 'Unknown')
                
                if migrated_platform:
                    # Use migrated platform setting
                    self._platform = migrated_platform
                    print(f"\n[green]✓ Using platform from Content deployment: {migrated_platform}[/green]")
                    
                    # Use migrated ingress setting if available
                    if migrated_ingress is not None:
                        self._ingress = migrated_ingress
                        print(f"[green]✓ Using ingress configuration from Content deployment: {migrated_ingress}[/green]")
                        print(f"[dim]  Source: {ingress_source}[/dim]")
                    else:
                        # Fallback to platform-based logic if ingress setting not available
                        if migrated_platform == "OCP":
                            self._ingress = False
                            print(f"[green]✓ Ingress disabled (OCP uses Routes)[/green]")
                        else:
                            self._ingress = True
                            print(f"[yellow]⚠ Ingress setting not found in Content deployment, defaulting to enabled for CNCF platform[/yellow]")
                    
                    return
            
            # Enhanced platform selection prompt
            platform_info = Text()
            platform_info.append("🏗️ Kubernetes Platform Selection\n\n", style="bold cyan")
            platform_info.append("Select your Kubernetes platform type:\n\n", style="white")
            platform_info.append("Platform Options:\n", style="bold yellow")
            platform_info.append("  • ", style="cyan")
            platform_info.append("OCP", style="bold green")
            platform_info.append(" - OpenShift Container Platform\n", style="white")
            platform_info.append("    ", style="white")
            platform_info.append("Uses OpenShift Routes for external access\n", style="dim white")
            platform_info.append("    ", style="white")
            platform_info.append("Built-in ingress controller and routing\n\n", style="dim white")
            platform_info.append("  • ", style="cyan")
            platform_info.append("CNCF", style="bold green")
            platform_info.append(" - Cloud Native Computing Foundation (Standard Kubernetes)\n", style="white")
            platform_info.append("    ", style="white")
            platform_info.append("Requires ingress controller configuration\n", style="dim white")
            platform_info.append("    ", style="white")
            platform_info.append("Supports various ingress implementations\n\n", style="dim white")
            platform_info.append("💡 Note: ", style="bold yellow")
            platform_info.append("OCP automatically creates routes; CNCF requires ingress setup.", style="white")
            
            print(Panel(
                platform_info,
                title="[bold white]Platform Configuration[/bold white]",
                border_style="cyan",
                padding=(1, 2)
            ))
            print()
            
            result = questionary.select(
                "Select a Platform Type:",
                choices=[
                    questionary.Choice("OCP", value=1),
                    questionary.Choice("CNCF", value=2)
                ],
                style=Style([
                    ('qmark', 'fg:cyan bold'),
                    ('question', 'bold'),
                    ('answer', 'fg:cyan bold'),
                    ('pointer', 'fg:cyan bold'),
                    ('highlighted', 'fg:cyan'),
                    ('selected', 'fg:green bold')
                ])
            ).ask()
            
            if result is None:
                print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                sys.exit(0)

            self._platform = self.Platform(result).name

            # Only ask about ingress for CNCF platforms
            if self._platform == "other":
                # Enhanced ingress prompt for CNCF platforms
                ingress_info = Text()
                ingress_info.append("🌐 Ingress Configuration for CNCF Platform\n\n", style="bold cyan")
                ingress_info.append("Ingress provides external HTTP/HTTPS access to services in your cluster.\n\n", style="white")
                ingress_info.append("What Ingress Provides:\n", style="bold yellow")
                ingress_info.append("  ✓ Single entry point for external traffic\n", style="green")
                ingress_info.append("  ✓ SSL/TLS termination\n", style="green")
                ingress_info.append("  ✓ Name-based virtual hosting\n", style="green")
                ingress_info.append("  ✓ Load balancing across pods\n\n", style="green")
                ingress_info.append("Requirements:\n", style="bold yellow")
                ingress_info.append("  • Ingress controller must be installed (NGINX, Traefik, etc.)\n", style="white")
                ingress_info.append("  • DNS configuration for ingress hostnames\n", style="white")
                ingress_info.append("  • SSL certificates for HTTPS access\n\n", style="white")
                ingress_info.append("💡 Recommendation: ", style="bold yellow")
                ingress_info.append("Enable for production deployments requiring external access.", style="white")
                
                print(Panel(
                    ingress_info,
                    title="[bold white]External Access Configuration[/bold white]",
                    border_style="cyan",
                    padding=(1, 2)
                ))
                print()
                
                self._ingress = questionary.confirm(
                    "Do you want to enable ingress creation?",
                    default=False,
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                    ])
                ).ask()
                
                if self._ingress is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
            else:
                # For OCP, ingress is not needed (uses routes)
                self._ingress = False
                
        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_ingress function - {str(e)}")

    # Create a function to gather platform and ingress enabled from user
    def collect_platform_ingress(self):
        try:
            # Enhanced platform selection prompt
            platform_info = Text()
            platform_info.append("🏗️ Kubernetes Platform Selection\n\n", style="bold cyan")
            platform_info.append("Select your Kubernetes platform type:\n\n", style="white")
            platform_info.append("Platform Options:\n", style="bold yellow")
            platform_info.append("  • ", style="cyan")
            platform_info.append("OCP", style="bold green")
            platform_info.append(" - OpenShift Container Platform\n", style="white")
            platform_info.append("    ", style="white")
            platform_info.append("Uses OpenShift Routes for external access\n", style="dim white")
            platform_info.append("    ", style="white")
            platform_info.append("Built-in ingress controller and routing\n\n", style="dim white")
            platform_info.append("  • ", style="cyan")
            platform_info.append("CNCF", style="bold green")
            platform_info.append(" - Cloud Native Computing Foundation (Standard Kubernetes)\n", style="white")
            platform_info.append("    ", style="white")
            platform_info.append("Requires ingress controller configuration\n", style="dim white")
            platform_info.append("    ", style="white")
            platform_info.append("Supports various ingress implementations\n\n", style="dim white")
            platform_info.append("💡 Note: ", style="bold yellow")
            platform_info.append("OCP automatically creates routes; CNCF requires ingress setup.", style="white")
            
            print(Panel(
                platform_info,
                title="[bold white]Platform Configuration[/bold white]",
                border_style="cyan",
                padding=(1, 2)
            ))
            print()
            
            result = questionary.select(
                "Select a Platform Type:",
                choices=[
                    questionary.Choice("OCP", value=1),
                    questionary.Choice("CNCF", value=2)
                ],
                style=Style([
                    ('qmark', 'fg:cyan bold'),
                    ('question', 'bold'),
                    ('answer', 'fg:cyan bold'),
                    ('pointer', 'fg:cyan bold'),
                    ('highlighted', 'fg:cyan'),
                    ('selected', 'fg:green bold')
                ])
            ).ask()
            
            if result is None:
                print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                sys.exit(0)

            self._platform = self.Platform(result).name

            if self._platform == "other":
                # Enhanced ingress prompt for CNCF platforms
                ingress_info = Text()
                ingress_info.append("🌐 Ingress Configuration for CNCF Platform\n\n", style="bold cyan")
                ingress_info.append("Ingress provides external HTTP/HTTPS access to services in your cluster.\n\n", style="white")
                ingress_info.append("What Ingress Provides:\n", style="bold yellow")
                ingress_info.append("  ✓ Single entry point for external traffic\n", style="green")
                ingress_info.append("  ✓ SSL/TLS termination\n", style="green")
                ingress_info.append("  ✓ Name-based virtual hosting\n", style="green")
                ingress_info.append("  ✓ Load balancing across pods\n\n", style="green")
                ingress_info.append("Requirements:\n", style="bold yellow")
                ingress_info.append("  • Ingress controller must be installed (NGINX, Traefik, etc.)\n", style="white")
                ingress_info.append("  • DNS configuration for ingress hostnames\n", style="white")
                ingress_info.append("  • SSL certificates for HTTPS access\n\n", style="white")
                ingress_info.append("💡 Recommendation: ", style="bold yellow")
                ingress_info.append("Enable for production deployments requiring external access.", style="white")
                
                print(Panel(
                    ingress_info,
                    title="[bold white]External Access Configuration[/bold white]",
                    border_style="cyan",
                    padding=(1, 2)
                ))
                print()
                
                self._ingress = questionary.confirm(
                    "Do you want to enable ingress creation?",
                    default=False,
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                    ])
                ).ask()
                
                if self._ingress is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)


        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_platform_ingress function -  {str(e)}")

    # Create a function to gather idp_number from user
    def collect_idp_number(self):
        try:
            # Check if we have migrated IDP settings from FNCMCluster CR
            if hasattr(self, '_fncm_migration_settings') and self._fncm_migration_settings:
                idp_config = self._fncm_migration_settings.get('idp_config', {})
                if idp_config and idp_config.get('discovery_url'):
                    # Use migrated IDP configuration
                    self._idp_number = 1
                    self._ssl_directory_list.append("idp")
                    print(f"\n[green]✓ Using IDP configuration from Content deployment[/green]")
                    return
            
            if self._auth_type == "SCIM_IDP":
                self._idp_number = 1
                self._scim_number = 1
                self._ssl_directory_list.append("scim")
            else:
                # Enhanced IDP configuration panel
                idp_info = Text()
                idp_info.append("🔐 Identity Provider Configuration\n\n", style="bold cyan")
                idp_info.append("Configure Identity Providers (IDP) for single sign-on authentication using OpenID Connect discovery or manual endpoint configuration.\n\n", style="white")

                idp_info.append("Common Scenarios:\n", style="bold yellow")
                idp_info.append("  • ", style="white")
                idp_info.append("Single IDP", style="bold green")
                idp_info.append(" - One provider such as IBM Verify, Azure AD, Okta, or Keycloak\n", style="white")
                idp_info.append("  • ", style="white")
                idp_info.append("Multiple IDPs", style="bold green")
                idp_info.append(" - Separate providers for different tenants, user populations, or environments\n\n", style="white")

                idp_info.append("💡 Tip: ", style="bold yellow")
                idp_info.append("Most deployments use a single IDP. Configure multiple only when distinct authentication providers are required.", style="white")

                print(Panel(
                    idp_info,
                    title="[bold white]Identity Provider (IDP) Configuration[/bold white]",
                    border_style="cyan",
                    padding=(1, 2)
                ))
                print()

                while True:
                    result_str = questionary.text(
                        "How many IDP's do you want to configure?",
                        default="1",
                        validate=lambda text: text.isdigit() and int(text) >= 1,
                        style=Style([
                            ('qmark', 'fg:cyan bold'),
                            ('question', 'bold'),
                            ('answer', 'fg:cyan bold'),
                        ])
                    ).ask()

                    if result_str is None:
                        print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                        sys.exit(0)

                    self._idp_number = int(result_str)
                    break
        except Exception as e:
            self._logger.exception(
                f'Exception from gather script in collect_idp_number function -  {str(e)}')

    # Create a function to gather idp_number from user
    def collect_idp_discovery(self):
        try:
            # Check if we have migrated IDP settings from FNCMCluster CR
            if hasattr(self, '_fncm_migration_settings') and self._fncm_migration_settings:
                idp_config = self._fncm_migration_settings.get('idp_config', {})
                if idp_config and idp_config.get('discovery_url'):
                    # Use migrated IDP configuration - create Idp object with migrated settings
                    idp_obj = self.Idp(
                        discovery_enabled=True,
                        idp_id="idp",
                        discovery_url=idp_config.get('discovery_url', '')
                    )
                    
                    # Parse the discovery URL to extract all endpoints
                    idp_obj.parse_discovery_url()
                    
                    # Set client credentials if available
                    if idp_config.get('client_id') and idp_config['client_id'] != '<From Secret>':
                        idp_obj._client_id = idp_config['client_id']
                    if idp_config.get('client_secret') and idp_config['client_secret'] != '<From Secret>':
                        idp_obj._client_secret = idp_config['client_secret']
                    
                    self._idp_info.append(idp_obj)
                    print(f"[green]  Discovery URL: {idp_config.get('discovery_url', '')}[/green]")
                    if idp_config.get('client_id') and idp_config['client_id'] != '<From Secret>':
                        print(f"[green]  Client ID: {idp_config.get('client_id', '')}[/green]")
                    return
            
            for i in range(self._idp_number):
                if i == 0:
                    idp_id = "idp"
                else:
                    idp_id = f"idp{i + 1}"

                self._ssl_directory_list.append(idp_id)

                print()
                print(Panel(
                    Text(f"Configuring identity provider: {idp_id}", style="bold white"),
                    title="[bold white]Identity Provider[/bold white]",
                    border_style="cyan",
                    padding=(0, 2)
                ))

                while True:
                    print()
                    # Enhanced IDP discovery prompt
                    idp_discovery_info = Text()
                    idp_discovery_info.append("🔍 Identity Provider Discovery\n\n", style="bold cyan")
                    idp_discovery_info.append("OpenID Connect discovery automates IDP configuration.\n\n", style="white")
                    idp_discovery_info.append("With Discovery:\n", style="bold yellow")
                    idp_discovery_info.append("  ✓ Automatic endpoint configuration\n", style="green")
                    idp_discovery_info.append("  ✓ Simplified setup process\n", style="green")
                    idp_discovery_info.append("  ✓ Reduced configuration errors\n\n", style="green")
                    idp_discovery_info.append("💡 Note: ", style="bold yellow")
                    idp_discovery_info.append("Discovery URLs typically end with '/.well-known/openid-configuration'", style="white")
                    
                    print(Panel(
                        idp_discovery_info,
                        title="[bold white]IDP Discovery Configuration[/bold white]",
                        border_style="cyan",
                        padding=(1, 2)
                    ))
                    print()
                    
                    discovery_enabled = questionary.confirm(
                        "Does this IDP support discovery?",
                        default=False,
                        style=Style([
                            ('qmark', 'fg:cyan bold'),
                            ('question', 'bold'),
                            ('answer', 'fg:cyan bold'),
                        ])
                    ).ask()
                    
                    if discovery_enabled is None:
                        print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                        sys.exit(0)

                    if discovery_enabled:
                        print()
                        url = questionary.text(
                            "Enter a valid URL for the IDP discovery endpoint:",
                            style=Style([
                                ('qmark', 'fg:cyan bold'),
                                ('question', 'bold'),
                                ('answer', 'fg:cyan bold'),
                            ])
                        ).ask()
                        
                        if url is None:
                            print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                            sys.exit(0)

                        if self.check_discovery_url(url):
                            idp = self.Idp(discovery_enabled, idp_id, url)
                            idp.parse_discovery_url()
                            self._idp_info.append(idp)
                            break
                        else:
                            print("\n[prompt.invalid]Discovery URL is invalid")
                            print(
                                '\n[prompt.invalid]Make sure your discovery URL ends with ".well-known/openid-configuration"')
                    else:
                        idp = self.Idp(discovery_enabled, idp_id)
                        self._idp_info.append(idp)
                        break



        except Exception as e:
            self._logger.exception(
                f'Exception from gather script in collect_idp function -  {str(e)}')

    # Create a function to gather ldap_number from user
    def collect_ldap_number(self):

        try:
            # Enhanced LDAP configuration panel
            ldap_info = Text()
            ldap_info.append("🔐 LDAP Directory Configuration\n\n", style="bold cyan")
            ldap_info.append("Configure LDAP (Lightweight Directory Access Protocol) servers for user authentication and authorization.\n\n", style="white")
            
            ldap_info.append("Common Scenarios:\n", style="bold yellow")
            ldap_info.append("  • ", style="white")
            ldap_info.append("Single LDAP", style="bold green")
            ldap_info.append(" - One directory server for all users\n", style="white")
            ldap_info.append("  • ", style="white")
            ldap_info.append("Multiple LDAPs", style="bold green")
            ldap_info.append(" - Separate directories for different departments or regions\n\n", style="white")
            
            ldap_info.append("💡 Tip: ", style="bold yellow")
            ldap_info.append("Most deployments use a single LDAP server. Configure multiple only if you have separate directory services.", style="white")
            
            print(Panel(
                ldap_info,
                title="[bold white]LDAP Server Configuration[/bold white]",
                border_style="cyan",
                padding=(1, 2)
            ))
            print()
            
            while True:
                result_str = questionary.text(
                    "How many LDAP's do you want to configure?",
                    default="1",
                    validate=lambda text: text.isdigit() and int(text) >= 1,
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                    ])
                ).ask()
                
                if result_str is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                    
                self._ldap_number = int(result_str)
                break
        except Exception as e:
            self._logger.exception(
                f'Exception from gather script in object_store_menu function -  {str(e)}')

    # Create a function to gather ldap_type from the user
    def collect_ldap_type(self):
        # loop through the number of ldaps and collect the type
        try:
            for i in range(self._ldap_number):
                if i == 0:
                    ldap_id = "ldap"
                else:
                    ldap_id = f"ldap{i + 1}"

                print()
                
                # Enhanced LDAP ID panel
                ldap_id_info = Text()
                ldap_id_info.append(f"🔑 LDAP Configuration: ", style="bold cyan")
                ldap_id_info.append(f"{ldap_id}\n\n", style="bold green")
                ldap_id_info.append("Select your directory server type to configure the appropriate connection settings.\n\n", style="white")
                
                ldap_id_info.append("💡 Note: ", style="bold yellow")
                ldap_id_info.append("Each LDAP type has specific configuration requirements and connection parameters.", style="white")
                
                print(Panel(
                    ldap_id_info,
                    title=f"[bold white]Directory Server: {ldap_id}[/bold white]",
                    border_style="cyan",
                    padding=(1, 2)
                ))
                print()
                
                result = questionary.select(
                    "Select a LDAP Type:",
                    choices=[
                        questionary.Choice("Microsoft Active Directory", value=1),
                        questionary.Choice("IBM Security Verify Directory", value=2),
                        questionary.Choice("NetIQ eDirectory", value=3),
                        questionary.Choice("Oracle Internet Directory", value=4),
                        questionary.Choice("Oracle Directory Server Enterprise Edition", value=5),
                        questionary.Choice("Oracle Unified Directory", value=6),
                        questionary.Choice("CA eTrust", value=7)
                    ],
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                        ('pointer', 'fg:cyan bold'),
                        ('highlighted', 'fg:cyan'),
                        ('selected', 'fg:green bold')
                    ])
                ).ask()
                
                if result is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)

                ldap_type = self.Ldap.ldapTypes(result)
                # Enhanced LDAP SSL prompt
                ldap_ssl_info = Text()
                ldap_ssl_info.append("🔒 LDAP SSL/TLS Configuration\n\n", style="bold cyan")
                ldap_ssl_info.append("Secure LDAP connections with SSL/TLS encryption.\n\n", style="white")
                ldap_ssl_info.append("Benefits:\n", style="bold yellow")
                ldap_ssl_info.append("  ✓ Encrypted authentication credentials\n", style="green")
                ldap_ssl_info.append("  ✓ Protected directory queries\n", style="green")
                ldap_ssl_info.append("  ✓ Compliance with security standards\n\n", style="green")
                ldap_ssl_info.append("💡 Recommended: ", style="bold yellow")
                ldap_ssl_info.append("Always enable SSL for production environments.", style="white")
                
                print(Panel(
                    ldap_ssl_info,
                    title="[bold white]LDAP Security Configuration[/bold white]",
                    border_style="cyan",
                    padding=(1, 2)
                ))
                print()
                
                ldap_ssl = questionary.confirm(
                    "Do you want to enable SSL for this LDAP?",
                    default=False,
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                    ])
                ).ask()
                
                if ldap_ssl is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)

                if ldap_ssl:
                    self._ssl_directory_list.append(ldap_id)

                # add the ldap type and ssl to the list
                self._ldap_info.append((self.Ldap(ldap_type, ldap_ssl, ldap_id)))

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in ldap_menu function -  {str(e)}")

    # Create a function to print all the deployment options
    def print_deployment_options(self):
        print(f"Optional Components: {self.optional_components}")

        # Print all ldap info
        for i in range(self._ldap_number):
            print(f"LDAP {i + 1}:")
            self._ldap_info[i].display()
        print(f"Database Type: {self.db_type}")
        print(f"OS Number: {self.os_number}")
        print(f"License Model: {self.license_model}")
        print(f"Content Initialize: {self.content_initialize}")
        print(f"Content Verification: {self.content_verification}")
        print(f"Platform: {self.platform}")
        print(f"Ingress: {self.ingress}")
        print("")

    # Create a function to return all the deployment options as a dictionary
    def to_dict(self):

        ldap_list = []
        for i in range(self._ldap_number):
            ldap_list.append(self._ldap_info[i].to_dict())

        idp_list = []
        for i in range(self._idp_number):
            idp_list.append(self._idp_info[i].to_dict())

        return {
            "optional_components": self.optional_components,
            "ldap_info": ldap_list,
            "idp_info": idp_list,
            "db_type": self.db_type,
            "os_number": self.os_number,
            "db_ssl": self.db_ssl,
            "auth_type": self.auth_type,
            "np_support": self.np_support,
            "fips_support": self.fips_support,
            "egress_support": self.egress_support,
            "license_model": self.license_model,
            "ccx_version": self.ccx_version,
            "sendmail_support": self.sendmail_support,
            "content_initialize": self.content_initialize,
            "content_verification": self.content_verification,
            "platform": self.platform,
            "ingress": self.ingress,
            "watsonx_type": self.watsonx_type,
            "model_provider_count": self.model_provider_count,
            "model_providers": self.model_providers,
        }


