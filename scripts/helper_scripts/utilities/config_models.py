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
Pydantic models for validating FNCM deployment configuration files.

This module provides comprehensive validation for silent mode TOML configuration
files using Pydantic v2, ensuring type safety and data integrity before deployment.
"""

from enum import Enum
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator, HttpUrl
from pydantic_core import PydanticCustomError


# Placeholder values that indicate a field has not been filled in
_NAMESPACE_PLACEHOLDERS = {'<namespace>', '<required>', '<your-namespace>', 'changeme', 'todo'}


def _assert_namespace_not_placeholder(v: str) -> None:
    """Raise PydanticCustomError if the namespace value is still a template placeholder."""
    if v.strip().lower() in _NAMESPACE_PLACEHOLDERS or (v.strip().startswith('<') and v.strip().endswith('>')):
        raise PydanticCustomError(
            'placeholder_namespace',
            f"NAMESPACE '{v.strip()}' is a placeholder — replace it with your actual Kubernetes namespace"
        )


class PlatformType(str, Enum):
    """Supported Kubernetes platforms."""
    OCP = "1"
    CNCF = "2"


class DeployOperatorConfig(BaseModel):
    """
    Pydantic model for validating deploy operator silent configuration.
    
    This model validates the silent_install_deployoperator.toml file structure
    and ensures all required fields meet the deployment requirements.
    """
    
    # License
    LICENSE_ACCEPT: bool = Field(
        description="Must be true to accept IBM license terms",
        examples=[True]
    )

    LICENSE_TYPE: Optional[str] = Field(
        default="Essentials",
        description="License type: 'Essentials' (Usage Metering only) or 'CP4BA' (License Service required)",
        examples=["Essentials", "CP4BA"]
    )
    
    # Platform (Optional - can be detected or specified via CLI)
    PLATFORM: Optional[PlatformType] = Field(
        default=None,
        description="Target Kubernetes platform (1=OCP, 2=CNCF)",
        examples=["1", "2"]
    )
    
    # Namespace
    NAMESPACE: str = Field(
        min_length=1,
        max_length=63,
        description="Kubernetes namespace for deployment",
        examples=["ibm-fncm", "fncm-prod"]
    )
    
    # Registry Authentication
    ENTITLEMENT_KEY: str = Field(
        min_length=1,
        description="IBM Entitlement Registry key",
        examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."]
    )
    
    # Private Registry (Optional)
    PRIVATE_REGISTRY: bool = Field(
        default=False,
        description="Use private registry instead of IBM Entitlement Registry"
    )
    
    PRIVATE_REGISTRY_URL: Optional[str] = Field(
        default=None,
        description="Private registry URL with optional port and path",
        examples=["registry.example.com:5000/fncm", "registry.example.com"]
    )
    
    PRIVATE_REGISTRY_USERNAME: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Private registry username"
    )
    
    PRIVATE_REGISTRY_PASSWORD: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Private registry password"
    )
    
    PRIVATE_REGISTRY_SSL_ENABLED: bool = Field(
        default=True,
        description="Whether private registry uses SSL/TLS"
    )
    
    PRIVATE_REGISTRY_SSL_CRT_PATH: Optional[str] = Field(
        default=None,
        description="Path to private registry SSL certificate (PEM format)"
    )
    
    # Advanced Deployment Options (Optional)
    FORCE_REINSTALL: Optional[bool] = Field(
        default=False,
        description="Force reinstall of operators (uninstall then install)"
    )
    
    PARALLEL_WORKERS: Optional[int] = Field(
        default=3,
        ge=1,
        le=10,
        description="Number of parallel workers for operator deployment (1-10)"
    )
    
    DEPLOYMENT_TIMEOUT: Optional[int] = Field(
        default=600,
        ge=60,
        le=3600,
        description="Deployment timeout in seconds per operator (60-3600)"
    )
    
    # Validators
    
    @field_validator('LICENSE_ACCEPT')
    @classmethod
    def validate_license_accepted(cls, v: bool) -> bool:
        """Ensure license is accepted."""
        if not v:
            raise PydanticCustomError(
                'license_not_accepted',
                'LICENSE_ACCEPT must be true. Review license terms at: '
                'https://ibm.biz/CPE_CCX_License_26_0_0',
                {}
            )
        return v
    
    @field_validator('NAMESPACE')
    @classmethod
    def validate_namespace(cls, v: str) -> str:
        """Validate namespace follows Kubernetes naming conventions."""
        _assert_namespace_not_placeholder(v)

        # Reserved namespaces
        reserved = {
            "services", "default", "calico-system", "ibm-cert-store",
            "ibm-observe", "ibm-system", "ibm-odf-validation-webhook"
        }

        if v.lower() in reserved:
            raise PydanticCustomError(
                'reserved_namespace',
                f'Namespace "{v}" is reserved and cannot be used',
                {'namespace': v, 'reserved': list(reserved)}
            )

        # Check prefixes
        if v.lower().startswith(('openshift', 'kube')):
            raise PydanticCustomError(
                'invalid_namespace_prefix',
                f'Namespace cannot start with "openshift" or "kube": {v}',
                {'namespace': v}
            )

        # Kubernetes naming rules
        if not v.replace('-', '').replace('_', '').isalnum():
            raise PydanticCustomError(
                'invalid_namespace_chars',
                'Namespace must contain only alphanumeric characters, hyphens, and underscores',
                {'namespace': v}
            )

        return v
    
    @field_validator('ENTITLEMENT_KEY')
    @classmethod
    def validate_entitlement_key(cls, v: str) -> str:
        """Validate entitlement key is not a placeholder."""
        placeholders = ['<IBMEntitlementKey>', '<Required>', 'CHANGEME', 'TODO']
        
        if any(placeholder.lower() in v.lower() for placeholder in placeholders):
            raise PydanticCustomError(
                'placeholder_entitlement_key',
                'ENTITLEMENT_KEY contains placeholder text. '
                'Obtain a valid key from: https://myibm.ibm.com/products-services/containerlibrary',
                {'value': v}
            )
        
        if len(v) < 50:  # IBM entitlement keys are typically much longer
            raise PydanticCustomError(
                'invalid_entitlement_key_length',
                'ENTITLEMENT_KEY appears too short. Verify you have the complete key.',
                {'length': len(v)}
            )
        
        return v
    
    @field_validator('PRIVATE_REGISTRY_URL')
    @classmethod
    def validate_registry_url(cls, v: Optional[str]) -> Optional[str]:
        """Validate private registry URL format - only validates placeholders, not emptiness."""
        if v is None:
            return v
        
        # Only check for obvious placeholders, not emptiness
        # Emptiness will be validated in model_validator when PRIVATE_REGISTRY is true
        placeholders = ['<RegistryURL>', '<Required>', 'CHANGEME']
        if any(placeholder in v for placeholder in placeholders):
            # This is a placeholder, return as-is and let model validator handle it
            return v
        
        return v
    
    @field_validator('PRIVATE_REGISTRY_SSL_CRT_PATH')
    @classmethod
    def validate_ssl_cert_path(cls, v: Optional[str]) -> Optional[str]:
        """Validate SSL certificate path - only when it's not a placeholder."""
        # Skip validation for None or placeholder values
        # Model validator will check these when PRIVATE_REGISTRY is true
        if v is None or v == "/path/to/my/certificate.crt":
            return v
        
        # Only validate if it looks like a real path (not a placeholder)
        if '<' in v or '>' in v:
            return v
        
        cert_path = Path(v)
        if not cert_path.exists():
            raise PydanticCustomError(
                'cert_file_not_found',
                f'SSL certificate file not found: {v}',
                {'path': v}
            )
        
        if not cert_path.is_file():
            raise PydanticCustomError(
                'cert_path_not_file',
                f'SSL certificate path is not a file: {v}',
                {'path': v}
            )
        
        # Check if file is readable
        try:
            with open(cert_path, 'r') as f:
                content = f.read(100)  # Read first 100 chars
                if '-----BEGIN CERTIFICATE-----' not in content:
                    raise PydanticCustomError(
                        'invalid_cert_format',
                        f'SSL certificate does not appear to be in PEM format: {v}',
                        {'path': v}
                    )
        except PermissionError:
            raise PydanticCustomError(
                'cert_file_not_readable',
                f'SSL certificate file is not readable: {v}',
                {'path': v}
            )
        
        return v
    
    @model_validator(mode='after')
    def validate_private_registry_config(self) -> 'DeployOperatorConfig':
        """Validate private registry configuration is complete when enabled."""
        if self.PRIVATE_REGISTRY:
            # Check required fields
            if not self.PRIVATE_REGISTRY_URL:
                raise PydanticCustomError(
                    'missing_registry_url',
                    'PRIVATE_REGISTRY_URL is required when PRIVATE_REGISTRY is true',
                    {}
                )
            
            # Check for placeholder in URL
            placeholders = ['<RegistryURL>', '<Required>', 'CHANGEME']
            if any(placeholder in self.PRIVATE_REGISTRY_URL for placeholder in placeholders):
                raise PydanticCustomError(
                    'placeholder_registry_url',
                    'PRIVATE_REGISTRY_URL contains placeholder text. Provide actual registry URL.',
                    {'value': self.PRIVATE_REGISTRY_URL}
                )
            
            if not self.PRIVATE_REGISTRY_USERNAME:
                raise PydanticCustomError(
                    'missing_registry_username',
                    'PRIVATE_REGISTRY_USERNAME is required when PRIVATE_REGISTRY is true',
                    {}
                )
            
            if not self.PRIVATE_REGISTRY_PASSWORD:
                raise PydanticCustomError(
                    'missing_registry_password',
                    'PRIVATE_REGISTRY_PASSWORD is required when PRIVATE_REGISTRY is true',
                    {}
                )
            
            # Check SSL certificate if SSL is enabled
            if self.PRIVATE_REGISTRY_SSL_ENABLED:
                if not self.PRIVATE_REGISTRY_SSL_CRT_PATH:
                    raise PydanticCustomError(
                        'missing_ssl_cert',
                        'PRIVATE_REGISTRY_SSL_CRT_PATH is required when '
                        'PRIVATE_REGISTRY_SSL_ENABLED is true',
                        {}
                    )
                
                # Check for placeholder
                if self.PRIVATE_REGISTRY_SSL_CRT_PATH == "/path/to/my/certificate.crt":
                    raise PydanticCustomError(
                        'placeholder_ssl_cert_path',
                        'PRIVATE_REGISTRY_SSL_CRT_PATH contains placeholder path. '
                        'Provide actual certificate path.',
                        {}
                    )
        
        return self
    
    class Config:
        """Pydantic model configuration."""
        use_enum_values = True
        validate_assignment = True
        extra = 'forbid'  # Reject unknown fields
        str_strip_whitespace = True


