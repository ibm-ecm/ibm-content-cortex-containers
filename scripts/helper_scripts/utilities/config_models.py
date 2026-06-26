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
    
    # Cluster Configuration
    GLOBAL_CATALOG: bool = Field(
        default=False,
        description="Install catalog globally (openshift-marketplace) vs namespace-scoped"
    )
    
    # CRD Management Configuration (Optional - for Helm deployments)
    CONTENT_CRD_MANAGEMENT: Optional[str] = Field(
        default="manage",
        description="How to manage Content Operator CRD: manage, skip, or replace"
    )
    
    AI_SERVICES_CRD_MANAGEMENT: Optional[str] = Field(
        default="manage",
        description="How to manage AI Services Operator CRD: manage, skip, or replace"
    )
    
    LICENSE_SERVICE_CRD_MANAGEMENT: Optional[str] = Field(
        default="manage",
        description="How to manage License Service Operator CRD: manage, skip, or replace"
    )
    
    USAGE_METERING_CRD_MANAGEMENT: Optional[str] = Field(
        default="manage",
        description="How to manage Usage Metering Operator CRD: manage, skip, or replace"
    )
    
    # RBAC Management Configuration (Optional - for Helm deployments)
    CONTENT_RBAC_MANAGEMENT: Optional[str] = Field(
        default="create",
        description="How to manage Content Operator RBAC: create, skip, or replace"
    )
    
    AI_SERVICES_RBAC_MANAGEMENT: Optional[str] = Field(
        default="create",
        description="How to manage AI Services Operator RBAC: create, skip, or replace"
    )
    
    LICENSE_SERVICE_RBAC_MANAGEMENT: Optional[str] = Field(
        default="create",
        description="How to manage License Service Operator RBAC: create, skip, or replace"
    )
    
    USAGE_METERING_RBAC_MANAGEMENT: Optional[str] = Field(
        default="create",
        description="How to manage Usage Metering Operator RBAC: create, skip, or replace"
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
    
    @field_validator('CONTENT_CRD_MANAGEMENT', 'AI_SERVICES_CRD_MANAGEMENT',
                     'LICENSE_SERVICE_CRD_MANAGEMENT', 'USAGE_METERING_CRD_MANAGEMENT')
    @classmethod
    def validate_crd_management(cls, v: Optional[str]) -> Optional[str]:
        """Validate CRD management option."""
        if v is None:
            return "manage"  # Default value
        
        valid_values = ['manage', 'skip', 'replace']
        if v.lower() not in valid_values:
            raise PydanticCustomError(
                'invalid_crd_management',
                'CRD management must be one of: manage, skip, replace',
                {'value': v, 'valid_values': valid_values}
            )
        
        return v.lower()
    
    @field_validator('CONTENT_RBAC_MANAGEMENT', 'AI_SERVICES_RBAC_MANAGEMENT',
                     'LICENSE_SERVICE_RBAC_MANAGEMENT', 'USAGE_METERING_RBAC_MANAGEMENT')
    @classmethod
    def validate_rbac_management(cls, v: Optional[str]) -> Optional[str]:
        """Validate RBAC management option."""
        if v is None:
            return "create"  # Default value
        
        valid_values = ['create', 'skip', 'replace']
        if v.lower() not in valid_values:
            raise PydanticCustomError(
                'invalid_rbac_management',
                'RBAC management must be one of: create, skip, replace',
                {'value': v, 'valid_values': valid_values}
            )
        
        return v.lower()
    
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


# Made with Bob
