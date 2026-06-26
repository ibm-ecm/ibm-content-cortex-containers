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
Enhanced TOML Property File Reader with Pydantic Validation

This module provides robust validation for FNCM property files using Pydantic models.
It includes comprehensive error reporting with remediation guidance and rich terminal output.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from enum import Enum

import toml
from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

# Import DN validator
try:
    from .dn_validator import validate_dn, DNValidator
except ImportError:
    from dn_validator import validate_dn, DNValidator


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS FOR VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

class DatabaseType(str, Enum):
    """Supported database types."""
    DB2 = "db2"
    DB2HADR = "db2hadr"
    DB2RDS = "db2rds"
    DB2RDSHADR = "db2rdshadr"
    ORACLE = "oracle"
    POSTGRESQL = "postgresql"
    SQLSERVER = "sqlserver"


class LDAPType(str, Enum):
    """Supported LDAP types."""
    AD = "Microsoft Active Directory"
    TDS = "IBM Tivoli Directory Server"
    CA = "CA eTrust"
    NOVELL = "Novell eDirectory"
    ORACLE = "Oracle Internet Directory"
    IBM_VERIFY = "IBM Security Verify Directory"


class SCIMType(str, Enum):
    """Supported SCIM types."""
    AUTO_DETECT = "AUTO_DETECT"
    SCIM_11 = "SCIM_11"
    SCIM_20 = "SCIM_20"
    IBM_IAM = "IBM_IAM"
    IBM_VERIFY = "IBM_Verify"


class AIDeploymentType(str, Enum):
    """Supported AI provider deployment types."""
    SAAS = "saas"
    LIGHTWEIGHT_ENGINE = "lightweightengine"


class ValidationMethod(str, Enum):
    """Token validation methods."""
    INTROSPECT = "introspect"
    USERINFO = "userinfo"


class SSLMode(str, Enum):
    """SSL modes for database connections."""
    REQUIRE = "require"
    VERIFY_CA = "verify-ca"
    VERIFY_FULL = "verify-full"


class AuthMode(str, Enum):
    """Authentication modes for AI Services."""
    DUAL = "dual"
    JWT = "jwt"
    DEBUG = "debug"


# ═══════════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS FOR VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

class DatabaseConfig(BaseModel):
    """Database configuration validation model."""
    DATABASE_TYPE: DatabaseType = Field(..., description="Database type")
    DATABASE_SSL_ENABLE: bool = Field(..., description="Enable SSL for database")
    DATABASE_SERVERNAME: str = Field(..., min_length=1, description="Database server hostname or IP")
    DATABASE_PORT: int = Field(..., gt=0, le=65535, description="Database server port")
    DATABASE_NAME: str = Field(..., min_length=1, description="Database name")
    DATABASE_USERNAME: str = Field(..., min_length=1, description="Database username")
    DATABASE_PASSWORD: str = Field(..., min_length=1, description="Database password")
    
    # Optional fields
    SSL_MODE: Optional[SSLMode] = Field(None, description="SSL mode for PostgreSQL")
    ORACLE_JDBC_URL: Optional[str] = Field(None, description="JDBC URL for Oracle")
    TABLESPACE_NAME: Optional[str] = Field(None, description="Tablespace name")
    SCHEMA_NAME: Optional[str] = Field(None, description="Schema name")
    HADR_STANDBY_SERVERNAME: Optional[str] = Field(None, description="HADR standby server")
    HADR_STANDBY_PORT: Optional[int] = Field(None, gt=0, le=65535, description="HADR standby port")
    
    # Object Store specific
    OS_LABEL: Optional[str] = Field(None, description="Object Store label")
    DATASOURCE_NAME: Optional[str] = Field(None, description="Datasource name")
    DATASOURCE_NAME_XA: Optional[str] = Field(None, description="XA datasource name")

    @field_validator('DATABASE_SERVERNAME')
    @classmethod
    def validate_servername(cls, v: str) -> str:
        """Validate server name format."""
        if not v or v == '<Required>':
            raise ValueError("Database server name is required")
        return v

    @field_validator('ORACLE_JDBC_URL')
    @classmethod
    def validate_oracle_jdbc(cls, v: Optional[str], info) -> Optional[str]:
        """Validate Oracle JDBC URL when database type is Oracle."""
        if info.data.get('DATABASE_TYPE') == DatabaseType.ORACLE:
            if not v or v == '<Required>':
                raise ValueError("ORACLE_JDBC_URL is required for Oracle databases")
        return v

    @model_validator(mode='after')
    def validate_hadr_config(self) -> 'DatabaseConfig':
        """Validate HADR configuration for DB2 HADR."""
        if self.DATABASE_TYPE in [DatabaseType.DB2HADR, DatabaseType.DB2RDSHADR]:
            if not self.HADR_STANDBY_SERVERNAME:
                raise ValueError("HADR_STANDBY_SERVERNAME is required for HADR configurations")
            if not self.HADR_STANDBY_PORT:
                raise ValueError("HADR_STANDBY_PORT is required for HADR configurations")
        return self

    @model_validator(mode='after')
    def validate_ssl_mode(self) -> 'DatabaseConfig':
        """Validate SSL mode for PostgreSQL."""
        if self.DATABASE_TYPE == DatabaseType.POSTGRESQL and self.DATABASE_SSL_ENABLE:
            if not self.SSL_MODE:
                raise ValueError("SSL_MODE is required when DATABASE_SSL_ENABLE is true for PostgreSQL")
        return self