def validate_deploy_operator_config(config_dict: dict) -> tuple[bool, Optional[DeployOperatorConfig], list[str]]:
    """
    Validate deploy operator configuration dictionary.
    
    Args:
        config_dict: Dictionary loaded from TOML file
        
    Returns:
        Tuple of (success: bool, validated_config: Optional[DeployOperatorConfig], errors: list[str])
    """
    try:
        validated_config = DeployOperatorConfig(**config_dict)
        return True, validated_config, []
    except Exception as e:
        from pydantic import ValidationError
        
        if isinstance(e, ValidationError):
            errors = []
            for error in e.errors():
                field = ' -> '.join(str(loc) for loc in error['loc'])
                msg = error['msg']
                errors.append(f"❌ {field}: {msg}")
            return False, None, errors
        else:
            return False, None, [f"❌ Validation error: {str(e)}"]


# ============================================================================
# Multi-Operator Configuration Models
# ============================================================================

class DeploymentMode(str, Enum):
    """Deployment mode for operator installation."""
    SINGLE_OPERATOR = "single-operator"
    MULTI_OPERATOR = "multi-operator"


class OperatorConfig(BaseModel):
    """Configuration for an individual operator in multi-operator deployment."""
    
    enabled: bool = Field(
        default=False,
        description="Whether this operator should be deployed"
    )
    
    namespace: str = Field(
        min_length=1,
        max_length=63,
        description="Kubernetes namespace for the operator"
    )
    
    deployment_type: Optional[str] = Field(
        default="olm",
        description="Deployment type (olm or cncf)"
    )
    
    @field_validator('namespace')
    @classmethod
    def validate_namespace(cls, v: str) -> str:
        """Validate Kubernetes namespace format."""
        # Kubernetes namespace naming rules
        if not v.replace('-', '').replace('_', '').isalnum():
            raise ValueError(
                f"Invalid namespace format: {v}. "
                "Must contain only alphanumeric characters, hyphens, and underscores"
            )
        
        # Check for reserved namespaces
        reserved = ['kube-system', 'kube-public', 'kube-node-lease', 'default']
        if v in reserved:
            raise ValueError(
                f"Cannot use reserved namespace: {v}"
            )
        
        return v
    
    @field_validator('deployment_type')
    @classmethod
    def validate_deployment_type(cls, v: Optional[str]) -> Optional[str]:
        """Validate deployment type."""
        if v and v.lower() not in ['olm', 'cncf']:
            raise ValueError(
                f"Invalid deployment type: {v}. Must be 'olm' or 'cncf'"
            )
        return v.lower() if v else 'olm'


