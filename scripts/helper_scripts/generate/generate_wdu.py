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
WDU (Enhanced Extraction) Artifact Generator

Generates Kubernetes artifacts for IBM Content Cortex Watson Document Understanding:
- Custom Resource (CR) for CCXWDUServices
- Admin password secret (preserved but no longer called — no CRD field references it)
- PostgreSQL TLS secrets for session and transaction PgBouncer poolers (external PG only)
"""

import base64
import os
from logging import Logger
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ruamel.yaml import YAML, CommentedMap
from ruamel.yaml.scalarstring import SingleQuotedScalarString


class GenerateWDU:
    """
    Generator class for WDU (Enhanced Extraction) Kubernetes artifacts.

    Generates:
    - CCXWDUServices Custom Resource (CR)
    - Admin password secret
    """

    def __init__(
        self,
        wdu_properties: Dict,
        deployment_properties: Dict,
        namespace: str = "",
        logger: Optional[Logger] = None,
    ):
        self._logger = logger
        self._wdu_properties = wdu_properties
        self._deployment_properties = deployment_properties
        self._namespace = namespace

        self.ccx_version = self._deployment_properties.get("CCX_Version", "26.0.1")

        # Track generated files
        self._generated_files: List[Tuple[str, Path, int]] = []

        # Setup output paths
        self._generate_folder = Path.cwd() / "generatedFiles" / self._namespace
        self._generate_folder.mkdir(parents=True, exist_ok=True)

        self._secrets_folder = self._generate_folder / "secrets"
        self._secrets_folder.mkdir(parents=True, exist_ok=True)

        self._ssl_folder = self._generate_folder / "ssl"
        self._ssl_folder.mkdir(parents=True, exist_ok=True)

        self._configmaps_folder = self._generate_folder / "configmaps"
        self._configmaps_folder.mkdir(parents=True, exist_ok=True)

        # CR template path
        self._base_template = (
            Path.cwd()
            / "helper_scripts"
            / "generate"
            / "cr_templates"
            / self.ccx_version
            / "wdu"
            / "base.yaml"
        )

        # Output file paths
        self._generated_cr = self._generate_folder / "ibm_wdu_cr_production.yaml"
        self._generated_admin_secret = self._secrets_folder / "ibm-ccx-wdu-admin-secret.yaml"
        self._generated_configmap = self._configmaps_folder / "ibm-ccx-wdu-config.yaml"

        # YAML handler
        self._yaml = YAML()
        self._yaml.preserve_quotes = True
        self._yaml.representer.ignore_aliases = lambda *args: True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log_info(self, message: str):
        if self._logger:
            self._logger.info(message)

    def _log_error(self, message: str):
        if self._logger:
            self._logger.error(message)

    def _b64(self, value: str) -> str:
        return base64.b64encode(value.encode()).decode()

    # ------------------------------------------------------------------
    # CR generation
    # ------------------------------------------------------------------

    def generate_cr(self) -> bool:
        """Generate the CCXWDUServices Custom Resource YAML."""
        try:
            if not self._base_template.exists():
                self._log_error(f"WDU CR base template not found: {self._base_template}")
                return False

            with open(self._base_template) as f:
                cr = self._yaml.load(f)

            spec = cr.get("spec", {})

            # License
            spec["license"]["accept"] = True

            shared = spec.get("shared_configuration", {})

            # Determine whether Content operator is co-deployed in this namespace.
            # CPE=True in deployment_properties is the canonical signal.
            content_deployed = bool(self._deployment_properties.get("CPE", False))

            # sc_deployment_context and root_ca_secret depend on the deployment topology:
            #   Content + WDU  → FNCM context, share the Content CA secret
            #   WDU only       → Standalone context, use WDU's own CA secret
            if content_deployed:
                shared["sc_deployment_context"] = "FNCM"
                shared["root_ca_secret"] = "content-root-ca"
            else:
                shared["sc_deployment_context"] = "Standalone"
                shared["root_ca_secret"] = "wdu-root-ca"

            # License model — required field in the CRD.
            # LICENSE may be a comma-separated list (e.g. "CCx.Pre.AU,CCx.Pre.EP,CCx.Pre.PE").
            # Any Premium token → "Premium"; otherwise → "Essentials".
            # license_model = self._deployment_properties.get("LICENSE", "")
            # premium_tokens = {"CCx.Pre.AU", "CCx.Pre.EP", "CCx.Pre.PE"}
            # license_tokens = {t.strip() for t in license_model.split(",")}
            # wdu_license = "Premium" if license_tokens & premium_tokens else "Essentials"
            #WDU license will always be "Essentials"
            wdu_license = "Essentials"
            shared["sc_ccx_license_model"] = SingleQuotedScalarString(wdu_license)

            shared["sc_deployment_platform"] = SingleQuotedScalarString(
                self._deployment_properties.get("PLATFORM", "<Required>")
            )
            # Profile size defaults to "small" in the template; only override when
            # the deployment properties carry an explicit DEPLOYMENT_PROFILE_SIZE.
            shared["sc_deployment_profile_size"] = SingleQuotedScalarString(
                str(self._deployment_properties.get("DEPLOYMENT_PROFILE_SIZE", "small"))
            )
            # Storage class resolution — priority order:
            #   1. ccx-deployment.toml  → deployment_properties["FAST_FILE_STORAGE_CLASSNAME"]
            #   2. ccx-wdu.toml [storage] → wdu_properties["storage"]["FAST_FILE_STORAGE_CLASSNAME"]
            #   3. "<Required>" sentinel (stand-alone, user has not filled it in yet)
            _fast_sc = self._deployment_properties.get("FAST_FILE_STORAGE_CLASSNAME", "")
            if not _fast_sc or _fast_sc == "<Required>":
                _wdu_storage = self._wdu_properties.get("storage", {})
                _fast_sc = _wdu_storage.get("FAST_FILE_STORAGE_CLASSNAME", "<Required>")
            storage = shared.get("storage_configuration", CommentedMap())
            storage["sc_fast_file_storage_classname"] = SingleQuotedScalarString(str(_fast_sc))
            shared["storage_configuration"] = storage

            with open(self._generated_cr, "w") as f:
                self._yaml.dump(cr, f)

            self._generated_files.append(("WDU CR", self._generated_cr, os.path.getsize(self._generated_cr)))
            self._log_info(f"Generated WDU CR: {self._generated_cr}")
            return True

        except Exception as e:
            self._log_error(f"Error generating WDU CR: {e}")
            if self._logger:
                self._logger.exception("Detailed error:")
            return False

    # ------------------------------------------------------------------
    # Secret generation
    # ------------------------------------------------------------------

    def generate_admin_secret(self) -> bool:
        """Generate the WDU admin password Kubernetes secret."""
        try:
            admin_password = str(self._wdu_properties.get("ADMIN_PASSWORD", "<Required>"))

            secret: Dict = {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": "ibm-ccx-wdu-admin-secret",
                    "namespace": self._namespace,
                },
                "type": "Opaque",
                "data": {
                    "adminPassword": self._b64(admin_password),
                },
            }

            with open(self._generated_admin_secret, "w") as f:
                self._yaml.dump(secret, f)

            self._generated_files.append(
                ("WDU Admin Secret", self._generated_admin_secret,
                 os.path.getsize(self._generated_admin_secret))
            )
            self._log_info(f"Generated WDU admin secret: {self._generated_admin_secret}")
            return True

        except Exception as e:
            self._log_error(f"Error generating WDU admin secret: {e}")
            if self._logger:
                self._logger.exception("Detailed error:")
            return False

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def generate_wxai_secret(self) -> bool:
        """Generate ibm-ccx-wdu-wxai-secret when WDU_ENABLE_WXAI=true.

        The secret holds a nested YAML document under the key 'wxai_vars.yaml'
        matching the WatsonX AI configuration structure documented in the
        wdu-manual-test README WatsonX AI section.

        Only called when self._wdu_properties['WDU_ENABLE_WXAI'] is truthy.
        """
        try:
            from ruamel.yaml.scalarstring import LiteralScalarString

            # The TOML [wxai] section is parsed into a nested dict under the
            # "wxai" key — the same pattern as [postgres] → self._wdu_properties["postgres"].
            wxai = self._wdu_properties.get("wxai", {})

            wxai_content = (
                f"wxai:\n"
                f"  api_key: {wxai.get('WXAI_API_KEY', '<Required>')}\n"
                f"  image_description:\n"
                f"    model_id: {wxai.get('WXAI_IMAGE_DESCRIPTION_MODEL_ID', '<Required>')}\n"
                f"    space_id: {wxai.get('WXAI_IMAGE_DESCRIPTION_SPACE_ID', '<Required>')}\n"
                f"  kvp:\n"
                f"    model_id: {wxai.get('WXAI_KVP_MODEL_ID', '<Required>')}\n"
                f"    space_id: {wxai.get('WXAI_KVP_SPACE_ID', '<Required>')}\n"
                f"  provider: {wxai.get('WXAI_PROVIDER', 'watsonx')}\n"
                f"  semantic_kvp:\n"
                f"    model_id: {wxai.get('WXAI_SEMANTIC_KVP_MODEL_ID', '<Required>')}\n"
                f"    space_id: {wxai.get('WXAI_SEMANTIC_KVP_SPACE_ID', '<Required>')}\n"
                f"  url: {wxai.get('WXAI_URL', 'https://us-south.ml.cloud.ibm.com')}\n"
                f"  version: \"{wxai.get('WXAI_VERSION', '2024-03-14')}\"\n"
            )

            secret = {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": "ibm-ccx-wdu-wxai-secret",
                    "namespace": self._namespace,
                },
                "type": "Opaque",
                "stringData": {
                    "wxai_vars.yaml": LiteralScalarString(wxai_content),
                },
            }

            wxai_path = self._secrets_folder / "ibm-ccx-wdu-wxai-secret.yaml"
            with open(wxai_path, "w") as f:
                self._yaml.dump(secret, f)

            self._generated_files.append(
                ("WDU WatsonX AI Secret", wxai_path, os.path.getsize(wxai_path))
            )
            self._log_info(f"Generated WDU WatsonX AI secret: {wxai_path}")
            return True

        except Exception as e:
            self._log_error(f"Error generating WDU WatsonX AI secret: {e}")
            if self._logger:
                self._logger.exception("Detailed error:")
            return False

    # ------------------------------------------------------------------
    # PostgreSQL TLS secret generation (external PG only)
    # ------------------------------------------------------------------

    def _read_pg_ssl_certs(self, ssl_subdir: str) -> Dict[str, str]:
        """Read SSL certs from a wdu/<ssl_subdir>/ folder on disk.

        Expected layout (created by property.py __create_ssl_folder):
          ssl-certs/wdu/<ssl_subdir>/serverca/   → ca.crt
          ssl-certs/wdu/<ssl_subdir>/clientcert/ → tls.crt
          ssl-certs/wdu/<ssl_subdir>/clientkey/  → tls.key

        Returns a dict mapping Kubernetes secret key → base64-encoded content.
        Only keys whose subfolder contains a cert file are included.
        """
        from ..utilities.prerequisites_utilites import collect_visible_files

        ssl_base = (
            Path.cwd() / "propertyFile" / self._namespace / "ssl-certs" / "wdu" / ssl_subdir
        )
        certs: Dict[str, str] = {}

        if not ssl_base.is_dir():
            self._log_info(
                f"WDU ssl-certs folder not found at {ssl_base} — skipping cert injection"
            )
            return certs

        _subfolder_to_key = {
            "serverca":   "ca.crt",
            "clientcert": "tls.crt",
            "clientkey":  "tls.key",
        }

        for subfolder, secret_key in _subfolder_to_key.items():
            subfolder_path = ssl_base / subfolder
            if not subfolder_path.is_dir():
                continue
            cert_files = [
                f for f in collect_visible_files(str(subfolder_path))
                if any(f.endswith(ext) for ext in (".crt", ".cer", ".pem", ".cert", ".key", ".arm"))
            ]
            if cert_files:
                cert_path = subfolder_path / cert_files[0]
                with open(cert_path, "rb") as fh:
                    certs[secret_key] = base64.b64encode(fh.read()).decode()
                self._log_info(
                    f"Loaded WDU SSL cert: wdu/{ssl_subdir}/{subfolder}/{cert_files[0]}"
                    f" → secret key '{secret_key}'"
                )

        return certs

    def generate_pg_ssl_secrets(self) -> bool:
        """Generate ibm-ccx-wdu-db-session-ssl-secret and ibm-ccx-wdu-db-transaction-ssl-secret.

        Each secret contains three TLS keys sourced from the respective cert subfolder:
          ca.crt  ← ssl-certs/wdu/pg_sess/serverca/   (or pg_txn/)
          tls.crt ← ssl-certs/wdu/pg_sess/clientcert/ (or pg_txn/)
          tls.key ← ssl-certs/wdu/pg_sess/clientkey/  (or pg_txn/)

        Only called when USE_IBM_CNPG=false and SSL_ENABLED=true.
        Returns True only when both secrets are written successfully.
        """
        results = []
        for secret_name, ssl_subdir in (
            ("ibm-ccx-wdu-db-session-ssl-secret",     "pg_sess"),
            ("ibm-ccx-wdu-db-transaction-ssl-secret", "pg_txn"),
        ):
            try:
                certs = self._read_pg_ssl_certs(ssl_subdir)
                secret_path = self._ssl_folder / f"{secret_name}.yaml"

                secret: Dict = {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "metadata": {
                        "name": secret_name,
                        "namespace": self._namespace,
                    },
                    "type": "Opaque",
                    "data": certs,
                }

                with open(secret_path, "w") as fh:
                    self._yaml.dump(secret, fh)

                self._generated_files.append(
                    (f"WDU SSL Secret ({ssl_subdir})", secret_path, os.path.getsize(secret_path))
                )
                self._log_info(f"Generated WDU SSL secret: {secret_path}")
                results.append(True)
            except Exception as e:
                self._log_error(f"Error generating WDU SSL secret '{secret_name}': {e}")
                if self._logger:
                    self._logger.exception("Detailed error:")
                results.append(False)

        return all(results)

    def generate_configmap(self) -> bool:
        """Generate the ibm-ccx-wdu-config ConfigMap YAML.

        The ConfigMap ties all WDU secret names together.

        Keys:
            PROVIDER_SECRET_NAME        — name of the providers secret
            WXAI_SECRET_NAME            — WatsonX AI secret name (empty if not used)
            SESSION_SSL_SECRET_NAME     — TLS secret for session PgBouncer pool
            TRANSACTION_SSL_SECRET_NAME — TLS secret for transaction PgBouncer pool
            IBM_CNPG_ENABLE             — "true" / "false" matching USE_IBM_CNPG

        For IBM CNPG: both SSL secret names point to ccx-wdu-pg-ca (operator-created).
        For external PG: each pooler gets its own dedicated TLS secret.
        """
        try:
            # postgres_session is the primary section in the written TOML;
            # fall back to the legacy "postgres" key for backward compatibility.
            _pg = self._wdu_properties.get(
                "postgres_session", self._wdu_properties.get("postgres", {})
            )
            use_cnpg = str(_pg.get("USE_IBM_CNPG", False)).lower() in ("true", "1", "yes")

            enable_wxai = str(
                self._wdu_properties.get("WDU_ENABLE_WXAI", False)
            ).lower() in ("true", "1", "yes")
            wxai_secret = "ibm-ccx-wdu-wxai-secret" if enable_wxai else ""

            # For IBM CNPG the operator already created ccx-wdu-pg-ca.
            # For external PG each pooler gets its own TLS secret.
            if use_cnpg:
                session_ssl_secret     = "ccx-wdu-pg-ca"
                transaction_ssl_secret = "ccx-wdu-pg-ca"
            else:
                session_ssl_secret     = "ibm-ccx-wdu-db-session-ssl-secret"
                transaction_ssl_secret = "ibm-ccx-wdu-db-transaction-ssl-secret"

            cm: Dict = {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {
                    "name": "ibm-ccx-wdu-config",
                    "namespace": SingleQuotedScalarString(self._namespace),
                    "labels": {
                        "cp4ba.ibm.com/backup-type": "mandatory",
                    },
                },
                "data": {
                    "PROVIDER_SECRET_NAME": "ibm-ccx-wdu-providers-secret",
                    "WXAI_SECRET_NAME": wxai_secret,
                    "SESSION_SSL_SECRET_NAME": session_ssl_secret,
                    "TRANSACTION_SSL_SECRET_NAME": transaction_ssl_secret,
                    "IBM_CNPG_ENABLE": SingleQuotedScalarString("true" if use_cnpg else "false"),
                },
            }

            with open(self._generated_configmap, "w") as f:
                self._yaml.dump(cm, f)

            self._generated_files.append(
                ("WDU ConfigMap", self._generated_configmap,
                 os.path.getsize(self._generated_configmap))
            )
            self._log_info(f"Generated WDU ConfigMap: {self._generated_configmap}")
            return True

        except Exception as e:
            self._log_error(f"Error generating WDU ConfigMap: {e}")
            if self._logger:
                self._logger.exception("Detailed error:")
            return False

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def generate_all(self) -> bool:
        """Generate all WDU artifacts. Returns True if all succeeded."""
        results = [
            self.generate_cr(),
            self.generate_configmap(),
            # generate_admin_secret() is intentionally omitted: no CRD field in
            # CCXWDUServices references ibm-ccx-wdu-admin-secret in the 26.x schema.
            # The method is preserved below for reference but not called.
        ]

        # Optional: WatsonX AI secret — only generated when WDU_ENABLE_WXAI=true
        enable_wxai = str(
            self._wdu_properties.get("WDU_ENABLE_WXAI", False)
        ).lower() in ("true", "1", "yes")
        if enable_wxai:
            results.append(self.generate_wxai_secret())

        # External PG TLS secrets — only generated when USE_IBM_CNPG=false and SSL is enabled.
        _pg = self._wdu_properties.get(
            "postgres_session", self._wdu_properties.get("postgres", {})
        )
        use_cnpg = str(_pg.get("USE_IBM_CNPG", False)).lower() in ("true", "1", "yes")
        ssl_enabled = str(_pg.get("SSL_ENABLED", False)).lower() in ("true", "1", "yes")
        if not use_cnpg and ssl_enabled:
            results.append(self.generate_pg_ssl_secrets())

        return all(results)