class LDAPConfig(BaseModel):
    """LDAP configuration validation model."""
    LDAP_TYPE: Optional[LDAPType] = Field(..., description="LDAP server type")
    LDAP_ID: str = Field(..., min_length=1, description="LDAP server ID")
    LDAP_SERVER: str = Field(..., min_length=1, description="LDAP server hostname")
    LDAP_PORT: int = Field(..., gt=0, le=65535, description="LDAP server port")
    LDAP_BASE_DN: str = Field(..., min_length=1, description="LDAP base DN")
    LDAP_GROUP_BASE_DN: str = Field(..., min_length=1, description="LDAP group base DN")
    LDAP_BIND_DN: str = Field(..., min_length=1, description="LDAP bind DN")
    LDAP_BIND_DN_PASSWORD: str = Field(..., min_length=1, description="LDAP bind password")
    LDAP_SSL_ENABLED: bool = Field(..., description="Enable SSL for LDAP")
    LDAP_USER_NAME_ATTRIBUTE: str = Field(..., min_length=1, description="User name attribute")
    LDAP_USER_DISPLAY_NAME_ATTR: str = Field(..., min_length=1, description="User display name attribute")
    LDAP_GROUP_NAME_ATTRIBUTE: str = Field(..., min_length=1, description="Group name attribute")
    LDAP_GROUP_DISPLAY_NAME_ATTR: str = Field(..., min_length=1, description="Group display name attribute")
    LDAP_GROUP_MEMBERSHIP_ID_MAP: str = Field(..., min_length=1, description="Group membership ID map")
    LDAP_GROUP_MEMBERSHIP_SEARCH_FILTER: str = Field(..., min_length=1, description="Group membership search filter")
    LC_USER_FILTER: str = Field(..., min_length=1, description="User filter")
    LC_GROUP_FILTER: str = Field(..., min_length=1, description="Group filter")
    
    # Optional AD Global Catalog
    LC_AD_GC_HOST: Optional[str] = Field(None, description="AD Global Catalog host")
    LC_AD_GC_PORT: Optional[Union[int, str]] = Field(None, description="AD Global Catalog port")

    @field_validator('LDAP_TYPE', mode='before')
    @classmethod
    def validate_ldap_type(cls, v: Union[str, LDAPType]) -> Union[str, LDAPType, None]:
        """Validate LDAP type, allowing <Optional> placeholder."""
        if isinstance(v, str) and v == '<Optional>':
            return None
        # Let Pydantic handle the enum conversion for valid values
        return v

    @field_validator('LC_AD_GC_PORT', mode='before')
    @classmethod
    def validate_gc_port(cls, v: Union[int, str, None]) -> Optional[int]:
        """Validate AD Global Catalog port, allowing <Optional> placeholder."""
        if v is None:
            return None
        if isinstance(v, str):
            if v == '<Optional>':
                return None
            # Try to convert string to int
            try:
                port = int(v)
                if port <= 0 or port > 65535:
                    raise ValueError(f"Port must be between 1 and 65535, got {port}")
                return port
            except ValueError as e:
                if 'invalid literal' in str(e):
                    raise ValueError(f"LC_AD_GC_PORT must be a valid integer or '<Optional>', got '{v}'")
                raise
        if isinstance(v, int):
            if v <= 0 or v > 65535:
                raise ValueError(f"Port must be between 1 and 65535, got {v}")
        return v

    @field_validator('LDAP_PORT')
    @classmethod
    def validate_ldap_port(cls, v: int, info) -> int:
        """Validate LDAP port based on SSL setting."""
        ssl_enabled = info.data.get('LDAP_SSL_ENABLED', False)
        if ssl_enabled and v == 389:
            raise ValueError("LDAP_PORT should typically be 636 for SSL connections (389 is standard non-SSL)")
        return v

    @field_validator('LDAP_BASE_DN')
    @classmethod
    def validate_base_dn(cls, v: str) -> str:
        """Validate LDAP base DN format."""
        if not v or v == '<Required>':
            raise ValueError("LDAP_BASE_DN is required")
        
        result = validate_dn(v, strict_mode=False)
        if not result.is_valid:
            raise ValueError(
                f"Invalid LDAP_BASE_DN format: {result.error_message}. "
                f"Example: dc=example,dc=com"
            )
        return v

    @field_validator('LDAP_GROUP_BASE_DN')
    @classmethod
    def validate_group_base_dn(cls, v: str) -> str:
        """Validate LDAP group base DN format."""
        if not v or v == '<Required>':
            raise ValueError("LDAP_GROUP_BASE_DN is required")
        
        result = validate_dn(v, strict_mode=False)
        if not result.is_valid:
            raise ValueError(
                f"Invalid LDAP_GROUP_BASE_DN format: {result.error_message}. "
                f"Example: ou=Groups,dc=example,dc=com"
            )
        return v

    @field_validator('LDAP_BIND_DN')
    @classmethod
    def validate_bind_dn(cls, v: str) -> str:
        """Validate LDAP bind DN format."""
        if not v or v == '<Required>':
            raise ValueError("LDAP_BIND_DN is required")
        
        result = validate_dn(v, strict_mode=False)
        if not result.is_valid:
            raise ValueError(
                f"Invalid LDAP_BIND_DN format: {result.error_message}. "
                f"Example: cn=admin,dc=example,dc=com"
            )
        return v


class IDPConfig(BaseModel):
    """Identity Provider (IDP) configuration validation model."""
    PROVIDER_NAME: str = Field(..., min_length=1, description="Provider name")
    IDP_SSL_ENABLED: bool = Field(..., description="Enable SSL for IDP")
    DISPLAY_NAME: str = Field(..., min_length=1, description="Display name")
    DISCOVERY_ENDPOINT: str = Field(..., min_length=1, description="OIDC discovery endpoint")
    JWKS_ENDPOINT: str = Field(..., min_length=1, description="JWKS endpoint")
    CLIENT_ID: str = Field(..., min_length=1, description="OIDC client ID")
    CLIENT_SECRET: str = Field(..., min_length=1, description="OIDC client secret")
    VALIDATION_METHOD: ValidationMethod = Field(..., description="Token validation method")
    USER_IDENTIFIER: str = Field(..., min_length=1, description="User identifier")
    UNIQUE_USER_IDENTIFIER: str = Field(..., min_length=1, description="Unique user identifier")
    USER_IDENTIFIER_TO_CREATE_SUBJECT: str = Field(..., min_length=1, description="User identifier for subject")
    ISSUER: str = Field(..., min_length=1, description="IDP issuer")
    TOKEN_ENDPOINT: str = Field(..., min_length=1, description="Token endpoint")
    INTROSPECT_ENDPOINT: Optional[str] = Field(None, description="Introspect endpoint")
    USERINFO_ENDPOINT: Optional[str] = Field(None, description="User info endpoint")
    REVOCATION_ENDPOINT: str = Field(..., min_length=1, description="Revocation endpoint")

    @model_validator(mode='after')
    def validate_endpoints(self) -> 'IDPConfig':
        """Validate required endpoints based on validation method."""
        if self.VALIDATION_METHOD == ValidationMethod.INTROSPECT:
            if not self.INTROSPECT_ENDPOINT or self.INTROSPECT_ENDPOINT == '<Required>':
                raise ValueError("INTROSPECT_ENDPOINT is required when VALIDATION_METHOD is 'introspect'")
        elif self.VALIDATION_METHOD == ValidationMethod.USERINFO:
            if not self.USERINFO_ENDPOINT or self.USERINFO_ENDPOINT == '<Required>':
                raise ValueError("USERINFO_ENDPOINT is required when VALIDATION_METHOD is 'userinfo'")
        return self


class SCIMConfig(BaseModel):
    """SCIM configuration validation model."""
    DISPLAY_NAME: str = Field(..., min_length=1, description="SCIM display name")
    SCIM_TYPE: SCIMType = Field(SCIMType.AUTO_DETECT, description="SCIM provider type")
    SCIM_SSL_ENABLED: bool = Field(..., description="Enable SSL for SCIM")
    SCIM_SERVER: str = Field(..., min_length=1, description="SCIM server hostname")
    SCIM_PORT: int = Field(..., gt=0, le=65535, description="SCIM server port")
    SCIM_CONTEXT_PATH: str = Field(..., min_length=1, description="SCIM context path")
    TOKEN_ENDPOINT: str = Field(..., min_length=1, description="Token endpoint")
    SCIM_CLIENT_ID: str = Field(..., min_length=1, description="SCIM client ID")
    SCIM_CLIENT_SECRET: str = Field(..., min_length=1, description="SCIM client secret")


class AIServicesConfig(BaseModel):
    """AI Services configuration validation model for generic AI providers."""
    AI_PROVIDER_LABEL: str = Field(..., min_length=1, description="Descriptive label for the AI provider")
    DEPLOYMENT_TYPE: AIDeploymentType = Field(..., description="AI provider deployment type")
    SERVICE_ENDPOINT: str = Field(..., min_length=1, description="AI provider service endpoint")
    API_KEY: str = Field(..., min_length=1, description="API key for authentication")
    SPACE_ID: Optional[str] = Field("", description="Space ID (if applicable)")
    PROJECT_ID: Optional[str] = Field("", description="Project ID (if applicable)")
    ENABLE_REDIS: bool = Field(False, description="Enable Redis")

    @field_validator('SERVICE_ENDPOINT')
    @classmethod
    def validate_endpoint(cls, v: str) -> str:
        """Validate service endpoint format."""
        if not v.startswith(('http://', 'https://')):
            raise ValueError("SERVICE_ENDPOINT must start with http:// or https://")
        return v

    @model_validator(mode='after')
    def validate_space_or_project(self) -> 'AIServicesConfig':
        """Validate that at least one of space_id or project_id is provided for SaaS."""
        if self.DEPLOYMENT_TYPE == AIDeploymentType.SAAS:
            if not self.SPACE_ID and not self.PROJECT_ID:
                raise ValueError(
                    "At least one of SPACE_ID or PROJECT_ID is required for SaaS deployment"
                )
        return self