class DeploymentOptions(BaseModel):
    """Deployment execution options for multi-operator deployment."""
    
    parallel: bool = Field(
        default=False,
        description="Enable parallel deployment of independent operators"
    )
    
    max_parallel: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum number of operators to deploy in parallel"
    )
    
    validate_dependencies: bool = Field(
        default=True,
        description="Validate operator dependencies before deployment"
    )
    
    backup_before_deploy: bool = Field(
        default=True,
        description="Backup existing configurations before deployment"
    )
    
    @field_validator('max_parallel')
    @classmethod
    def validate_max_parallel(cls, v: int, info) -> int:
        """Validate max_parallel is reasonable."""
        if v < 1:
            raise ValueError("max_parallel must be at least 1")
        if v > 10:
            raise ValueError(
                "max_parallel cannot exceed 10 for stability reasons"
            )
        return v


class SharedConfig(BaseModel):
    """Shared configuration across all operators."""
    
    entitlement_key: str = Field(
        min_length=1,
        description="IBM Entitlement Key for image registry access"
    )
    
    private_registry: Optional[str] = Field(
        default="",
        description="Private container registry URL"
    )
    
    private_registry_user: Optional[str] = Field(
        default="",
        description="Private registry username"
    )
    
    private_registry_password: Optional[str] = Field(
        default="",
        description="Private registry password"
    )
    
    verify_tls: bool = Field(
        default=True,
        description="Verify TLS certificates for registry connections"
    )
    
    @field_validator('entitlement_key')
    @classmethod
    def validate_entitlement_key(cls, v: str) -> str:
        """Validate entitlement key is not a placeholder."""
        placeholders = ['<IBMEntitlementKey>', '<Required>', 'CHANGEME', '']
        if v in placeholders:
            raise ValueError(
                "Entitlement key must be set to a valid IBM Entitlement Key. "
                "Get your key from https://myibm.ibm.com/products-services/containerlibrary"
            )
        if len(v) < 10:
            raise ValueError(
                "Entitlement key appears to be invalid (too short)"
            )
        return v
    
    @model_validator(mode='after')
    def validate_private_registry_credentials(self):
        """Validate that if private registry is set, credentials are provided."""
        if self.private_registry and self.private_registry.strip():
            if not self.private_registry_user or not self.private_registry_password:
                raise ValueError(
                    "Private registry credentials (user and password) are required "
                    "when private_registry is specified"
                )
        return self


