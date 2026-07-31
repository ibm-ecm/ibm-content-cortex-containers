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
Operator configuration module for IBM Content Cortex multi-operator deployment.

This module defines the structure and metadata for all Content Cortex operators,
enabling flexible multi-operator deployment scenarios.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional


class OperatorType(str, Enum):
    """Available Content Cortex operators."""
    CONTENT = "content"
    AI_SERVICES = "ai-services"
    LICENSE_ADVISOR = "license-service"
    USAGE_METERING = "usage-metering"
    MODEL_GATEWAY = "model-gateway"
    ENHANCED_EXTRACTION = "enhanced-extraction"
    CNPG = "cnpg"
    REDIS = "redis"


@dataclass
class OperatorMetadata:
    """
    Metadata for a Content Cortex operator.
    
    Attributes:
        operator_type: Type of operator (from OperatorType enum)
        display_name: Human-readable name for UI display
        description: Brief description of operator functionality
        descriptor_path: Relative path to operator descriptors
        crd_file: CRD filename
        operator_file: Operator deployment filename
        rbac_files: List of RBAC-related files
        olm_files: List of OLM-related files (if applicable)
        dependencies: List of operator types this operator depends on
        required: Whether this operator is required for basic deployment
        resource_requirements: Estimated resource requirements
    """
    operator_type: OperatorType
    display_name: str
    description: str
    descriptor_path: str
    crd_file: str
    operator_file: str
    rbac_files: List[str]
    olm_files: List[str]
    dependencies: List[OperatorType]
    required: bool = False
    resource_requirements: Optional[Dict[str, str]] = None


