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
        logger: Optional[Logger] = None
    ):
        """
        Initialize the README generator.

        Args:
            namespace: Kubernetes namespace for the deployment
            deployment_properties: Dictionary containing deployment configuration
            db_properties: Dictionary containing database configuration
            logger: Optional logger instance for logging operations
        """
        self._logger = logger
        self._namespace = namespace
        self._deployment_properties = deployment_properties or {}
        self._db_properties = db_properties or {}
        
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

        # Only add database parameters if there are database files
        if files:
            # Check which database files actually exist
            has_gcd = any('GCD' in f.upper() for f in files)
            has_os = any('OS' in f.upper() or 'createos' in f.lower() for f in files)
            has_icn = any('ICN' in f.upper() for f in files)
            
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

# For SQL Server
sqlcmd -S <server> -U <user> -P <password> -i createGCD.sql
```

### Execution Order

1. **createGCD.sql** - Must be created first
2. **createICN.sql** - If Business Automation Navigator is deployed
3. **createos.sql** - Create all Object Store databases

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
├── ibm_content_cr_production.yaml     # Content Operator CR
├── ibm_ai_services_cr_production.yaml # AI Services CR (if configured)
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

#### 6. Deploy Custom Resources

```bash
cd ..
kubectl apply -f ibm_content_cr_production.yaml -n {self._namespace}
# If AI Services configured:
kubectl apply -f ibm_ai_services_cr_production.yaml -n {self._namespace}
```

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
        vault_path = self._deployment_properties.get("VAULT_PATH", "secret/data")

        content = f"""# HashiCorp Vault Integration

## Overview

This folder contains all artifacts needed to integrate IBM Content Cortex with HashiCorp Vault for secret management.

**Namespace**: {self._namespace}

**Vault URL**: {vault_url}

**Vault Role**: {vault_role}

**Vault Path**: {vault_path}

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
                secret_name = file.replace('.json', '').replace('-vault-data', '')
                
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
            secret_name = file.replace('.json', '').replace('-vault-data', '')
            
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
        vault_path = self._deployment_properties.get("VAULT_PATH", "secret/data")

        content = f"""# Vault JSON Data Files

## Overview

This folder contains JSON files with secret data to be imported into HashiCorp Vault.

**Total Files**: {len(files)}

**Namespace**: {self._namespace}

**Vault Path**: {vault_path}

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