class DeploymentConfig(BaseModel):
    """Deployment configuration validation model."""
    CCX_Version: str = Field(..., min_length=1, description="Content Cortex version")
    LICENSE: str = Field(..., min_length=1, description="Deployment license")
    PLATFORM: str = Field(..., min_length=1, description="Platform type")
    FIPS_SUPPORT: bool = Field(False, description="FIPS support enabled")
    GENERATE_NETWORK_POLICIES: bool = Field(False, description="Generate network policies")
    
    # Vault configuration
    VAULT_ENABLED: bool = Field(False, description="Enable HashiCorp Vault for secret management")
    VAULT_URL: Optional[str] = Field(None, description="Vault server URL")
    VAULT_ROLE: Optional[str] = Field(None, description="Vault Kubernetes authentication role")
    VAULT_PATH: Optional[str] = Field("secret/data", description="Vault KV secrets engine path")
    VAULT_CERT_PATH: Optional[str] = Field("", description="Path to Vault CA certificate")

    @model_validator(mode='after')
    def validate_vault_config(self) -> 'DeploymentConfig':
        """Validate vault configuration when vault is enabled."""
        if self.VAULT_ENABLED:
            if not self.VAULT_URL or self.VAULT_URL == '<Required>':
                raise ValueError("VAULT_URL is required when VAULT_ENABLED is true")
            if not self.VAULT_ROLE or self.VAULT_ROLE == '<Required>':
                raise ValueError("VAULT_ROLE is required when VAULT_ENABLED is true")
            if not self.VAULT_PATH or self.VAULT_PATH == '<Required>':
                raise ValueError("VAULT_PATH is required when VAULT_ENABLED is true")
        return self


class IngressConfig(BaseModel):
    """Ingress configuration validation model."""
    INGRESS_ENABLED: bool = Field(True, description="Enable ingress")
    INGRESS_HOSTNAME: Optional[str] = Field(None, description="Ingress hostname")
    INGRESS_ANNOTATIONS: List[str] = Field(default_factory=list, description="Ingress annotations")
    INGRESS_TLS_ENABLED: bool = Field(False, description="Enable TLS")
    INGRESS_TLS_SECRET_NAME: Optional[str] = Field(None, description="TLS secret name")
    SERVICE_TYPE: str = Field("ClusterIP", description="Service type")

    @model_validator(mode='after')
    def validate_ingress_config(self) -> 'IngressConfig':
        """Validate ingress configuration."""
        if self.INGRESS_ENABLED and not self.INGRESS_HOSTNAME:
            raise ValueError("INGRESS_HOSTNAME is required when INGRESS_ENABLED is true")
        if self.INGRESS_TLS_ENABLED and not self.INGRESS_TLS_SECRET_NAME:
            raise ValueError("INGRESS_TLS_SECRET_NAME is required when INGRESS_TLS_ENABLED is true")
        return self


class EgressConfig(BaseModel):
    """Egress configuration validation model."""
    RESTRICTED_INTERNET_ACCESS: bool = Field(False, description="Restricted internet access")
    K8_API_NAMESPACE: List[str] = Field(..., description="Kubernetes API namespaces")
    K8_API_PORT: List[int] = Field([443, 6443], description="Kubernetes API ports")
    K8_DNS_NAMESPACE: List[str] = Field(..., description="Kubernetes DNS namespaces")
    K8_DNS_PORT: List[int] = Field([53, 5353], description="Kubernetes DNS ports")


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATION ERROR HANDLER
# ═══════════════════════════════════════════════════════════════════════════════

