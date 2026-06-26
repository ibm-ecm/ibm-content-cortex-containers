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

"""
Generate README documentation for property files created during gather mode.
This module creates comprehensive documentation for all property files,
explaining their purpose and describing each property.
"""

import os
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
from logging import Logger


class GeneratePropertyReadme:
    """
    Generates README documentation for property files created during gather mode.
    
    This class creates a comprehensive README.md file in the propertyFile/<namespace>
    folder that documents all property files, their purpose, and property descriptions.
    """
    
    def __init__(
        self,
        namespace: str,
        property_folder: str,
        gather_obj,
        logger: Optional[Logger] = None
    ):
        """
        Initialize the property README generator.
        
        Args:
            namespace: Kubernetes namespace for the deployment
            property_folder: Path to the property files folder
            gather_obj: Gather object containing deployment configuration
            logger: Optional logger instance for logging operations
        """
        self._logger = logger
        self._namespace = namespace
        self._property_folder = Path(property_folder)
        self._gather = gather_obj
        
        # Determine which operators are deployed
        self._has_content = gather_obj.has_content_operator() if hasattr(gather_obj, 'has_content_operator') else False
        self._has_ai_services = gather_obj.has_ai_services_operator() if hasattr(gather_obj, 'has_ai_services_operator') else False
        
        # Determine authentication type
        self._auth_type = gather_obj.auth_type if hasattr(gather_obj, 'auth_type') else None
        
        # Determine optional components
        self._has_sendmail = gather_obj.sendmail_support if hasattr(gather_obj, 'sendmail_support') else False
        self._has_icc = gather_obj.icc_support if hasattr(gather_obj, 'icc_support') else False
        self._has_tm = gather_obj.tm_custom_groups if hasattr(gather_obj, 'tm_custom_groups') else False
        self._has_ingress = gather_obj.ingress if hasattr(gather_obj, 'ingress') else False
        
    def _log_info(self, message: str):
        """Log info message if logger is available."""
        if self._logger:
            self._logger.info(message)
    
    def _log_error(self, message: str):
        """Log error message if logger is available."""
        if self._logger:
            self._logger.error(message)
    
    def _write_readme(self, content: str) -> bool:
        """
        Write README content to file.
        
        Args:
            content: README content to write
            
        Returns:
            True if successful, False otherwise
        """
        try:
            readme_path = self._property_folder / "README.md"
            with open(readme_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self._log_info(f"✓ Property README generated: {readme_path}")
            return True
        except Exception as e:
            self._log_error(f"Error writing property README: {str(e)}")
            return False
    
    def _get_property_files(self) -> List[str]:
        """Get list of property files in the folder."""
        if not self._property_folder.exists():
            return []
        return sorted([f.name for f in self._property_folder.iterdir() if f.suffix == '.toml'])
    
    def generate_readme(self) -> bool:
        """
        Generate comprehensive README for all property files.
        
        Returns:
            True if successful, False otherwise
        """
        self._log_info(f"Generating property file README for namespace: {self._namespace}")
        
        files = self._get_property_files()
        if not files:
            self._log_info("No property files found, skipping README generation")
            return True
        
        content = self._generate_header()
        content += self._generate_overview()
        content += self._generate_file_list(files)
        content += self._generate_file_descriptions(files)
        content += self._generate_next_steps()
        content += self._generate_footer()
        
        return self._write_readme(content)
    
    def _generate_header(self) -> str:
        """Generate README header."""
        return f"""# IBM Content Cortex Property Files

**Namespace**: `{self._namespace}`  
**Generated**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

"""
    
    def _generate_overview(self) -> str:
        """Generate overview section."""
        operators = []
        if self._has_content:
            operators.append("Content Operator")
        if self._has_ai_services:
            operators.append("AI Services Operator")
        
        operator_text = " and ".join(operators) if operators else "Unknown"
        
        return f"""## Overview

This folder contains property files for configuring your IBM Content Cortex deployment.
These files were generated during the **gather** mode and contain configuration settings
that will be used during the **generate** mode to create Kubernetes resources.

**Deployment Type**: {operator_text}  
**Authentication**: {self._auth_type or 'Not configured'}

## Important Notes

⚠️ **Security**: These files contain sensitive information including passwords and connection details.
- Protect these files with appropriate file system permissions
- Do not commit these files to version control
- Store securely and delete after deployment if not needed

📝 **Editing**: You can edit these files to adjust configuration before running generate mode.
- Use a text editor that preserves TOML format
- Ensure all required fields are filled
- Validate syntax after editing

"""
    
    def _generate_file_list(self, files: List[str]) -> str:
        """Generate quick reference file list."""
        content = "## Property Files\n\n"
        content += "| File | Purpose | Required For |\n"
        content += "|------|---------|-------------|\n"
        
        for file in files:
            purpose, required_for = self._get_file_metadata(file)
            content += f"| `{file}` | {purpose} | {required_for} |\n"
        
        content += "\n"
        return content
    
    def _get_file_metadata(self, filename: str) -> tuple:
        """Get purpose and requirement metadata for a file."""
        metadata = {
            "content_db_server.toml": (
                "Database configuration",
                "Content Operator (CPE, BAN)"
            ),
            "content_ldap_server.toml": (
                "LDAP server configuration",
                "Content Operator with LDAP auth"
            ),
            "ccx-identity_provider.toml": (
                "Identity Provider (IDP) configuration",
                "IDP authentication"
            ),
            "content_scim_server.toml": (
                "SCIM server configuration",
                "SCIM authentication"
            ),
            "content_user_group.toml": (
                "User and group configuration",
                "Content Operator"
            ),
            "ccx-deployment.toml": (
                "Deployment settings and component selection",
                "All deployments"
            ),
            "ccx-ingress.toml": (
                "Ingress configuration",
                "Ingress-enabled deployments"
            ),
            "content_components_options.toml": (
                "Optional component settings (SendMail, ICC, TM)",
                "Optional components"
            ),
            "aiservices_providers.toml": (
                "AI model provider configuration",
                "AI Services Operator"
            ),
            "aiservices_integration.toml": (
                "AI Services integration with Content",
                "AI Services Operator"
            ),
        }
        
        return metadata.get(filename, ("Configuration file", "Varies"))
    
    def _generate_file_descriptions(self, files: List[str]) -> str:
        """Generate detailed descriptions for each property file."""
        content = "## Detailed File Descriptions\n\n"
        
        for file in files:
            content += self._generate_file_section(file)
        
        return content
    
    def _generate_file_section(self, filename: str) -> str:
        """Generate detailed section for a specific property file."""
        sections = {
            "content_db_server.toml": self._describe_database_file,
            "content_ldap_server.toml": self._describe_ldap_file,
            "ccx-identity_provider.toml": self._describe_idp_file,
            "content_scim_server.toml": self._describe_scim_file,
            "content_user_group.toml": self._describe_usergroup_file,
            "ccx-deployment.toml": self._describe_deployment_file,
            "ccx-ingress.toml": self._describe_ingress_file,
            "content_components_options.toml": self._describe_custom_components_file,
            "aiservices_providers.toml": self._describe_aiservices_file,
            "aiservices_integration.toml": self._describe_aiservices_integration_file,
        }
        
        generator = sections.get(filename)
        if generator:
            return generator()
        return f"### {filename}\n\nConfiguration file for IBM Content Cortex.\n\n"
    
    def _describe_database_file(self) -> str:
        """Describe database property file."""
        return """### content_db_server.toml

**Purpose**: Configures database connections for Content Operator components (GCD, Object Stores, Navigator).

**Property Reference**:

| Property | Required | Type | Validation | Description |
|----------|----------|------|------------|-------------|
| DATABASE_TYPE | Yes | String | db2, db2hadr, oracle, postgresql, sqlserver | Database type from your infrastructure |
| DATABASE_SSL_ENABLE | Yes | Boolean | true/false | Enable SSL/TLS for database connections |
| DATABASE_SERVERNAME | Yes | String | Min 1 char, IPv6 in brackets | Database server hostname or IP address |
| DATABASE_PORT | Yes | Integer | 1-65535 | Database server port |
| DATABASE_NAME | Yes | String | Min 1 char | Database name |
| DATABASE_USERNAME | Yes | String | Min 1 char | Database user with appropriate privileges |
| DATABASE_PASSWORD | Yes | String | Min 1 char | Database user password |
| OS_LABEL | Yes* | String | No spaces allowed | Object Store label (*for Object Stores only) |
| DATASOURCE_NAME | Yes* | String | - | Datasource name (*for Object Stores only) |
| DATASOURCE_NAME_XA | Yes* | String | - | XA datasource name (*for Object Stores only) |
| SSL_MODE | Conditional | String | require, verify-ca, verify-full | Required for PostgreSQL when SSL enabled |
| ORACLE_JDBC_URL | Conditional | String | Valid JDBC URL, IPv6 in brackets | Required for Oracle databases |
| TABLESPACE_NAME | Conditional | String | - | Required for Oracle databases |
| SCHEMA_NAME | Conditional | String | - | Required for Oracle databases |
| HADR_STANDBY_SERVERNAME | Conditional | String | - | Required for DB2 HADR configurations |
| HADR_STANDBY_PORT | Conditional | Integer | 1-65535 | Required for DB2 HADR configurations |

**Multiple Databases**: This file supports multiple database configurations:
- **GCD**: Global Configuration Database (required for CPE)
- **OS1, OS2, ...**: Object Store databases (one per Object Store)
- **ICN**: Navigator database (required for BAN)

**SSL Configuration**: If DATABASE_SSL_ENABLE is true:
- Place database SSL certificates in `ssl-certs/db-<database-name>/` folders
- Certificates must be in PEM format (.pem, .crt, or .cer)

"""
    
    def _describe_ldap_file(self) -> str:
        """Describe LDAP property file."""
        return """### content_ldap_server.toml

**Purpose**: Configures LDAP directory servers for user authentication and authorization.

**Property Reference**:

| Property | Required | Type | Validation | Description |
|----------|----------|------|------------|-------------|
| LDAP_TYPE | Yes | String | IBM TDS, Microsoft AD, CA eTrust, Oracle ID, Oracle DSEE, Oracle UD, NetIQ eDirectory | LDAP server type |
| LDAP_ID | Yes | String | - | Unique identifier for this LDAP server |
| LDAP_SERVER | Yes | String | Min 1 char, IPv6 in brackets | LDAP server hostname or IP address |
| LDAP_PORT | Yes | Integer | 1-65535 | LDAP server port (389 non-SSL, 636 SSL) |
| LDAP_BASE_DN | Yes | String | Valid DN format | Base Distinguished Name for user searches |
| LDAP_GROUP_BASE_DN | Yes | String | Valid DN format | Base DN for group searches |
| LDAP_BIND_DN | Yes | String | Valid DN format | Bind DN for LDAP authentication |
| LDAP_BIND_DN_PASSWORD | Yes | String | Min 1 char | Password for bind DN |
| LDAP_SSL_ENABLED | Yes | Boolean | true/false | Enable SSL/TLS for LDAP connections |
| LDAP_GC_HOST | No | String | IPv6 in brackets | Global Catalog server (Active Directory) |
| LDAP_GC_PORT | Conditional | Integer | 1-65535 | GC port (required if LDAP_GC_HOST set, typically 3268/3269) |

**Multiple LDAP Servers**: This file supports multiple LDAP configurations (LDAP, LDAP2, LDAP3, etc.) for:
- Failover and high availability
- Multiple directory sources
- Geographic distribution

**SSL Configuration**: If LDAP_SSL_ENABLED is true:
- Place LDAP SSL certificates in `ssl-certs/ldap<n>/` folders
- Certificates must be in PEM format (.pem, .crt, or .cer)

"""
    
    def _describe_idp_file(self) -> str:
        """Describe IDP property file."""
        return """### ccx-identity_provider.toml

**Purpose**: Configures OpenID Connect (OIDC) Identity Providers for modern authentication.

**Property Reference**:

| Property | Required | Type | Pre-filled | Validation | Description |
|----------|----------|------|------------|------------|-------------|
| IDP_ID | Yes | String | No | - | Unique identifier for this identity provider |
| PROVIDER_NAME | Yes | String | No | - | Name used within the redirect URL |
| DISPLAY_NAME | Yes | String | No | - | Sign-in button display name |
| DISCOVERY_ENDPOINT | Yes | String | No | Valid URL | OIDC discovery endpoint URL |
| ISSUER | Yes | String | **Yes** | - | IDP Issuer (from discovery endpoint) |
| TOKEN_ENDPOINT | Yes | String | **Yes** | Valid URL | Endpoint to retrieve tokens (from discovery) |
| JWKS_ENDPOINT | Yes | String | **Yes** | Valid URL | JSON Web Key Set endpoint (from discovery) |
| INTROSPECT_ENDPOINT | Conditional | String | **Yes** | Valid URL | Token introspection endpoint (if validation_method=introspect) |
| USERINFO_ENDPOINT | Conditional | String | **Yes** | Valid URL | User info endpoint (if validation_method=userinfo) |
| REVOCATION_ENDPOINT | Yes | String | **Yes** | Valid URL | Token revocation endpoint (from discovery) |
| CLIENT_ID | Yes | String | No | Min 1 char | OAuth2 client ID registered with the IDP |
| CLIENT_SECRET | Yes | String | No | Min 1 char | OAuth2 client secret |
| VALIDATION_METHOD | Yes | String | No | introspect, userinfo | Method of token validation |
| USER_IDENTIFIER | Yes | String | No | - | Principle user JSON ID token attribute |
| UNIQUE_USER_IDENTIFIER | Yes | String | No | - | Unique user JSON ID token attribute |
| USER_IDENTIFIER_TO_CREATE_SUBJECT | Yes | String | No | - | Claim that represents a unique user |
| IDP_SSL_ENABLED | Yes | Boolean | No | true/false | Enable SSL certificate validation |

**Pre-filled Properties**: Properties marked as "Pre-filled" are automatically populated from the OIDC discovery endpoint. You can override these values if needed, but the discovered values are typically correct.

**Multiple IDPs**: This file supports multiple IDP configurations (IDP1, IDP2, etc.) for:
- Multiple authentication sources
- Different user populations
- Failover scenarios

**SSL Configuration**: If IDP_SSL_ENABLED is true:
- Place IDP SSL certificates in `ssl-certs/idp<n>/` folders
- Place IDP public keys in `ssl-certs/idp<n>-public-key/` folder
- Certificates must be in PEM format

"""
    
    def _describe_scim_file(self) -> str:
        """Describe SCIM property file."""
        return """### content_scim_server.toml

**Purpose**: Configures SCIM (System for Cross-domain Identity Management) servers for user provisioning.

**Key Properties**:

- **SCIM_ID**: Unique identifier for this SCIM server
- **SCIM_HOST**: SCIM server hostname or IP address
- **SCIM_PORT**: SCIM server port (typically 443 for HTTPS)
- **SCIM_CONTEXT_ROOT**: SCIM API context root (e.g., /scim/v2)
- **SCIM_CLIENT_ID**: SCIM client ID for authentication
- **SCIM_CLIENT_SECRET**: SCIM client secret
- **SCIM_SSL_ENABLED**: Enable SSL/TLS for SCIM connections

**SSL Configuration**: If SCIM_SSL_ENABLED is true:
- Place SCIM SSL certificates in `ssl-certs/scim<n>/` folders
- Certificates must be in PEM format

**SCIM Protocol**: Supports SCIM 2.0 protocol for:
- User provisioning and deprovisioning
- Group management
- Attribute synchronization

"""
    
    def _describe_usergroup_file(self) -> str:
        """Describe user/group property file."""
        return """### content_user_group.toml

**Purpose**: Configures administrative users and groups for Content Operator components.

**Key Properties**:

**P8 Domain (CPE)**:
- **P8_ADMIN_USER_NAME**: P8 domain administrator username
- **P8_ADMIN_USER_PASSWORD**: P8 domain administrator password

**GCD (Global Configuration Database)**:
- **GCD_ADMIN_USER_NAME**: GCD administrator username
- **GCD_ADMIN_USER_PASSWORD**: GCD administrator password
- **GCD_ADMIN_GROUP_NAME**: GCD administrators group

**Object Stores**:
- **OS_ADMIN_USER_NAME**: Object Store administrator username
- **OS_ADMIN_USER_PASSWORD**: Object Store administrator password
- **OS_ADMIN_GROUP_NAME**: Object Store administrators group

**Navigator (BAN)**:
- **ICN_ADMIN_USER_NAME**: Navigator administrator username
- **ICN_ADMIN_USER_PASSWORD**: Navigator administrator password
- **ICN_ADMIN_GROUP_NAME**: Navigator administrators group
- **ICN_ADMIN_DESKTOP_ID**: Navigator desktop ID

**Keystores**:
- **KEYSTORE_PASSWORD**: Password for Java keystores (min 14 chars for FIPS)

**Security Notes**:
- Use strong passwords meeting your organization's policy
- These users must exist in your LDAP directory
- Groups must be valid LDAP groups

"""
    
    def _describe_deployment_file(self) -> str:
        """Describe deployment property file."""
        content = """### ccx-deployment.toml

**Purpose**: Main deployment configuration file controlling global settings and deployment options.

**Property Reference**:

| Property | Required | Type | Validation | Description |
|----------|----------|------|------------|-------------|
| CCX_Version | Yes | String | Valid version | IBM Content Cortex version |
| LICENSE | Yes | String | Production/non-production license codes | Deployment license type |
| PLATFORM | Yes | String | OCP, ROKS, other | Kubernetes platform type |
| FIPS_SUPPORT | Yes | Boolean | true/false | Enable FIPS 140-2 compliance |
"""
        
        # Add component selection section only for Content Operator deployments
        if self._has_content:
            content += """
**Component Selection** (Content Operator):

| Property | Required | Type | Description |
|----------|----------|------|-------------|
| CPE | Yes | Boolean | Deploy Content Platform Engine |
| BAN | Yes | Boolean | Deploy Business Automation Navigator |
| GRAPHQL | Yes | Boolean | Deploy GraphQL service |
| CMIS | Yes | Boolean | Deploy CMIS service |
| CSS | No | Boolean | Deploy Content Search Services |
| TM | No | Boolean | Deploy Task Manager |
| IER | No | Boolean | Deploy IBM Enterprise Records |
| ICCSAP | No | Boolean | Deploy ICC for SAP |
"""
        
        content += """
**Secret Management** (Vault):

| Property | Required | Type | Validation | Description |
|----------|----------|------|------------|-------------|
| VAULT_ENABLED | Yes | Boolean | true/false | Use HashiCorp Vault instead of Kubernetes Secrets |
| VAULT_URL | Conditional | String | Valid URL | Vault server URL (required if VAULT_ENABLED=true) |
| VAULT_ROLE | Conditional | String | - | Vault Kubernetes auth role (required if VAULT_ENABLED=true) |
| VAULT_PATH | Conditional | String | - | Vault KV secrets engine path (default: secret/data) |
| VAULT_CERT_PATH | No | String | File path | Path to Vault CA certificate for TLS verification |

**Storage**:

| Property | Required | Type | Description |
|----------|----------|------|-------------|
| SLOW_FILE_STORAGE_CLASSNAME | Yes | String | Storage class for persistent volumes |
"""
        
        if self._has_content:
            content += """| MEDIUM_FILE_STORAGE_CLASSNAME | No | String | Storage class for medium-speed storage |
| FAST_FILE_STORAGE_CLASSNAME | No | String | Storage class for high-speed storage |
"""
        
        content += """
**Network Policies**:

| Property | Required | Type | Description |
|----------|----------|------|-------------|
| GENERATE_NETWORK_POLICIES | Yes | Boolean | Enable network policy generation by operator |

"""
        
        if self._has_content:
            content += """
**Resource Limits** (Content Operator): CPU and memory limits for each deployed component

"""
        
        return content
    
    def _describe_ingress_file(self) -> str:
        """Describe ingress property file."""
        return """### ccx-ingress.toml

**Purpose**: Configures Kubernetes Ingress for external access to Content Cortex services.

**Key Properties**:

- **INGRESS_ENABLED**: Enable Ingress resource creation (true/false)
- **INGRESS_HOSTNAME**: Hostname for Ingress (e.g., ccx.example.com)
- **INGRESS_TLS_ENABLED**: Enable TLS/SSL for Ingress (true/false)
- **INGRESS_TLS_SECRET_NAME**: Name of Kubernetes secret containing TLS certificate
- **SERVICE_TYPE**: Kubernetes service type (ClusterIP, NodePort, LoadBalancer)

**Ingress Annotations**: Custom annotations for Ingress controller:
- Format: `key: value` (one per line)
- Examples:
  - `nginx.ingress.kubernetes.io/ssl-redirect: "true"`
  - `cert-manager.io/cluster-issuer: letsencrypt-prod`
  - `kubernetes.io/ingress.class: nginx`

**TLS Configuration**: If INGRESS_TLS_ENABLED is true:
- Create a Kubernetes TLS secret with your certificate and key
- Reference the secret name in INGRESS_TLS_SECRET_NAME
- Certificate must be valid for INGRESS_HOSTNAME

**Platform-Specific**:
- **OpenShift**: Uses Routes instead of Ingress (automatically handled)
- **Other Kubernetes**: Requires Ingress controller (nginx, traefik, etc.)

"""
    
    def _describe_custom_components_file(self) -> str:
        """Describe custom components property file."""
        return """### content_components_options.toml

**Purpose**: Configures optional components and features for Content Operator.

**SendMail Configuration** (if enabled):
- **MAIL_SERVER_HOST**: SMTP server hostname
- **MAIL_SERVER_PORT**: SMTP server port (typically 25, 587, or 465)
- **MAIL_SERVER_USERNAME**: SMTP authentication username
- **MAIL_SERVER_PASSWORD**: SMTP authentication password
- **MAIL_SERVER_SSL**: Enable SSL/TLS for SMTP (true/false)

**IBM Content Collector (ICC)** (if enabled):
- **ICC_MASTERKEY**: Master encryption key for ICC
- Place ICC configuration files in `icc/` folder

**Task Manager Custom Groups** (if enabled):
- **TM_ADMIN_GROUP**: Task Manager administrators group
- **TM_USER_GROUP**: Task Manager users group
- Additional custom groups as needed

**Usage**:
- This file is only created if you enabled optional components during gather
- SendMail: Required for email notifications from Content Navigator
- ICC: Required for IBM Content Collector for Email
- Task Manager: Required for custom group configuration

"""
    
    def _describe_aiservices_file(self) -> str:
        """Describe AI Services property file."""
        return """### aiservices_providers.toml

**Purpose**: Configures AI model providers for IBM Content Cortex AI Services.

**Supported Providers**:
- **WatsonX SaaS**: IBM watsonx.ai cloud service
- **WatsonX LWE**: IBM watsonx.ai Local Workload Engine (on-premises)
- **Microsoft Foundry**: Microsoft Azure AI Foundry

**Key Properties per Provider**:

**Provider Configuration**:
- **PROVIDER_ID**: Unique identifier for this provider
- **ENABLED**: Enable this provider (true/false)
- **DEPLOYMENT_TYPE**: Deployment type (SAAS or LWE)
- **API_KEY**: API key for authentication
- **ENDPOINT**: Provider API endpoint URL

**WatsonX Specific**:
- **PROJECT_ID**: WatsonX project ID (for SaaS)
- **SPACE_ID**: WatsonX deployment space ID (for SaaS)

**Model Configuration**:
Each provider can have multiple models configured:
- **MODEL**: Model identifier (e.g., ibm/granite-13b-chat-v2)
- **ENABLED**: Enable this model (true/false)
- **DEFAULT**: Set as default model (true/false) - only ONE model across ALL providers should be default
- **DISPLAY_NAME**: User-friendly model name

**SSL Configuration** (for LWE deployments):
- Place provider SSL certificates in `ssl-certs/ai-provider-<provider_id>/` folders
- Certificates must be in PEM format

**Important**:
- At least one provider must be enabled
- Exactly ONE model across all providers must be marked as DEFAULT
- For LWE deployments, SSL certificates are required

"""
    
    def _describe_aiservices_integration_file(self) -> str:
        """Describe AI Services integration property file."""
        return """### aiservices_integration.toml

**Purpose**: Configures integration between AI Services and Content Operator components.

**Key Properties**:

**GraphQL Integration**:
- **GRAPHQL_ENDPOINT**: GraphQL service endpoint URL
- **GRAPHQL_SSL_ENABLED**: Enable SSL for GraphQL connection (true/false)

**Navigator Integration**:
- **NAVIGATOR_URL**: IBM Content Navigator URL
- **NAVIGATOR_DESKTOP_ID**: Navigator desktop ID for AI features

**Authentication**:
- **AUTH_MODE**: Authentication mode (OIDC or LDAP)
- **IDP_ID**: Identity Provider ID (if AUTH_MODE is OIDC)
- **LDAP_ID**: LDAP server ID (if AUTH_MODE is LDAP)

**SSL Configuration**: If GRAPHQL_SSL_ENABLED is true:
- Place GraphQL SSL certificates in `ssl-certs/graphql/` folder
- Certificates must be in PEM format

**Usage**:
- This file is only created when AI Services Operator is deployed
- Required for AI Services to communicate with Content Operator
- Ensures proper authentication and secure communication

"""
    
    def _generate_next_steps(self) -> str:
        """Generate next steps section."""
        content_steps = ""
        if self._has_content:
            content_steps = """
### For Content Operator Deployments

**Before validation**, you must create the databases:

1. **Generate SQL Scripts**:
   ```bash
   python3 prerequisites.py generate
   ```
   This creates SQL scripts in `generatedFiles/<namespace>/database/`:
   - `createGCDDB.sql` - Global Configuration Database
   - `createOS1DB.sql` - Object Store database(s)
   - `createICNDB.sql` - Navigator database (if BAN deployed)

2. **Execute SQL Scripts on Database Server**:
   Run the generated SQL scripts with database administrator privileges:
   ```bash
   # For DB2
   db2 -tvf createGCDDB.sql
   db2 -tvf createOS1DB.sql
   db2 -tvf createICNDB.sql  # If BAN deployed
   
   # For Oracle
   sqlplus / as sysdba @createGCDDB.sql
   
   # For PostgreSQL
   psql -U postgres -f createGCDDB.sql
   
   # For SQL Server
   sqlcmd -S <server> -U <user> -P <password> -i createGCDDB.sql
   ```

3. **Verify Database Creation**:
   Confirm databases, tablespaces, and users were created successfully.

"""
        
        return f"""## Next Steps

After reviewing and editing these property files:
{content_steps}
### Validate Configuration

Run validation to check your configuration:
```bash
python3 prerequisites.py validate
```

This will verify:
- All required fields are filled
- Property values are valid
- SSL certificates are present and correct format
- Database connectivity (if databases created)
- LDAP connectivity
- IDP discovery endpoints

### Generate Kubernetes Resources

After validation passes:
```bash
python3 prerequisites.py generate
```

This will create:
- Kubernetes Secrets (or Vault SecretProviderClass if Vault enabled)
- Custom Resource (CR) YAML files
- Usage metering metrics (for Content Operator)
- AI Services configuration (if AI Services deployed)
- Comprehensive README documentation

### Deploy to Kubernetes

Deploy the operators and resources:
```bash
python3 deploy_operator.py
```

This will deploy the operators and custom resources to your cluster.

## SSL Certificates

SSL certificates should be placed in the `ssl-certs/` folder structure:

```
ssl-certs/
├── db-<database-name>/     # Database SSL certificates
├── ldap<n>/                # LDAP SSL certificates
├── idp<n>/                 # IDP SSL certificates
├── idp<n>-public-key/      # IDP public keys
├── scim<n>/                # SCIM SSL certificates
├── graphql/                # GraphQL SSL certificates
├── ai-provider-<id>/       # AI provider SSL certificates (LWE)
└── trusted-certs/          # Additional trusted certificates
```

**Certificate Format**: All certificates must be in PEM format with extensions:
- `.pem`
- `.crt`
- `.cer`

## Troubleshooting

**Common Issues**:

1. **Missing Required Fields**: Run validate mode to identify missing values
2. **Invalid TOML Syntax**: Use a TOML validator or linter
3. **SSL Certificate Errors**: Ensure certificates are in PEM format and placed in correct folders
4. **Database Connection Failures**: Verify network connectivity and credentials
5. **LDAP Connection Failures**: Check LDAP server accessibility and bind DN credentials

**Getting Help**:
- Review the IBM Content Cortex documentation
- Check the validation output for specific error messages
- Examine the logs in the `logs/` folder

"""
    
    def _generate_footer(self) -> str:
        """Generate README footer."""
        return """## Additional Resources

- [IBM Content Cortex Documentation](https://www.ibm.com/docs/en/cloud-paks/cp-biz-automation)
- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [TOML Specification](https://toml.io/)

---

*Generated by IBM Content Cortex Prerequisites Script*  
*Namespace: {}*  
*Generated: {}*
""".format(self._namespace, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

# Made with Bob
