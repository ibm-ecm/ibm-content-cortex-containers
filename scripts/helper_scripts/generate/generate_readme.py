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
Module for generating README files in the generated artifacts folders.
Provides documentation and usage instructions for each section of generated files.
"""

import os
from pathlib import Path
from typing import Optional, List
from logging import Logger
from datetime import datetime


class GenerateReadme:
    """
    Generate README.md files for each section of the generated artifacts folder.
    
    This class creates comprehensive documentation for:
    - Database SQL scripts
    - Kubernetes Secrets
    - SSL certificate secrets
    - Usage metering metrics
    - AI Services artifacts
    - Custom Resource (CR) files
    """

    def __init__(
        self,
        namespace: str,
        deployment_properties: dict = None,
        db_properties: dict = None,
        model_gateway_properties: dict = None,
        wdu_properties: dict = None,
        logger: Optional[Logger] = None
    ):
        """
        Initialize the README generator.

        Args:
            namespace: Kubernetes namespace for the deployment
            deployment_properties: Dictionary containing deployment configuration
            db_properties: Dictionary containing database configuration
            model_gateway_properties: Dictionary containing Model Gateway configuration
            wdu_properties: Dictionary containing WDU configuration
            logger: Optional logger instance for logging operations
        """
        self._logger = logger
        self._namespace = namespace
        self._deployment_properties = deployment_properties or {}
        self._db_properties = db_properties or {}
        self._mg_properties = model_gateway_properties or {}
        self._wdu_properties = wdu_properties or {}
        
        # Set up paths
        self._base_dir = Path.cwd()
        self._generated_folder = self._base_dir / "generatedFiles" / self._namespace
        
        # Track which components are deployed
        self._cpe_deployed = self._deployment_properties.get("CPE", False)
        self._ban_deployed = self._deployment_properties.get("BAN", False)
        self._graphql_deployed = self._deployment_properties.get("GRAPHQL", False)
        self._cmis_deployed = self._deployment_properties.get("CMIS", False)
        
        # Track if AI Services is deployed
        # We'll determine this dynamically by checking if AI Services secrets exist in generated files
        self._ai_services_deployed = False  # Will be set to True if AI Services secrets are found

        # Track Model Gateway and WDU deployment & infra flags
        self._use_ibm_cnpg_mg = str(self._mg_properties.get("postgres", {}).get("USE_IBM_CNPG", False)).lower() in ("true", "1", "yes")
        self._use_ibm_redis = str(self._mg_properties.get("redis", {}).get("USE_IBM_REDIS", False)).lower() in ("true", "1", "yes")
        # postgres_session is the primary TOML section written by create_wdu_propertyfile();
        # fall back to the legacy bare "postgres" key for property files written before the split.
        _wdu_pg = self._wdu_properties.get("postgres_session") or self._wdu_properties.get("postgres", {})
        self._use_ibm_cnpg_wdu = str(_wdu_pg.get("USE_IBM_CNPG", False)).lower() in ("true", "1", "yes")
        
        # Track if any Content Operator components are deployed
        self._content_deployed = any([self._cpe_deployed, self._ban_deployed, self._graphql_deployed, self._cmis_deployed])
        
        # Track if vault is enabled
        vault_enabled_value = self._deployment_properties.get("VAULT_ENABLED", False)
        if isinstance(vault_enabled_value, bool):
            self._vault_enabled = vault_enabled_value
        else:
            self._vault_enabled = str(vault_enabled_value).lower() == "true"

    def _log_info(self, message: str) -> None:
        """Log an info message if logger is available."""
        if self._logger:
            self._logger.info(message)

    def _log_error(self, message: str) -> None:
        """Log an error message if logger is available."""
        if self._logger:
            self._logger.error(message)

    def _write_readme(self, folder_path: Path, content: str) -> bool:
        """
        Write README.md file to the specified folder.

        Args:
            folder_path: Path to the folder where README should be created
            content: Content to write to the README file

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            readme_path = folder_path / "README.md"
            readme_path.write_text(content, encoding='utf-8')
            self._log_info(f"✓ Generated README: {readme_path}")
            return True
        except Exception as e:
            self._log_error(f"Failed to write README to {folder_path}: {str(e)}")
            return False

    def _get_file_list(self, folder_path: Path, pattern: str = "*") -> List[str]:
        """
        Get list of files in a folder matching the pattern.

        Args:
            folder_path: Path to the folder
            pattern: Glob pattern for file matching

        Returns:
            List of filenames (not full paths)
        """
        if not folder_path.exists():
            return []
        return sorted([f.name for f in folder_path.glob(pattern) if f.is_file() and f.name != "README.md"])
    def _get_secret_ownership(self, spc_file_path: Path) -> str:
        """
        Read the owned-by annotation from a SecretProviderClass YAML file.
        
        Args:
            spc_file_path: Path to the SecretProviderClass YAML file
            
        Returns:
            str: The owned-by annotation value (e.g., "content-operator" or "content-operator,ai-services-operator")
                 Returns empty string if file doesn't exist or annotation not found
        """
        try:
            import yaml
            if not spc_file_path.exists():
                return ""
            
            with open(spc_file_path, 'r') as f:
                spc_data = yaml.safe_load(f)
            
            annotations = spc_data.get('metadata', {}).get('annotations', {})
            return annotations.get('ccx.ibm.com/owned-by', '')
        except Exception as e:
            self._log_error(f"Failed to read ownership from {spc_file_path}: {str(e)}")
            return ""


    @staticmethod
    def generate_infrastructure_readme(
        namespace: str,
        use_mg_cnpg: bool = False,
        use_mg_redis: bool = False,
        output_folder: str = "",
        logger=None,
        use_wdu_cnpg_pooler: bool = False,
        # Legacy aliases kept for any direct callers; map onto new names
        use_ibm_cnpg: bool = False,
        use_ibm_redis: bool = False,
    ) -> bool:
        """Generate infrastructure/README.md covering all IBM-managed infrastructure components.

        Produces a single sequenced guide whose steps are generated dynamically based on
        which components are actually deployed.  Sections for Model Gateway (CNPG, Redis)
        and/or WDU (CNPG cluster + PgBouncer pooler) are included only when the
        corresponding flag is True.  When both are deployed the steps are numbered
        contiguously so the customer follows one document end-to-end.

        Args:
            namespace:          Kubernetes namespace for the deployment.
            use_mg_cnpg:        True when Model Gateway IBM-managed CNPG is selected.
            use_mg_redis:       True when Model Gateway IBM-managed Redis is selected.
            output_folder:      Path to the infrastructure/ folder.
            logger:             Optional logger instance.
            use_wdu_cnpg_pooler: True when WDU IBM-managed CNPG is selected — adds the
                                 WDU cluster and PgBouncer pooler steps.
            use_ibm_cnpg:       Legacy alias for use_mg_cnpg (takes precedence if set).
            use_ibm_redis:      Legacy alias for use_mg_redis (takes precedence if set).

        Returns:
            True if the README was written successfully; False on error.
        """
        # Honour legacy aliases so existing call sites need no changes
        use_mg_cnpg  = use_mg_cnpg  or use_ibm_cnpg
        use_mg_redis = use_mg_redis or use_ibm_redis

        try:
            folder = Path(output_folder)
            folder.mkdir(parents=True, exist_ok=True)

            # ── Derive a context-sensitive title and overview ──────────────────
            _components: list[str] = []
            if use_mg_cnpg or use_mg_redis:
                _components.append("Model Gateway")
            if use_wdu_cnpg_pooler:
                _components.append("Enhanced Extraction (WDU)")
            _component_str = " and ".join(_components)

            lines = [
                "# IBM Infrastructure Deployment Guide",
                "",
                f"> Namespace: `{namespace}`  |  Components: {_component_str}",
                "",
                "## Overview",
                "",
                "This folder contains the Kubernetes Custom Resources (CRs) that must be",
                "deployed **before** you run `python3 prerequisites.py generate`.",
                "",
                "The `generate` command reads live credentials from these running instances",
                "and writes them into the final connection secrets automatically.",
                "**No manual credential copy step is required.**",
                "",
            ]

            # ── Contents table ─────────────────────────────────────────────────
            _table_rows: list[str] = []
            if use_mg_redis:
                _table_rows += [
                    "| `secrets/ibm-redis-mg-secret.yaml` | Redis admin password secret (Model Gateway) |",
                    "| `ibm_redis_cr.yaml` | IBM Redis CR (Model Gateway) |",
                ]
            if use_mg_cnpg:
                _table_rows.append(
                    "| `ibm_pg_cluster_mg_cr.yaml` | CNPG PostgreSQL cluster CR (Model Gateway) |"
                )
            if use_wdu_cnpg_pooler:
                _table_rows += [
                    "| `ibm_pg_cluster_wdu_cr.yaml` | CNPG PostgreSQL cluster CR (WDU) |",
                    "| `ibm_pg_pooler_wdu_cr.yaml` | PgBouncer connection pooler CR (WDU) |",
                ]
            lines += ["## Files in this folder", "", "| File | Purpose |", "| --- | --- |"]
            lines += _table_rows
            lines += [""]

            # ── Prerequisites ──────────────────────────────────────────────────
            lines += [
                "## Prerequisites",
                "",
                "Ensure the following IBM operators are installed in the namespace before",
                "applying the CRs in this folder:",
                "",
            ]
            if use_mg_redis:
                lines.append("- **IBM Redis Operator** — required for `ibm_redis_cr.yaml`")
            if use_mg_cnpg and use_wdu_cnpg_pooler:
                lines.append(
                    "- **IBM CloudNativePG (CNPG) Operator** — required for"
                    " `ibm_pg_cluster_mg_cr.yaml`, `ibm_pg_cluster_wdu_cr.yaml`,"
                    " and `ibm_pg_pooler_wdu_cr.yaml`"
                )
            elif use_mg_cnpg:
                lines.append(
                    "- **IBM CloudNativePG (CNPG) Operator** — required for `ibm_pg_cluster_mg_cr.yaml`"
                )
            elif use_wdu_cnpg_pooler:
                lines.append(
                    "- **IBM CloudNativePG (CNPG) Operator** — required for"
                    " `ibm_pg_cluster_wdu_cr.yaml` and `ibm_pg_pooler_wdu_cr.yaml`"
                )
            lines += [""]

            # ── Numbered deployment steps ──────────────────────────────────────
            step = 1

            if use_mg_redis:
                lines += [
                    f"## Step {step}: Apply Redis credential secret (Model Gateway)",
                    "",
                    "The IBM Redis operator reads its admin password from `ibm-redis-mg-secret`.",
                    "Apply it **before** the Redis CR:",
                    "",
                    "```bash",
                    f"kubectl apply -f secrets/ibm-redis-mg-secret.yaml -n {namespace}",
                    "```",
                    "",
                ]
                step += 1

                lines += [
                    f"## Step {step}: Apply IBM Redis CR (Model Gateway)",
                    "",
                    "```bash",
                    f"kubectl apply -f ibm_redis_cr.yaml -n {namespace}",
                    "```",
                    "",
                    "Watch readiness (≈ 1–3 min):",
                    "",
                    "```bash",
                    f"kubectl get rediscp ibm-redis-mg -n {namespace} -w",
                    "```",
                    "",
                    "Wait until the `STATUS` column shows `Successful` or `Ready`.",
                    "",
                ]
                step += 1

            if use_mg_cnpg:
                lines += [
                    f"## Step {step}: Apply IBM CNPG PostgreSQL CR (Model Gateway)",
                    "",
                    "```bash",
                    f"kubectl apply -f ibm_pg_cluster_mg_cr.yaml -n {namespace}",
                    "```",
                    "",
                    "Watch readiness (≈ 2–5 min):",
                    "",
                    "```bash",
                    f"kubectl get clusters.pg.ibm.com ibm-pg-cluster-mg -n {namespace} -w",
                    "```",
                    "",
                    "Wait until the cluster shows `Cluster in healthy state`.",
                    "",
                ]
                step += 1

            if use_wdu_cnpg_pooler:
                lines += [
                    f"## Step {step}: Apply IBM CNPG PostgreSQL CR (WDU)",
                    "",
                    "```bash",
                    f"kubectl apply -f ibm_pg_cluster_wdu_cr.yaml -n {namespace}",
                    "```",
                    "",
                    "Watch readiness (≈ 2–5 min):",
                    "",
                    "```bash",
                    f"kubectl get clusters.pg.ibm.com ccx-wdu-pg -n {namespace} -w",
                    "```",
                    "",
                    "Wait until the cluster shows `Cluster in healthy state`.",
                    "",
                ]
                step += 1

                lines += [
                    f"## Step {step}: Apply PgBouncer Pooler CR (WDU)",
                    "",
                    "> **Apply this only after `ccx-wdu-pg` is in healthy state.**",
                    ">",
                    "> The PgBouncer pooler multiplexes client connections onto a smaller set",
                    "> of real PostgreSQL server connections (transaction-pooling mode), reducing",
                    "> load on the primary and improving connection scalability.",
                    "",
                    "```bash",
                    f"kubectl apply -f ibm_pg_pooler_wdu_cr.yaml -n {namespace}",
                    "```",
                    "",
                    "Verify the pooler pod is running:",
                    "",
                    "```bash",
                    f"kubectl get pooler ibm-pg-pooler-wdu -n {namespace}",
                    f"kubectl get pods -l pg.ibm.com/poolerName=ibm-pg-pooler-wdu -n {namespace}",
                    "```",
                    "",
                ]
                step += 1

            # ── Verify readiness ───────────────────────────────────────────────
            lines += [
                f"## Step {step}: Verify readiness",
                "",
                "Run a quick sanity check across all deployed infrastructure:",
                "",
                "```bash",
            ]
            if use_mg_redis:
                lines.append(f"kubectl get rediscp ibm-redis-mg -n {namespace}")
                lines.append(f"kubectl get secret ibm-redis-mg-secret -n {namespace}")
            if use_mg_cnpg:
                lines.append(f"kubectl get clusters.pg.ibm.com ibm-pg-cluster-mg -n {namespace}")
                lines.append(f"kubectl get secret ibm-pg-cluster-mg-ca -n {namespace}")
                lines.append(f"kubectl get secret ibm-pg-cluster-mg-app -n {namespace}")
            if use_wdu_cnpg_pooler:
                lines.append(f"kubectl get clusters.pg.ibm.com ccx-wdu-pg -n {namespace}")
                lines.append(f"kubectl get pooler ibm-pg-pooler-wdu -n {namespace}")
                lines.append(f"kubectl get secret ccx-wdu-pg-ca -n {namespace}")
                lines.append(f"kubectl get secret ccx-wdu-pg-app -n {namespace}")
            lines += [
                "```",
                "",
            ]
            step += 1

            lines += [
                f"## Step {step}: Run generate mode",
                "",
                "Once all instances above show ready status, run:",
                "",
                "```bash",
                "python3 prerequisites.py generate",
                "```",
                "",
                "Generate mode will read the live credentials from the cluster automatically",
                "and write fully-populated connection secrets into"
                f" `generatedFiles/{namespace}/secrets/`.",
                "",
                "---",
                "",
                f"*Generated by IBM Content Cortex prerequisites script — namespace: `{namespace}`*",
            ]

            content = "\n".join(lines) + "\n"
            readme_path = folder / "README.md"
            readme_path.write_text(content, encoding="utf-8")
            if logger:
                logger.info(f"Generated infrastructure README: {readme_path}")
            return True

        except Exception as exc:
            if logger:
                logger.error(f"Failed to generate infrastructure README: {exc}")
            return False

    def generate_all_readmes(self) -> bool:
        """
        Generate all README files for the generated artifacts.

        Returns:
            bool: True if all READMEs were generated successfully
        """
        success = True
        
        self._log_info("Generating README files for generated artifacts")
        
        # Generate README for each folder
        if not self.generate_database_readme():
            success = False
        
        if not self.generate_secrets_readme():
            success = False
        
        if not self.generate_ssl_readme():
            success = False
        
        if not self.generate_metrics_readme():
            success = False
        
        if not self.generate_configmaps_readme():
            success = False

        if self._wdu_properties:
            if not self.generate_wdu_readme():
                success = False

        if not self.generate_root_readme():
            success = False
        
        if success:
            self._log_info("✓ All README files generated successfully")
        else:
            self._log_info("⚠ Some README files failed to generate")
        
        # Generate vault READMEs if vault is enabled
        if self._vault_enabled:
            if not self.generate_vault_main_readme():
                success = False
            if not self.generate_vault_json_readme():
                success = False
            if not self.generate_vault_spc_readme():
                success = False

        return success

    def generate_database_readme(self) -> bool:
        """Generate README for the database folder."""
        folder_path = self._generated_folder / "database"
        if not folder_path.exists():
            return True  # Not an error if folder doesn't exist

        files = self._get_file_list(folder_path, "*.sql")
        if not files:
            return True

        db_type = self._db_properties.get("DATABASE_TYPE", "Unknown").upper()
        
        content = f"""# Database SQL Scripts

## Overview

This folder contains SQL scripts for creating and initializing IBM Content Cortex databases.

**Generated for**: {self._namespace}  

**Database Type**: {db_type} 

**Generated on**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Files

"""
        
        for file in files:
            if "GCD" in file.upper():
                content += f"- **{file}**: Global Configuration Database (GCD) - Required for all deployments\n"
            elif "ICN" in file.upper():
                content += f"- **{file}**: IBM Content Navigator database - Required for BAN\n"
            elif "OS" in file.upper() or "createos" in file.lower():
                content += f"- **{file}**: Object Store database(s) - Required for CPE\n"
            elif "modelgateway" in file.lower():
                content += f"- **{file}**: Model Gateway PostgreSQL database - Required when using external PostgreSQL for Model Gateway\n"
            elif "wdu" in file.lower():
                content += f"- **{file}**: WDU (Enhanced Extraction) PostgreSQL database - Required when using external PostgreSQL for WDU\n"

        # Only add database parameters if there are database files
        if files:
            # Check which database files actually exist
            has_gcd = any('GCD' in f.upper() for f in files)
            has_os = any('OS' in f.upper() or 'createos' in f.lower() for f in files)
            has_icn = any('ICN' in f.upper() for f in files)
            has_mg = any('modelgateway' in f.lower() for f in files)
            has_wdu = any('wdu' in f.lower() for f in files)
            
            content += f"""
## Database Script Parameters

These SQL scripts use template variables that are substituted during generation.
"""
            
            # GCD Database parameters
            if has_gcd:
                content += """
### GCD Database (createGCDDB.sql)
- **${{gcd_name}}**: Global Configuration Database name (e.g., GCDDB)
- **${{youruser1}}**: GCD database user who will own the schema
- **${{yourpassword}}**: Password for the GCD database user
- **${{gcd_name}}DATA_TS**: Tablespace for GCD data (auto-created)
- **${{gcd_name}}_TMP_TBS**: Temporary tablespace (auto-created)
- **${{gcd_name}}_1_32K**: Buffer pool for data (auto-created)
- **${{gcd_name}}_2_32K**: Buffer pool for temp space (auto-created)
"""
            
            # Object Store parameters
            if has_os:
                content += """
### Object Store Database (createOS1DB.sql)
- **${{os_name}}**: Object Store database name (e.g., OS1DB)
- **${{youruser1}}**: Object Store database user who will own the schema
- **${{yourpassword}}**: Password for the Object Store database user
- **${{datatablespace}}**: Tablespace for Object Store data
- **${{indextablespace}}**: Tablespace for indexes
- **${{lobtablespace}}**: Tablespace for BLOB/LOB data (optional, commented by default)
- **${{tmp_tablespace}}**: Temporary tablespace
"""
            
            # Navigator parameters
            if has_icn:
                content += """
### Navigator Database (createICNDB.sql)
- **${{icn_name}}**: Navigator database name (e.g., ICNDB)
- **${{youruser1}}**: Navigator database user (granted DBADM)
- **${{yourtablespace}}**: Tablespace for Navigator data (Oracle only)
- **${{yourschema}}**: Schema name for Navigator (Oracle only)
"""

            # Model Gateway parameters
            if has_mg:
                content += """
### Model Gateway Database (createModelGatewayDB.sql)
- **${{mg_name}}**: Model Gateway database name (from `postgres.DATABASE_NAME`, default: `modelgateway`)
- **${{youruser1}}**: PostgreSQL username (from `postgres.USERNAME`)
- **${{yourpassword}}**: PostgreSQL password (from `postgres.PASSWORD`)

> ℹ️ Only generated when `postgres.USE_IBM_CNPG = false`. IBM-managed CNPG bootstraps its own database automatically.
"""

            # WDU parameters
            if has_wdu:
                content += """
### WDU Database (createWDUDB.sql)
- **${{wdu_name}}**: WDU database name (from `postgres.DATABASE_NAME`, default: `wdu`)
- **${{youruser1}}**: PostgreSQL username (from `postgres.USERNAME`)
- **${{yourpassword}}**: PostgreSQL password (from `postgres.PASSWORD`)

> ℹ️ Only generated when `postgres.USE_IBM_CNPG = false`. IBM-managed CNPG bootstraps its own database automatically.
"""
        
        content += f"""
## Usage

### Execute SQL Scripts

Run these scripts on your database server with administrator privileges:

```bash
# For DB2
db2 -tvf createGCD.sql
db2 -tvf createICN.sql  # If BAN deployed
db2 -tvf createos.sql

# For Oracle
sqlplus / as sysdba @createGCD.sql

# For PostgreSQL
psql -U postgres -f createGCD.sql
psql -U postgres -f createModelGatewayDB.sql  # If Model Gateway with external PostgreSQL
psql -U postgres -f createWDUDB.sql           # If WDU with external PostgreSQL

# For SQL Server
sqlcmd -S <server> -U <user> -P <password> -i createGCD.sql
```

### Execution Order

1. **createGCD.sql** - Must be created first
2. **createICN.sql** - If Business Automation Navigator is deployed
3. **createos.sql** - Create all Object Store databases
4. **createModelGatewayDB.sql** - If Model Gateway is deployed with external PostgreSQL (`USE_IBM_CNPG=false`)
5. **createWDUDB.sql** - If WDU is deployed with external PostgreSQL (`USE_IBM_CNPG=false`)

### Security Notes

⚠️ These files contain database passwords. Protect and delete after use.

### Next Steps

After database creation:
1. Verify database connectivity from Kubernetes cluster
2. Apply secrets from `../secrets/` folder
3. Apply SSL secrets from `../ssl/` folder (if SSL enabled)
4. Deploy the Custom Resource from parent folder

---
*Generated by IBM Content Cortex Prerequisites Script*
"""

        return self._write_readme(folder_path, content)

    def generate_secrets_readme(self) -> bool:
        """Generate README for the secrets folder."""
        folder_path = self._generated_folder / "secrets"
        if not folder_path.exists():
            return True

        files = self._get_file_list(folder_path, "*.yaml")
        if not files:
            return True

        content = f"""# Kubernetes Secrets

## Overview

This folder contains Kubernetes Secret manifests for IBM Content Cortex components.

**Generated for**: {self._namespace}  

**Generated on**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Files

"""

        for file in files:
            if "fncm-secret" in file:
                content += f"- **{file}**: CPE admin credentials\n"
            elif "ban-secret" in file:
                content += f"- **{file}**: Navigator admin credentials\n"
            elif "ldap-bind-secret" in file:
                content += f"- **{file}**: LDAP bind credentials\n"
            elif "idp-oidc-secret" in file or "idp" in file and "oidc" in file:
                content += f"- **{file}**: Identity Provider OIDC configuration\n"
            elif "ai-services-oidc" in file:
                content += f"- **{file}**: AI Services OIDC client credentials\n"
            elif "providers-config" in file:
                content += f"- **{file}**: AI Services Provider Configuration (models, endpoints, API keys)\n"
            elif "ai-services" in file:
                content += f"- **{file}**: AI Services credentials\n"
            elif "scim" in file:
                content += f"- **{file}**: SCIM server credentials\n"
            elif "ier" in file:
                content += f"- **{file}**: IBM Enterprise Records credentials\n"
            elif "iccsap" in file:
                content += f"- **{file}**: ICC SAP credentials\n"
            elif "icc" in file:
                content += f"- **{file}**: ICC (Integrated Content Capture) credentials\n"
            elif "model-gateway-postgres-external-secret" in file:
                content += f"- **{file}**: Model Gateway PostgreSQL external-connection secret (host, port, username, password, dbname, parameters)\n"
            elif "model-gateway-redis-external-secret" in file:
                content += f"- **{file}**: Model Gateway Redis external-connection secret (redis-url-ssl1 or redis-url)\n"
            elif "ibm-redis-mg-secret" in file:
                content += f"- **{file}**: IBM Redis operator credential secret (admin_password, default_password, password)\n"

        # Only add parameter descriptions if there are relevant secrets
        if files:
            content += f"""
## Secret Parameters
"""
            
            # Check which secret files actually exist
            has_fncm_secret = any('fncm-secret' in f for f in files)
            has_ban_secret = any('ban-secret' in f for f in files)
            has_ldap_secret = any('ldap-bind-secret' in f or 'ldap' in f for f in files)
            has_idp_oidc = any('idp-oidc-secret' in f or ('idp' in f and 'oidc' in f) for f in files)
            has_ai_oidc = any('ai-services-oidc' in f for f in files)
            has_providers_config = any('providers-config' in f for f in files)
            has_scim = any('scim' in f for f in files)
            has_mg_postgres_ext = any('model-gateway-postgres-external-secret' in f for f in files)
            has_mg_redis_ext = any('model-gateway-redis-external-secret' in f for f in files)
            has_redis_pwd = any('ibm-redis-mg-secret' in f for f in files)
            has_mg_db_secret = has_mg_postgres_ext  # legacy alias kept for section gating below
            # CPE Admin Secret
            if has_fncm_secret:
                content += """
### CPE Admin Secret (fncm-secret)
- **appLoginUsername**: CPE administrator username
- **appLoginPassword**: CPE administrator password (XOR encoded)
- **keystorePassword**: Keystore password for CPE SSL/TLS (XOR encoded)
- **ltpaPassword**: LTPA key password for SSO (XOR encoded)
- **gcdDBUsername**: GCD database username
- **gcdDBPassword**: GCD database password (XOR encoded)
- **{OS_LABEL}DBUsername**: Object Store database username (e.g., OS1DBUsername)
- **{OS_LABEL}DBPassword**: Object Store database password (XOR encoded)
"""
            
            # Navigator Admin Secret
            if has_ban_secret:
                content += """
### Navigator Admin Secret (ban-secret)
- **navigatorDBUsername**: Navigator database username
- **navigatorDBPassword**: Navigator database password (XOR encoded)
- **appLoginUsername**: Navigator administrator username
- **appLoginPassword**: Navigator administrator password (XOR encoded)
- **keystorePassword**: Keystore password for Navigator SSL/TLS (XOR encoded)
- **ltpaPassword**: LTPA key password for SSO (XOR encoded)
- **jMailUsername**: Email server username (if configured)
- **jMailPassword**: Email server password (XOR encoded, if configured)
"""
            
            # LDAP Bind Secret
            if has_ldap_secret:
                content += """
### LDAP Bind Secret (ldap-bind-secret)
- **ldapUsername**: LDAP bind DN (Distinguished Name)
- **ldapPassword**: LDAP bind password (XOR encoded)
- **ldap{ID}Username**: Additional LDAP bind DN (for multi-LDAP, e.g., ldap2Username)
- **ldap{ID}Password**: Additional LDAP bind password (XOR encoded, for multi-LDAP)
"""
            
            # IDP OIDC Secret
            if has_idp_oidc:
                content += """
### Identity Provider OIDC Secret (idp-oidc-secret)
- **client_id**: OIDC client identifier
- **client_secret**: OIDC client secret (XOR encoded)
"""
            
            # AI Services OIDC Secret
            if has_ai_oidc:
                content += """
### AI Services OIDC Secret (ai-services-oidc-secret)
- **client_id**: AI Services OIDC client identifier (base64 encoded)
- **client_secret**: AI Services OIDC client secret (base64 encoded)
"""
            
            # AI Services Provider Configuration
            if has_providers_config:
                content += """
### AI Services Provider Configuration Secret (providers-config-secret)
- **providers_config.json**: JSON configuration containing:
  - **active_llm**: Currently active LLM model identifier
  - **llms**: Object mapping model IDs to configurations
    - **provider**: Provider type ("watsonx", "azure")
    - **deployment_mode**: Deployment mode ("saas", "lightweight")
    - **url**: API endpoint URL
    - **api_key**: API authentication key
    - **model**: Model identifier
    - **max_completion_tokens**: Maximum completion tokens
    - **temperature**: Sampling temperature (0.0-1.0)
    - **context_window_token_limit**: Context window size
    - Additional provider-specific fields (space_id, instance_id, username, version, etc.)
"""
            
            # SCIM Server Secret
            if has_scim:
                content += """
### SCIM Server Secret (scim-secret)
- **scimUsername**: SCIM client ID
- **scimPassword**: SCIM client secret (XOR encoded)
"""

            # Model Gateway Postgres External Secret
            if has_mg_postgres_ext:
                cnpg_ssl_note = ""
                if self._use_ibm_cnpg_mg:
                    cnpg_ssl_note = """
> **IBM-managed CNPG:** `username` is always `app` (fixed by the CNPG operator).
> `password` and `ca.crt` are injected automatically into this secret once the CNPG
> cluster is ready — `prerequisites.py validate` handles this. If running manually,
> see the deployment steps below for the exact `kubectl patch` commands.
"""
                content += f"""
### Model Gateway Postgres External Secret (model-gateway-postgres-external-secret)
Required by the Model Gateway operator when `deploy_postgres: false` (always our case).
- **host**: PostgreSQL hostname / FQDN
- **port**: PostgreSQL port (default: `5432`)
- **username**: Database username — always `app` when IBM-managed CNPG is used (fixed by the operator, not user-configurable)
- **password**: Database password — for IBM-managed CNPG, auto-injected from `ibm-pg-cluster-mg-app` at apply time; fill in manually for BYO PostgreSQL
- **dbname**: Database name (default: `modelgateway`)
- **parameters**: SSL connection string (default: `sslmode=require`; `sslmode=verify-ca&sslrootcert=/postgres-secrets/ca.crt` for IBM-managed CNPG)
- **ca.crt** *(required for verify-ca / verify-full)*: CA certificate PEM — for IBM-managed CNPG, auto-injected from `ibm-pg-cluster-mg-ca` at apply time
- **client.crt** *(optional)*: Client certificate PEM — for mTLS
- **client.key** *(optional)*: Client private key PEM — for mTLS
{cnpg_ssl_note}"""

            # Model Gateway Redis External Secret
            if has_mg_redis_ext:
                content += """
### Model Gateway Redis External Secret (model-gateway-redis-external-secret)
Referenced by the MG CR via `externalRedisSecret`. Operator resolves `external_redis_url_key` by scanning which key is present.
- **redis-url-ssl1** *(TLS)*: `rediss://:<password>@<host>:<port>/0` — operator finds this key → `external_redis_url_key = "redis-url-ssl1"` → TLS path
- **redis-url** *(plain)*: `redis://:<password>@<host>:<port>/0` — used when `redis-url-ssl1` is absent
Only one key is written by prerequisites generate:
  - `MG_USE_IBM_REDIS=true`  → `redis-url-ssl1` (IBM Redis operator creates `ibm-redis-mg-cert` at runtime; referenced via `externalRedisCertificateSecret` in the MG CR)
  - `MG_USE_IBM_REDIS=false` and `MG_REDIS_USE_TLS=true`  → `redis-url-ssl1`
  - `MG_USE_IBM_REDIS=false` and `MG_REDIS_USE_TLS=false` → `redis-url`
"""

            # Redis Credential Secret
            if has_redis_pwd:
                content += """
### Redis Credential Secret (ibm-redis-mg-secret)
Consumed by the IBM Redis operator Ansible role. Auto-generated when MG_USE_IBM_REDIS=true.
- **password**: Redis password
- **admin_password**: Redis admin password (same value — required by operator)
- **default_password**: Redis default password (same value — required by operator)
"""

        content += f"""
## Usage

### Apply All Secrets

```bash
kubectl apply -f . -n {self._namespace}
kubectl get secrets -n {self._namespace}
```

### Apply Individual Secret

```bash
kubectl apply -f <secret-name>.yaml -n {self._namespace}
```

### Security Best Practices

⚠️ **CRITICAL**:
- Restrict file permissions: `chmod 600 *.yaml`
- Do not commit to version control
- Delete after successful deployment
- Use Kubernetes RBAC to restrict access
- Enable encryption at rest
- Rotate credentials regularly

### Updating Secrets

```bash
kubectl delete secret <secret-name> -n {self._namespace}
kubectl apply -f <secret-name>.yaml -n {self._namespace}
# Restart affected pods
kubectl rollout restart deployment/<deployment-name> -n {self._namespace}
```

### Next Steps

1. Apply SSL secrets from `../ssl/` folder
   - Includes WDU external-PostgreSQL TLS secrets (`ibm-ccx-wdu-db-session-ssl-secret.yaml`,
     `ibm-ccx-wdu-db-transaction-ssl-secret.yaml`) when `USE_IBM_CNPG=false`
2. Apply ConfigMaps from `../configmaps/` folder (if AI Services)
3. Deploy Custom Resource from parent folder

---
*Generated by IBM Content Cortex Prerequisites Script*
"""

        return self._write_readme(folder_path, content)

    def generate_ssl_readme(self) -> bool:
        """Generate README for the SSL folder."""
        folder_path = self._generated_folder / "ssl"
        if not folder_path.exists():
            return True

        files = self._get_file_list(folder_path, "*.yaml")
        if not files:
            return True

        content = f"""# SSL Certificate Secrets

## Overview

This folder contains SSL/TLS certificate secrets for secure communication.

**Generated for**: {self._namespace}  

**Generated on**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Files

"""

        for file in files:
            if "gcd-ssl" in file:
                content += f"- **{file}**: GCD database SSL certificate\n"
            elif "os-ssl" in file or ("os" in file and "ssl" in file):
                content += f"- **{file}**: Object Store database SSL certificate\n"
            elif "icn-ssl" in file:
                content += f"- **{file}**: ICN database SSL certificate\n"
            elif "ldap-ssl" in file:
                content += f"- **{file}**: LDAP server SSL certificate\n"
            elif "scim-ssl" in file:
                content += f"- **{file}**: SCIM server SSL certificate\n"
            elif "graphql-ssl" in file:
                content += f"- **{file}**: GraphQL API SSL certificate\n"
            elif "idp-ssl" in file:
                content += f"- **{file}**: Identity Provider SSL certificate\n"
            elif "idp-public-key" in file:
                content += f"- **{file}**: IDP public key for JWT token verification\n"
            elif "trusted-cert" in file:
                content += f"- **{file}**: Trusted CA certificate\n"
            elif "wdu-db-session-ssl-secret" in file:
                content += f"- **{file}**: WDU external PostgreSQL — session-pooler TLS certificates (ca.crt, tls.crt, tls.key)\n"
            elif "wdu-db-transaction-ssl-secret" in file:
                content += f"- **{file}**: WDU external PostgreSQL — transaction-pooler TLS certificates (ca.crt, tls.crt, tls.key)\n"

        # Only add SSL parameters if there are SSL secrets
        if files:
            content += f"""
## SSL Certificate Parameters
"""
            
            # Check which SSL files actually exist and show parameters accordingly
            has_db_ssl = any('gcd-ssl' in f or 'os-ssl' in f or 'icn-ssl' in f for f in files)
            has_ldap_ssl = any('ldap-ssl' in f for f in files)
            has_graphql_ssl = any('graphql-ssl' in f for f in files)
            has_idp_ssl = any('idp-ssl' in f for f in files)
            has_idp_public_key = any('idp-public-key' in f for f in files)
            has_trusted_cert = any('trusted-cert' in f for f in files)
            has_wdu_pg_ssl = any('wdu-db-session-ssl-secret' in f or 'wdu-db-transaction-ssl-secret' in f for f in files)

            # Database SSL secrets (Content Operator)
            if has_db_ssl:
                content += """
### Database SSL Secrets (gcd-ssl, os-ssl, icn-ssl)
- **tls.crt**: Base64-encoded SSL certificate (PEM format)
"""
            
            # LDAP SSL (Content Operator)
            if has_ldap_ssl:
                content += """
### LDAP SSL Secret (ldap-ssl)
- **tls.crt**: Base64-encoded LDAP server certificate (PEM format)
"""
            
            # GraphQL SSL (Content Operator or AI Services)
            if has_graphql_ssl:
                content += """
### GraphQL SSL Secret (graphql-ssl-secret)
- **tls.crt**: Base64-encoded GraphQL server certificate (PEM format)
"""
            
            # IDP SSL (Content Operator or AI Services)
            if has_idp_ssl:
                content += """
### IDP SSL Secret (idp-ssl-secret)
- **tls.crt**: Base64-encoded IDP server certificate (PEM format)
"""
            
            # IDP Public Key (Content Operator or AI Services)
            if has_idp_public_key:
                content += """
### IDP Public Key Secret (idp-public-key-secret)
- **public.pem**: Base64-encoded RSA/ECDSA public key in PEM format for JWT verification
  - Fetched from IDP JWKS endpoint and converted to PEM format
  - Used for validating JWT tokens signed by the Identity Provider
"""
            
            # Trusted certs
            if has_trusted_cert:
                content += """
### Trusted Certificate Secrets (trusted-cert-*)
- **tls.crt**: Base64-encoded trusted CA certificate (PEM format)
"""

            # WDU external PostgreSQL SSL secrets
            if has_wdu_pg_ssl:
                content += """
### WDU External PostgreSQL TLS Secrets
Used when `USE_IBM_CNPG=false` and `SSL_ENABLED=true` in the WDU property file.
Two secrets are generated — one per PgBouncer pooler — with identical key names:
- **ca.crt**: Base64-encoded CA certificate that signed the PostgreSQL server certificate (PEM)
- **tls.crt**: Base64-encoded client certificate for mutual TLS (mTLS) authentication (PEM)
- **tls.key**: Base64-encoded client private key for mTLS authentication (PEM)

Source folders (populated before running `prerequisites.py generate`):
- Session pooler:      `propertyFile/<namespace>/ssl-certs/wdu/pg_sess/{serverca,clientcert,clientkey}/`
- Transaction pooler:  `propertyFile/<namespace>/ssl-certs/wdu/pg_txn/{serverca,clientcert,clientkey}/`
"""
        
        content += f"""
## Usage

### Apply All SSL Secrets

```bash
kubectl apply -f . -n {self._namespace}
kubectl get secrets -n {self._namespace} | grep ssl
```

### Verify Certificates

```bash
# Check certificate expiration
kubectl get secret <ssl-secret> -n {self._namespace} -o jsonpath='{{.data.tls\\.crt}}' | base64 -d | openssl x509 -enddate -noout

# View certificate details
kubectl get secret <ssl-secret> -n {self._namespace} -o jsonpath='{{.data.tls\\.crt}}' | base64 -d | openssl x509 -text -noout
```

### Certificate Management

#### Check Expiration

Monitor certificate expiration dates and renew before expiry.

#### Certificate Renewal

1. Generate or obtain new certificates
2. Update property files with new certificate paths
3. Re-run generate command
4. Apply updated SSL secrets
5. Restart affected pods

### Trusted Certificates

If `trusted-certs/` subfolder exists:

```bash
kubectl apply -f trusted-certs/ -n {self._namespace}
```

### Security Notes

⚠️ **SSL SECURITY**:
- Store private keys securely
- Use strong encryption
- Validate certificate chains
- Disable weak protocols
- Monitor expiration dates
- Rotate certificates regularly

### Next Steps

1. Verify certificates are valid
2. Test SSL connectivity
3. Deploy Custom Resource
4. Monitor for SSL errors

---
*Generated by IBM Content Cortex Prerequisites Script*
"""

        return self._write_readme(folder_path, content)

    def generate_metrics_readme(self) -> bool:
        """Generate README for the metrics folder."""
        folder_path = self._generated_folder / "metrics"
        if not folder_path.exists():
            return True

        files = self._get_file_list(folder_path, "*.yaml")
        if not files:
            return True

        content = f"""# Usage Metering Metrics

## Overview

This folder contains IBM Service Meter Definition files for license tracking and usage reporting.

**Generated for**: {self._namespace}  

**Generated on**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Files

"""

        for file in files:
            if "cpe-metrics" in file:
                content += f"- **{file}**: CPE instance count and usage metrics\n"
            elif "graphql-metrics" in file:
                content += f"- **{file}**: GraphQL service usage metrics\n"
            elif "cmis-metrics" in file:
                content += f"- **{file}**: CMIS service usage metrics\n"

        content += f"""
## Usage

### Prerequisites

- IBM Usage Metering Operator installed
- License Service configured
- Appropriate RBAC permissions

### Apply Metrics

```bash
kubectl apply -f . -n {self._namespace}
kubectl get ibmservicemeterdefinitions -n {self._namespace}
```

### Verify Metrics

```bash
# List metrics
kubectl get ibmservicemeterdefinitions -n {self._namespace}

# Describe metric
kubectl describe ibmservicemeterdefinition <metric-name> -n {self._namespace}

# Check status
kubectl get ibmservicemeterdefinition <metric-name> -n {self._namespace} -o jsonpath='{{.status}}'
```

### Monitoring

```bash
# Check operator logs
kubectl logs -n ibm-common-services deployment/ibm-usage-metering-operator

# Verify component pods
kubectl get pods -n {self._namespace} -l app=<component>
```

### License Compliance

Access usage reports through:
1. License Service UI
2. License Service API
3. IBM License Metric Tool

### Troubleshooting

**Metrics not collected**:
- Check operator status
- Verify metric definition
- Check component pod labels

**Incorrect counts**:
- Verify pods are running
- Check metric definition matches labels

### Next Steps

1. Verify metrics are being collected
2. Check License Service for usage data
3. Set up monitoring and alerting
4. Schedule regular compliance reviews

---
*Generated by IBM Content Cortex Prerequisites Script*
"""

        return self._write_readme(folder_path, content)

    def generate_configmaps_readme(self) -> bool:
        """Generate README for the configmaps folder."""
        folder_path = self._generated_folder / "configmaps"
        if not folder_path.exists():
            return True

        files = self._get_file_list(folder_path, "*.yaml")
        if not files:
            return True

        content = f"""# ConfigMaps

## Overview

This folder contains Kubernetes ConfigMap manifests for AI Services integration.

**Generated for**: {self._namespace}  

**Generated on**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Files

"""

        for file in files:
            if "ai-services-integration" in file:
                content += f"- **{file}**: AI Services integration configuration (GraphQL, OIDC, JWT, CORS)\n"
            else:
                content += f"- **{file}**: Configuration settings\n"

        content += f"""
## Usage

### Apply ConfigMaps

```bash
kubectl apply -f . -n {self._namespace}
kubectl get configmaps -n {self._namespace}
```

### View Configuration

```bash
kubectl get configmap <configmap-name> -n {self._namespace} -o yaml
```

### Update ConfigMap

```bash
kubectl replace -f <configmap-name>.yaml -n {self._namespace}
# Restart pods to pick up changes
kubectl rollout restart deployment/<deployment-name> -n {self._namespace}
```

### Configuration Details

The AI Services integration ConfigMap contains:
- **GraphQL Integration**: Endpoint URL and SSL certificate reference
- **Authentication**: JWT and OIDC configuration for secure access
- **CORS Settings**: Allowed origins for cross-origin requests
- **Object Store**: Target object store for content operations
- **IDP Configuration**: Identity provider endpoints and secrets

## ConfigMap Parameters

### AI Services Integration Configuration (ibm-ai-services-integration-config)

All values are stored as strings in the ConfigMap's `data` section.

#### GraphQL Integration
- **graphql_url**: GraphQL API endpoint URL (includes /content-services-graphql/graphql path)
- **graphql_cert_secret**: Name of secret containing GraphQL SSL certificate (e.g., 'ibm-graphql-ssl-secret')
- **object_stores**: Object Store symbolic name (e.g., 'OS1')
- **auth_mode**: Authentication mode ('dual', 'oidc', or 'basic')
- **cors_allowed_origins**: CORS allowed origins (Navigator external URL)

#### JWT Configuration
- **jwt_algorithm**: JWT signing algorithm (always 'RS256')
- **jwt_audience**: JWT audience claim (matches OIDC CLIENT_ID)
- **jwt_issuer**: JWT issuer claim (IDP issuer URL from DISCOVERY_ENDPOINT)
- **jwt_jws_url**: JWKS endpoint URL for JWT public key verification
- **jwt_public_key_secret**: Name of secret containing IDP public key (always 'ibm-idp-public-key-secret')
- **jwt_required_scopes**: Required JWT scopes (always 'openid,profile,email')

#### OIDC Configuration
- **oidc_auth_server**: OIDC authorization endpoint (derived from DISCOVERY_ENDPOINT + /protocol/openid-connect/auth)
- **oidc_config_url**: OIDC discovery endpoint URL (from IDP DISCOVERY_ENDPOINT)
- **oidc_client_secret**: Name of secret containing OIDC client credentials (always 'ibm-ai-services-oidc-secret')
- **oidc_ssl_secret**: Name of secret containing IDP SSL certificate (always 'ibm-idp-ssl-secret')
"""
        
        content += """

### Best Practices

1. Keep ConfigMaps in version control
2. Document configuration changes
3. Test changes in non-production first
4. Monitor pod restarts after updates

### Next Steps

1. Verify AI Services pods are running
2. Check pod logs for configuration loading
3. Test AI Services functionality

---
*Generated by IBM Content Cortex Prerequisites Script*
"""

        return self._write_readme(folder_path, content)

    def generate_wdu_readme(self) -> bool:
        """Generate README for WDU (Enhanced Extraction) artifacts.

        Documents the correct apply order for all WDU secrets, ConfigMap, and CR,
        distinguishing the internal-CNPG and external-Postgres paths.
        Only written when WDU properties are present.

        Returns:
            bool: True if the README was written successfully.
        """
        if not self._wdu_properties:
            return True  # Not configured — not an error

        folder_path = self._generated_folder
        if not folder_path.exists():
            return True

        use_cnpg = self._use_ibm_cnpg_wdu
        ns = self._namespace
        pg_source = "IBM-managed CNPG cluster (ccx-wdu-pg)" if use_cnpg else "external PostgreSQL"

        # Reflect the same topology logic used in GenerateWDU.generate_cr()
        content_deployed = any([self._cpe_deployed, self._ban_deployed, self._graphql_deployed, self._cmis_deployed])
        if content_deployed:
            deployment_mode = "Content + WDU (co-deployed)"
            root_ca_secret = "content-root-ca"
            deployment_context = "FNCM"
            ca_note = (
                "WDU shares the Content operator's CA (`content-root-ca`). "
                "Ensure the Content operator is deployed in the same namespace before applying the WDU CR."
            )
        else:
            deployment_mode = "WDU standalone"
            root_ca_secret = "wdu-root-ca"
            deployment_context = "Standalone"
            ca_note = (
                "WDU uses its own CA (`wdu-root-ca`). "
                "No Content operator is required in this namespace."
            )

        content = f"""# Enhanced Extraction (WDU) — Generated Artifacts

## Overview

This document describes the Kubernetes artifacts generated for IBM Watson Document
Understanding (WDU / Enhanced Extraction) and the correct order in which to apply them.

**Namespace**: {ns}
**Deployment mode**: {deployment_mode}
**PostgreSQL source**: {pg_source}
**Deployment context** (`sc_deployment_context`): `{deployment_context}`
**Root CA secret** (`root_ca_secret`): `{root_ca_secret}`
**Generated on**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

> **ℹ️ CA secret note:** {ca_note}

---

## Files (apply in this order)

| # | File | Kind | Description |
|---|------|------|-------------|
| 1 | `ibm_pg_cluster_wdu_cr.yaml` | `Cluster` (CNPG) | Creates the PostgreSQL cluster for WDU (internal path only) |
| 2 | `secrets/ibm-ccx-wdu-providers-secret.yaml` | `Secret` | WDU DB connection config (`provider_vars.yaml` block scalar) |
| 2b | `ssl/ibm-ccx-wdu-db-session-ssl-secret.yaml` | `Secret` | TLS certificates for session-pooler (ca.crt, tls.crt, tls.key) |
| 2b | `ssl/ibm-ccx-wdu-db-transaction-ssl-secret.yaml` | `Secret` | TLS certificates for transaction-pooler (ca.crt, tls.crt, tls.key) |
| 2b | `secrets/ccx-wdu-pg-ca.yaml` | `Secret` | Same CA cert — operator-hardcoded volume mount name |
| 3 | `configmaps/ibm-ccx-wdu-config.yaml` | `ConfigMap` | Ties all secret names together; read by the WDU CR |
| 4 | `ibm_wdu_cr_production.yaml` | `CCXWDUServices` | The main WDU operator CR — apply **last** |

> ⚠️  **The `ccx-wdu-pg-ca` secret is not a typo.** The WDU operator hardcodes this volume-mount
> name regardless of what `SESSION_SSL_SECRET_NAME` / `TRANSACTION_SSL_SECRET_NAME` are set to.
> All three CA secrets (2b) contain the same `ca.crt` content.

---

## Step-by-Step Apply Order

### Step 0 — Set your namespace

```bash
export NS={ns}
```

---
"""

        if use_cnpg:
            content += f"""\
### Step 1 — Apply the IBM-managed CNPG Cluster CR

```bash
kubectl apply -f ibm_pg_cluster_wdu_cr.yaml -n $NS
```

Wait for the cluster to become healthy (≈2–5 min):

```bash
kubectl get clusters.pg.ibm.com ccx-wdu-pg -n $NS -w
# Ready when: Ready = 1/1   Phase = "Cluster in healthy state"
```

> **Note:** During `generate` mode (`prerequisites.py generate`), the script
> fetches the CNPG CA cert and `app` user password live from the cluster and
> embeds them directly into the generated secrets (steps 2 and 2b below).
> You do **not** need to extract them manually.

---

"""
        else:
            content += """\
### Step 1 — (External Postgres — no CNPG cluster to apply)

Your external PostgreSQL server is already running. The connection details
were read from your WDU property file during `prerequisites.py generate`.

TLS certificates were read from the per-pooler subdirectories on disk:
- Session pooler CA / client cert / key: `ssl-certs/wdu/pg_sess/{serverca,clientcert,clientkey}/`
- Transaction pooler CA / client cert / key: `ssl-certs/wdu/pg_txn/{serverca,clientcert,clientkey}/`

---

"""

        content += f"""\
### Step 2 — Apply the providers secret

```bash
kubectl apply -f secrets/ibm-ccx-wdu-providers-secret.yaml -n $NS
```

---

### Step 2b — Apply the CA/TLS secrets

The session and transaction TLS secrets live in the `ssl/` subfolder; the operator-hardcoded
CA secret lives in `secrets/`:

```bash
kubectl apply -f ssl/ibm-ccx-wdu-db-session-ssl-secret.yaml -n $NS
kubectl apply -f ssl/ibm-ccx-wdu-db-transaction-ssl-secret.yaml -n $NS
kubectl apply -f secrets/ccx-wdu-pg-ca.yaml -n $NS
```

---

### Step 3 — Apply the ConfigMap

```bash
kubectl apply -f configmaps/ibm-ccx-wdu-config.yaml -n $NS
```

---

### Step 4 — Apply the WDU CR

```bash
kubectl apply -f ibm_wdu_cr_production.yaml -n $NS
```

Watch the operator reconcile:

```bash
kubectl get ccxwduservices enhanced-extraction -n $NS -w
# Phase = Running   Ready = True
```

Check all 5 component deployments:

```bash
kubectl get deployments -n $NS | grep wdu
```

---

## Automated Application

`python3 prerequisites.py validate --apply` handles this entire sequence
automatically, including readiness polling for the CNPG cluster before
generating the secrets.

---

## Troubleshooting

```bash
# Check operator logs
kubectl logs -l control-plane=ibm-ccx-wdu-services-operator -n $NS -f

# Check CR events
kubectl describe ccxwduservices enhanced-extraction -n $NS

# Check CNPG cluster status (internal path only)
kubectl describe cluster ccx-wdu-pg -n $NS

# List all WDU pods
kubectl get pods -n $NS | grep wdu
```

### Common issues

- **Pods stuck in `Pending`**: Check PVC availability — the WDU CR requires a
  block-mode RWO PVC for the result store (see `datavolume.existing_pvc_for_ccxwdu`
  in the CR).
- **`ccx-wdu-pg-ca` not found**: Ensure step 3b was applied before the CR.
- **`provider_vars.yaml` parsing errors**: The providers secret must contain a
  valid YAML literal block scalar. Do not base64-encode or JSON-escape the value.
- **`WXAI_SECRET_NAME` empty in ConfigMap**: Expected when WatsonX AI is disabled
  (`WDU_ENABLE_WXAI=false`). The WDU operator treats an empty string as "not configured".

---
*Generated by IBM Content Cortex Prerequisites Script*
"""

        return self._write_readme(folder_path, content)


    def generate_root_readme(self) -> bool:
        """Generate README for the root generated folder."""
        folder_path = self._generated_folder
        if not folder_path.exists():
            return False

        cr_files = self._get_file_list(folder_path, "*_cr_*.yaml")
        
        content = f"""# IBM Content Cortex Generated Artifacts

## Overview

This folder contains all generated Kubernetes artifacts for deploying IBM Content Cortex and AI Services.

**Namespace**: {self._namespace}  

**Generated on**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Folder Structure

```
{self._namespace}/
├── README.md                          # This file
├── ibm_content_cr_production.yaml     # Content Operator CR (if configured)
├── ibm_ai_services_cr_production.yaml # AI Services CR (if configured)
├── ibm_model_gateway_cr_production.yaml # Model Gateway CR (if configured)
├── ibm_wdu_cr_production.yaml         # Enhanced Extraction (WDU) CR (if configured)
├── ibm_pg_cluster_mg_cr.yaml          # CNPG PostgreSQL Cluster for Model Gateway (if configured)
├── ibm_pg_cluster_wdu_cr.yaml         # CNPG PostgreSQL Cluster for WDU (if configured)
├── database/                          # SQL scripts
│   ├── README.md
│   └── *.sql
"""

        if self._vault_enabled:
            content += """\
├── vault/                             # HashiCorp Vault integration
│   ├── README.md
│   ├── json-data/                     # Secret data to import into Vault
│   │   └── *.json
│   └── secret-provider-classes/       # SecretProviderClass definitions
│       └── *.yaml
"""
        else:
            content += """\
├── secrets/                           # Kubernetes secrets
│   ├── README.md
│   └── *.yaml
├── ssl/                               # SSL certificates
│   ├── README.md
│   └── *.yaml
"""

        content += """\
├── metrics/                           # Usage metering
│   ├── README.md
│   └── *.yaml
└── configmaps/                        # ConfigMaps (if AI Services)
    ├── README.md
    └── *.yaml
```

## Deployed Components

"""

        if self._cpe_deployed:
            content += "- ✓ Content Platform Engine (CPE)\n"
        if self._ban_deployed:
            content += "- ✓ Business Automation Navigator (BAN)\n"
        if self._graphql_deployed:
            content += "- ✓ GraphQL API\n"
        if self._cmis_deployed:
            content += "- ✓ CMIS\n"
        if self._mg_properties:
            content += "- ✓ Model Gateway\n"
        if self._wdu_properties:
            content += "- ✓ Enhanced Extraction (WDU)\n"

        content += f"""
## Quick Start

### Prerequisites

1. Kubernetes cluster with admin permissions
2. IBM Content Cortex Operator installed
3. IBM AI Services Operator (if using AI Services)
4. IBM License Service installed
5. IBM Usage Metering Operator installed

### Deployment Steps

#### 1. Create Databases

```bash
cd database/
# See database/README.md for instructions
```

"""

        if self._vault_enabled:
            content += f"""\
#### 2. Import Secrets into Vault

```bash
cd vault/
# See vault/README.md for full instructions
```

#### 3. Apply SecretProviderClasses

```bash
cd vault/secret-provider-classes/
kubectl apply -f . -n {self._namespace}
```

#### 4. Apply ConfigMaps (if AI Services)
"""
        else:
            content += f"""\
#### 2. Apply Secrets

```bash
cd ../secrets/
kubectl apply -f . -n {self._namespace}
```

#### 3. Apply SSL Secrets

```bash
cd ../ssl/
kubectl apply -f . -n {self._namespace}
```

#### 4. Apply ConfigMaps (if AI Services)
"""

        content += f"""\

```bash
cd ../configmaps/
kubectl apply -f . -n {self._namespace}
```

#### 5. Apply Metrics

```bash
cd ../metrics/
kubectl apply -f . -n {self._namespace}
```

"""

        # Step 6: IBM-Managed Infrastructure if configured
        has_ibm_redis = self._use_ibm_redis
        has_ibm_cnpg_mg = self._use_ibm_cnpg_mg
        has_ibm_cnpg_wdu = self._use_ibm_cnpg_wdu
        has_infra = has_ibm_redis or has_ibm_cnpg_mg or has_ibm_cnpg_wdu
        has_mg = bool(self._mg_properties)

        if has_infra or has_mg:
            content += f"""#### 6. Apply Secrets, IBM-Managed Infrastructure, and Wait for Readiness

> **⚠️ Order matters for Model Gateway.**
> The MG operator reads Postgres and Redis connection details from secrets at startup.
> If those backing services are not yet ready when the Model Gateway CR is applied, the operator
> will fail to reconcile and enter a crash loop.
>
> **Automated path:** `python3 prerequisites.py validate --apply` handles this order
> automatically, including readiness polling. Use the manual steps below only if you
> are applying artifacts yourself.

```bash
cd generatedFiles/{self._namespace}

# ── Step 6a: Apply all secrets first ──────────────────────────────────────────
kubectl apply -f secrets/ -n {self._namespace}
"""
            if has_ibm_redis:
                content += f"""
# ── Step 6b: Apply IBM Redis CR ───────────────────────────────────────────────
kubectl apply -f ibm_redis_cr.yaml -n {self._namespace}

# Wait for Redis to be ready (≈1–3 min):
kubectl get rediscp ibm-redis-mg -n {self._namespace} -w
"""
            if has_ibm_cnpg_mg:
                content += f"""
# ── Step 6c: Apply Model Gateway CNPG Cluster CR ─────────────────────────────
# Note: The CNPG CR is generated during gather mode into infrastructure/.
# Apply it from there and wait for readiness before running generate mode.
# See generatedFiles/{self._namespace}/infrastructure/README.md for instructions.
"""
            if has_ibm_cnpg_wdu:
                content += f"""
# ── Step 6d: Apply WDU CNPG Cluster CR and WDU secrets ───────────────────────
kubectl apply -f ibm_pg_cluster_wdu_cr.yaml -n {self._namespace}

# Wait for WDU CNPG cluster to be ready (≈2–5 min):
kubectl wait cluster/ccx-wdu-pg -n {self._namespace} \\
  --for=jsonpath='{{.status.readyInstances}}'=1 \\
  --timeout=900s

# Once the cluster is Ready, apply WDU secrets in order:
# Providers secret (WDU DB connection config — provider_vars.yaml block scalar)
kubectl apply -f secrets/ibm-ccx-wdu-providers-secret.yaml -n {self._namespace}
# CA/TLS secrets — three names, same content (ccx-wdu-pg-ca is operator-hardcoded)
kubectl apply -f secrets/ibm-ccx-wdu-db-session-ssl-secret.yaml -n {self._namespace}
kubectl apply -f secrets/ibm-ccx-wdu-db-transaction-ssl-secret.yaml -n {self._namespace}
kubectl apply -f secrets/ccx-wdu-pg-ca.yaml -n {self._namespace}
# ConfigMap (ties all secret names together; must exist before the CR)
kubectl apply -f configmaps/ibm-ccx-wdu-config.yaml -n {self._namespace}
"""
            content += f"""```

#### 7. Deploy Operator Custom Resources

> Apply these **only after** all infrastructure above is in a ready state.

```bash
cd generatedFiles/{self._namespace}
"""
        else:
            content += f"""#### 6. Deploy Operator Custom Resources

```bash
cd generatedFiles/{self._namespace}
"""

        if self._content_deployed:
            content += f"""kubectl apply -f ibm_content_cr_production.yaml -n {self._namespace}\n"""
        
        # Check if AI Services / MG / WDU CRs exist in generated folder or are configured
        ai_services_cr_exists = (self._generated_folder / "ibm_ai_services_cr_production.yaml").exists()
        mg_cr_exists = (self._generated_folder / "ibm_model_gateway_cr_production.yaml").exists() or bool(self._mg_properties)
        wdu_cr_exists = (self._generated_folder / "ibm_wdu_cr_production.yaml").exists() or bool(self._wdu_properties)

        if ai_services_cr_exists:
            content += f"""kubectl apply -f ibm_ai_services_cr_production.yaml -n {self._namespace}\n"""
        if mg_cr_exists:
            content += f"""kubectl apply -f ibm_model_gateway_cr_production.yaml -n {self._namespace}\n"""
        if wdu_cr_exists:
            content += f"""kubectl apply -f ibm_wdu_cr_production.yaml -n {self._namespace}\n"""

        content += f"""```

### Monitor Deployment

```bash
# Watch pods
kubectl get pods -n {self._namespace} -w

# Check CR status
kubectl get fncmclusters -n {self._namespace}

# View events
kubectl get events -n {self._namespace} --sort-by='.lastTimestamp'
```

## Custom Resource Files

"""

        for file in cr_files:
            if "content_cr" in file:
                content += f"- **{file}**: FNCMCluster Custom Resource for Content Operator\n"
            elif "ai_services_cr" in file:
                content += f"- **{file}**: CCXAIServices Custom Resource for AI Services\n"
            elif "model_gateway_cr" in file:
                content += f"- **{file}**: ModelGateway Custom Resource for Model Gateway\n"
            elif "wdu_cr" in file:
                wdu_ca = "content-root-ca" if self._content_deployed else "wdu-root-ca"
                wdu_ctx = "FNCM" if self._content_deployed else "Standalone"
                content += (
                    f"- **{file}**: CCXWDUServices Custom Resource for Enhanced Extraction (WDU) "
                    f"— `sc_deployment_context: {wdu_ctx}`, `root_ca_secret: {wdu_ca}`\n"
                )
            elif "ibm_pg_cluster_mg_cr" in file:
                content += f"- **{file}**: CNPG Cluster Custom Resource for Model Gateway PostgreSQL\n"
            elif "ibm_pg_cluster_wdu_cr" in file:
                content += f"- **{file}**: CNPG Cluster Custom Resource for Enhanced Extraction (WDU) PostgreSQL\n"
        content += """
## Troubleshooting

### Pods Not Starting

```bash
kubectl describe pod <pod-name> -n """ + self._namespace + """
kubectl logs <pod-name> -n """ + self._namespace + """
```

### Database Connection Issues

- Verify database secrets
- Test connectivity from cluster
- Check SSL configuration

### SSL/TLS Errors

- Verify SSL secrets exist
- Check certificate validity
- Ensure certificate chains are complete

### Operator Issues

```bash
kubectl logs -n <operator-namespace> deployment/<operator-name>
```

## Post-Deployment

1. Verify all pods are running
2. Access user interfaces
3. Configure Object Stores
4. Test functionality
5. Set up monitoring
6. Backup configuration

## Support

For issues:
1. Check logs and events
2. Review README files in subfolders
3. Verify prerequisites
4. Contact IBM Support

---
*Generated by IBM Content Cortex Prerequisites Script*
"""

        return self._write_readme(folder_path, content)

    def generate_vault_main_readme(self) -> bool:
        """Generate main README for the vault folder with helm upgrade commands."""
        folder_path = self._generated_folder / "vault"
        if not folder_path.exists():
            return True

        # Get list of generated secrets from both subfolders
        json_folder = folder_path / "json-data"
        spc_folder = folder_path / "secret-provider-classes"
        
        json_files = self._get_file_list(json_folder, "*.json") if json_folder.exists() else []
        spc_files = self._get_file_list(spc_folder, "*.yaml") if spc_folder.exists() else []
        
        if not json_files and not spc_files:
            return True

        vault_url = self._deployment_properties.get("VAULT_URL", "https://vault.example.com")
        vault_role = self._deployment_properties.get("VAULT_ROLE", f"{self._namespace}-role")
        raw_vault_path = self._deployment_properties.get("VAULT_PATH", "secret/data")
        # "vault kv put" will automatically add the "/data" in the path
        # so we should remove "/data" if it is part of path (eg. use "vault kv put secret/ccx/my-secret")
        vault_path = "/".join(
            segment for segment in raw_vault_path.split("/") if segment != "data"
        )

        content = f"""# HashiCorp Vault Integration

## Overview

This folder contains all artifacts needed to integrate IBM Content Cortex with HashiCorp Vault for secret management.

**Namespace**: {self._namespace}

**Vault URL**: {vault_url}

**Vault Role**: {vault_role}

**Vault Path**: {raw_vault_path}

**Generated on**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Folder Structure

```
vault/
├── README.md                      # This file
├── json-data/                     # Secret data to import into Vault
│   ├── README.md
"""

        for file in json_files[:5]:  # Show first 5 as examples
            content += f"│   ├── {file}\n"
        if len(json_files) > 5:
            content += f"│   └── ... ({len(json_files) - 5} more files)\n"
        
        content += """└── secret-provider-classes/        # SecretProviderClass definitions
    ├── README.md
"""

        for file in spc_files[:5]:  # Show first 5 as examples
            content += f"    ├── {file}\n"
        if len(spc_files) > 5:
            content += f"    └── ... ({len(spc_files) - 5} more files)\n"

        content += f"""```

## Quick Start

### 1. Import Secrets into Vault

```bash
cd json-data/

# Import all secrets
for json_file in *.json; do
    secret_name=$(basename "$json_file" .json)
    echo "Importing $secret_name..."
    vault kv put {vault_path}/$secret_name @$json_file
done

# Verify imports
vault kv list {vault_path}
```

### 2. Apply SecretProviderClass Definitions

```bash
cd ../secret-provider-classes/

# Apply all SecretProviderClass resources
kubectl apply -f . -n {self._namespace}

# Verify
kubectl get secretproviderclass -n {self._namespace}
```

### 3. Deploy with Helm

Use the following helm upgrade commands with values files to deploy with Vault integration:

"""

        # Generate helm upgrade commands based on what was deployed
        if self._content_deployed:
            # Build vault.secrets array for content operator
            # Use owned-by annotation from SecretProviderClass files to determine ownership
            content_secrets_yaml = []
            for file in json_files:
                secret_name = file.replace('.json', '')
                
                # Check the corresponding SPC file for owned-by annotation
                spc_file = f"{secret_name}.yaml"
                if spc_file in spc_files:
                    owned_by = self._get_secret_ownership(spc_folder / spc_file)
                    # Only include if owned by content-operator
                    if 'content-operator' not in owned_by:
                        continue
                
                # Determine secret type based on name
                if 'ssl' in secret_name or 'cert' in secret_name or 'public-key' in secret_name:
                    secret_type = 'certificate'
                else:
                    secret_type = 'secret'
                content_secrets_yaml.append(f"    - name: {secret_name}")
                content_secrets_yaml.append(f"      type: {secret_type}")
            
            content += f"""
#### Content Operator Deployment

Create a values file `content-operator-vault-values.yaml`:

```yaml
vault:
  certificatesMountPath: /tmp/certificates
  enabled: true
  secrets:
"""
            for secret_line in content_secrets_yaml:
                content += f"{secret_line}\n"
            content += f"""  secretsMountPath: /tmp/secrets
```

Deploy with Helm:

```bash
helm upgrade ibm-content-operator \\
  oci://cp.icr.io/cp/ibm-content-operator \\
  --namespace {self._namespace} \\
  --values content-operator-vault-values.yaml
```

**Note**: The operator will mount secrets from Vault at:
- Credentials: `/tmp/secrets/<secret-name>/`
- Certificates: `/tmp/certificates/<secret-name>/`
"""

        # Check if AI Services secrets exist to determine if we should generate AI Services section
        # Use owned-by annotation from SecretProviderClass files to determine ownership
        ai_secrets_yaml = []
        for file in json_files:
            secret_name = file.replace('.json', '')
            
            # Check the corresponding SPC file for owned-by annotation
            spc_file = f"{secret_name}.yaml"
            if spc_file in spc_files:
                owned_by = self._get_secret_ownership(spc_folder / spc_file)
                # Only include if owned by ai-services-operator
                if 'ai-services-operator' not in owned_by:
                    continue
            else:
                # If no SPC file, skip
                continue
            
            # Determine secret type based on name
            if 'ssl' in secret_name or 'cert' in secret_name or 'public-key' in secret_name:
                secret_type = 'certificate'
            else:
                secret_type = 'secret'
            ai_secrets_yaml.append(f"    - name: {secret_name}")
            ai_secrets_yaml.append(f"      type: {secret_type}")
        
        # Generate AI Services section if we found AI Services secrets
        if ai_secrets_yaml:
            
            content += f"""
#### AI Services Operator Deployment

Create a values file `ai-services-operator-vault-values.yaml`:

```yaml
vault:
  certificatesMountPath: /tmp/certificates
  enabled: true
  secrets:
"""
            for secret_line in ai_secrets_yaml:
                content += f"{secret_line}\n"
            content += f"""  secretsMountPath: /tmp/secrets
```

Deploy with Helm:

```bash
helm upgrade ibm-ai-services-operator \\
  oci://cp.icr.io/cp/ibm-ai-services-operator \\
  --namespace {self._namespace} \\
  --values ai-services-operator-vault-values.yaml
```

**Note**: The operator will mount secrets from Vault at:
- Credentials: `/tmp/secrets/<secret-name>/`
- Certificates: `/tmp/certificates/<secret-name>/`
"""

        content += f"""

## Generated Secrets

### JSON Data Files ({len(json_files)} total)

"""

        # Categorize secrets
        cpe_secrets = [f for f in json_files if 'fncm' in f or 'cpe' in f.lower()]
        ban_secrets = [f for f in json_files if 'ban' in f or 'navigator' in f.lower()]
        ldap_secrets = [f for f in json_files if 'ldap' in f]
        ssl_secrets = [f for f in json_files if 'ssl' in f]
        idp_secrets = [f for f in json_files if 'idp' in f]
        ai_secrets = [f for f in json_files if 'ai-services' in f or 'providers' in f]
        other_secrets = [f for f in json_files if f not in cpe_secrets + ban_secrets + ldap_secrets + ssl_secrets + idp_secrets + ai_secrets]

        if cpe_secrets:
            content += f"**CPE Secrets** ({len(cpe_secrets)}):\n"
            for secret in cpe_secrets:
                content += f"- {secret}\n"
            content += "\n"

        if ban_secrets:
            content += f"**Navigator Secrets** ({len(ban_secrets)}):\n"
            for secret in ban_secrets:
                content += f"- {secret}\n"
            content += "\n"

        if ldap_secrets:
            content += f"**LDAP Secrets** ({len(ldap_secrets)}):\n"
            for secret in ldap_secrets:
                content += f"- {secret}\n"
            content += "\n"

        if idp_secrets:
            content += f"**Identity Provider Secrets** ({len(idp_secrets)}):\n"
            for secret in idp_secrets:
                content += f"- {secret}\n"
            content += "\n"

        if ai_secrets:
            content += f"**AI Services Secrets** ({len(ai_secrets)}):\n"
            for secret in ai_secrets:
                content += f"- {secret}\n"
            content += "\n"

        if ssl_secrets:
            content += f"**SSL/TLS Secrets** ({len(ssl_secrets)}):\n"
            for secret in ssl_secrets:
                content += f"- {secret}\n"
            content += "\n"

        if other_secrets:
            content += f"**Other Secrets** ({len(other_secrets)}):\n"
            for secret in other_secrets:
                content += f"- {secret}\n"
            content += "\n"

        content += f"""
### SecretProviderClass Definitions ({len(spc_files)} total)

Each SecretProviderClass maps to a corresponding JSON file and mounts secrets as volumes in pods.

## Prerequisites

1. **HashiCorp Vault** - Running and accessible
2. **Secrets Store CSI Driver** - Installed in cluster
3. **Vault CSI Provider** - Installed in cluster
4. **Vault Configuration**:
   - Kubernetes auth method enabled
   - Service account for {self._namespace}
   - Vault role: `{vault_role}`
   - KV Secrets Engine v2 enabled

## Verification

### Check Vault Secrets

```bash
# List all secrets
vault kv list {vault_path}

# Get a specific secret
vault kv get {vault_path}/ibm-fncm-secret
```

### Check SecretProviderClass

```bash
# List all SecretProviderClass resources
kubectl get secretproviderclass -n {self._namespace}

# Describe a specific one
kubectl describe secretproviderclass ibm-fncm-secret -n {self._namespace}
```

### Check CSI Driver

```bash
# Check CSI driver pods
kubectl get pods -n kube-system -l app=secrets-store-csi-driver

# Check Vault provider pods
kubectl get pods -n kube-system -l app=vault-csi-provider

# View logs
kubectl logs -n kube-system -l app=secrets-store-csi-driver
```

## Troubleshooting

### Secrets Not Syncing

1. Check SecretProviderClass is applied
2. Verify Vault secrets exist at correct paths
3. Check CSI driver logs
4. Verify Vault authentication

### Permission Denied

1. Check Vault role has correct policies
2. Verify service account token
3. Ensure namespace matches configuration

### Import Failures

1. Validate JSON syntax
2. Check Vault authentication
3. Verify path permissions

## Security Best Practices

✓ **Delete JSON files** after importing to Vault
✓ **Restrict file permissions** on JSON files
✓ **Use Vault ACL policies** for access control
✓ **Enable Vault audit logging**
✓ **Rotate secrets regularly**
✓ **Monitor CSI driver logs**

## Next Steps

1. ✅ Import all JSON files into Vault
2. ✅ Apply SecretProviderClass definitions
3. ✅ Deploy operators with Vault integration
4. ✅ Verify pods can access secrets
5. ✅ Delete JSON files from disk
6. ✅ Monitor for any issues

## Additional Resources

- [Vault Documentation](https://developer.hashicorp.com/vault/docs)
- [Secrets Store CSI Driver](https://secrets-store-csi-driver.sigs.k8s.io/)
- [Vault CSI Provider](https://developer.hashicorp.com/vault/docs/platform/k8s/csi)

---
*Generated by IBM Content Cortex Prerequisites Script*
"""

        return self._write_readme(folder_path, content)

    def generate_vault_json_readme(self) -> bool:
        """Generate README for the vault/json-data folder."""
        folder_path = self._generated_folder / "vault" / "json-data"
        if not folder_path.exists():
            return True

        files = self._get_file_list(folder_path, "*.json")
        if not files:
            return True

        vault_url = self._deployment_properties.get("VAULT_URL", "https://vault.example.com")
        raw_vault_path = self._deployment_properties.get("VAULT_PATH", "secret/data")
        # "vault kv put" will automatically add the "/data" in the path
        # so we should remove "/data" if it is part of path (eg. use "vault kv put secret/ccx/my-secret")
        vault_path = "/".join(
            segment for segment in raw_vault_path.split("/") if segment != "data"
        )

        content = f"""# Vault JSON Data Files

## Overview

This folder contains JSON files with secret data to be imported into HashiCorp Vault.

**Total Files**: {len(files)}

**Namespace**: {self._namespace}

**Vault Path**: {raw_vault_path}

## Files

"""

        for file in files:
            content += f"- `{file}`\n"

        content += f"""

## Import to Vault

### Import All Secrets

```bash
# Import all JSON files
for json_file in *.json; do
    secret_name=$(basename "$json_file" .json)
    echo "Importing $secret_name..."
    vault kv put {vault_path}/$secret_name @$json_file
done
```

### Import Individual Secret

```bash
# Import a specific secret
vault kv put {vault_path}/ibm-fncm-secret @ibm-fncm-secret.json
```

### Verify Import

```bash
# List all secrets
vault kv list {vault_path}

# Get a specific secret
vault kv get {vault_path}/ibm-fncm-secret
```

## Security Notes

⚠️ **IMPORTANT**: After importing secrets to Vault:
1. Delete these JSON files from disk
2. Clear shell history if commands contained sensitive data
3. Ensure Vault access is properly restricted

## File Format

Each JSON file contains key-value pairs that will be stored in Vault:

```json
{{
  "key1": "value1",
  "key2": "value2"
}}
```

---
*Generated by IBM Content Cortex Prerequisites Script*
"""

        return self._write_readme(folder_path, content)

    def generate_vault_spc_readme(self) -> bool:
        """Generate README for the vault/secret-provider-classes folder."""
        folder_path = self._generated_folder / "vault" / "secret-provider-classes"
        if not folder_path.exists():
            return True

        files = self._get_file_list(folder_path, "*.yaml")
        if not files:
            return True

        vault_url = self._deployment_properties.get("VAULT_URL", "https://vault.example.com")
        vault_role = self._deployment_properties.get("VAULT_ROLE", f"{self._namespace}-role")

        content = f"""# SecretProviderClass Definitions

## Overview

This folder contains SecretProviderClass resources that configure the Secrets Store CSI Driver to fetch secrets from HashiCorp Vault and mount them as volumes in pods.

**Total Files**: {len(files)}

**Namespace**: {self._namespace}

**Vault URL**: {vault_url}

**Vault Role**: {vault_role}

## Files

"""

        for file in files:
            content += f"- `{file}`\n"

        content += f"""

## Apply SecretProviderClass Resources

### Apply All

```bash
# Apply all SecretProviderClass resources
kubectl apply -f . -n {self._namespace}

# Verify
kubectl get secretproviderclass -n {self._namespace}
```

### Apply Individual Resource

```bash
# Apply a specific SecretProviderClass
kubectl apply -f ibm-fncm-secret.yaml -n {self._namespace}

# Check status
kubectl describe secretproviderclass ibm-fncm-secret -n {self._namespace}
```

## How It Works

1. **SecretProviderClass** defines which secrets to fetch from Vault
2. **CSI Driver** mounts secrets as volumes in pods at the configured mount paths
3. **Helm Chart** configures volume mounts in pod specifications
4. **Pods** access secrets directly from mounted volumes (not as Kubernetes Secret objects)

## Prerequisites

Before applying these resources:

1. ✅ Vault is running and accessible
2. ✅ Secrets Store CSI Driver is installed
3. ✅ Vault CSI Provider is installed
4. ✅ Vault secrets have been imported
5. ✅ Vault authentication is configured

## Verification

```bash
# Check SecretProviderClass resources
kubectl get secretproviderclass -n {self._namespace}

# View SecretProviderClass details
kubectl describe secretproviderclass ibm-fncm-secret -n {self._namespace}

# Check pod volume mounts (after deployment)
kubectl describe pod <pod-name> -n {self._namespace}
```

## Troubleshooting

### Secrets Not Mounted in Pods

1. Check CSI driver is running:
   ```bash
   kubectl get pods -n kube-system -l app=secrets-store-csi-driver
   ```

2. Check Vault provider is running:
   ```bash
   kubectl get pods -n kube-system -l app=vault-csi-provider
   ```

3. View CSI driver logs:
   ```bash
   kubectl logs -n kube-system -l app=secrets-store-csi-driver
   ```

### Permission Denied Errors

1. Verify Vault role has correct policies
2. Check service account token is valid
3. Ensure namespace matches configuration

---
*Generated by IBM Content Cortex Prerequisites Script*
"""

        return self._write_readme(folder_path, content)

# Made with Bob