class ValidationErrorHandler:
    """Handles validation errors with rich terminal output and remediation guidance."""
    
    def __init__(self, console: Optional[Console] = None):
        """Initialize the error handler."""
        self.console = console or Console()
        self.remediation_guide = self._build_remediation_guide()
    
    def _build_remediation_guide(self) -> Dict[str, Dict[str, str]]:
        """Build comprehensive remediation guidance for common errors."""
        return {
            "DATABASE_TYPE": {
                "error": "Invalid database type",
                "remediation": "Use one of: db2, db2hadr, db2rds, db2rdshadr, oracle, postgresql, sqlserver",
                "example": 'DATABASE_TYPE = "postgresql"'
            },
            "DATABASE_PORT": {
                "error": "Invalid port number",
                "remediation": "Port must be between 1 and 65535",
                "example": "DATABASE_PORT = 5432  # PostgreSQL default"
            },
            "LDAP_TYPE": {
                "error": "Invalid LDAP type",
                "remediation": "Use one of: Microsoft Active Directory, IBM Tivoli Directory Server, CA eTrust, Novell eDirectory, Oracle Internet Directory",
                "example": 'LDAP_TYPE = "Microsoft Active Directory"'
            },
            "LDAP_PORT": {
                "error": "LDAP port mismatch with SSL setting",
                "remediation": "Use port 636 for SSL connections, 389 for non-SSL",
                "example": "LDAP_PORT = 636  # For SSL\nLDAP_SSL_ENABLED = true"
            },
            "WATSONX_DEPLOYMENT_TYPE": {
                "error": "Invalid WatsonX deployment type",
                "remediation": "Use either 'saas' or 'lightweightengine'",
                "example": 'WATSONX_DEPLOYMENT_TYPE = "saas"'
            },
            "WATSONX_SERVICE_ENDPOINT": {
                "error": "Invalid service endpoint format",
                "remediation": "Endpoint must start with http:// or https://",
                "example": 'WATSONX_SERVICE_ENDPOINT = "https://us-south.ml.cloud.ibm.com"'
            },
            "WATSONX_SPACE_ID": {
                "error": "Missing space or project ID for SaaS",
                "remediation": "Provide at least one of WATSONX_SPACE_ID or WATSONX_PROJECT_ID for SaaS deployment",
                "example": 'WATSONX_SPACE_ID = "your-space-id-here"'
            },
            "ORACLE_JDBC_URL": {
                "error": "Missing JDBC URL for Oracle",
                "remediation": "ORACLE_JDBC_URL is required for Oracle databases",
                "example": 'ORACLE_JDBC_URL = "jdbc:oracle:thin:@//hostname:1521/servicename"'
            },
            "HADR_STANDBY_SERVERNAME": {
                "error": "Missing HADR standby configuration",
                "remediation": "HADR_STANDBY_SERVERNAME and HADR_STANDBY_PORT are required for HADR configurations",
                "example": 'HADR_STANDBY_SERVERNAME = "standby-db-server.example.com"\nHADR_STANDBY_PORT = 50000'
            },
            "SSL_MODE": {
                "error": "Missing SSL mode for PostgreSQL",
                "remediation": "SSL_MODE is required when DATABASE_SSL_ENABLE is true for PostgreSQL",
                "example": 'SSL_MODE = "verify-full"  # Options: require, verify-ca, verify-full'
            },
            "VALIDATION_METHOD": {
                "error": "Invalid validation method",
                "remediation": "Use either 'introspect' or 'userinfo'",
                "example": 'VALIDATION_METHOD = "introspect"'
            },
            "INTROSPECT_ENDPOINT": {
                "error": "Missing introspect endpoint",
                "remediation": "INTROSPECT_ENDPOINT is required when VALIDATION_METHOD is 'introspect'",
                "example": 'INTROSPECT_ENDPOINT = "https://idp.example.com/oauth2/introspect"'
            },
            "USERINFO_ENDPOINT": {
                "error": "Missing userinfo endpoint",
                "remediation": "USERINFO_ENDPOINT is required when VALIDATION_METHOD is 'userinfo'",
                "example": 'USERINFO_ENDPOINT = "https://idp.example.com/oauth2/userinfo"'
            },
            "INGRESS_HOSTNAME": {
                "error": "Missing ingress hostname",
                "remediation": "INGRESS_HOSTNAME is required when INGRESS_ENABLED is true",
                "example": 'INGRESS_HOSTNAME = "fncm.example.com"'
            },
            "INGRESS_TLS_SECRET_NAME": {
                "error": "Missing TLS secret name",
                "remediation": "INGRESS_TLS_SECRET_NAME is required when INGRESS_TLS_ENABLED is true",
                "example": 'INGRESS_TLS_SECRET_NAME = "fncm-tls-secret"'
            },
            "VAULT_URL": {
                "error": "Missing Vault URL",
                "remediation": "VAULT_URL is required when VAULT_ENABLED is true",
                "example": 'VAULT_URL = "https://vault.example.com:8200"'
            },
            "VAULT_ROLE": {
                "error": "Missing Vault role",
                "remediation": "VAULT_ROLE is required when VAULT_ENABLED is true. This role must be configured in Vault with appropriate policies.",
                "example": 'VAULT_ROLE = "ccx-role"  # Or use namespace-specific role like "my-namespace-role"'
            },
            "VAULT_PATH": {
                "error": "Missing Vault path",
                "remediation": "VAULT_PATH is required when VAULT_ENABLED is true. Use 'secret/data' for KV v2 or 'secret' for KV v1.",
                "example": 'VAULT_PATH = "secret/data"  # For KV v2 engine (default)'
            },
            "<Required>": {
                "error": "Required field not filled",
                "remediation": "Replace '<Required>' with an actual value",
                "example": "Remove the placeholder and provide a real value"
            }
        }
    
    def display_validation_errors(
        self,
        errors: List[Dict[str, Any]],
        file_path: str,
        property_type: str
    ) -> None:
        """Display validation errors with rich formatting and remediation guidance."""
        
        # Header panel
        self.console.print()
        self.console.print(Panel(
            f"[bold red]✗ Validation Failed[/bold red]\n"
            f"[yellow]File:[/yellow] {file_path}\n"
            f"[yellow]Type:[/yellow] {property_type}",
            title="Property File Validation Error",
            border_style="red",
            box=box.DOUBLE
        ))
        
        # Create error table
        table = Table(
            title=f"[bold]Found {len(errors)} Validation Error(s)[/bold]",
            show_header=True,
            header_style="bold cyan",
            border_style="red",
            box=box.ROUNDED
        )
        
        table.add_column("Field", style="yellow", no_wrap=True)
        table.add_column("Error", style="red")
        table.add_column("Location", style="dim")
        
        for error in errors:
            field = error.get('loc', ['unknown'])[-1]
            msg = error.get('msg', 'Unknown error')
            loc = ' → '.join(str(l) for l in error.get('loc', []))
            
            table.add_row(field, msg, loc)
        
        self.console.print(table)
        
        # Display remediation guidance
        self._display_remediation(errors)
        
        # Summary panel
        self.console.print()
        self.console.print(Panel(
            "[bold yellow]⚠ Action Required[/bold yellow]\n\n"
            "Please review and fix the errors above before proceeding.\n"
            "Each error includes specific remediation guidance and examples.",
            border_style="yellow",
            box=box.ROUNDED
        ))
        self.console.print()
    
    def _display_remediation(self, errors: List[Dict[str, Any]]) -> None:
        """Display remediation guidance for errors."""
        self.console.print()
        self.console.print("[bold cyan]📋 Remediation Guidance:[/bold cyan]")
        self.console.print()
        
        for idx, error in enumerate(errors, 1):
            field = error.get('loc', ['unknown'])[-1]
            msg = error.get('msg', '')
            
            # Find matching remediation
            remediation = None
            for key, guide in self.remediation_guide.items():
                if key in str(field) or key in msg:
                    remediation = guide
                    break
            
            if remediation:
                panel_content = (
                    f"[bold red]Error:[/bold red] {remediation['error']}\n\n"
                    f"[bold green]Fix:[/bold green] {remediation['remediation']}\n\n"
                    f"[bold blue]Example:[/bold blue]\n[dim]{remediation['example']}[/dim]"
                )
            else:
                panel_content = (
                    f"[bold red]Error:[/bold red] {msg}\n\n"
                    f"[bold green]Fix:[/bold green] Please check the property file documentation\n"
                    f"for valid values for the '{field}' field."
                )
            
            self.console.print(Panel(
                panel_content,
                title=f"[bold]{idx}. {field}[/bold]",
                border_style="cyan",
                box=box.ROUNDED
            ))
            self.console.print()


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PROPERTY READER CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

class ReadProp:
    """
    Enhanced property file reader with Pydantic validation.
    
    This class reads TOML property files and validates them using Pydantic models.
    It provides comprehensive error reporting with remediation guidance.
    """
    
    # Validation model mapping
    VALIDATION_MODELS: Dict[str, type[BaseModel]] = {}
    
    # Fields that are optional and should not be flagged when empty
    OPTIONAL_EMPTY_FIELDS: set[str] = set()
    
    def __init__(self, propertyfile: str, logger: logging.Logger, console: Optional[Console] = None,
                 auto_display_errors: bool = False):
        """
        Initialize the property reader.
        
        Args:
            propertyfile: Path to the TOML property file
            logger: Logger instance for logging
            console: Rich console for output (optional)
            auto_display_errors: If True, display errors automatically (default: False for unified display)
        """
        self._prop_filepath = Path(propertyfile)
        self._logger = logger
        self._console = console or Console()
        self._error_handler = ValidationErrorHandler(self._console)
        self._toml_dict: Dict[str, Any] = {}
        self._validation_errors: List[Dict[str, Any]] = []
        self._has_required_fields = False
        self._auto_display_errors = auto_display_errors
        
        # Initialize required_fields for backward compatibility with old code
        self.required_fields: Dict[str, List[Tuple[List[str], Any]]] = {}
        
        # Load and validate the property file
        self._load_property_file()
        
        # Automatically check for required fields
        self._check_required_fields(self._toml_dict)
    
    def _load_property_file(self) -> None:
        """Load the TOML property file."""
        try:
            with open(self._prop_filepath, encoding="utf-8") as f:
                self._toml_dict = toml.load(f)
            self._logger.info(f"Loaded property file: {self._prop_filepath}")
        except FileNotFoundError:
            self._logger.error(f"Property file not found: {self._prop_filepath}")
            raise
        except toml.TomlDecodeError as e:
            self._logger.error(f"Invalid TOML syntax in {self._prop_filepath}: {e}")
            self._console.print(Panel(
                f"[bold red]✗ TOML Syntax Error[/bold red]\n\n"
                f"[yellow]File:[/yellow] {self._prop_filepath}\n"
                f"[red]Error:[/red] {str(e)}\n\n"
                f"[bold]Fix:[/bold] Check for missing quotes, brackets, or commas in your TOML file.",
                title="TOML Parse Error",
                border_style="red"
            ))
            raise
    
    def _check_required_fields(self, data: Dict[str, Any], path: Optional[List[str]] = None) -> None:
        """
        Recursively check for required fields marked with '<Required>'.
        
        Args:
            data: Dictionary to check
            path: Current path in the nested structure
        """
        if path is None:
            path = []
        
        for key, value in data.items():
            current_path = path + [key]
            
            if isinstance(value, dict):
                self._check_required_fields(value, current_path)
            elif isinstance(value, list):
                if '<Required>' in value:
                    self._has_required_fields = True
                    self._validation_errors.append({
                        'loc': tuple(current_path),
                        'msg': 'Required field contains placeholder value',
                        'type': 'value_error.required'
                    })
                    # Populate required_fields for backward compatibility
                    file_name = self._prop_filepath.name
                    if file_name not in self.required_fields:
                        self.required_fields[file_name] = []
                    self.required_fields[file_name].append((current_path, value))
            elif value == '<Required>' or value == '':
                # Skip optional fields that are allowed to be empty
                field_name = current_path[-1] if current_path else ''
                if field_name in self.OPTIONAL_EMPTY_FIELDS:
                    continue
                    
                self._has_required_fields = True
                self._validation_errors.append({
                    'loc': tuple(current_path),
                    'msg': 'Required field is empty or contains placeholder',
                    'type': 'value_error.required'
                })
                # Populate required_fields for backward compatibility
                file_name = self._prop_filepath.name
                if file_name not in self.required_fields:
                    self.required_fields[file_name] = []
                self.required_fields[file_name].append((current_path, value))
        
        # Display errors automatically if requested (for backward compatibility)
        if self._auto_display_errors and self._has_required_fields:
            self._error_handler.display_validation_errors(
                self._validation_errors,
                str(self._prop_filepath),
                self.__class__.__name__
            )
    
    def validate(self, model_class: Optional[type[BaseModel]] = None) -> bool:
        """
        Validate the property file using Pydantic model.
        
        Args:
            model_class: Pydantic model class to use for validation
            
        Returns:
            True if validation passes, False otherwise
        """
        # First check for required fields
        self._check_required_fields(self._toml_dict)
        
        if self._has_required_fields and self._auto_display_errors:
            self._error_handler.display_validation_errors(
                self._validation_errors,
                str(self._prop_filepath),
                self.__class__.__name__
            )
            return False
        
        # If a validation model is provided, use it
        if model_class:
            try:
                model_class(**self._toml_dict)
                self._logger.info(f"✓ Validation passed for {self._prop_filepath}")
                return True
            except ValidationError as e:
                self._validation_errors = [dict(err) for err in e.errors()]
                if self._auto_display_errors:
                    self._error_handler.display_validation_errors(
                        self._validation_errors,
                        str(self._prop_filepath),
                        model_class.__name__
                    )
                return False
        
        return True
    
    def missing_required_fields(self) -> bool:
        """Check if there are missing required fields."""
        return self._has_required_fields or len(self._validation_errors) > 0
    
    def get_validation_errors(self) -> List[Dict[str, Any]]:
        """Get the list of validation errors."""
        return self._validation_errors
    
    def to_dict(self) -> Dict[str, Any]:
        """Return the property dictionary."""
        return self._toml_dict