# Operator Definitions
OPERATORS = {
    OperatorType.CONTENT: OperatorMetadata(
        operator_type=OperatorType.CONTENT,
        display_name="Content",
        description="Core Content components - document management, workflow, records",
        descriptor_path="content",
        crd_file="fncmclusters_v1_fncmclusters_crd.yaml",
        operator_file="operator.yaml",
        rbac_files=[
            "rbac/role.yaml",
            "rbac/role_binding.yaml",
            "rbac/service_account.yaml"
        ],
        olm_files=[
            "../op-olm/catalogsource.yaml",
            "../op-olm/operator_group.yaml",
            "../op-olm/subscription.yaml"
        ],
        dependencies=[],
        required=False,  # Content is optional
        resource_requirements={
            "cpu": "500m",
            "memory": "512Mi",
            "storage": "Minimal"
        }
    ),
    
    OperatorType.AI_SERVICES: OperatorMetadata(
        operator_type=OperatorType.AI_SERVICES,
        display_name="AI Services",
        description="AI-powered content analysis, classification, and extraction capabilities",
        descriptor_path="ai-services",
        crd_file="ccxaiservices_v1_ccxaiservices_crd.yaml",
        operator_file="operator.yaml",
        rbac_files=[
            "rbac/role.yaml",
            "rbac/role_binding.yaml",
            "rbac/service_account.yaml"
        ],
        olm_files=[
            "../op-olm/catalogsource.yaml",
            "../op-olm/operator_group.yaml",
            "../op-olm/subscription.yaml"
        ],
        dependencies=[OperatorType.CONTENT],  # Depends on content operator (shares unified OLM descriptors)
        required=False,  # AI Services is optional
        resource_requirements={
            "cpu": "1000m",
            "memory": "2Gi",
            "storage": "10Gi"
        }
    ),
    
    OperatorType.LICENSE_ADVISOR: OperatorMetadata(
        operator_type=OperatorType.LICENSE_ADVISOR,
        display_name="License Service",
        description="License management and compliance tracking for Content Cortex deployments",
        descriptor_path="../license-service",  # Root level, not in content-cortex/
        crd_file="licensing_v1_licensing_crd.yaml",
        operator_file="operator.yaml",
        rbac_files=[
            "rbac/role.yaml",
            "rbac/role_binding.yaml",
            "rbac/service_account.yaml",
            "rbac/cluster_role.yaml",
            "rbac/cluster_role_binding.yaml"
        ],
        olm_files=[
            "op-olm/catalogsource.yaml",
            "op-olm/operator_group.yaml",
            "op-olm/subscription.yaml"
        ],
        dependencies=[],  # Independent operator
        required=True,  # License Service is required
        resource_requirements={
            "cpu": "200m",
            "memory": "256Mi",
            "storage": "Minimal"
        }
    ),
    
    OperatorType.USAGE_METERING: OperatorMetadata(
        operator_type=OperatorType.USAGE_METERING,
        display_name="Usage Metering",
        description="Usage tracking and metering for licensing and capacity planning",
        descriptor_path="../usage-metering",  # Root level, not in content-cortex/
        crd_file="ibmusagemeterings_v1_ibmusagemeterings_crd.yaml",
        operator_file="operator.yaml",
        rbac_files=[
            "rbac/role.yaml",
            "rbac/role_binding.yaml",
            "rbac/service_account.yaml"
        ],
        olm_files=[
            "op-olm/catalogsource.yaml",
            "op-olm/operator_group.yaml",
            "op-olm/subscription.yaml"
        ],
        dependencies=[],  # No dependencies - CRDs applied directly before helm install
        required=True,  # Usage Metering is required
        resource_requirements={
            "cpu": "200m",
            "memory": "256Mi",
            "storage": "5Gi"
        }
    ),

    OperatorType.MODEL_GATEWAY: OperatorMetadata(
        operator_type=OperatorType.MODEL_GATEWAY,
        display_name="Model Gateway",
        description="AI model gateway for routing and managing model inference requests",
        descriptor_path="model-gateway",
        crd_file="modelgateway_v1_modelgateway_crd.yaml",
        operator_file="operator.yaml",
        rbac_files=[
            "rbac/role.yaml",
            "rbac/role_binding.yaml",
            "rbac/service_account.yaml"
        ],
        olm_files=[],
        dependencies=[],  # Dependencies (CNPG, Redis) injected at selection time
        required=False,
        resource_requirements={
            "cpu": "100m",
            "memory": "256Mi",
            "storage": "Minimal"
        }
    ),

    OperatorType.ENHANCED_EXTRACTION: OperatorMetadata(
        operator_type=OperatorType.ENHANCED_EXTRACTION,
        display_name="Enhanced Extraction (WDU)",
        description="Watson Document Understanding services for advanced content extraction",
        descriptor_path="wdu",
        crd_file="ccxwduservices_v1_ccxwduservices_crd.yaml",
        operator_file="operator.yaml",
        rbac_files=[
            "rbac/role.yaml",
            "rbac/role_binding.yaml",
            "rbac/service_account.yaml"
        ],
        olm_files=[],
        dependencies=[],  # Dependencies (CNPG) injected at selection time
        required=False,
        resource_requirements={
            "cpu": "10m",
            "memory": "64Mi",
            "storage": "Minimal"
        }
    ),

    OperatorType.CNPG: OperatorMetadata(
        operator_type=OperatorType.CNPG,
        display_name="Cloud Native PostgreSQL (CNPG)",
        description="IBM Operator for PostgreSQL - required by Model Gateway and WDU",
        descriptor_path="cnpg",
        crd_file="cnpg_v1_cnpg_crd.yaml",
        operator_file="operator.yaml",
        rbac_files=[
            "rbac/role.yaml",
            "rbac/role_binding.yaml",
            "rbac/service_account.yaml"
        ],
        olm_files=[],
        dependencies=[],
        required=False,  # Injected automatically as a dependency
        resource_requirements={
            "cpu": "500m",
            "memory": "200Mi",
            "storage": "Minimal"
        }
    ),

    OperatorType.REDIS: OperatorMetadata(
        operator_type=OperatorType.REDIS,
        display_name="Redis Operator",
        description="IBM Redis operator - required by Model Gateway",
        descriptor_path="redis",
        crd_file="rediscp_v1_rediscp_crd.yaml",
        operator_file="operator.yaml",
        rbac_files=[
            "rbac/role.yaml",
            "rbac/role_binding.yaml",
            "rbac/service_account.yaml"
        ],
        olm_files=[],
        dependencies=[],
        required=False,  # Injected automatically as a dependency
        resource_requirements={
            "cpu": "100m",
            "memory": "256Mi",
            "storage": "Minimal"
        }
    )
}


def get_operator_metadata(operator_type: OperatorType) -> OperatorMetadata:
    """
    Get metadata for a specific operator.
    
    Args:
        operator_type: Type of operator to retrieve
        
    Returns:
        OperatorMetadata for the specified operator
        
    Raises:
        KeyError: If operator type is not found
    """
    return OPERATORS[operator_type]


def get_all_operators() -> List[OperatorMetadata]:
    """
    Get metadata for all available operators.
    
    Returns:
        List of all operator metadata
    """
    return list(OPERATORS.values())


def get_required_operators() -> List[OperatorMetadata]:
    """
    Get metadata for required operators only.
    
    Returns:
        List of required operator metadata
    """
    return [op for op in OPERATORS.values() if op.required]


