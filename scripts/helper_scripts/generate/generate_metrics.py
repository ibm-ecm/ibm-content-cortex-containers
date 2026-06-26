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
Module for generating IBM Service Meter Definition YAML files for Content Cortex components.
Handles CPE, GraphQL, and CMIS metrics definitions with license-based template selection.
"""

import os
from logging import Logger
from pathlib import Path
from typing import Optional, Dict, Any, List

from jinja2 import Environment, FileSystemLoader, Template
from ruamel.yaml import YAML


class GenerateMetrics:
    """
    Generate usage metering metrics YAML files for deployed Content Cortex components.
    
    This class handles the generation of IBMServiceMeterDefinition resources for:
    - CPE (Content Platform Engine)
    - GraphQL
    - CMIS (Content Management Interoperability Services)
    
    The metrics are generated from Jinja templates with license-specific data sections.
    """

    # License to product information mapping
    LICENSE_PRODUCT_MAP = {
        "CCx.AR": {
            "prefix": "ar",
            "product_id": "16a1047d9e884768a5a0e768326442ed",
            "product_name": "IBM Content Cortex Authorized Restricted"
        },
        "CCx.PR": {
            "prefix": "pr",
            "product_id": "8db79758cb9642f8be674da9805cf653",
            "product_name": "IBM Content Cortex Eligible Participant Restricted"
        },
        "CCx.ER": {
            "prefix": "er",
            "product_id": "424418b1551a453eb29f1ab633036879",
            "product_name": "IBM Content Cortex Employee Restricted"
        },
        "CCx.Ess.AU": {
            "prefix": "au",
            "product_id": "9ae1b024ae3b4331ab4811097ffe60a9",
            "product_name": "IBM Content Cortex Essentials"
        },
        "CCx.Ess.EP": {
            "prefix": "ep",
            "product_id": "9ae1b024ae3b4331ab4811097ffe60a9",
            "product_name": "IBM Content Cortex Essentials"
        },
        "CCx.EE": {
            "prefix": "ee",
            "product_id": "2f16e146694e4c3eaac64ff1ec9b813e",
            "product_name": "IBM Content Cortex Essentials Employee"
        },
        "CP4BA.NonProd": {
            "prefix": "cp4ba",
            "product_id": "e270b00ce6d7486db1e31fc5fd09fffc",
            "product_name": "IBM Content Cortex Essentials Containers"
        },
        "CP4BA.Prod": {
            "prefix": "cp4ba",
            "product_id": "e270b00ce6d7486db1e31fc5fd09fffc",
            "product_name": "IBM Content Cortex Essentials Containers"
        },
        "CP4BA.User": {
            "prefix": "cp4ba",
            "product_id": "e270b00ce6d7486db1e31fc5fd09fffc",
            "product_name": "IBM Content Cortex Essentials Containers"
        },
    }

    # Component-specific data for metrics
    COMPONENT_DATA = {
        "CMIS": {
            "component_id": "3191c7cdc4c8413dafaaad1f180e4ce8",
            "component_name": "IBM ECM CMIS",
            "metric_description": "count of CMIS instances"
        },
        "CPE": {
            "component_id": "7ab1213e53cf4260a247c75f16c2569d",
            "component_name": "IBM Content Platform Engine",
            "metric_description": "count of CPE instances"
        },
        "GRAPHQL": {
            "component_id": "ee43abe0ed114b9a9b3412705eb77edc",
            "component_name": "IBM Content Cortex GraphQL API",
            "metric_description": "count of GraphQL instances"
        }
    }

    def __init__(
        self,
        deployment_properties: dict,
        namespace: str,
        logger: Optional[Logger] = None
    ):
        """
        Initialize the metrics generator.

        Args:
            deployment_properties: Dictionary containing deployment configuration including LICENSE
            namespace: Kubernetes namespace for the deployment
            logger: Optional logger instance for logging operations
        """
        self._logger = logger
        self._deployment_properties = deployment_properties
        self._namespace = namespace

        # Extract license information
        self._license = deployment_properties.get("LICENSE", "")
        self._license_info = self._get_license_info()

        # Set up paths - always use absolute paths relative to this file's location
        # This ensures consistency whether running from project root or scripts directory
        script_dir = Path(__file__).parent  # .../scripts/helper_scripts/generate/
        self._templates_dir = script_dir / "metrics_templates"
        
        # Generated files go in scripts/generatedFiles/<namespace>/metrics
        # Navigate up from generate/ to scripts/ directory
        scripts_dir = script_dir.parent.parent  # Up 2 levels from generate/ to scripts/
        self._generated_folder = scripts_dir / "generatedFiles" / self._namespace / "metrics"

        # Ensure generated folder exists
        self._generated_folder.mkdir(parents=True, exist_ok=True)

        # Set up Jinja2 environment
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(self._templates_dir)),
            trim_blocks=True,
            lstrip_blocks=True
        )

        # Validate license and log information
        self._validate_license()

    def _get_license_info(self) -> Optional[Dict[str, str]]:
        """
        Get the product information based on the license type.
        
        Returns:
            dict: License information including prefix, product_id, and product_name
                  or None if license is invalid
        """
        return self.LICENSE_PRODUCT_MAP.get(self._license)

    def _validate_license(self) -> None:
        """Validate that the license is properly configured and supported."""
        if not self._license:
            self._log_error("LICENSE not found in deployment properties")
            return
        
        if not self._license_info:
            self._log_warning(
                f"License '{self._license}' not recognized. "
                f"Supported licenses: {', '.join(self.LICENSE_PRODUCT_MAP.keys())}"
            )
        else:
            self._log_info(
                f"Using license: {self._license} "
                f"(prefix: {self._license_info['prefix']}, "
                f"product: {self._license_info['product_name']})"
            )

    def _log_info(self, message: str) -> None:
        """Log an info message if logger is available."""
        if self._logger:
            self._logger.info(message)

    def _log_warning(self, message: str) -> None:
        """Log a warning message if logger is available."""
        if self._logger:
            self._logger.warning(message)

    def _log_error(self, message: str) -> None:
        """Log an error message if logger is available."""
        if self._logger:
            self._logger.error(message)

    def _is_component_deployed(self, component: str) -> bool:
        """
        Check if a component is configured for deployment.

        Args:
            component: Component name (CPE, GRAPHQL, CMIS)

        Returns:
            bool: True if component is enabled for deployment
        """
        return self._deployment_properties.get(component, False)

    def _get_component_template_name(self, component: str) -> str:
        """
        Get the Jinja template filename for a component.
        
        Args:
            component: Component name (CPE, GRAPHQL, CMIS)
            
        Returns:
            str: Template filename (e.g., 'ccx-cpe-metrics.yaml')
        """
        component_lower = component.lower()
        return f"ccx-{component_lower}-metrics.yaml"

    def _get_metrics_data(self, component: str) -> Dict[str, Any]:
        """
        Generate the data section for metrics based on component and license.
        
        Args:
            component: Component name (CPE, GRAPHQL, CMIS)
            
        Returns:
            dict: Data section for the metrics YAML
        """
        if not self._license_info:
            raise ValueError(f"Invalid license: {self._license}")
        
        if component not in self.COMPONENT_DATA:
            raise ValueError(f"Unknown component: {component}")
        
        component_data = self.COMPONENT_DATA[component]
        
        return {
            "componentId": component_data["component_id"],
            "componentName": component_data["component_name"],
            "productId": self._license_info["product_id"],
            "productName": self._license_info["product_name"],
            "metricName": "INSTANCE_COUNT",
            "metricDescription": component_data["metric_description"],
            "metricType": "ADOPTION"
        }

    def _generate_from_template(
        self,
        component: str,
        template_name: str,
        output_filename: str
    ) -> bool:
        """
        Generate a metrics YAML file from a Jinja template.
        
        Args:
            component: Component name (CPE, GRAPHQL, CMIS)
            template_name: Name of the Jinja template file
            output_filename: Name of the output file
            
        Returns:
            bool: True if generation was successful
        """
        try:
            # Load the template
            template = self._jinja_env.get_template(template_name)
            
            # Get the data section for this component and license
            data_section = self._get_metrics_data(component)
            
            # Prepare template variables
            template_vars = {
                "namespace": self._namespace,
                "license_prefix": self._license_info["prefix"],
                "data": data_section
            }
            
            # Render the template
            rendered_content = template.render(**template_vars)
            
            # Write to output file
            output_path = self._generated_folder / output_filename
            with open(output_path, 'w') as f:
                f.write(rendered_content)
            
            return True
            
        except Exception as e:
            self._log_error(f"Error generating metrics from template {template_name}: {str(e)}")
            return False

    def generate_component_metrics(self, component: str) -> bool:
        """
        Generate metrics YAML for a specific component based on the configured license.

        Args:
            component: Component name (CPE, GRAPHQL, CMIS)

        Returns:
            bool: True if generation was successful
        """
        if not self._is_component_deployed(component):
            self._log_info(f"{component} is not deployed, skipping metrics generation")
            return True

        # Validate license
        if not self._license_info:
            self._log_error(f"Cannot generate metrics for {component}: invalid license '{self._license}'")
            return False

        # Get template name
        template_name = self._get_component_template_name(component)
        
        # Check if template exists
        template_path = self._templates_dir / template_name
        if not template_path.exists():
            self._log_error(
                f"Template not found: {template_path}\n"
                f"Expected template for component '{component}'"
            )
            return False

        # Generate output filename with license prefix
        component_lower = component.lower()
        output_filename = f"ccx-{self._license_info['prefix']}-{component_lower}-metrics.yaml"
        
        self._log_info(
            f"Generating {component} metrics from template {template_name} "
            f"for license {self._license}"
        )

        success = self._generate_from_template(component, template_name, output_filename)
        
        if success:
            self._log_info(f"✓ Generated {component} metrics: {output_filename}")
        else:
            self._log_error(f"✗ Failed to generate {component} metrics")

        return success

    def generate_all_metrics(self) -> bool:
        """
        Generate metrics YAML files for all deployed components based on the configured license.

        Returns:
            bool: True if all applicable metrics were generated successfully
        """
        # Validate license before attempting to generate any metrics
        if not self._license_info:
            self._log_error(
                f"Cannot generate metrics: License '{self._license}' is not valid or not supported.\n"
                f"Supported licenses: {', '.join(self.LICENSE_PRODUCT_MAP.keys())}"
            )
            return False

        self._log_info(
            f"Generating usage metering metrics for deployed components "
            f"(License: {self._license}, Product: {self._license_info['product_name']})"
        )

        components_to_check = ["CPE", "GRAPHQL", "CMIS"]
        results = []
        deployed_components = []

        for component in components_to_check:
            if self._is_component_deployed(component):
                deployed_components.append(component)
                result = self.generate_component_metrics(component)
                results.append(result)

        # Return True only if all generated metrics succeeded
        if not results:
            self._log_info("No components requiring metrics generation")
            return True

        all_success = all(results)
        if all_success:
            self._log_info(
                f"✓ All metrics generated successfully for: {', '.join(deployed_components)}"
            )
        else:
            failed_count = len([r for r in results if not r])
            self._log_warning(
                f"⚠ {failed_count} of {len(results)} metrics failed to generate"
            )

        return all_success

    def get_license_info(self) -> Dict[str, Any]:
        """
        Get information about the current license configuration.
        
        Returns:
            dict: Dictionary containing license information including:
                - license: Current license string
                - license_prefix: Metrics file prefix
                - product_id: Product ID for the license
                - product_name: Product name for the license
                - valid: Whether the license is valid
                - supported_licenses: List of supported license types
        """
        info = {
            "license": self._license,
            "valid": bool(self._license_info),
            "supported_licenses": list(self.LICENSE_PRODUCT_MAP.keys())
        }
        
        if self._license_info:
            info.update({
                "license_prefix": self._license_info["prefix"],
                "product_id": self._license_info["product_id"],
                "product_name": self._license_info["product_name"]
            })
        
        else:
            info.update({
                "license_prefix": None,
                "product_id": None,
                "product_name": None
            })
        
        return info

# Made with Bob