class MultiOperatorConfig(BaseModel):
    """
    Multi-operator deployment configuration.
    
    This model validates the extended TOML configuration for deploying
    multiple operators simultaneously with dependency management.
    """
    
    mode: DeploymentMode = Field(
        default=DeploymentMode.SINGLE_OPERATOR,
        description="Deployment mode (single-operator or multi-operator)"
    )
    
    operators: dict[str, OperatorConfig] = Field(
        description="Configuration for each operator"
    )
    
    options: DeploymentOptions = Field(
        default_factory=DeploymentOptions,
        description="Deployment execution options"
    )
    
    shared: SharedConfig = Field(
        description="Shared configuration across all operators"
    )
    
    @field_validator('operators')
    @classmethod
    def validate_operators(cls, v: dict[str, OperatorConfig]) -> dict[str, OperatorConfig]:
        """Validate at least one operator is enabled."""
        enabled = [k for k, cfg in v.items() if cfg.enabled]
        if not enabled:
            raise ValueError(
                "At least one operator must be enabled for deployment"
            )
        
        # Validate operator names are valid
        valid_operators = ['content', 'ai_services', 'license-service', 'usage_metering']
        for op_name in v.keys():
            if op_name not in valid_operators:
                raise ValueError(
                    f"Invalid operator name: {op_name}. "
                    f"Valid operators are: {', '.join(valid_operators)}"
                )
        
        return v
    
    def get_enabled_operators(self) -> list[str]:
        """Get list of enabled operator names."""
        return [k for k, cfg in self.operators.items() if cfg.enabled]
    
    def get_operator_config(self, operator_name: str) -> Optional[OperatorConfig]:
        """Get configuration for a specific operator."""
        return self.operators.get(operator_name)


def validate_multi_operator_config(
    config_dict: dict
) -> tuple[bool, Optional[MultiOperatorConfig], list[str]]:
    """
    Validate multi-operator configuration dictionary.
    
    Args:
        config_dict: Dictionary loaded from TOML file
        
    Returns:
        Tuple of (success: bool, validated_config: Optional[MultiOperatorConfig], errors: list[str])
    """
    try:
        validated_config = MultiOperatorConfig(**config_dict)
        return True, validated_config, []
    except Exception as e:
        from pydantic import ValidationError
        
        if isinstance(e, ValidationError):
            errors = []
            for error in e.errors():
                field = ' -> '.join(str(loc) for loc in error['loc'])
                msg = error['msg']
                errors.append(f"❌ {field}: {msg}")
            return False, None, errors
        else:
            return False, None, [f"❌ Validation error: {str(e)}"]


# ============================================================================
# Prerequisites Silent Configuration Model
# ============================================================================

class AuthenticationType(int, Enum):
    """Authentication type for FNCM deployment."""
    LDAP = 1
    LDAP_IDP = 2
    SCIM_IDP = 3


class DatabaseType(int, Enum):
    """Database type for FNCM deployment."""
    DB2 = 1
    DB2_HADR = 2
    SQLSERVER = 3
    POSTGRESQL = 4
    ORACLE = 5
    DB2_RDS = 6
    DB2_RDS_HADR = 7


class PlatformTypePrereq(str, Enum):
    """Kubernetes platform type for prerequisites (user-facing string values)."""
    OCP = "OCP"
    CNCF = "CNCF"


class LDAPSectionConfig(BaseModel):
    """LDAP section from [LDAP] / [LDAP2] etc."""
    LDAP_TYPE: int = Field(
        ge=1, le=7,
        description="LDAP server type (1=AD, 2=IBM SVD, 3=NetIQ, 4=OID, 5=ODSEE, 6=OUD, 7=CA eTrust)"
    )
    LDAP_SSL_ENABLE: bool = Field(
        description="Enable SSL for LDAP connection"
    )

    class Config:
        extra = 'allow'