class ReadPropDb(ReadProp):
    """Database property file reader with enhanced validation."""
    
    VALIDATION_MODELS = {'default': DatabaseConfig}
    
    def __init__(self, propertyfile: str, logger: logging.Logger, console: Optional[Console] = None):
        """Initialize database property reader."""
        super().__init__(propertyfile, logger, console)
        self._find_os_ids()
        self._force_postgres_dbnames()
        self._generate_tablespace_names()
        self._calculate_db_info()
    
    def _find_os_ids(self) -> None:
        """Find all Object Store IDs in the property file."""
        os_ids = [key for key in self._toml_dict.keys() if "OS" in key]
        self._toml_dict["_os_ids"] = os_ids
        self._logger.info(f"Found {len(os_ids)} Object Store(s): {', '.join(os_ids)}")
    
    def _force_postgres_dbnames(self) -> None:
        """Force lowercase database names for PostgreSQL."""
        if self._toml_dict.get("DATABASE_TYPE", "").lower() == "postgresql":
            self._logger.info("Forcing lowercase on PostgreSQL database names...")
            
            if "GCD" in self._toml_dict:
                self._toml_dict["GCD"]["DATABASE_NAME"] = self._toml_dict["GCD"]["DATABASE_NAME"].lower()
            
            if "ICN" in self._toml_dict:
                self._toml_dict["ICN"]["DATABASE_NAME"] = self._toml_dict["ICN"]["DATABASE_NAME"].lower()
            
            for os_id in self._toml_dict.get("_os_ids", []):
                if os_id in self._toml_dict:
                    self._toml_dict[os_id]["DATABASE_NAME"] = self._toml_dict[os_id]["DATABASE_NAME"].lower()
    
    def _generate_tablespace_names(self) -> None:
        """Generate tablespace names based on database type."""
        db_type = self._toml_dict.get("DATABASE_TYPE", "").lower()
        
        for os_id in self._toml_dict.get("_os_ids", []):
            if os_id not in self._toml_dict:
                continue
                
            os_name = self._toml_dict[os_id].get("DATABASE_NAME", "")
            
            if db_type == "sqlserver":
                self._toml_dict[os_id]["DATA_TABLESPACE"] = "PRIMARY"
                self._toml_dict[os_id]["INDEX_TABLESPACE"] = f"{os_name}INDEXTS"
                self._toml_dict[os_id]["LOB_TABLESPACE"] = f"{os_name}LOBTS"
            
            elif db_type == "oracle":
                self._toml_dict[os_id]["DATA_TABLESPACE"] = f"{os_name}DATATS".upper()
                self._toml_dict[os_id]["TMP_TABLESPACE"] = f"{os_name}DATATSTEMP".upper()
                self._toml_dict[os_id]["INDEX_TABLESPACE"] = f"{os_name}INDEXTS".upper()
                self._toml_dict[os_id]["LOB_TABLESPACE"] = f"{os_name}LOBTS".upper()
            
            elif db_type == "postgresql":
                self._toml_dict[os_id]["DATA_TABLESPACE"] = f"{os_name}_tbs".lower()
                self._toml_dict[os_id]["INDEX_TABLESPACE"] = f"{os_name}indexts".lower()
            
            elif db_type in ["db2", "db2hadr", "db2rds", "db2rdshadr"]:
                self._toml_dict[os_id]["DATA_TABLESPACE"] = f"{os_name}DATA_TS"
                self._toml_dict[os_id]["INDEX_TABLESPACE"] = f"{os_name}INDEX_TS"
                self._toml_dict[os_id]["LOB_TABLESPACE"] = f"{os_name}LOB_TS"
                self._toml_dict[os_id]["TMP_TABLESPACE"] = f"{os_name}_TMP_TBS"
    
    def _calculate_db_info(self) -> None:
        """Calculate database count and list."""
        db_list = self._toml_dict.get("_os_ids", []).copy()
        db_number = len(db_list)
        
        if "GCD" in self._toml_dict:
            db_number += 1
            db_list.append("GCD")
        
        if "ICN" in self._toml_dict:
            db_number += 1
            db_list.append("ICN")
        
        self._toml_dict["db_number"] = db_number
        self._toml_dict["db_list"] = db_list
        self._logger.info(f"Total databases configured: {db_number}")


class ReadPropLdap(ReadProp):
    """LDAP property file reader with enhanced validation."""
    
    VALIDATION_MODELS = {'default': LDAPConfig}
    
    def __init__(self, propertyfile: str, logger: logging.Logger, console: Optional[Console] = None):
        """Initialize LDAP property reader."""
        super().__init__(propertyfile, logger, console)
        self._find_ldap_ids()
        self._validate_ldap_configs()
    
    def _find_ldap_ids(self) -> None:
        """Find all LDAP IDs in the property file."""
        ldap_ids = list(self._toml_dict.keys())
        self._toml_dict["_ldap_ids"] = ldap_ids
        self._toml_dict["ldap_number"] = len(ldap_ids)
        self._logger.info(f"Found {len(ldap_ids)} LDAP configuration(s)")
    
    def _validate_ldap_configs(self) -> None:
        """Validate each LDAP configuration using Pydantic model."""
        for ldap_id in self._toml_dict.get("_ldap_ids", []):
            if ldap_id.startswith("_"):
                continue
            
            ldap_config = self._toml_dict.get(ldap_id, {})
            if not ldap_config:
                continue
            
            try:
                # Validate using LDAPConfig model
                LDAPConfig(**ldap_config)
                self._logger.debug(f"✓ LDAP configuration '{ldap_id}' validation passed")
            except ValidationError as e:
                # Add errors to validation errors list
                for error in e.errors():
                    error_dict = dict(error)
                    # Prepend LDAP ID to location path
                    loc = error_dict.get('loc', ())
                    if isinstance(loc, tuple):
                        error_dict['loc'] = (ldap_id,) + loc
                    else:
                        error_dict['loc'] = (ldap_id,)
                    self._validation_errors.append(error_dict)
                # Use debug level since errors will be shown in unified display
                self._logger.debug(f"LDAP configuration '{ldap_id}' has validation errors")


