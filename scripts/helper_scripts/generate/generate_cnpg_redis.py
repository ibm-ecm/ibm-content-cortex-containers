###############################################################################
#
# Licensed Materials - Property of IBM
#
# (C) Copyright IBM Corp. 2026. All Rights Reserved.
#
# US Government Users Restricted Rights - Use, duplication or
# disclosure restricted by GSA ADP Schedule Contract with IBM Corp.
#
###############################################################################

"""
CNPG & Redis Artifact Generator — external-connection secret contract

Model Gateway always uses deploy_redis: false / deploy_postgres: false.
It connects via the external-connection interface using two secrets whose
exact schemas come from the IBM Model Gateway operator:

Postgres secret  (model-gateway-postgres-external-secret)
---------------------------------------------------------------------------
Keys (all b64-encoded in data):
  host        PostgreSQL hostname / FQDN
  port        PostgreSQL port            (default: "5432")
  username    Database username
  password    Database password
  dbname      Database name              (default: "modelgateway")
  parameters  SSL connection string      (default: "sslmode=disable")
              e.g. "sslmode=require"
              e.g. "sslmode=verify-full&sslrootcert=/postgres-secrets/ca.crt"
Optional TLS keys (b64-encoded PEM):
  ca.crt      CA certificate
  client.crt  Client certificate  (mutual TLS)
  client.key  Client private key  (mutual TLS)
Reference: https://www.ibm.com/docs/en/cloud-paks/cp-biz-automation/26.0.0
           ?topic=installing-model-gateway

Redis secret  (name provided via CR param externalRedisSecret)
---------------------------------------------------------------------------
We use the fixed name: model-gateway-redis-external-secret
Keys (b64-encoded, operator scans for whichever is present):
  redis-url-ssl1  rediss://:<password>@<host>:<port>/0   (TLS — operator checks this first)
  redis-url       redis://:<password>@<host>:<port>/0    (plain)
The operator's auto-detection:
  redis-url-ssl1 present → external_redis_url_key = "redis-url-ssl1" → TLS path
  redis-url only         → external_redis_url_key = "redis-url"      → plain path
  neither                → operator fails with clear message
Reference: github.ibm.com/IBMPrivateCloud/ibm-model-gateway-bundle PR #232

Generation paths
----------------
MG_USE_IBM_CNPG=true
  → ibm_pg_cluster_mg_cr.yaml
  → secrets/model-gateway-postgres-external-secret.yaml  (auto-populated)

MG_USE_IBM_CNPG=false
  → secrets/model-gateway-postgres-external-secret.yaml  (placeholder — user fills)

MG_USE_IBM_REDIS=true
  → ibm_redis_cr.yaml
  → secrets/ibm-redis-mg-secret.yaml
  → secrets/model-gateway-redis-external-secret.yaml     (auto-populated, plain URL)

MG_USE_IBM_REDIS=false
  → secrets/model-gateway-redis-external-secret.yaml     (placeholder — user fills)

WDU_USE_IBM_CNPG=true
  → ibm_pg_cluster_wdu_cr.yaml

Apply order (internal IBM-managed path):
  1. secrets/ibm-redis-mg-secret.yaml                          (IBM Redis only)
  2. ibm_redis_cr.yaml                                         (IBM Redis only)
  3. secrets/model-gateway-postgres-external-secret.yaml
  4. secrets/model-gateway-redis-external-secret.yaml
  5. ibm_pg_cluster_mg_cr.yaml                                 (IBM CNPG only)
  Wait for readiness, then:
  6. ibm_model_gateway_cr_production.yaml
"""

import base64
import os
import secrets
import string
from logging import Logger
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString, SingleQuotedScalarString

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# CNPG cluster names — one per operator, deterministic
CNPG_CLUSTER_NAME_MG = "ibm-pg-cluster-mg"
CNPG_CLUSTER_NAME_WDU = "ccx-wdu-pg"

# The CNPG operator creates a read-write service at this predictable FQDN.
CNPG_RW_SERVICE_TEMPLATE = "{cluster}.{namespace}.svc.cluster.local"

# PgBouncer pooler name for WDU — the IBM PG operator creates a service
# <pooler-name> that fronts the primary CNPG instance.
CNPG_POOLER_NAME_WDU = "ibm-pg-pooler-wdu"

# IBM Redis master service short name (operator sets name = CR name + "-master-svc").
# The short name is explicitly in the Redis TLS cert's SANs; the FQDN is not.
REDIS_MASTER_SVC_NAME = "ibm-redis-mg-master-svc"

# Postgres external-connection secret — name required by the MG operator
MG_POSTGRES_EXTERNAL_SECRET_NAME = "model-gateway-postgres-external-secret"

# Redis external-connection secret — name we choose; passed to CR via externalRedisSecret
MG_REDIS_EXTERNAL_SECRET_NAME = "model-gateway-redis-external-secret"

# WDU CNPG credentials secret — consumed by CNPG Cluster CR superuserSecret ref
WDU_DB_SECRET_NAME = "ibm-wdu-db-secret"

# WDU providers secret — consumed by the WDU operator via ibm-ccx-wdu-config ConfigMap
WDU_PROVIDERS_SECRET_NAME = "ibm-ccx-wdu-providers-secret"

# Redis operator credential secret — consumed by the IBM Redis operator Ansible role
REDIS_PWD_SECRET_NAME = "ibm-redis-mg-secret"

# Default CNPG postgres user (created automatically by CNPG)
CNPG_SUPERUSER = "app"

# Default Postgres connection parameters
DEFAULT_PG_PORT = "5432"
DEFAULT_PG_DBNAME = "modelgateway"
DEFAULT_WDU_PG_DBNAME = "wdu"
DEFAULT_PG_SSLMODE = "sslmode=require"
# IBM-managed CNPG always enables server-side TLS — verify-ca is the required default
CNPG_PG_SSLMODE = "sslmode=verify-ca&sslrootcert=/postgres-secrets/ca.crt"

