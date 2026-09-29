###############################################################################
#
# Licensed Materials - Property of IBM
#
# (C) Copyright IBM Corp. 2023. All Rights Reserved.
#
# US Government Users Restricted Rights - Use, duplication or
# disclosure restricted by GSA ADP Schedule Contract with IBM Corp.
#
###############################################################################

# Create a class to silently set variables from config file
#  - the class should have a constructor that takes the filename as an argument
#  - the class should have a method to parse the file

import inspect
import os

import toml
import typer

from ..gather.gather_prerequisites import GatherPrereqOptions, _CP4BA_PREMIUM_ADDON_ENABLED
from ..utilities.prerequisites_utilites import gather_var


# create a class to silently set variables from config file
class SilentGatherPrereqOptions(GatherPrereqOptions):
    # Default path for env file
    _envfile_path = os.path.join(os.getcwd(), "silent_config",
                                 "silent_install_prerequisites.toml")
    _error_list = []

    def __init__(self, logger, envfile_path=_envfile_path, tls_verify=True):

        super().__init__(logger, console=None)

        self._envfile_path = envfile_path
        self._tls_verify = tls_verify

        try:
            self._envfile = toml.loads(open(self._envfile_path, encoding="utf-8").read())
        except Exception as e:
            self._logger.exception(
                f"Exception from silent.py script - error loading {self._envfile_path} file -  {str(e)}")

    def parse_envfile(self):
        """Run the full silent gather sequence.

        Mirrors the explicit call order used by prerequisites.py gather() so that
        tests and tooling that call this method get identical behaviour.
        If you update the call sequence in prerequisites.py, update this method too.
        """
        try:
            self.silent_version({})
            self.silent_namespace()
            self.silent_auth_type()
            self.silent_optional_components()
            self.silent_operators()

            if self.has_ai_services_operator():
                self.silent_model_providers()

            if self.has_content_operator() and self.auth_type in ("LDAP", "LDAP_IDP"):
                self.silent_ldap()

            if self.auth_type in ("LDAP_IDP", "SCIM_IDP"):
                self.silent_idp()

            self.silent_ingress()
            self.silent_fips_support()
            self.silent_network_policies_support()
            self.silent_secret_management()
            self.silent_sendmail_support()
            self.silent_icc_support()
            self.silent_tm_support()
            self.silent_db()
            self.silent_license_model()
            self.silent_initverify()
            self.silent_model_gateway_infra()
            self.error_check()

        except Exception as e:
            self._logger.exception(
                f"Exception from silent.py script in {inspect.currentframe().f_code.co_name} function -  {str(e)}")

    def error_check(self):
        if len(self._error_list) > 0:
            for error in self._error_list:
                self._logger.warning(error)

            raise typer.Exit(code=1)
        return len(self._error_list)

    def silent_version(self, version_data):
        self._logger.info(f"Version data from config file: {version_data}")
        # APP_VERSION drives CR template directory selection (e.g. 26.0.0)
        app_version = version_data.get("APP_VERSION", version_data.get("VERSION", '26.0.0'))
        if app_version:
            self._ccx_version = app_version.split('-')[0]
        self._logger.info(f"CR template version (APP_VERSION): {self._ccx_version}")

    def silent_sendmail_support(self):
        sendmail_support = gather_var(key="SENDMAIL_SUPPORT", _logger=self._logger, _envfile=self._envfile,
                                      _error_list=self._error_list)
        if sendmail_support is not None:
            self._sendmail_support = sendmail_support
        else:
            self._sendmail_support = False
        if "ban" not in self._optional_components:
            self._sendmail_support = False


    def silent_network_policies_support(self):
        np_support = gather_var(key="GENERATE_NETWORK_POLICIES", _logger=self._logger, _envfile=self._envfile,
                                _error_list=self._error_list)
        if np_support is not None:
            self._np_support = np_support
        else:
            self._np_support = False
        self._egress_support = False

        self._logger.info(f"Egress Support: {self._egress_support}, Network Policies Support: {self._np_support}")

    def silent_secret_management(self):
        """Parse SECRET_MANAGEMENT from the silent config file.

        Valid TOML values: "kubernetes" (default) or "vault".
        When "vault" is chosen the user must configure VAULT_URL (and optionally
        VAULT_ROLE / VAULT_PATH) in the generated ccx-deployment.toml property
        file before running generate mode — exactly as in interactive mode.
        """
        raw = self._envfile.get("SECRET_MANAGEMENT", "kubernetes")
        if not isinstance(raw, str):
            self._error_list.append(
                f"ERROR with SECRET_MANAGEMENT in {self._envfile_path}: "
                "value must be a string — valid values are \"kubernetes\" or \"vault\""
            )
            return

        normalised = raw.strip().lower()
        if normalised not in ("kubernetes", "vault"):
            self._error_list.append(
                f"ERROR with SECRET_MANAGEMENT in {self._envfile_path}: "
                f"'{raw}' is not a valid value — use \"kubernetes\" or \"vault\""
            )
            return

        self._vault_enabled = (normalised == "vault")
        self._vault_url = None  # Populated later from the ccx-deployment.toml property file
        self._logger.info(f"Secret management: {'HashiCorp Vault' if self._vault_enabled else 'Kubernetes Secrets'}")

        if self._vault_enabled:
            # Vault is only supported by Content Operator and AI Services Operator.
            # MG, WDU, CNPG/Redis, and UMS have no Vault code path.
            unsupported = []
            if self.has_model_gateway_operator():
                unsupported.append("Model Gateway")
            if self.has_wdu_operator():
                unsupported.append("Enhanced Extraction (WDU)")
            unsupported.extend(["IBM-managed CNPG / Redis", "Usage Metering (UMS)"])
            self._logger.warning(
                "HashiCorp Vault is only supported by the Content Operator and AI Services Operator. "
                "Not supported: " + ", ".join(unsupported)
            )

    def silent_fips_support(self):
        fips_support = gather_var(key="FIPS_SUPPORT", _logger=self._logger, _envfile=self._envfile,
                                  _error_list=self._error_list)
        if fips_support is not None:
            self._fips_support = fips_support
        else:
            self._fips_support = False

    def silent_icc_support(self):
        icc_support = gather_var(key="ICC_SUPPORT", _logger=self._logger, _envfile=self._envfile,
                                 _error_list=self._error_list)
        if icc_support is not None:
            self._icc_support = icc_support
        else:
            self._icc_support = False
        if "css" not in self._optional_components:
            self._icc_support = False

    def silent_tm_support(self):
        tm_support = gather_var(key="TM_CUSTOM_GROUP_SUPPORT", _logger=self._logger, _envfile=self._envfile,
                                _error_list=self._error_list)
        if tm_support is not None:
            self._tm_custom_groups = tm_support
        else:
            self._tm_custom_groups = False
        if "tm" not in self._optional_components:
            self._tm_custom_groups = False

    def silent_optional_components(self):

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
        

        if cpe is not None and cpe is True:
            self._optional_components.add("cpe")
        if graphql is not None and graphql is True:
            self._optional_components.add("graphql")
        if ban is not None and ban is True:
            self._optional_components.add("ban")
        if cmis is not None and cmis is True:
            self._optional_components.add("cmis")
        if css is not None and css is True:
            self._optional_components.add("css")
        if tm is not None and tm is True:
            self._optional_components.add("tm")
        if es is not None and es is True:
            self._optional_components.add("es")
        if ier is not None and ier is True:
            self._optional_components.add("ier")
        if iccsap is not None and iccsap is True:
            self._optional_components.add("iccsap")
        if ccxmo is not None and ccxmo is True:
            self._optional_components.add("ccxmo")

        if (
            "graphql" in self._optional_components or "cmis" in self._optional_components) and "cpe" not in self._optional_components:
            print("CPE is required to deploy graphql or CMIS and will be added as a component to this deployment")
            self._optional_components.add("cpe")
        if "tm" in self._optional_components and "ban" not in self._optional_components:
            print(
                "Navigator is required to deploy Task Manager and will be added as a component to this deployment")
            self._optional_components.add("ban")
        if "es" in self._optional_components and not {"ban", "cpe"}.issubset(self._optional_components):
            print(
                "Navigator and CPE is required to deploy External Share and will be added as a component to this deployment")
            self._optional_components.add("ban")
            self._optional_components.add("cpe")
        if "ier" in self._optional_components and not {"ban", "cpe"}.issubset(self._optional_components):
            print(
                "Navigator and CPE is required to deploy Enterprise Records and will be added as a component to this deployment")
            self._optional_components.add("ban")
            self._optional_components.add("cpe")
        if "iccsap" in self._optional_components and not {"ban", "cpe"}.issubset(self._optional_components):
            print(
                "Navigator and CPE is required to deploy Content Collector for SAP and will be added as a component to this deployment")
            self._optional_components.add("ban")
            self._optional_components.add("cpe")
        if "ccxmo" in self._optional_components and not {"ban"}.issubset(self._optional_components):
            print(
                "Navigator is required to deploy Content Cortex for Microsoft Office and will be added as a component to this deployment")
            self._optional_components.add("ban")

    def silent_ldap(self):
        self._ldap_number = self.__find_ldap_count()
        for i in range(self._ldap_number):
            ldap_id = f"LDAP{str(i + 1) if i > 0 else ''}"
            ldap_type = gather_var(key="LDAP_TYPE", section_header=ldap_id, valid_values=[1, 2, 3, 4, 5, 6, 7],
                                   _logger=self._logger, _envfile=self._envfile, _error_list=self._error_list)
            ldap_ssl = gather_var(key="LDAP_SSL_ENABLE", section_header=ldap_id, _logger=self._logger,
                                  _envfile=self._envfile, _error_list=self._error_list)
            if ldap_ssl:
                self._ssl_directory_list.append(ldap_id.lower())
            if ldap_type is not None and ldap_ssl is not None:
                self._ldap_info.append((self.Ldap(self.Ldap.ldapTypes(ldap_type), ldap_ssl, ldap_id)))

    def silent_idp(self):
        self._idp_number = self.__find_idp_count()

        if self._auth_type == "SCIM_IDP":
            if self._idp_number == 0:
                self._error_list.append("Authentication type is set to SCIM_IDP but no IDP configuration found.")
            elif self._idp_number > 1:
                self._error_list.append("Multiple IDP configurations found. Only one IDP configuration is allowed when Authentication type is set to SCIM_IDP.")

            # Add SCIM folder for SSL if not already present
            if "scim" not in self._ssl_directory_list:
                self._ssl_directory_list.append("scim")

        for i in range(self._idp_number):
            idp_id = f"IDP{str(i + 1) if i > 0 else ''}"
            idp_discovery_enabled = gather_var(key="DISCOVERY_ENABLED", section_header=idp_id, _logger=self._logger,
                                               _envfile=self._envfile, _error_list=self._error_list)
            if idp_discovery_enabled:
                idp_discovery_url = gather_var(key="DISCOVERY_URL", section_header=idp_id, valid_values="url",
                                               _logger=self._logger, _envfile=self._envfile,
                                               _error_list=self._error_list)
            else:
                idp_discovery_url = None

            if idp_discovery_enabled is not None:
                idp = self.Idp(idp_discovery_enabled, idp_id, idp_discovery_url)
                idp.parse_discovery_url()
                self._idp_info.append(idp)
                self._ssl_directory_list.append(idp_id.lower())

    def silent_auth_type(self):
        auth_type = gather_var(key="AUTHENTICATION", valid_values=[1, 2, 3], _logger=self._logger,
                               _envfile=self._envfile, _error_list=self._error_list)
        if auth_type is not None:
            self._auth_type = self.AuthType(auth_type).name

    def silent_db(self):

        db_type = gather_var(key="DATABASE_TYPE", valid_values=[1, 2, 3, 4, 5, 6, 7], _logger=self._logger,
                        _envfile=self._envfile, _error_list=self._error_list)
        if db_type is not None:
            # self.db_type = self.__gather_var("DATABASE.TYPE",["db2", "db2HADR", "oracle", "sqlserver", "postgresql"])
            self.db_type = self.DatabaseType(db_type).name

        os_number = gather_var(key="DATABASE_OBJECT_STORE_COUNT", valid_values=(1, float('inf')), _logger=self._logger,
                               _envfile=self._envfile, _error_list=self._error_list)
        # self.db_ssl = self.__gather_var("DATABASE.SSL_ENABLE",["True","False"]) in ["True"]
        if os_number is not None:
            self.os_number = os_number

        db_ssl = gather_var(key="DATABASE_SSL_ENABLE", _logger=self._logger, _envfile=self._envfile,
                            _error_list=self._error_list)
        if db_ssl:
            self._db_ssl = db_ssl
            if "cpe" in self._optional_components:
                self._ssl_directory_list.append("gcd")
                self._ssl_directory_list.append("os")
                for i in range(1, os_number):
                    self._ssl_directory_list.append(f"os{i + 1}")
            if "ban" in self._optional_components:
                self._ssl_directory_list.append("icn")
        
        # Add GraphQL SSL folder only if AI Services operator is selected WITHOUT Content operator
        # When both are deployed together, they share the same GraphQL endpoint
        if self.has_ai_services_operator() and not self.has_content_operator():
            self._ssl_directory_list.append("graphql")

    def silent_license_model(self):
        # Support both old format (ESS.AU) and new format (CCx.Ess.AU)
        # Multiple metrics can be specified as comma-separated values for Essentials and Premium
        valid_values = [
            # Old format (for backward compatibility)
            "ESS.AU", "ESS.EP", "ESS.U",
            # New Content Cortex Essentials format
            "CCx.Ess.AU", "CCx.Ess.EP", "CCx.EE",
            # New Content Cortex Restricted format
            "CCx.AR", "CCx.PR", "CCx.ER",
            # New Content Cortex Premium format
            "CCx.Pre.AU", "CCx.Pre.EP", "CCx.Pre.PE",
            # CP4BA format
            "CP4BA.NonProd", "CP4BA.Prod", "CP4BA.User",
            # DBACLD-261229: CP4BA Premium Add-On metrics — only valid when gate is on (~Oct 9)
            *( ["CCx.CP4BA.NonProd.Premium", "CCx.CP4BA.Prod.Premium", "CCx.CP4BA.User.Premium"]
               if _CP4BA_PREMIUM_ADDON_ENABLED else [] ),
        ]

        license_model_raw = gather_var(key="LICENSE", valid_values=None,
                                       _logger=self._logger,
                                       _envfile=self._envfile, _error_list=self._error_list)

        if license_model_raw is not None:
            # Map old format to new format for consistency
            license_mapping = {
                "ESS.AU": "CCx.Ess.AU",
                "ESS.EP": "CCx.Ess.EP",
                "ESS.U": "CCx.Ess.AU",  # Default ESS.U to AU
                "ESS.AR": "CCx.AR",
                "ESS.PR": "CCx.PR",
                "ESS.EE": "CCx.EE",
                "ESS.ER": "CCx.ER",
                "Premium.EE": "CCx.Pre.PE",  # Legacy alias used in older config files
            }
            # Support comma-separated multi-metric values (Essentials and Premium)
            tokens = [t.strip() for t in license_model_raw.split(",")]
            mapped_tokens = [license_mapping.get(t, t) for t in tokens]
            # Validate each token against valid_values
            invalid = [t for t in mapped_tokens if t not in valid_values]
            if invalid:
                self._error_list.append(
                    f"LICENSE contains invalid metric(s): {', '.join(invalid)}. "
                    f"Valid values: {', '.join(valid_values)}"
                )
                return
            self._license_model = ",".join(mapped_tokens)

            # DBACLD-261229: mutual-exclusivity check — only relevant when gate is on
            if _CP4BA_PREMIUM_ADDON_ENABLED:
                cp4ba_tokens = {"CP4BA.NonProd", "CP4BA.Prod", "CP4BA.User"}
                cp4ba_premium_tokens = {"CCx.CP4BA.NonProd.Premium", "CCx.CP4BA.Prod.Premium", "CCx.CP4BA.User.Premium"}
                has_cp4ba = bool(set(mapped_tokens) & cp4ba_tokens)
                has_cp4ba_premium = bool(set(mapped_tokens) & cp4ba_premium_tokens)

                if has_cp4ba and has_cp4ba_premium:
                    self._error_list.append(
                        "LICENSE cannot mix CP4BA base metrics (CP4BA.NonProd, CP4BA.Prod, CP4BA.User) "
                        "with CP4BA Premium Add-On metrics (CCx.CP4BA.NonProd.Premium, CCx.CP4BA.Prod.Premium, "
                        "CCx.CP4BA.User.Premium). Choose one group or the other."
                    )
                    return

    # Function to read namespace information from toml file
    def silent_namespace(self):
        namespace = self._envfile.get("NAMESPACE")
        super().collect_namespace(namespace)
        self._namespace = super().namespace

    def silent_ingress(self):
        platform = gather_var(key="PLATFORM", _logger=self._logger, _envfile=self._envfile,
                              _error_list=self._error_list, valid_values=["OCP", "CNCF"])
        if platform is not None:
            # Map user-facing strings to the internal Platform enum
            platform_map = {"OCP": 1, "CNCF": 2}
            platform_int = platform_map.get(str(platform).upper())
            if platform_int is not None:
                self._platform = self.Platform(platform_int).name
            else:
                self._error_list.append(
                    f"Invalid PLATFORM value '{platform}'. Valid values are: OCP, CNCF")

        ingress = gather_var(key="INGRESS", _logger=self._logger, _envfile=self._envfile,
                             _error_list=self._error_list)
        if ingress is not None:
            # Only set ingress for CNCF (stored as "other"); OCP always uses Routes
            if self._platform == "other":
                self._ingress = ingress
            else:
                self._ingress = False
        self._logger.info(f"Platform: {self._platform}, Ingress: {self._ingress}")

    def silent_operators(self):
        """Populate _selected_operators from DEPLOY_* flags in the prereqs toml.

        Uses display name strings that match has_model_gateway_operator() /
        has_wdu_operator() etc. in GatherPrereqOptions.
        """
        # Content and AI Services are always deployed via prerequisites
        self._selected_operators = ["Content", "AI Services"]

        deploy_model_gateway = self._envfile.get("DEPLOY_MODEL_GATEWAY", False)
        deploy_enhanced_extraction = self._envfile.get("DEPLOY_ENHANCED_EXTRACTION", False)

        if deploy_enhanced_extraction:
            self._selected_operators.append("Enhanced Extraction (WDU)")
        if deploy_model_gateway:
            self._selected_operators.append("Model Gateway")

        self._logger.info(f"Silent operators: {self._selected_operators}")

    def silent_model_providers(self):
        """Parse [PROVIDER_N] sections from the silent config and populate _model_providers.

        When Model Gateway is already selected as an operator, silent_model_gateway_infra()
        handles provider auto-selection — this method is a no-op in that case.

        For external providers (WatsonX SaaS, WLE, Microsoft Foundry), each
        [PROVIDER_N] section must contain a PROVIDER_TYPE key with one of:
          WATSONX_SAAS        — IBM WatsonX.ai SaaS
          WATSONX_LWE         — IBM WatsonX.ai Lightweight Engine
          MICROSOFT_FOUNDRY   — Microsoft Azure AI Foundry

        Multiple providers are supported via [PROVIDER_1], [PROVIDER_2], etc.
        All other fields in the section (API_KEY, MODEL, etc.) are written into
        the generated property file — they are not consumed here.
        """
        # Already handled by silent_model_gateway_infra() — skip.
        if self.has_model_gateway_operator():
            return

        # Not deploying AI Services — nothing to do.
        if not self.has_ai_services_operator():
            return

        valid_types = {
            "WATSONX_SAAS": self.ModelProviderType.WATSONX_SAAS.value,
            "WATSONX_LWE": self.ModelProviderType.WATSONX_LWE.value,
            "MICROSOFT_FOUNDRY": self.ModelProviderType.MICROSOFT_FOUNDRY.value,
        }

        _max_providers = 5
        providers = []
        provider_num = 1
        while True:
            # Check the section exists before enforcing the limit so that
            # PROVIDER_5 is accepted but PROVIDER_6 is rejected.
            section_key = f"PROVIDER_{provider_num}"
            section = self._envfile.get(section_key, {})
            if not section:
                break

            if provider_num > _max_providers:
                self._error_list.append(
                    f"ERROR in {self._envfile_path}: a maximum of {_max_providers} providers "
                    f"is supported — remove [{section_key}] and above"
                )
                break

            raw_type = section.get("PROVIDER_TYPE", "")
            if not raw_type:
                self._error_list.append(
                    f"ERROR with {section_key}.PROVIDER_TYPE in {self._envfile_path}: "
                    "field is required — valid values: WATSONX_SAAS, WATSONX_LWE, MICROSOFT_FOUNDRY"
                )
                break

            normalised = str(raw_type).strip().upper()
            if normalised not in valid_types:
                self._error_list.append(
                    f"ERROR with {section_key}.PROVIDER_TYPE in {self._envfile_path}: "
                    f"'{raw_type}' is not valid — valid values: WATSONX_SAAS, WATSONX_LWE, MICROSOFT_FOUNDRY"
                )
                break

            providers.append({
                "provider_number": provider_num,
                "provider_type": normalised,
                "provider_type_value": valid_types[normalised],
            })
            self._logger.info(f"Silent mode: Provider {provider_num} = {normalised}")
            provider_num += 1

        if not providers:
            self._error_list.append(
                f"ERROR in {self._envfile_path}: at least one [PROVIDER_1] section with a valid "
                "PROVIDER_TYPE is required when AI Services is deployed without Model Gateway"
            )
            return

        self._model_providers = providers
        self._model_provider_count = len(providers)

        # Set _watsonx_type from the first provider for backward compatibility
        first_type = providers[0]["provider_type"]
        if first_type == "WATSONX_SAAS":
            self._watsonx_type = self.WatsonXType.SAAS.name
        elif first_type == "WATSONX_LWE":
            self._watsonx_type = self.WatsonXType.LWE.name

        # Add SSL cert folders for LWE providers — same as interactive gather
        lwe_idx = 0
        for provider in providers:
            if provider["provider_type"] == "WATSONX_LWE":
                lwe_idx += 1
                suffix = f"-{lwe_idx}" if lwe_idx > 1 else ""
                folder = f"watsonx-onprem{suffix}"
                if folder not in self._ssl_directory_list:
                    self._ssl_directory_list.append(folder)
                    self._logger.info(f"Added SSL folder for LWE provider: {folder}")

        self._logger.info(f"Silent mode: {len(providers)} provider(s) configured: "
                          f"{[p['provider_type'] for p in providers]}")

    def silent_model_gateway_infra(self):
        """Read Model Gateway and WDU infrastructure settings from the prereqs toml.

        Reads [MODEL_GATEWAY] for MG CNPG + Redis flags and BLOCK_STORAGE_CLASSNAME,
        and [WDU] for WDU CNPG flag.
        Populates self._mg_use_ibm_cnpg, self._mg_use_ibm_redis, self._wdu_use_ibm_cnpg,
        and self._mg_block_storage_class so prerequisites.py can pass them to
        GenerateCNPGRedis for infrastructure CR generation.  Any combination is valid.

        Silent model-provider auto-selection: when Model Gateway operator is selected
        alongside AI Services, self._model_providers is pre-set to MODEL_GATEWAY=4 so
        no additional provider prompts are needed.
        """
        # --- Model Gateway provider auto-selection ---
        if self.has_model_gateway_operator() and self.has_ai_services_operator():
            self._model_providers = [{
                "provider_number": 1,
                "provider_type": "MODEL_GATEWAY",
                "provider_type_value": 4,
            }]
            self._model_provider_count = 1
            self._logger.info("Silent mode: Model Gateway auto-selected as AI Services provider")

        # --- Model Gateway infrastructure section ---
        if self.has_model_gateway_operator():
            mg_section = self._envfile.get("MODEL_GATEWAY", {})

            use_cnpg = mg_section.get("USE_IBM_CNPG", False)
            use_redis = mg_section.get("USE_IBM_REDIS", False)
            self._mg_use_ibm_cnpg = bool(use_cnpg)
            self._mg_use_ibm_redis = bool(use_redis)

            if self._mg_use_ibm_cnpg or self._mg_use_ibm_redis:
                # Read block storage class directly from [MODEL_GATEWAY] section.
                block_sc = mg_section.get("BLOCK_STORAGE_CLASSNAME", "")
                if not block_sc or block_sc == "<Required>":
                    self._error_list.append(
                        "MODEL_GATEWAY.BLOCK_STORAGE_CLASSNAME is required when "
                        "MODEL_GATEWAY.USE_IBM_CNPG = true or MODEL_GATEWAY.USE_IBM_REDIS = true"
                    )
                self._mg_block_storage_class = block_sc

            # PG SSL — only relevant for external postgres.
            # Falls back to db_ssl (Content DB answer) if not explicitly set.
            if not self._mg_use_ibm_cnpg:
                _db_ssl_fallback = getattr(self, "_db_ssl", False)
                raw_ssl = mg_section.get("MG_PG_SSL", _db_ssl_fallback)
                self._mg_pg_ssl = bool(raw_ssl)
                if self._mg_pg_ssl:
                    self._ssl_directory_list.append("model-gateway")
            else:
                self._mg_pg_ssl = False

            self._logger.info(
                f"Model Gateway infra — CNPG: IBM-managed={self._mg_use_ibm_cnpg}, "
                f"PG SSL: {self._mg_pg_ssl}, "
                f"Redis: IBM-managed={self._mg_use_ibm_redis}"
                + (f", Block Storage: {self._mg_block_storage_class}" if (self._mg_use_ibm_cnpg or self._mg_use_ibm_redis) else "")
            )

        # --- WDU section ---
        if self.has_wdu_operator():
            wdu_section = self._envfile.get("WDU", {})

            use_cnpg = wdu_section.get("USE_IBM_CNPG", False)
            self._wdu_use_ibm_cnpg = bool(use_cnpg)

            if self._wdu_use_ibm_cnpg:
                # Read block storage class directly from [WDU] section.
                block_sc = wdu_section.get("BLOCK_STORAGE_CLASSNAME", "")
                if not block_sc or block_sc == "<Required>":
                    self._error_list.append(
                        "WDU.BLOCK_STORAGE_CLASSNAME is required when WDU.USE_IBM_CNPG = true"
                    )
                self._wdu_block_storage_class = block_sc
                self._wdu_cnpg_instances = wdu_section.get("CNPG_INSTANCES", 1)
                self._wdu_cnpg_storage_size = wdu_section.get("CNPG_STORAGE_SIZE", "10Gi")

            # PG SSL — only relevant for external postgres.
            # Falls back to db_ssl (Content DB answer) if not explicitly set.
            if not self._wdu_use_ibm_cnpg:
                _db_ssl_fallback = getattr(self, "_db_ssl", False)
                raw_ssl = wdu_section.get("WDU_PG_SSL", _db_ssl_fallback)
                self._wdu_pg_ssl = bool(raw_ssl)
                if self._wdu_pg_ssl:
                    self._ssl_directory_list.append("wdu/pg_sess")
                    self._ssl_directory_list.append("wdu/pg_txn")
            else:
                self._wdu_pg_ssl = False

            # KVP with WatsonX AI — optional, defaults to false.
            self._wdu_enable_wxai = bool(wdu_section.get("ENABLE_WXAI", False))

            self._logger.info(
                f"WDU infra — CNPG: IBM-managed={self._wdu_use_ibm_cnpg}, "
                f"PG SSL: {self._wdu_pg_ssl}"
                + (f", Block Storage: {self._wdu_block_storage_class}" if self._wdu_use_ibm_cnpg else "")
                + f", WatsonX AI (KVP): {self._wdu_enable_wxai}"
            )

    def silent_initverify(self):
        content_initialize = gather_var(key="CONTENT_INIT", _logger=self._logger, _envfile=self._envfile,
                                        _error_list=self._error_list)
        if content_initialize is not None:
            self.content_initialize = content_initialize
        content_verification = gather_var(key="CONTENT_VERIFY", _logger=self._logger, _envfile=self._envfile,
                                          _error_list=self._error_list)
        if content_verification is not None:
            self.content_verification = content_verification
        if "cpe" not in self._optional_components:
            self.content_initialize = False
            self.content_verification = False

    # Return the count of ldap to use
    def __find_ldap_count(self):
        num_ldap = 0
        for key in self._envfile:
            # Parse the keys with more than 4 characters ie. LDAP2; LDAP3
            if "LDAP" in key:
                num_ldap += 1
        return num_ldap

    def __find_idp_count(self):
        num_idp = 0
        for key in self._envfile:
            # Parse the keys with more than 4 characters ie. IDP2; IDP3
            if "IDP" in key:
                num_idp += 1
        return num_idp