class ReadPropIdp(ReadProp):
    """IDP property file reader with enhanced validation."""
    
    VALIDATION_MODELS = {'default': IDPConfig}
    
    def __init__(self, propertyfile: str, logger: logging.Logger, console: Optional[Console] = None):
        """Initialize IDP property reader."""
        super().__init__(propertyfile, logger, console)
        self._find_idp_ids()
    
    def _find_idp_ids(self) -> None:
        """Find all IDP IDs in the property file."""
        idp_ids = list(self._toml_dict.keys())
        self._toml_dict["_idp_ids"] = idp_ids
        self._toml_dict["idp_number"] = len(idp_ids)
        self._logger.info(f"Found {len(idp_ids)} IDP configuration(s)")


class ReadPropSCIM(ReadProp):
    """SCIM property file reader with enhanced validation."""
    
    VALIDATION_MODELS = {'default': SCIMConfig}
    
    def __init__(self, propertyfile: str, logger: logging.Logger, console: Optional[Console] = None):
        """Initialize SCIM property reader."""
        super().__init__(propertyfile, logger, console)
        self._find_scim_ids()
    
    def _find_scim_ids(self) -> None:
        """Find all SCIM IDs in the property file."""
        scim_ids = [key for key in self._toml_dict.keys() if "SCIM" in key]
        self._toml_dict["_scim_ids"] = scim_ids
        self._toml_dict["scim_number"] = len(scim_ids)
        self._logger.info(f"Found {len(scim_ids)} SCIM configuration(s)")


class ReadPropUsergroup(ReadProp):
    """User group property file reader."""
    
    def __init__(self, propertyfile: str, logger: logging.Logger, console: Optional[Console] = None):
        """Initialize user group property reader."""
        super().__init__(propertyfile, logger, console)


class ReadPropDeployment(ReadProp):
    """Deployment property file reader with enhanced validation."""
    
    VALIDATION_MODELS = {'default': DeploymentConfig}
    
    def __init__(self, propertyfile: str, logger: logging.Logger, console: Optional[Console] = None):
        """Initialize deployment property reader."""
        super().__init__(propertyfile, logger, console)
    
    def _check_required_fields(self, data: Dict[str, Any], path: Optional[List[str]] = None) -> None:
        """
        Override to handle vault fields conditionally based on VAULT_ENABLED.
        
        Args:
            data: Dictionary to check
            path: Current path in the nested structure
        """
        if path is None:
            path = []
        
        # Check if vault is enabled
        vault_enabled = data.get('VAULT_ENABLED', False)
        
        # Define vault-related fields that should only be required when vault is enabled
        vault_required_fields = {'VAULT_URL', 'VAULT_ROLE', 'VAULT_PATH'}
        
        # VAULT_CERT_PATH is always optional (for self-signed certs)
        vault_optional_fields = {'VAULT_CERT_PATH'}
        
        for key, value in data.items():
            current_path = path + [key]
            
            # Skip all vault fields if vault is not enabled
            if not vault_enabled and (key in vault_required_fields or key in vault_optional_fields):
                continue
            
            # Skip optional vault fields even when vault is enabled
            if key in vault_optional_fields:
                continue
            
            if isinstance(value, dict):
                self._check_required_fields(value, current_path)
            elif isinstance(value, list):
                if '<Required>' in value:
                    self._has_required_fields = True
                    self._validation_errors.append({
                        'loc': tuple(current_path),
                        'msg': 'Required field contains placeholder value',
                        'type': 'value_error.required'
                    })
                    # Populate required_fields for backward compatibility
                    file_name = self._prop_filepath.name
                    if file_name not in self.required_fields:
                        self.required_fields[file_name] = []
                    self.required_fields[file_name].append((current_path, value))
            elif value == '<Required>' or value == '':
                # Skip optional fields that are allowed to be empty
                field_name = current_path[-1] if current_path else ''
                if field_name in self.OPTIONAL_EMPTY_FIELDS:
                    continue
                    
                self._has_required_fields = True
                self._validation_errors.append({
                    'loc': tuple(current_path),
                    'msg': 'Required field is empty or contains placeholder',
                    'type': 'value_error.required'
                })
                # Populate required_fields for backward compatibility
                file_name = self._prop_filepath.name
                if file_name not in self.required_fields:
                    self.required_fields[file_name] = []
                self.required_fields[file_name].append((current_path, value))
        
        # Display errors automatically if requested (for backward compatibility)
        if self._auto_display_errors and self._has_required_fields:
            self._error_handler.display_validation_errors(
                self._validation_errors,
                str(self._prop_filepath),
                self.__class__.__name__
            )


class ReadPropIngress(ReadProp):
    """Ingress property file reader with enhanced validation."""
    
    VALIDATION_MODELS = {'default': IngressConfig}
    
    def __init__(self, propertyfile: str, logger: logging.Logger, console: Optional[Console] = None):
        """Initialize ingress property reader."""
        super().__init__(propertyfile, logger, console)


class ReadPropCustomComponent(ReadProp):
    """Custom component property file reader."""
    
    def __init__(self, propertyfile: str, logger: logging.Logger, console: Optional[Console] = None):
        """Initialize custom component property reader."""
        super().__init__(propertyfile, logger, console)


class ReadPropImageTag(ReadProp):
    """Image tag property file reader."""
    
    def __init__(self, propertyfile: str, logger: logging.Logger, console: Optional[Console] = None):
        """Initialize image tag property reader."""
        super().__init__(propertyfile, logger, console)
    
    def check_toml(self) -> List[str]:
        """Check for incorrect keys in image tag configuration."""
        keys_to_check = ["TAG", "REPOSITORY", "DIGEST"]
        incorrect_keys_list = []
        
        for key, value in self._toml_dict.items():
            if isinstance(value, dict) and set(keys_to_check).issubset(set(value.keys())):
                incorrect_keys_list.append(key)
        
        return incorrect_keys_list