# Default Redis ports — plain and TLS are on different ports
DEFAULT_REDIS_PORT_PLAIN = "6379"
DEFAULT_REDIS_PORT_TLS   = "6380"

# ---------------------------------------------------------------------------
# Small-profile sizing defaults — used when generating CRs from gather mode.
# Sizing is not exposed as customer-facing properties; these defaults are
# intentionally conservative (single instance, minimal storage).
# ---------------------------------------------------------------------------
CNPG_DEFAULT_INSTANCES: int = 1
CNPG_DEFAULT_STORAGE: str = "10Gi"
REDIS_DEFAULT_SCALE: str = "small"
REDIS_DEFAULT_REPLICAS: int = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_password(length: int = 24) -> str:
    """Generate a cryptographically secure random password."""
    alphabet = string.ascii_letters + string.digits
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.isdigit() for c in pwd) and any(c.isalpha() for c in pwd):
            return pwd


def _b64(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


# ---------------------------------------------------------------------------
# Generator class
# ---------------------------------------------------------------------------

class GenerateCNPGRedis:
    """
    Generator for IBM-managed CNPG (PostgreSQL) and Redis artifacts, plus
    the Model Gateway external-connection secrets.

    Model Gateway always uses deploy_redis: false / deploy_postgres: false
    and connects via:
      model-gateway-postgres-external-secret  (Postgres)
      model-gateway-redis-external-secret     (Redis, via externalRedisSecret CR param)

    For IBM-managed infra the secrets are auto-populated.
    For external/BYO infra placeholder secrets are written for the user to fill.
    """

    def __init__(
        self,
        mg_properties: Dict,
        wdu_properties: Dict,
        deployment_properties: Dict,
        namespace: str = "",
        logger: Optional[Logger] = None,
        output_folder: Optional[str] = None,
        block_storage_class: Optional[str] = None,
    ):
        self._logger = logger
        self._mg_props = mg_properties
        self._wdu_props = wdu_properties
        self._deployment_properties = deployment_properties
        self._namespace = namespace
        # block_storage_class: explicit override used when called from gather mode.
        # Falls back to BLOCK_STORAGE_CLASSNAME from deployment properties.
        self._block_storage_class: str = (
            block_storage_class
            or str(deployment_properties.get("BLOCK_STORAGE_CLASSNAME", ""))
            or "<Required>"
        )

        self.ccx_version = self._deployment_properties.get("CCX_Version", "26.0.1")

        # Track generated files for summary display
        self._generated_files: List[Tuple[str, Path, int]] = []

        # Output paths — caller can redirect CR output (e.g. to infrastructure/)
        if output_folder:
            self._generate_folder = Path(output_folder)
        else:
            self._generate_folder = Path.cwd() / "generatedFiles" / self._namespace
        self._generate_folder.mkdir(parents=True, exist_ok=True)
        self._secrets_folder = self._generate_folder / "secrets"
        self._secrets_folder.mkdir(parents=True, exist_ok=True)

        # CR template paths
        _tmpl_base = (
            Path.cwd()
            / "helper_scripts"
            / "generate"
            / "cr_templates"
            / self.ccx_version
        )
        self._cnpg_template = _tmpl_base / "cnpg" / "base.yaml"
        self._cnpg_pooler_template = _tmpl_base / "cnpg" / "pooler.yaml"
        self._redis_template = _tmpl_base / "redis" / "base.yaml"

        # Output file paths
        self._cnpg_mg_cr_path = self._generate_folder / "ibm_pg_cluster_mg_cr.yaml"
        self._cnpg_wdu_cr_path = self._generate_folder / "ibm_pg_cluster_wdu_cr.yaml"
        self._cnpg_wdu_pooler_cr_path = self._generate_folder / "ibm_pg_pooler_wdu_cr.yaml"
        self._redis_cr_path = self._generate_folder / "ibm_redis_cr.yaml"

        self._mg_postgres_ext_secret_path = (
            self._secrets_folder / f"{MG_POSTGRES_EXTERNAL_SECRET_NAME}.yaml"
        )
        self._mg_redis_ext_secret_path = (
            self._secrets_folder / f"{MG_REDIS_EXTERNAL_SECRET_NAME}.yaml"
        )
        self._wdu_db_secret_path = self._secrets_folder / f"{WDU_DB_SECRET_NAME}.yaml"
        self._wdu_providers_secret_path = self._secrets_folder / f"{WDU_PROVIDERS_SECRET_NAME}.yaml"
        self._redis_pwd_secret_path = self._secrets_folder / f"{REDIS_PWD_SECRET_NAME}.yaml"

        # YAML handler
        self._yaml = YAML()
        self._yaml.preserve_quotes = True
        self._yaml.representer.ignore_aliases = lambda *args: True

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _log_info(self, msg: str) -> None:
        if self._logger:
            self._logger.info(msg)

    def _log_error(self, msg: str) -> None:
        if self._logger:
            self._logger.error(msg)

    # ------------------------------------------------------------------
    # Service FQDN helpers
    # ------------------------------------------------------------------

    def cnpg_mg_hostname(self) -> str:
        """Deterministic CNPG read-write service FQDN for Model Gateway."""
        return CNPG_RW_SERVICE_TEMPLATE.format(
            cluster=f"{CNPG_CLUSTER_NAME_MG}-rw",
            namespace=self._namespace,
        )

    def cnpg_wdu_hostname(self) -> str:
        """Deterministic CNPG read-write service FQDN for WDU."""
        return CNPG_RW_SERVICE_TEMPLATE.format(
            cluster=f"{CNPG_CLUSTER_NAME_WDU}-rw",
            namespace=self._namespace,
        )

    def redis_master_svc_name(self) -> str:
        """IBM Redis master service short name for Model Gateway.

        Uses the short name (ibm-redis-mg-master-svc) rather than the FQDN
        because the Redis TLS cert's SANs only cover the short service name —
        the FQDN (<name>.<namespace>.svc.cluster.local) is not included.
        Both pods are in the same namespace so the short name resolves correctly.
        """
        return REDIS_MASTER_SVC_NAME

    # ------------------------------------------------------------------
    # CNPG Cluster CRs
    # ------------------------------------------------------------------

    def _generate_cnpg_cr(
        self,
        cluster_name: str,
        database_name: str,
        instances: int,
        storage_size: str,
        storage_class: str,
        output_path: Path,
        label: str,
    ) -> bool:
        """Generate a CNPG Cluster CR.

        Args:
            cluster_name:   metadata.name for the Cluster CR (e.g. ibm-pg-cluster-mg).
            database_name:  Bootstrap database created by initdb (e.g. modelgateway, wdu).
            instances:      Number of PostgreSQL instances (primary + replicas).
            storage_size:   PVC storage size string (e.g. "10Gi").
            storage_class:  Block storage class name.
            output_path:    Destination file for the rendered CR.
            label:          Human-readable label used in log messages.
        """
        try:
            if not self._cnpg_template.exists():
                self._log_error(f"CNPG CR template not found: {self._cnpg_template}")
                return False

            with open(self._cnpg_template) as f:
                cr = self._yaml.load(f)

            cr["metadata"]["name"] = cluster_name
            cr["metadata"]["namespace"] = self._namespace
            spec = cr.get("spec", {})
            spec["instances"] = instances
            spec["bootstrap"]["initdb"]["database"] = database_name
            spec["storage"]["size"] = SingleQuotedScalarString(storage_size)
            spec["storage"]["storageClass"] = SingleQuotedScalarString(storage_class)

            with open(output_path, "w") as f:
                self._yaml.dump(cr, f)

            self._generated_files.append((label, output_path, os.path.getsize(output_path)))
            self._log_info(f"Generated {label}: {output_path}")
            return True

        except Exception as e:
            self._log_error(f"Error generating {label}: {e}")
            if self._logger:
                self._logger.exception("Detailed error:")
            return False

    def generate_cnpg_mg_cr(self) -> bool:
        """Generate the CNPG Cluster CR for Model Gateway."""
        return self._generate_cnpg_cr(
            cluster_name=CNPG_CLUSTER_NAME_MG,
            database_name=DEFAULT_PG_DBNAME,
            instances=CNPG_DEFAULT_INSTANCES,
            storage_size=CNPG_DEFAULT_STORAGE,
            storage_class=self._block_storage_class,
            output_path=self._cnpg_mg_cr_path,
            label="CNPG Cluster CR (Model Gateway)",
        )

    def generate_cnpg_wdu_cr(self) -> bool:
        """Generate the CNPG Cluster CR for WDU.

        Reads CNPG_INSTANCES, CNPG_STORAGE_SIZE, and DATABASE_NAME from
        wdu_props["postgres_session"] (falling back to bare "postgres" for legacy
        property files).  Storage class comes from block_storage_class resolved in
        __init__ (BLOCK_STORAGE_CLASSNAME from deployment properties).
        """
        # postgres_session is the primary TOML section; fall back to legacy "postgres".
        wdu_pg = self._wdu_props.get("postgres_session") or self._wdu_props.get("postgres", {})
        instances = int(wdu_pg.get("CNPG_INSTANCES", CNPG_DEFAULT_INSTANCES))
        storage_size = str(wdu_pg.get("CNPG_STORAGE_SIZE", CNPG_DEFAULT_STORAGE))
        database_name = str(wdu_pg.get("DATABASE_NAME", DEFAULT_WDU_PG_DBNAME))
        return self._generate_cnpg_cr(
            cluster_name=CNPG_CLUSTER_NAME_WDU,
            database_name=database_name,
            instances=instances,
            storage_size=storage_size,
            storage_class=self._block_storage_class,
            output_path=self._cnpg_wdu_cr_path,
            label="CNPG Cluster CR (WDU)",
        )

    def generate_cnpg_wdu_pooler_cr(self) -> bool:
        """Generate the CNPG Pooler CR (PgBouncer) for WDU.

        The Pooler CR must be applied after the WDU Cluster CR reaches healthy
        state.  It fronts ccx-wdu-pg with a PgBouncer instance that
        multiplexes client connections in transaction-pooling mode.

        Returns:
            True if the CR was written successfully; False on error.
        """
        try:
            if not self._cnpg_pooler_template.exists():
                self._log_error(
                    f"CNPG Pooler CR template not found: {self._cnpg_pooler_template}"
                )
                return False

            with open(self._cnpg_pooler_template) as f:
                cr = self._yaml.load(f)

            cr["metadata"]["name"] = "ibm-pg-pooler-wdu"
            cr["metadata"]["namespace"] = self._namespace
            cr["spec"]["cluster"]["name"] = CNPG_CLUSTER_NAME_WDU

            with open(self._cnpg_wdu_pooler_cr_path, "w") as f:
                self._yaml.dump(cr, f)

            self._generated_files.append(
                (
                    "CNPG Pooler CR (WDU)",
                    self._cnpg_wdu_pooler_cr_path,
                    os.path.getsize(self._cnpg_wdu_pooler_cr_path),
                )
            )
            self._log_info(
                f"Generated CNPG Pooler CR (WDU): {self._cnpg_wdu_pooler_cr_path}"
            )
            return True

        except Exception as e:
            self._log_error(f"Error generating CNPG Pooler CR (WDU): {e}")
            if self._logger:
                self._logger.exception("Detailed error:")
            return False

    # ------------------------------------------------------------------
    # IBM Redis — Rediscp CR + ibm-redis-mg-secret
    # ------------------------------------------------------------------

    def generate_redis_cr(self, redis_password: str) -> bool:
        """Generate the IBM Redis Rediscp CR.

        The credentialSecret field points to ibm-redis-mg-secret which must exist
        before the operator reconciles the CR.
        """
        try:
            if not self._redis_template.exists():
                self._log_error(f"Redis CR template not found: {self._redis_template}")
                return False

            with open(self._redis_template) as f:
                cr = self._yaml.load(f)

            cr["metadata"]["namespace"] = self._namespace
            spec = cr.get("spec", {})
            spec["scale_config"] = SingleQuotedScalarString(REDIS_DEFAULT_SCALE)
            spec["size"] = REDIS_DEFAULT_REPLICAS
            spec["file_storage_class"] = SingleQuotedScalarString(self._block_storage_class)
            spec["block_storage_class"] = SingleQuotedScalarString(self._block_storage_class)

            with open(self._redis_cr_path, "w") as f:
                self._yaml.dump(cr, f)

            self._generated_files.append(
                ("Redis CR (Model Gateway)", self._redis_cr_path,
                 os.path.getsize(self._redis_cr_path))
            )
            self._log_info(f"Generated Redis CR: {self._redis_cr_path}")
            return True

        except Exception as e:
            self._log_error(f"Error generating Redis CR: {e}")
            if self._logger:
                self._logger.exception("Detailed error:")
            return False

    def generate_redis_pwd_secret(self, redis_password: str) -> bool:
        """Generate ibm-redis-mg-secret consumed by the IBM Redis operator.

        The operator's Ansible role reads admin_password and default_password.
        All three keys are written to avoid broken probe auth / HAProxy startup.
        """
        try:
            secret = {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": REDIS_PWD_SECRET_NAME, "namespace": self._namespace},
                "type": "Opaque",
                "data": {
                    "password": _b64(redis_password),
                    "admin_password": _b64(redis_password),
                    "default_password": _b64(redis_password),
                },
            }
            with open(self._redis_pwd_secret_path, "w") as f:
                self._yaml.dump(secret, f)
            self._generated_files.append(
                (f"Redis Credential Secret ({REDIS_PWD_SECRET_NAME})", self._redis_pwd_secret_path,
                 os.path.getsize(self._redis_pwd_secret_path))
            )
            self._log_info(f"Generated {REDIS_PWD_SECRET_NAME}: {self._redis_pwd_secret_path}")
            return True
        except Exception as e:
            self._log_error(f"Error generating {REDIS_PWD_SECRET_NAME}: {e}")
            if self._logger:
                self._logger.exception("Detailed error:")
            return False

    # ------------------------------------------------------------------
    # Postgres external-connection secret (model-gateway-postgres-external-secret)
    # ------------------------------------------------------------------

    def _read_mg_postgres_ssl_certs(self) -> Dict[str, str]:
        """Read SSL certs from ssl-certs/model-gateway/ subfolders.

        Follows the same pattern as generate_secrets.py for Content postgres:
          serverca/   → ca.crt   (server CA for verify-ca / verify-full)
          clientcert/ → client.crt (client cert for mTLS)
          clientkey/  → client.key (client key for mTLS)

        Returns a dict of secret key → b64-encoded cert content.
        Only keys whose subfolder contains a cert file are included.
        """
        from ..utilities.prerequisites_utilites import collect_visible_files, collect_visible_folders

        ssl_base = Path.cwd() / "propertyFile" / self._namespace / "ssl-certs" / "model-gateway"
        certs: Dict[str, str] = {}

        if not ssl_base.is_dir():
            self._log_info(f"No MG postgres ssl-certs folder found at {ssl_base}, skipping cert injection")
            return certs

        _subfolder_to_key = {
            "serverca":  "ca.crt",
            "clientcert": "client.crt",
            "clientkey":  "client.key",
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
                with open(cert_path, "rb") as f:
                    certs[secret_key] = base64.b64encode(f.read()).decode()
                self._log_info(f"Loaded MG postgres SSL cert: {subfolder}/{cert_files[0]} → secret key '{secret_key}'")

        return certs

    def generate_mg_postgres_external_secret(
        self,
        host: str,
        port: str,
        username: str,
        password: str,
        dbname: str,
        parameters: str = DEFAULT_PG_SSLMODE,
        live_ca_cert_b64: Optional[str] = None,
    ) -> bool:
        """Generate model-gateway-postgres-external-secret.

        Secret schema matches the IBM Model Gateway operator contract:
          host        PostgreSQL hostname
          port        PostgreSQL port
          username    Database username
          password    Database password
          dbname      Database name
          parameters  SSL connection string

        TLS key injected into the secret:
          ca.crt      Server CA certificate (from <cluster>-ca secret, key ca.crt)

        When ``live_ca_cert_b64`` is provided (IBM-managed CNPG path) the CA cert
        is injected directly.  The caller-supplied ``parameters`` is used as-is
        (should be ``sslmode=verify-ca&sslrootcert=/postgres-secrets/ca.crt``).

        For the external / BYO path the CA cert is read from
        ssl-certs/model-gateway/serverca/ on disk.

        Reference:
          https://www.ibm.com/docs/en/cloud-paks/cp-biz-automation/26.0.0
          ?topic=installing-model-gateway
        """
        try:
            data: Dict[str, str] = {
                "host":       _b64(host),
                "port":       _b64(port),
                "username":   _b64(username),
                "password":   _b64(password),
                "dbname":     _b64(dbname),
                "parameters": _b64(parameters),
            }

            # ── IBM-managed CNPG path ──────────────────────────────────────────
            # Inject the live CA cert fetched directly from the cluster secret.
            # Only the CA is needed for sslmode=verify-ca; client cert/key are
            # not used with internal IBM CNPG.
            if live_ca_cert_b64:
                data["ca.crt"] = live_ca_cert_b64
                self._log_info(
                    f"Injected live CA cert into {MG_POSTGRES_EXTERNAL_SECRET_NAME}"
                )
            else:
                # External / BYO path: read certs from ssl-certs/ folder on disk
                ssl_certs = self._read_mg_postgres_ssl_certs()
                data.update(ssl_certs)
                if ssl_certs:
                    self._log_info(
                        f"Injected SSL certs into {MG_POSTGRES_EXTERNAL_SECRET_NAME}: "
                        f"{list(ssl_certs.keys())}"
                    )
                    # If client cert and key are provided for mTLS, append them to the connection parameters
                    if "client.crt" in ssl_certs and "client.key" in ssl_certs:
                        if "sslcert=" not in parameters:
                            parameters = f"{parameters}&sslcert=/postgres-secrets/client.crt&sslkey=/postgres-secrets/client.key"
                            data["parameters"] = _b64(parameters)

            secret = {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": MG_POSTGRES_EXTERNAL_SECRET_NAME,
                    "namespace": self._namespace,
                },
                "type": "Opaque",
                "data": data,
            }
            with open(self._mg_postgres_ext_secret_path, "w") as f:
                self._yaml.dump(secret, f)
            self._generated_files.append((
                "Model Gateway Postgres External Secret",
                self._mg_postgres_ext_secret_path,
                os.path.getsize(self._mg_postgres_ext_secret_path),
            ))
            self._log_info(
                f"Generated {MG_POSTGRES_EXTERNAL_SECRET_NAME}: "
                f"{self._mg_postgres_ext_secret_path}"
            )
            return True
        except Exception as e:
            self._log_error(f"Error generating {MG_POSTGRES_EXTERNAL_SECRET_NAME}: {e}")
            if self._logger:
                self._logger.exception("Detailed error:")
            return False

    # ------------------------------------------------------------------
    # Redis external-connection secret (model-gateway-redis-external-secret)
    # ------------------------------------------------------------------

    def generate_mg_redis_external_secret(
        self,
        host: str,
        password: str,
        use_tls: bool = False,
    ) -> bool:
        """Generate model-gateway-redis-external-secret.

        Writes the canonical keys the MG operator reads:
          redis-url-ssl1  rediss://:<password>@<host>:6380  (TLS — operator reads this key)
          redis-url-ssl   rediss://:<password>@<host>:6380  (TLS fallback)
          redis-url       redis://:<password>@<host>:6379   (plain fallback)

        The CR template sets externalRedisUrlKey: "redis-url-ssl1", so that key
        must be present. redis-url-ssl and redis-url are kept for compatibility.
        Plain and TLS URLs use different ports (6379 / 6380).

        This secret is referenced in the MG CR via externalRedisSecret.
        """
        try:
            secret = {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": MG_REDIS_EXTERNAL_SECRET_NAME,
                    "namespace": self._namespace,
                },
                "type": "Opaque",
                "data": {
                    "auth":           _b64(password),
                    "redis-url":      _b64(f"redis://:{password}@{host}:{DEFAULT_REDIS_PORT_PLAIN}"),
                    "redis-url-ssl":  _b64(f"rediss://:{password}@{host}:{DEFAULT_REDIS_PORT_TLS}"),
                    "redis-url-ssl1": _b64(f"rediss://:{password}@{host}:{DEFAULT_REDIS_PORT_TLS}"),
                },
            }
            with open(self._mg_redis_ext_secret_path, "w") as f:
                self._yaml.dump(secret, f)
            self._generated_files.append((
                "Model Gateway Redis External Secret",
                self._mg_redis_ext_secret_path,
                os.path.getsize(self._mg_redis_ext_secret_path),
            ))
            self._log_info(
                f"Generated {MG_REDIS_EXTERNAL_SECRET_NAME}: "
                f"{self._mg_redis_ext_secret_path}"
            )
            return True
        except Exception as e:
            self._log_error(f"Error generating {MG_REDIS_EXTERNAL_SECRET_NAME}: {e}")
            if self._logger:
                self._logger.exception("Detailed error:")
            return False

    # ------------------------------------------------------------------
    # WDU DB secret
    # ------------------------------------------------------------------

    def _read_wdu_postgres_ssl_certs(self, pool: str = "pg_sess") -> Dict[str, str]:
        """Read SSL certs from ssl-certs/wdu/<pool>/ subfolders.

        The WDU ssl-certs now live under per-pooler subdirectories created by
        property.py __create_ssl_folder:
          ssl-certs/wdu/pg_sess/serverca/   → ca.crt
          ssl-certs/wdu/pg_sess/clientcert/ → client.crt
          ssl-certs/wdu/pg_sess/clientkey/  → client.key

        The same layout applies to ssl-certs/wdu/pg_txn/ for the transaction pooler.

        Args:
            pool: Subfolder name under ssl-certs/wdu/ — "pg_sess" (default) or "pg_txn".

        Returns a dict of secret key → b64-encoded cert content.
        Only keys whose subfolder contains a cert file are included.
        """
        from ..utilities.prerequisites_utilites import collect_visible_files

        ssl_base = Path.cwd() / "propertyFile" / self._namespace / "ssl-certs" / "wdu" / pool
        certs: Dict[str, str] = {}

        if not ssl_base.is_dir():
            self._log_info(
                f"No WDU postgres ssl-certs folder found at {ssl_base}, skipping cert injection"
            )
            return certs

        _subfolder_to_key = {
            "serverca":   "ca.crt",
            "clientcert": "client.crt",
            "clientkey":  "client.key",
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
                with open(cert_path, "rb") as f:
                    certs[secret_key] = base64.b64encode(f.read()).decode()
                self._log_info(
                    f"Loaded WDU postgres SSL cert: wdu/{pool}/{subfolder}/{cert_files[0]}"
                    f" → secret key '{secret_key}'"
                )

        return certs

    # WDU external-postgres secret name (consumed by the WDU operator)
    WDU_EXTERNAL_POSTGRES_SECRET_NAME = "wdu-external-postgres-secret"

    def generate_wdu_external_postgres_secret(
        self,
        host: str,
        port: str,
        username: str,
        password: str,
        dbname: str,
        ssl_enabled: bool = False,
        ssl_mode: str = "require",
    ) -> bool:
        """Generate wdu-external-postgres-secret for external (BYO) PostgreSQL.

        Secret keys match the WDU operator's expected environment variables:
          PGHOST       PostgreSQL hostname
          PGPORT       PostgreSQL port
          PGDATABASE   Database name
          PGUSER       Username
          PGPASSWORD   Password
          PGSSLMODE    SSL mode string (e.g. 'require', 'verify-ca', 'verify-full')

        Optional TLS keys are read from ssl-certs/wdu/pg_sess/ (per-pooler layout):
          serverca/   → ca.crt   (required for verify-ca / verify-full)
          clientcert/ → client.crt (mTLS)
          clientkey/  → client.key (mTLS)

        Mirrors generate_mg_postgres_external_secret() exactly, using WDU-specific
        key names and the wdu/pg_sess ssl-certs folder.
        """
        try:
            _secret_name = self.WDU_EXTERNAL_POSTGRES_SECRET_NAME
            _secret_path = self._secrets_folder / f"{_secret_name}.yaml"

            # Build parameters string (mirrors MG external path)
            if ssl_enabled and ssl_mode in ("verify-ca", "verify-full"):
                parameters = f"sslmode={ssl_mode}&sslrootcert=/postgres-secrets/ca.crt"
            elif ssl_enabled:
                parameters = f"sslmode={ssl_mode}"
            else:
                parameters = DEFAULT_PG_SSLMODE

            data: Dict[str, str] = {
                "PGHOST":      _b64(host),
                "PGPORT":      _b64(port),
                "PGDATABASE":  _b64(dbname),
                "PGUSER":      _b64(username),
                "PGPASSWORD":  _b64(password),
                "PGSSLMODE":   _b64(ssl_mode if ssl_enabled else "disable"),
            }

            # Inject SSL certs from disk (same pattern as MG external path)
            ssl_certs = self._read_wdu_postgres_ssl_certs()
            data.update(ssl_certs)
            if ssl_certs:
                self._log_info(
                    f"Injected SSL certs into {_secret_name}: {list(ssl_certs.keys())}"
                )

            secret = {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": _secret_name, "namespace": self._namespace},
                "type": "Opaque",
                "data": data,
            }
            with open(_secret_path, "w") as f:
                self._yaml.dump(secret, f)
            self._generated_files.append((
                "WDU External Postgres Secret",
                _secret_path,
                os.path.getsize(_secret_path),
            ))
            self._log_info(f"Generated {_secret_name}: {_secret_path}")
            return True
        except Exception as e:
            self._log_error(f"Error generating {self.WDU_EXTERNAL_POSTGRES_SECRET_NAME}: {e}")
            if self._logger:
                self._logger.exception("Detailed error:")
            return False

    def generate_providers_secret(
        self,
        host: str,
        port: str,
        username: str,
        password: str,
        dbname: str,
        txn_host: Optional[str] = None,
        txn_username: Optional[str] = None,
        txn_password: Optional[str] = None,
        use_cnpg: bool = False,
    ) -> bool:
        """Generate ibm-ccx-wdu-providers-secret.

        The WDU operator consumes this secret via the ConfigMap key PROVIDER_SECRET_NAME.
        It contains a nested YAML document under the key 'provider_vars.yaml' with the
        full Postgres connection config for two logical DB connections (transaction +
        session) and the backend provider types (kv / queue / storage).

        The 'postgres' (transaction) section routes through the PgBouncer pooler when
        txn_host is provided.  The 'postgres_session' section always connects directly
        to the CNPG read-write service — PgBouncer runs in transaction-pooling mode
        which is incompatible with session-level features (advisory locks, SET LOCAL).

        For IBM CNPG deployments, both connections share the same username/password
        (the CNPG 'app' user).  For external/BYO Postgres, the ccx-wdu.toml provides
        separate [postgres_transaction] and [postgres_session] sections which may carry
        different hostnames and credentials (e.g. separate PgBouncer endpoints).

        TLS blocks:
          CNPG  — ``tls: mode: verify-ca`` + ``cafile: /certs/pg/ca.crt`` only (both
                  sections). The CNPG operator mounts the cluster CA; no client cert.
          Ext.  — full three-field block per section:
                  transaction → /certs/pg-txn/{ca,tls.crt,tls.key}
                  session     → /certs/pg/{ca,tls.crt,tls.key}

        Args:
            host:         Direct Postgres FQDN — used for postgres_session.
            port:         Postgres port (default 5432).
            username:     Postgres user for the session connection.
            password:     Postgres password for the session connection (plaintext).
            dbname:       Database name (default 'wdu').
            txn_host:     Hostname for the transaction connection. When None, falls back
                          to host (both sections use the same host).
            txn_username: Username for the transaction connection. When None, falls back
                          to username (both sections share the same user).
            txn_password: Password for the transaction connection. When None, falls back
                          to password (both sections share the same password).
            use_cnpg:     True for IBM-managed CNPG (CA-only TLS); False for external
                          Postgres (full certfile + keyfile TLS).
        """
        try:
            _txn_host = txn_host if txn_host else host
            _txn_username = txn_username if txn_username else username
            _txn_password = txn_password if txn_password else password
            provider_vars_content = (
                f"# ── PostgreSQL Transaction connection (via PgBouncer pooler) ────────────\n"
                f"postgres:\n"
                f"  host: {_txn_host}\n"
                f"  port: {port}\n"
                f"  dbname: {dbname}\n"
                f"  username: {_txn_username}\n"
                f"  password: {_txn_password}\n"
                f"  tls:\n"
                f"    mode: verify-ca\n"
                + (  # CNPG: CA-only, shared /certs/pg mount
                   "    cafile: /certs/pg/ca.crt\n"
                   if use_cnpg else
                   # Ext. PG: dedicated txn cert path
                   "    cafile: /certs/pg-txn/ca.crt\n"
                   "    certfile: /certs/pg-txn/tls.crt\n"
                   "    keyfile: /certs/pg-txn/tls.key\n"
                ) + f"\n"
                f"# ── PostgreSQL Session connection (direct — bypasses pooler) ─────────\n"
                f"postgres_session:\n"
                f"  host: {host}\n"
                f"  port: {port}\n"
                f"  dbname: {dbname}\n"
                f"  username: {username}\n"
                f"  password: {password}\n"
                f"  tls:\n"
                f"    mode: verify-ca\n"
                + (  # CNPG: CA-only, same /certs/pg mount
                   "    cafile: /certs/pg/ca.crt\n"
                   if use_cnpg else
                   # Ext. PG: session cert path
                   "    cafile: /certs/pg/ca.crt\n"
                   "    certfile: /certs/pg/tls.crt\n"
                   "    keyfile: /certs/pg/tls.key\n"
                ) + f"\n"
                f"# ── Backend provider types ────────────────────────────────────────────────\n"
                f"providers:\n"
                f"  kv:\n"
                f"    type: POSTGRES\n"
                f"  queue:\n"
                f"    type: POSTGRES\n"
                f"  storage:\n"
                f"    type: DIR\n"
                f"    config:\n"
                f"      path: /results\n"
            )

            secret = {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": WDU_PROVIDERS_SECRET_NAME,
                    "namespace": self._namespace,
                    "labels": {
                        "cp4ba.ibm.com/backup-type": "mandatory",
                    },
                },
                "type": "Opaque",
                "stringData": {
                    "provider_vars.yaml": LiteralScalarString(provider_vars_content),
                },
            }

            with open(self._wdu_providers_secret_path, "w") as f:
                self._yaml.dump(secret, f)

            self._generated_files.append(
                ("WDU Providers Secret", self._wdu_providers_secret_path,
                 os.path.getsize(self._wdu_providers_secret_path))
            )
            self._log_info(f"Generated WDU providers secret: {self._wdu_providers_secret_path}")
            return True

        except Exception as e:
            self._log_error(f"Error generating WDU providers secret: {e}")
            if self._logger:
                self._logger.exception("Detailed error:")
            return False

    def generate_wdu_db_secret(self) -> bool:
        """Generate ibm-wdu-db-secret with auto-generated CNPG credentials.

        The CNPG operator expects stringData with keys 'username' and 'password'
        (not the old data.db_user / data.db_password base64 encoding).
        The username is always 'app' — CNPG hard-codes this in its bootstrap.
        """
        try:
            db_password = _generate_password()
            secret = {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": WDU_DB_SECRET_NAME, "namespace": self._namespace},
                "type": "Opaque",
                "stringData": {
                    "username": CNPG_SUPERUSER,
                    "password": db_password,
                },
            }
            with open(self._wdu_db_secret_path, "w") as f:
                self._yaml.dump(secret, f)
            self._generated_files.append(
                ("WDU DB Secret", self._wdu_db_secret_path,
                 os.path.getsize(self._wdu_db_secret_path))
            )
            self._log_info(f"Generated WDU DB secret: {self._wdu_db_secret_path}")
            return True
        except Exception as e:
            self._log_error(f"Error generating WDU DB secret: {e}")
            if self._logger:
                self._logger.exception("Detailed error:")
            return False

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def generate_all(self) -> bool:
        """Generate all requested artifacts based on property flags.

        Postgres external-connection secret is ALWAYS generated (internal or BYO).
        Redis external-connection secret is ALWAYS generated (internal or BYO).

        Internal (IBM-managed) path — postgres.USE_IBM_CNPG=true:
          Secret auto-populated with CNPG-derived host/user/password.
          CNPG Cluster CR also generated.

        External (BYO) path — postgres.USE_IBM_CNPG=false:
          Secret written with user-supplied values from property file
          (or <Required> placeholders if not set).

        Same pattern applies for Redis via redis.USE_IBM_REDIS.

        Properties are now nested:
          mg_props["postgres"]["USE_IBM_CNPG"]   mg_props["redis"]["USE_IBM_REDIS"]
          mg_props["postgres"]["HOSTNAME"]        mg_props["redis"]["HOSTNAME"]
          mg_props["postgres"]["PORT"]            mg_props["redis"]["PORT"]
          mg_props["postgres"]["DATABASE_NAME"]   mg_props["redis"]["PASSWORD"]
          mg_props["postgres"]["USERNAME"]        mg_props["redis"]["USE_TLS"]
          mg_props["postgres"]["PASSWORD"]
          mg_props["postgres"]["SSL_ENABLED"]
          mg_props["postgres"]["SSL_MODE"]

        Returns True if all succeeded.
        """
        mg_pg = self._mg_props.get("postgres", {})
        mg_redis = self._mg_props.get("redis", {})
        # postgres_session / postgres_transaction are the canonical TOML sections;
        # fall back to legacy "postgres" for old property files.
        _wdu_pg_legacy = self._wdu_props.get("postgres", {})
        wdu_pg     = self._wdu_props.get("postgres_session")     or _wdu_pg_legacy
        wdu_pg_txn = self._wdu_props.get("postgres_transaction") or _wdu_pg_legacy

        use_cnpg_mg   = str(mg_pg.get("USE_IBM_CNPG",   False)).lower() in ("true", "1", "yes")
        use_ibm_redis = str(mg_redis.get("USE_IBM_REDIS", False)).lower() in ("true", "1", "yes")
        use_cnpg_wdu  = str(wdu_pg.get("USE_IBM_CNPG",   False)).lower() in ("true", "1", "yes")

        results = []

        # ── MG Postgres ───────────────────────────────────────────────
        if use_cnpg_mg:
            # Internal IBM CNPG path.
            # username is always CNPG_SUPERUSER ("app") — fixed by the operator.
            # password is left empty: CNPG auto-generates it at cluster init time and
            # stores it in ibm-pg-cluster-mg-app. The real value is read from that
            # secret and patched into model-gateway-postgres-external-secret by
            # _extract_and_inject_cnpg_ca_cert() once the cluster is ready.
            results.append(self.generate_cnpg_mg_cr())
            results.append(self.generate_mg_postgres_external_secret(
                host=self.cnpg_mg_hostname(),
                port=DEFAULT_PG_PORT,
                username=CNPG_SUPERUSER,
                password="",
                dbname=DEFAULT_PG_DBNAME,
                parameters=CNPG_PG_SSLMODE,
            ))
        else:
            # External / BYO: build the SSL parameters string from SSL_ENABLED / SSL_MODE
            ssl_enabled = str(mg_pg.get("SSL_ENABLED", False)).lower() in ("true", "1", "yes")
            ssl_mode = str(mg_pg.get("SSL_MODE", "require"))
            if ssl_enabled and ssl_mode in ("verify-ca", "verify-full"):
                parameters = f"sslmode={ssl_mode}&sslrootcert=/postgres-secrets/ca.crt"
            elif ssl_enabled:
                parameters = f"sslmode={ssl_mode}"
            else:
                parameters = "sslmode=disable"

            results.append(self.generate_mg_postgres_external_secret(
                host=str(mg_pg.get("HOSTNAME",      "<Required>")),
                port=str(mg_pg.get("PORT",          DEFAULT_PG_PORT)),
                username=str(mg_pg.get("USERNAME",  "<Required>")),
                password=str(mg_pg.get("PASSWORD",  "<Required>")),
                dbname=str(mg_pg.get("DATABASE_NAME", DEFAULT_PG_DBNAME)),
                parameters=parameters,
            ))

        # ── Redis ─────────────────────────────────────────────────────
        if use_ibm_redis:
            # Internal IBM Redis: use the short master-svc name (in TLS cert SANs)
            # and port 6380 (TLS port). The operator creates the cert at runtime.
            redis_password = _generate_password()
            redis_host = self.redis_master_svc_name()
            results.append(self.generate_redis_cr(redis_password))
            results.append(self.generate_redis_pwd_secret(redis_password))
            results.append(self.generate_mg_redis_external_secret(
                host=redis_host,
                password=redis_password,
                use_tls=True,
            ))
        else:
            # External / BYO: stamp whatever the user set (or placeholders)
            results.append(self.generate_mg_redis_external_secret(
                host=str(mg_redis.get("HOSTNAME", "<Required>")),
                password=str(mg_redis.get("PASSWORD", "<Required>")),
                use_tls=str(mg_redis.get("USE_TLS", False)).lower() in ("true", "1", "yes"),
            ))

        # ── WDU Postgres ──────────────────────────────────────────────
        if use_cnpg_wdu:
            # Internal IBM CNPG path.
            # The CNPG CR was already generated during gather mode into infrastructure/.
            # The providers secret is generated by the caller (prerequisites.py) AFTER
            # the CNPG cluster is Ready (live credentials fetched via
            # fetch_cnpg_wdu_connection()). The CA secret (ccx-wdu-pg-ca) is
            # created automatically by the IBM PG operator — no CA secrets generated here.
            pass
        else:
            # External / BYO: generate providers secret from property file values.
            # Only runs when WDU is configured (wdu_props is non-empty).
            if self._wdu_props:
                _wdu_port = str(wdu_pg.get("PORT", wdu_pg_txn.get("PORT", DEFAULT_PG_PORT)))
                _wdu_db   = str(wdu_pg.get("DATABASE_NAME", wdu_pg_txn.get("DATABASE_NAME", DEFAULT_WDU_PG_DBNAME)))
                results.append(self.generate_providers_secret(
                    # session connection (direct host)
                    host=str(wdu_pg.get("HOSTNAME",     "<Required>")),
                    port=_wdu_port,
                    username=str(wdu_pg.get("USERNAME", "<Required>")),
                    password=str(wdu_pg.get("PASSWORD", "<Required>")),
                    dbname=_wdu_db,
                    # transaction connection (separate pooler host/credentials when set)
                    txn_host=str(wdu_pg_txn.get("HOSTNAME",  wdu_pg.get("HOSTNAME",  "<Required>"))),
                    txn_username=str(wdu_pg_txn.get("USERNAME", wdu_pg.get("USERNAME", "<Required>"))),
                    txn_password=str(wdu_pg_txn.get("PASSWORD", wdu_pg.get("PASSWORD", "<Required>"))),
                ))

        return all(results)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_generated_files(self) -> List[Tuple[str, Path, int]]:
        """Return list of (label, path, size) for all generated files."""
        return self._generated_files

    def get_cnpg_mg_hostname(self) -> str:
        """Return the CNPG read-write hostname for Model Gateway."""
        return self.cnpg_mg_hostname()

    def get_cnpg_wdu_hostname(self) -> str:
        """Return the CNPG read-write hostname for WDU."""
        return self.cnpg_wdu_hostname()