class IDPSectionConfig(BaseModel):
    """IDP section from [IDP] / [IDP2] etc."""
    DISCOVERY_ENABLED: bool = Field(
        description="Whether the IDP provides a discovery endpoint URL"
    )
    DISCOVERY_URL: Optional[str] = Field(
        default=None,
        description="Discovery URL ending with /.well-known/openid-configuration"
    )

    @field_validator('DISCOVERY_URL')
    @classmethod
    def validate_discovery_url(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v.strip():
            if not v.strip().endswith('/.well-known/openid-configuration'):
                raise PydanticCustomError(
                    'invalid_discovery_url',
                    "DISCOVERY_URL must end with '/.well-known/openid-configuration'"
                )
        return v

    class Config:
        extra = 'allow'


class PrerequisitesConfig(BaseModel):
    """
    Pydantic model for validating the prerequisites silent configuration.

    This model validates silent_install_prerequisites.toml, ensuring all fields
    are present and correct before the silent gather sequence runs.
    """

    # ── Namespace ──────────────────────────────────────────────────────────────
    NAMESPACE: str = Field(
        min_length=1,
        max_length=63,
        description="Kubernetes namespace for the deployment",
        examples=["ibm-fncm", "fncm-prod"]
    )

    # ── License ────────────────────────────────────────────────────────────────
    LICENSE: str = Field(
        description="Licensing model (e.g. CCx.Ess.EP, CCx.AR, CP4BA.Prod)",
        examples=["CCx.Ess.EP", "CCx.AR", "CP4BA.Prod"]
    )

    # ── Platform & Ingress ─────────────────────────────────────────────────────
    PLATFORM: Optional[PlatformTypePrereq] = Field(
        default=PlatformTypePrereq.OCP,
        description="Kubernetes platform type: OCP or CNCF",
        examples=["OCP", "CNCF"]
    )

    INGRESS: bool = Field(
        default=False,
        description="Enable ingress creation (only applicable for CNCF platform)"
    )

    # ── Auth ───────────────────────────────────────────────────────────────────
    AUTHENTICATION: AuthenticationType = Field(
        description="Authentication type (1=LDAP, 2=LDAP_IDP, 3=SCIM_IDP)"
    )

    # ── Networking / Security ──────────────────────────────────────────────────
    GENERATE_NETWORK_POLICIES: bool = Field(
        default=False,
        description="Generate network policy templates"
    )

    FIPS_SUPPORT: bool = Field(
        default=False,
        description="Enable FIPS mode"
    )

    # ── Optional Components ────────────────────────────────────────────────────
    CPE: bool = Field(default=True, description="Deploy Content Platform Engine")
    GRAPHQL: bool = Field(default=True, description="Deploy GraphQL")
    BAN: bool = Field(default=True, description="Deploy Navigator (BAN)")
    CSS: bool = Field(default=False, description="Deploy Content Search Services")
    CMIS: bool = Field(default=False, description="Deploy CMIS")
    TM: bool = Field(default=False, description="Deploy Task Manager")
    ES: bool = Field(default=False, description="Deploy External Share")
    IER: bool = Field(default=False, description="Deploy IBM Enterprise Records")
    ICCSAP: bool = Field(default=False, description="Deploy Content Collector for SAP")
    CCXMO: bool = Field(default=False, description="Deploy Content Cortex for Microsoft Office")

    # ── Database ───────────────────────────────────────────────────────────────
    DATABASE_TYPE: DatabaseType = Field(
        description="Database type (1=Db2, 2=Db2HADR, 3=SQLServer, 4=PostgreSQL, 5=Oracle, 6=Db2RDS, 7=Db2RDSHADR)"
    )

    DATABASE_SSL_ENABLE: bool = Field(
        default=False,
        description="Enable SSL for database connection"
    )

    DATABASE_OBJECT_STORE_COUNT: int = Field(
        default=1,
        ge=1,
        description="Number of object stores"
    )

    # ── Custom Components ──────────────────────────────────────────────────────
    SENDMAIL_SUPPORT: bool = Field(default=False, description="Java SendMail support")
    ICC_SUPPORT: bool = Field(default=False, description="ICC for Email support")
    TM_CUSTOM_GROUP_SUPPORT: bool = Field(default=False, description="Custom Task Manager users/groups")

    # ── Content Init/Verify ────────────────────────────────────────────────────
    CONTENT_INIT: bool = Field(default=True, description="Initialize Content")
    CONTENT_VERIFY: bool = Field(default=True, description="Verify Content")

    # ── LDAP / IDP sections (optional TOML tables) ─────────────────────────────
    # These are keyed sections (LDAP, LDAP2, IDP, IDP2, ...) and are validated
    # by the model_validator below rather than as fixed fields.

    @field_validator('NAMESPACE')
    @classmethod
    def validate_namespace(cls, v: str) -> str:
        _assert_namespace_not_placeholder(v)
        reserved = {
            'services', 'default', 'calico-system', 'ibm-cert-store',
            'ibm-observe', 'ibm-system', 'ibm-odf-validation-webhook'
        }
        stripped = v.strip()
        if stripped in reserved:
            raise PydanticCustomError(
                'reserved_namespace',
                f"NAMESPACE '{stripped}' is reserved and cannot be used"
            )
        if stripped.startswith(('openshift-', 'kube-')):
            raise PydanticCustomError(
                'reserved_namespace_prefix',
                f"NAMESPACE '{stripped}' uses a reserved prefix (openshift-* or kube-*)"
            )
        return stripped

    @field_validator('LICENSE')
    @classmethod
    def validate_license(cls, v: str) -> str:
        valid = {
            # Current CCx formats
            'CCx.Ess.AU', 'CCx.Ess.EP', 'CCx.EE',
            'CCx.AR', 'CCx.PR', 'CCx.ER',
            # CP4BA
            'CP4BA.NonProd', 'CP4BA.Prod', 'CP4BA.User',
            # Legacy (backward-compatible)
            'ESS.AU', 'ESS.EP', 'ESS.U',
        }
        if v.strip() not in valid:
            raise PydanticCustomError(
                'invalid_license',
                f"LICENSE '{v}' is not valid. Must be one of: {', '.join(sorted(valid))}"
            )
        return v.strip()

    @model_validator(mode='before')
    @classmethod
    def validate_ldap_idp_sections(cls, values: dict) -> dict:
        """Validate any LDAP* and IDP* TOML table sections present in the file."""
        errors = []
        for key, section in values.items():
            if not isinstance(section, dict):
                continue
            if key.startswith('LDAP'):
                try:
                    LDAPSectionConfig(**section)
                except Exception as e:
                    errors.append(f"[{key}]: {e}")
            elif key.startswith('IDP'):
                try:
                    IDPSectionConfig(**section)
                except Exception as e:
                    errors.append(f"[{key}]: {e}")
        if errors:
            raise PydanticCustomError(
                'invalid_section',
                'Invalid LDAP/IDP section(s): ' + '; '.join(errors)
            )
        return values

    @model_validator(mode='after')
    def validate_ingress_requires_cncf(self) -> 'PrerequisitesConfig':
        """Warn (as a validation error) if INGRESS=true but PLATFORM=OCP."""
        if self.INGRESS and self.PLATFORM == PlatformTypePrereq.OCP:
            raise PydanticCustomError(
                'ingress_platform_mismatch',
                "INGRESS = true is only valid when PLATFORM = \"CNCF\". "
                "OCP uses Routes; set INGRESS = false or change PLATFORM to \"CNCF\"."
            )
        return self

    class Config:
        """Pydantic model configuration."""
        use_enum_values = True
        validate_assignment = True
        extra = 'ignore'   # LDAP*/IDP* TOML table keys are handled by model_validator
        str_strip_whitespace = True


def validate_prerequisites_config(config_dict: dict) -> tuple[bool, Optional[PrerequisitesConfig], list[str]]:
    """
    Validate prerequisites silent configuration dictionary.

    Args:
        config_dict: Dictionary loaded from silent_install_prerequisites.toml

    Returns:
        Tuple of (success: bool, validated_config: Optional[PrerequisitesConfig], errors: list[str])
    """
    try:
        validated_config = PrerequisitesConfig(**config_dict)
        return True, validated_config, []
    except Exception as e:
        from pydantic import ValidationError

        if isinstance(e, ValidationError):
            errors = []
            for error in e.errors():
                field = ' -> '.join(str(loc) for loc in error['loc'])
                msg = error['msg']
                errors.append(f"❌ {field}: {msg}")
            return False, None, errors
        else:
            return False, None, [f"❌ Validation error: {str(e)}"]


# ============================================================================
# MustGather Silent Configuration Model
# ============================================================================

class MustGatherConfig(BaseModel):
    """
    Pydantic model for validating silent_install_mustgather.toml.
    Covers NAMESPACE, COLLECT_SENSITIVE_DATA, component toggles, and operator selection.
    """

    NAMESPACE: str = Field(min_length=1, max_length=63, description="Kubernetes namespace")

    COLLECT_SENSITIVE_DATA: bool = Field(
        default=False,
        description="Collect configuration and secrets (sensitive data)"
    )

    # Component toggles — all optional, default false
    CPE: bool = Field(default=False, description="Collect CPE logs/config")
    GRAPHQL: bool = Field(default=False, description="Collect GraphQL logs/config")
    BAN: bool = Field(default=False, description="Collect Navigator logs/config")
    CSS: bool = Field(default=False, description="Collect CSS logs/config")
    CMIS: bool = Field(default=False, description="Collect CMIS logs/config")
    TM: bool = Field(default=False, description="Collect Task Manager logs/config")
    ES: bool = Field(default=False, description="Collect External Share logs/config")
    IER: bool = Field(default=False, description="Collect IER logs/config")
    ICCSAP: bool = Field(default=False, description="Collect ICCSAP logs/config")
    CCXMO: bool = Field(default=False, description="Collect CCXMO logs/config")

    # AI Services component toggles
    COREMCP: bool = Field(default=False, description="Collect Core MCP logs/config")
    REASONING: bool = Field(default=False, description="Collect Reasoning Service logs/config")

    # Operator selection
    COLLECT_CONTENT_OPERATOR: bool = Field(
        default=True,
        description="Collect MustGather data for the Content Operator"
    )
    COLLECT_AI_SERVICES_OPERATOR: bool = Field(
        default=False,
        description="Collect MustGather data for the AI Services Operator"
    )

    @field_validator('NAMESPACE')
    @classmethod
    def validate_namespace(cls, v: str) -> str:
        _assert_namespace_not_placeholder(v)
        reserved = {
            'services', 'default', 'calico-system', 'ibm-cert-store',
            'ibm-observe', 'ibm-system', 'ibm-odf-validation-webhook'
        }
        stripped = v.strip()
        if stripped in reserved:
            raise PydanticCustomError(
                'reserved_namespace',
                f"NAMESPACE '{stripped}' is reserved and cannot be used"
            )
        if stripped.startswith(('openshift-', 'kube-')):
            raise PydanticCustomError(
                'reserved_namespace_prefix',
                f"NAMESPACE '{stripped}' uses a reserved prefix (openshift-* or kube-*)"
            )
        return stripped

    @model_validator(mode='after')
    def validate_operator_selection(self) -> 'MustGatherConfig':
        if not self.COLLECT_CONTENT_OPERATOR and not self.COLLECT_AI_SERVICES_OPERATOR:
            raise PydanticCustomError(
                'no_operator_selected',
                "At least one of COLLECT_CONTENT_OPERATOR or COLLECT_AI_SERVICES_OPERATOR must be true"
            )
        return self

    class Config:
        use_enum_values = True
        validate_assignment = True
        extra = 'ignore'
        str_strip_whitespace = True


def validate_mustgather_config(config_dict: dict) -> tuple[bool, Optional[MustGatherConfig], list[str]]:
    """Validate silent_install_mustgather.toml configuration dictionary."""
    try:
        validated_config = MustGatherConfig(**config_dict)
        return True, validated_config, []
    except Exception as e:
        from pydantic import ValidationError
        if isinstance(e, ValidationError):
            errors = [f"❌ {' -> '.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in e.errors()]
            return False, None, errors
        return False, None, [f"❌ Validation error: {str(e)}"]


# ============================================================================
# LoadImages Silent Configuration Model
# ============================================================================

class LoadImagesConfig(BaseModel):
    """
    Pydantic model for validating silent_install_loadimages.toml.
    Covers registry authentication and image source selection.
    """

    ENTITLEMENT_KEY: str = Field(
        min_length=1,
        description="IBM Entitlement Registry key (required when PRIVATE_REGISTRY = false)"
    )

    PRIVATE_REGISTRY: bool = Field(
        default=False,
        description="Push from a private registry (true) or pull via IBM Entitlement Registry (false)"
    )

    PRIVATE_REGISTRY_URL: Optional[str] = Field(
        default=None,
        description="Private registry hostname[:port][/path]"
    )

    PRIVATE_REGISTRY_USERNAME: Optional[str] = Field(default=None, description="Private registry username")
    PRIVATE_REGISTRY_PASSWORD: Optional[str] = Field(default=None, description="Private registry password")

    PRIVATE_REGISTRY_SSL_ENABLED: bool = Field(
        default=True,
        description="Whether the private registry uses SSL"
    )

    PRIVATE_REGISTRY_SSL_CRT_PATH: Optional[str] = Field(
        default=None,
        description="Path to private registry SSL certificate (PEM format)"
    )

    @field_validator('ENTITLEMENT_KEY')
    @classmethod
    def validate_entitlement_key(cls, v: str) -> str:
        if not v or not v.strip():
            raise PydanticCustomError(
                'empty_entitlement_key',
                "ENTITLEMENT_KEY cannot be empty"
            )
        return v.strip()

    @model_validator(mode='after')
    def validate_registry_config(self) -> 'LoadImagesConfig':
        if self.PRIVATE_REGISTRY:
            missing = []
            if not self.PRIVATE_REGISTRY_URL or not self.PRIVATE_REGISTRY_URL.strip():
                missing.append("PRIVATE_REGISTRY_URL")
            if not self.PRIVATE_REGISTRY_USERNAME or not self.PRIVATE_REGISTRY_USERNAME.strip():
                missing.append("PRIVATE_REGISTRY_USERNAME")
            if not self.PRIVATE_REGISTRY_PASSWORD or not self.PRIVATE_REGISTRY_PASSWORD.strip():
                missing.append("PRIVATE_REGISTRY_PASSWORD")
            if missing:
                raise PydanticCustomError(
                    'missing_registry_fields',
                    f"PRIVATE_REGISTRY = true requires: {', '.join(missing)}"
                )
            if self.PRIVATE_REGISTRY_SSL_ENABLED:
                if not self.PRIVATE_REGISTRY_SSL_CRT_PATH or not self.PRIVATE_REGISTRY_SSL_CRT_PATH.strip():
                    raise PydanticCustomError(
                        'missing_ssl_cert',
                        "PRIVATE_REGISTRY_SSL_CRT_PATH is required when PRIVATE_REGISTRY_SSL_ENABLED = true"
                    )
        else:
            placeholders = ['<IBMEntitlementKey>', '<Required>', 'CHANGEME']
            if any(p in self.ENTITLEMENT_KEY for p in placeholders):
                raise PydanticCustomError(
                    'placeholder_entitlement_key',
                    "ENTITLEMENT_KEY contains a placeholder value. Provide a valid IBM Entitlement key."
                )
        return self

    class Config:
        use_enum_values = True
        validate_assignment = True
        extra = 'ignore'
        str_strip_whitespace = True


def validate_loadimages_config(config_dict: dict) -> tuple[bool, Optional[LoadImagesConfig], list[str]]:
    """Validate silent_install_loadimages.toml configuration dictionary."""
    try:
        validated_config = LoadImagesConfig(**config_dict)
        return True, validated_config, []
    except Exception as e:
        from pydantic import ValidationError
        if isinstance(e, ValidationError):
            errors = [f"❌ {' -> '.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in e.errors()]
            return False, None, errors
        return False, None, [f"❌ Validation error: {str(e)}"]


# ============================================================================
# CleanDeployment Silent Configuration Model
# ============================================================================

class CleanDeploymentConfig(BaseModel):
    """
    Pydantic model for validating silent_install_cleandeployment.toml.
    Currently only requires NAMESPACE.
    """

    NAMESPACE: str = Field(min_length=1, max_length=63, description="Kubernetes namespace to clean")

    @field_validator('NAMESPACE')
    @classmethod
    def validate_namespace(cls, v: str) -> str:
        _assert_namespace_not_placeholder(v)
        reserved = {
            'services', 'default', 'calico-system', 'ibm-cert-store',
            'ibm-observe', 'ibm-system', 'ibm-odf-validation-webhook'
        }
        stripped = v.strip()
        if stripped in reserved:
            raise PydanticCustomError(
                'reserved_namespace',
                f"NAMESPACE '{stripped}' is reserved and cannot be used"
            )
        if stripped.startswith(('openshift-', 'kube-')):
            raise PydanticCustomError(
                'reserved_namespace_prefix',
                f"NAMESPACE '{stripped}' uses a reserved prefix (openshift-* or kube-*)"
            )
        return stripped

    class Config:
        use_enum_values = True
        validate_assignment = True
        extra = 'ignore'
        str_strip_whitespace = True


def validate_cleandeployment_config(config_dict: dict) -> tuple[bool, Optional[CleanDeploymentConfig], list[str]]:
    """Validate silent_install_cleandeployment.toml configuration dictionary."""
    try:
        validated_config = CleanDeploymentConfig(**config_dict)
        return True, validated_config, []
    except Exception as e:
        from pydantic import ValidationError
        if isinstance(e, ValidationError):
            errors = [f"❌ {' -> '.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in e.errors()]
            return False, None, errors
        return False, None, [f"❌ Validation error: {str(e)}"]


# ============================================================================
# UpgradeDeployment Silent Configuration Model
# ============================================================================

class UpgradeDeploymentConfig(BaseModel):
    """
    Pydantic model for validating silent_install_upgradedeployment.toml.
    Covers license model selection, namespace, and CR apply flag.
    """

    LICENSE: str = Field(
        min_length=1,
        description=(
            "License model for the upgraded deployment. "
            "Valid values: CCx.Ess.AU, CCx.Ess.EP, CCx.EE, CCx.AR, CCx.PR, CCx.ER, "
            "CP4BA.NonProd, CP4BA.Prod, CP4BA.User"
        )
    )

    NAMESPACE: str = Field(min_length=1, max_length=63, description="Kubernetes namespace")

    APPLY_CR: bool = Field(
        default=True,
        description="Scale down deployments to zero and apply the updated CR"
    )

    @field_validator('LICENSE')
    @classmethod
    def validate_license(cls, v: str) -> str:
        valid_values = {
            "CCx.Ess.AU", "CCx.Ess.EP", "CCx.EE",
            "CCx.AR", "CCx.PR", "CCx.ER",
            "CP4BA.NonProd", "CP4BA.Prod", "CP4BA.User",
        }
        stripped = v.strip()
        if stripped not in valid_values:
            raise PydanticCustomError(
                'invalid_license',
                f"LICENSE '{stripped}' is not a recognised value. "
                f"Valid values: {', '.join(sorted(valid_values))}"
            )
        return stripped

    @field_validator('NAMESPACE')
    @classmethod
    def validate_namespace(cls, v: str) -> str:
        _assert_namespace_not_placeholder(v)
        reserved = {
            'services', 'default', 'calico-system', 'ibm-cert-store',
            'ibm-observe', 'ibm-system', 'ibm-odf-validation-webhook'
        }
        stripped = v.strip()
        if stripped in reserved:
            raise PydanticCustomError(
                'reserved_namespace',
                f"NAMESPACE '{stripped}' is reserved and cannot be used"
            )
        if stripped.startswith(('openshift-', 'kube-')):
            raise PydanticCustomError(
                'reserved_namespace_prefix',
                f"NAMESPACE '{stripped}' uses a reserved prefix (openshift-* or kube-*)"
            )
        return stripped

    class Config:
        use_enum_values = True
        validate_assignment = True
        extra = 'ignore'
        str_strip_whitespace = True


def validate_upgradedeployment_config(config_dict: dict) -> tuple[bool, Optional[UpgradeDeploymentConfig], list[str]]:
    """Validate silent_install_upgradedeployment.toml configuration dictionary."""
    try:
        validated_config = UpgradeDeploymentConfig(**config_dict)
        return True, validated_config, []
    except Exception as e:
        from pydantic import ValidationError
        if isinstance(e, ValidationError):
            errors = [f"❌ {' -> '.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in e.errors()]
            return False, None, errors
        return False, None, [f"❌ Validation error: {str(e)}"]


# Made with Bob