class ReadPropAIServices(ReadProp):
    """AI Services property file reader with support for multiple AI providers."""
    
    VALIDATION_MODELS = {'default': AIServicesConfig}
    
    # SPACE_ID and PROJECT_ID are optional - only one is required for SaaS
    OPTIONAL_EMPTY_FIELDS = {'SPACE_ID', 'PROJECT_ID'}
    
    def __init__(self, propertyfile: str, logger: logging.Logger, console: Optional[Console] = None,
                 auto_display_errors: bool = False):
        """Initialize AI Services property reader."""
        super().__init__(propertyfile, logger, console, auto_display_errors)
        self._find_provider_ids()
    
    def display_provider_validation_errors(
        self,
        errors: List[Dict[str, Any]],
        file_path: str
    ) -> None:
        """
        Display validation errors grouped by provider for better readability.
        
        Args:
            errors: List of validation error dictionaries
            file_path: Path to the property file
        """
        from rich import box
        from rich.panel import Panel
        from rich.table import Table
        
        # Header panel
        self._console.print()
        self._console.print(Panel(
            f"[bold red]✗ Validation Failed[/bold red]\n"
            f"[yellow]File:[/yellow] {file_path}\n"
            f"[yellow]Type:[/yellow] AI Services Multi-Provider Configuration",
            title="Property File Validation Error",
            border_style="red",
            box=box.DOUBLE
        ))
        
        # Group errors by provider
        provider_errors = {}
        for error in errors:
            loc = error.get('loc', [])
            if not loc:
                continue
            
            # First element in loc is the provider (e.g., PROVIDER_1, PROVIDER_2)
            provider = loc[0] if loc else 'UNKNOWN'
            
            if provider not in provider_errors:
                provider_errors[provider] = []
            
            provider_errors[provider].append(error)
        
        # Display errors grouped by provider
        for provider, provider_error_list in sorted(provider_errors.items()):
            self._console.print()
            self._console.print(f"[bold cyan]📦 {provider}[/bold cyan] ([red]{len(provider_error_list)} issue(s)[/red])")
            
            # Create table for this provider's errors
            table = Table(
                show_header=True,
                header_style="bold yellow",
                border_style="red",
                box=box.SIMPLE,
                padding=(0, 1)
            )
            
            table.add_column("Field Path", style="yellow", no_wrap=False)
            table.add_column("Issue", style="red", no_wrap=False)
            
            for error in provider_error_list:
                loc = error.get('loc', [])
                msg = error.get('msg', 'Unknown error')
                
                # Format the field path (skip the provider name since it's in the header)
                if len(loc) > 1:
                    field_path = ' → '.join(str(l) for l in loc[1:])
                else:
                    field_path = str(loc[0]) if loc else 'unknown'
                
                table.add_row(field_path, msg)
            
            self._console.print(table)
        
        # Display remediation guidance
        self._console.print()
        self._console.print("[bold cyan]📋 Common Fixes:[/bold cyan]")
        self._console.print()
        
        remediation_panel = Panel(
            "[bold yellow]Required Fields:[/bold yellow]\n"
            "• [cyan]API_KEY[/cyan]: Provide valid API key for authentication\n"
            "• [cyan]PROVIDER_URL[/cyan]: Set the endpoint URL for the AI service\n"
            "• [cyan]MODEL[/cyan]: Specify the model identifier\n"
            "• [cyan]USERNAME/PASSWORD[/cyan]: Required for WatsonX LWE deployments\n\n"
            "[bold yellow]Optional Fields:[/bold yellow]\n"
            "• [cyan]SPACE_ID or PROJECT_ID[/cyan]: One is required for WatsonX SaaS\n"
            "• [cyan]DEPLOYMENT_NAME[/cyan]: Required for WatsonX LWE only\n\n"
            "[bold green]💡 Tip:[/bold green] Review each provider section and ensure all required\n"
            "fields are filled with actual values (not placeholders like '<Required>').",
            border_style="cyan",
            box=box.ROUNDED
        )
        self._console.print(remediation_panel)
        
        # Summary panel
        self._console.print()
        self._console.print(Panel(
            "[bold yellow]⚠ Action Required[/bold yellow]\n\n"
            f"Found validation errors in {len(provider_errors)} provider section(s).\n"
            "Please review and fix the errors above before proceeding.",
            border_style="yellow",
            box=box.ROUNDED
        ))
        self._console.print()
    
    def _find_provider_ids(self) -> None:
        """Find all AI provider IDs in the configuration."""
        provider_ids = []
        for key in self._toml_dict.keys():
            # Support both legacy (AI_PROVIDER) and new multi-provider format (PROVIDER_N)
            if key.startswith("AI_PROVIDER") or key.startswith("PROVIDER_"):
                provider_ids.append(key)
        self._toml_dict["_provider_ids"] = provider_ids
        self._toml_dict["provider_number"] = len(provider_ids)
    
    def _check_required_fields(self, data: Dict[str, Any], path: Optional[List[str]] = None) -> None:
        """
        Override to skip validation for disabled providers.
        
        Args:
            data: Dictionary to check
            path: Current path in the nested structure
        """
        if path is None:
            path = []
        
        for key, value in data.items():
            current_path = path + [key]
            
            # Skip provider sections that are disabled
            if len(path) == 0 and (key.startswith("PROVIDER_") or key.startswith("AI_PROVIDER")):
                # Check if this provider is enabled
                if isinstance(value, dict):
                    enabled = value.get("ENABLED", True)
                    # Convert string to boolean if needed
                    if isinstance(enabled, str):
                        enabled = enabled.lower() in ('true', '1', 'yes')
                    
                    # Skip validation for disabled providers
                    if not enabled:
                        self._logger.debug(f"Skipping validation for disabled provider: {key}")
                        continue
            
            # Continue with normal validation
            if isinstance(value, dict):
                self._check_required_fields(value, current_path)
            elif isinstance(value, list):
                if '<Required>' in value:
                    self._has_required_fields = True
                    self._validation_errors.append({
                        'loc': tuple(current_path),
                        'msg': 'Required field contains placeholder value',
                        'type': 'value_error.required'
                    })
                    # Populate required_fields for backward compatibility
                    file_name = self._prop_filepath.name
                    if file_name not in self.required_fields:
                        self.required_fields[file_name] = []
                    self.required_fields[file_name].append((current_path, value))
            elif value == '<Required>' or value == '':
                # Skip optional fields that are allowed to be empty
                field_name = current_path[-1] if current_path else ''
                if field_name in self.OPTIONAL_EMPTY_FIELDS:
                    continue
                    
                self._has_required_fields = True
                self._validation_errors.append({
                    'loc': tuple(current_path),
                    'msg': 'Required field is empty or contains placeholder',
                    'type': 'value_error.required'
                })
                # Populate required_fields for backward compatibility
                file_name = self._prop_filepath.name
                if file_name not in self.required_fields:
                    self.required_fields[file_name] = []
                self.required_fields[file_name].append((current_path, value))
    
    def validate(self, model_class: Optional[type[BaseModel]] = None) -> bool:
        """
        Validate the property file using Pydantic model with custom provider-grouped display.
        
        Args:
            model_class: Pydantic model class to use for validation
            
        Returns:
            True if validation passes, False otherwise
        """
        # First check for required fields
        self._check_required_fields(self._toml_dict)
        
        if self._has_required_fields and self._auto_display_errors:
            # Use custom provider-grouped display for AI services
            self.display_provider_validation_errors(
                self._validation_errors,
                str(self._prop_filepath)
            )
            return False
        
        # If a validation model is provided, use it
        if model_class:
            try:
                model_class(**self._toml_dict)
                self._logger.info(f"✓ Validation passed for {self._prop_filepath}")
                return True
            except ValidationError as e:
                self._validation_errors = [dict(err) for err in e.errors()]
                if self._auto_display_errors:
                    # Use custom provider-grouped display for AI services
                    self.display_provider_validation_errors(
                        self._validation_errors,
                        str(self._prop_filepath)
                    )
                return False
        
        return True
    
    def validate_single_default_model(self) -> tuple[bool, str]:
        """
        Validate that exactly one model is marked as default across all enabled providers.
        
        Returns:
            tuple: (is_valid, error_message)
        """
        default_models = []
        enabled_providers = []
        
        # Check all providers
        for provider_key in self._toml_dict.get("_provider_ids", []):
            provider = self._toml_dict.get(provider_key, {})
            
            # Skip disabled providers
            enabled = provider.get("ENABLED", True)
            # Convert string to boolean if needed
            if isinstance(enabled, str):
                enabled = enabled.lower() in ('true', '1', 'yes')
            if not enabled:
                continue
                
            enabled_providers.append(provider_key)
            provider_id = provider.get("PROVIDER_ID", provider_key)
            
            # Check models for this provider
            models = provider.get("models", [])
            for idx, model in enumerate(models):
                is_default = model.get("DEFAULT", False)
                # Convert string to boolean if needed
                if isinstance(is_default, str):
                    is_default = is_default.lower() in ('true', '1', 'yes')
                if is_default:
                    model_id = model.get("MODEL", f"model_{idx}")
                    default_models.append(f"{provider_id}/{model_id}")
        
        # Validation checks
        if not enabled_providers:
            return False, "No enabled providers found. At least one provider must be enabled."
        
        if len(default_models) == 0:
            return False, "No default model specified. Exactly one model across all enabled providers must be marked as DEFAULT=true."
        
        if len(default_models) > 1:
            return False, f"Multiple default models found: {', '.join(default_models)}. Only one model across all enabled providers can be marked as DEFAULT=true."
        
        return True, f"Valid: Default model is {default_models[0]}"
    
    def validate_deployment_type(self, provider_id: str = "AI_PROVIDER") -> bool:
        """Validate AI provider deployment type."""
        if provider_id not in self._toml_dict:
            return False
        deployment_type = self._toml_dict[provider_id].get("DEPLOYMENT_TYPE", "").lower()
        return deployment_type in ["saas", "lightweightengine"]
    
    def validate_space_or_project_id(self, provider_id: str = "AI_PROVIDER") -> bool:
        """Validate that at least one of space_id or project_id is provided for SaaS."""
        if provider_id not in self._toml_dict:
            return False
        if self._toml_dict[provider_id].get("DEPLOYMENT_TYPE", "").lower() == "saas":
            space_id = self._toml_dict[provider_id].get("SPACE_ID", "")
            project_id = self._toml_dict[provider_id].get("PROJECT_ID", "")
            return bool(space_id or project_id)
        return True
    
    def validate_lwe_ssl_certificates(self, ssl_cert_folder: str) -> tuple[bool, List[str]]:
        """
        Validate that SSL certificates exist for enabled LWE providers.
        
        Args:
            ssl_cert_folder: Path to the SSL certificates folder
            
        Returns:
            tuple: (all_valid, list of error messages)
        """
        import os
        from pathlib import Path
        
        errors = []
        provider_ids = self._toml_dict.get("_provider_ids", [])
        
        self._logger.debug(f"Validating LWE SSL certificates for {len(provider_ids)} providers")
        
        for provider_id in provider_ids:
            provider_config = self._toml_dict.get(provider_id, {})
            
            # Check if provider is enabled
            enabled = provider_config.get("ENABLED", True)
            if isinstance(enabled, str):
                enabled = enabled.lower() in ('true', '1', 'yes')
            
            if not enabled:
                self._logger.debug(f"Skipping {provider_id}: disabled")
                continue
            
            # Check if provider is LWE type
            deployment_type = provider_config.get("DEPLOYMENT_TYPE", "").lower()
            provider_type = provider_config.get("PROVIDER_TYPE", "").lower()
            is_lwe = deployment_type == "lightweightengine" or provider_type in ["watsonx_lwe"]
            
            self._logger.debug(f"{provider_id}: deployment_type={deployment_type}, provider_type={provider_type}, is_lwe={is_lwe}")
            
            if not is_lwe:
                self._logger.debug(f"Skipping {provider_id}: not LWE type")
                continue
            
            # Get the PROVIDER_ID value for folder naming
            provider_id_value = provider_config.get("PROVIDER_ID", provider_id)
            expected_folder = f"ai-provider-{provider_id_value.lower()}"
            ssl_folder_path = Path(ssl_cert_folder) / expected_folder
            
            # Get endpoint for error messages (may be placeholder or empty)
            service_endpoint = provider_config.get("SERVICE_ENDPOINT", "")
            provider_url = provider_config.get("PROVIDER_URL", "")
            endpoint = service_endpoint or provider_url or "<Not configured>"
            
            self._logger.debug(f"{provider_id}: checking SSL folder {expected_folder}")
            
            # Check if SSL folder exists
            if not ssl_folder_path.exists():
                errors.append(
                    f"[{provider_id}] SSL certificate folder missing: {expected_folder}\n"
                    f"  Provider Type: {provider_type or deployment_type}\n"
                    f"  Endpoint: {endpoint}\n"
                    f"  Expected folder: {ssl_cert_folder}/{expected_folder}"
                )
                continue
            
            # Check if folder contains certificate files
            cert_files = [f for f in os.listdir(ssl_folder_path)
                         if f.endswith(('.pem', '.crt', '.cer', '.key')) and not f.startswith('.')]
            
            if not cert_files:
                errors.append(
                    f"[{provider_id}] SSL certificate files missing in folder: {expected_folder}\n"
                    f"  Provider Type: {provider_type or deployment_type}\n"
                    f"  Endpoint: {endpoint}\n"
                    f"  Folder exists but contains no certificate files (.pem, .crt, .cer, .key)"
                )
        
        return len(errors) == 0, errors