def get_optional_operators() -> List[OperatorMetadata]:
    """
    Get metadata for optional operators only.
    
    Returns:
        List of optional operator metadata
    """
    return [op for op in OPERATORS.values() if not op.required]


def validate_operator_dependencies(selected_operators: List[OperatorType]) -> tuple[bool, List[str]]:
    """
    Validate that all dependencies for selected operators are met.
    
    Args:
        selected_operators: List of operator types to deploy
        
    Returns:
        Tuple of (valid: bool, missing_dependencies: List[str])
    """
    missing = []
    
    for op_type in selected_operators:
        metadata = get_operator_metadata(op_type)
        for dep in metadata.dependencies:
            if dep not in selected_operators:
                missing.append(
                    f"{metadata.display_name} requires {get_operator_metadata(dep).display_name}"
                )
    
    return len(missing) == 0, missing


def get_descriptor_files(operator_type: OperatorType, deployment_type: str = "cncf") -> List[str]:
    """
    Get list of descriptor files for an operator.
    
    Args:
        operator_type: Type of operator
        deployment_type: Deployment type ("olm" or "cncf")
        
    Returns:
        List of descriptor file paths relative to descriptors/ directory
        
    Note:
        - Content and AI Services operators are under descriptors/content-cortex/
        - License Service and Usage Metering are under descriptors/ (root level)
        - For OLM deployments, Content and AI Services share unified OLM
          descriptors located at descriptors/content-cortex/op-olm/
    """
    metadata = get_operator_metadata(operator_type)
    base_path = metadata.descriptor_path
    
    # Determine if operator is under content-cortex/ or at root level
    # License Service and Usage Metering paths start with "../" indicating root level
    if base_path.startswith("../"):
        # Root level operators (license-service, usage-metering)
        # Remove "../" prefix as we're already relative to descriptors/
        clean_path = base_path.replace("../", "")
        files = [
            f"{clean_path}/{metadata.crd_file}",
            f"{clean_path}/{metadata.operator_file}"
        ]
        # Add RBAC files
        files.extend([f"{clean_path}/{f}" for f in metadata.rbac_files])
        
        # Add OLM files if applicable
        if deployment_type == "olm" and metadata.olm_files:
            files.extend([f"{clean_path}/{f}" for f in metadata.olm_files])
    else:
        # Content-cortex operators (content, ai-services)
        files = [
            f"content-cortex/{base_path}/{metadata.crd_file}",
            f"content-cortex/{base_path}/{metadata.operator_file}"
        ]
        # Add RBAC files
        files.extend([f"content-cortex/{base_path}/{f}" for f in metadata.rbac_files])
        
        # Add OLM files if applicable
        # Note: Content and AI Services share unified OLM descriptors at content-cortex/op-olm/
        if deployment_type == "olm" and metadata.olm_files:
            files.extend([f"content-cortex/{base_path}/{f}" for f in metadata.olm_files])
    
    return files


def calculate_total_resources(selected_operators: List[OperatorType]) -> Dict[str, str]:
    """
    Calculate total resource requirements for selected operators.
    
    Args:
        selected_operators: List of operator types to deploy
        
    Returns:
        Dictionary with total CPU, memory, and storage requirements
    """
    total_cpu_m = 0
    total_memory_mi = 0
    total_storage_gi = 0
    
    for op_type in selected_operators:
        metadata = get_operator_metadata(op_type)
        if metadata.resource_requirements:
            # Parse CPU (millicores)
            cpu = metadata.resource_requirements.get("cpu", "0m")
            if cpu != "Minimal":
                total_cpu_m += int(cpu.replace("m", ""))
            
            # Parse Memory (Mi)
            memory = metadata.resource_requirements.get("memory", "0Mi")
            if memory != "Minimal":
                total_memory_mi += int(memory.replace("Mi", "").replace("Gi", "000"))
            
            # Parse Storage (Gi)
            storage = metadata.resource_requirements.get("storage", "0Gi")
            if storage not in ["Minimal", "0Gi"]:
                total_storage_gi += int(storage.replace("Gi", ""))
    
    return {
        "cpu": f"{total_cpu_m}m ({total_cpu_m/1000:.1f} cores)",
        "memory": f"{total_memory_mi}Mi ({total_memory_mi/1024:.1f}Gi)",
        "storage": f"{total_storage_gi}Gi" if total_storage_gi > 0 else "Minimal"
    }

# Made with Bob