class AIServicesIntegrationConfig(BaseModel):
    """AI Services Integration configuration validation model."""
    GRAPHQL_ENDPOINT: str = Field(..., min_length=1, description="GraphQL server endpoint URL")
    AUTH_MODE: AuthMode = Field(..., description="Authentication mode (dual, jwt, or debug)")
    OBJECT_STORE: str = Field(..., min_length=1, description="Object Store ID")
    NAVIGATOR_EXTERNAL_URL: str = Field(..., min_length=1, description="Navigator external URL for CORS")
    
    @field_validator('GRAPHQL_ENDPOINT')
    @classmethod
    def validate_graphql_endpoint(cls, v: str) -> str:
        """Validate GraphQL endpoint URL format."""
        if not v.startswith(('http://', 'https://')):
            raise ValueError('GRAPHQL_ENDPOINT must start with http:// or https://')
        return v
    
    @field_validator('NAVIGATOR_EXTERNAL_URL')
    @classmethod
    def validate_navigator_url(cls, v: str) -> str:
        """Validate Navigator external URL format."""
        if not v.startswith(('http://', 'https://')):
            raise ValueError('NAVIGATOR_EXTERNAL_URL must start with http:// or https://')
        return v
    
    @field_validator('AUTH_MODE', mode='before')
    @classmethod
    def validate_auth_mode(cls, v: Any) -> str:
        """Validate and normalize AUTH_MODE value."""
        if isinstance(v, str):
            v_lower = v.lower()
            if v_lower in ['dual', 'jwt', 'debug']:
                return v_lower
        raise ValueError(
            f"AUTH_MODE must be one of: 'dual', 'jwt', 'debug'. Got: {v}"
        )


class ReadPropAIServicesIntegration(ReadProp):
    """AI Services Integration property file reader for GraphQL and integration configuration."""
    
    # Validation model for integration properties
    VALIDATION_MODELS = {
        'root': AIServicesIntegrationConfig
    }
    
    def __init__(self, propertyfile: str, logger: logging.Logger, console: Optional[Console] = None,
                 auto_display_errors: bool = False):
        """Initialize AI Services Integration property reader."""
        super().__init__(propertyfile, logger, console, auto_display_errors)
        
        # Run Pydantic validation automatically
        self._run_pydantic_validation()
    
    def _run_pydantic_validation(self) -> None:
        """Run Pydantic validation on the loaded properties."""
        if 'root' in self.VALIDATION_MODELS:
            model_class = self.VALIDATION_MODELS['root']
            try:
                # Validate the root-level properties
                model_class(**self._toml_dict)
                self._logger.debug(f"✓ Pydantic validation passed for {self._prop_filepath}")
            except ValidationError as e:
                # Add validation errors to the list
                for error in e.errors():
                    self._validation_errors.append(dict(error))
                    self._has_required_fields = True
                # Use debug level since unified display will show the errors
                self._logger.debug(f"✗ Pydantic validation failed for {self._prop_filepath}")
    
    def validate_auth_mode(self) -> bool:
        """Validate authentication mode."""
        # Properties are at root level, no INTEGRATION section
        auth_mode = self._toml_dict.get("AUTH_MODE", "").lower()
        return auth_mode in ["dual", "jwt", "debug"]

# Made with Bob
