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

Copies ALL canonical descriptor files from descriptors/usage-metering/ccx-metrics/
for each deployed component, stamping the actual namespace in place of the
REPLACE_NAMESPACE placeholder.

Files are filtered by component only — all license variants are always applied
regardless of the customer's selected license (mirrors CP4BA behaviour, as
advised by the UMS dev team):
  - CPE deployed   → all CPE descriptor files
  - GraphQL deployed → all GraphQL descriptor files
  - CMIS deployed  → all CMIS descriptor files

Output is organised into per-component subfolders:
  generatedFiles/<namespace>/metrics/cpe/
  generatedFiles/<namespace>/metrics/graphql/
  generatedFiles/<namespace>/metrics/cmis/
"""

from logging import Logger
from pathlib import Path
from typing import Optional, List

# Namespace placeholder used in all descriptor files
_NAMESPACE_PLACEHOLDER = "REPLACE_NAMESPACE"

# All descriptor files per component.
# Source of truth: descriptors/usage-metering/ccx-metrics/
# License filtering is intentionally absent — all files are applied for each
# deployed component regardless of the customer's selected license.
COMPONENT_DESCRIPTOR_MAP = {
    "CPE": [
        "ccx-ar-cpe-metrics.yaml",
        "ccx-au-cpe-metrics.yaml",
        "ccx-ee-cpe-metrics.yaml",
        "ccx-ep-cpe-metrics.yaml",
        "ccx-er-cpe-metrics.yaml",
        "ccx-essentials-ar-cpe-metrics.yaml",
        "ccx-essentials-au-cpe-metrics.yaml",
        "ccx-essentials-ee-cpe-metrics.yaml",
        "ccx-essentials-ep-cpe-metrics.yaml",
        "ccx-essentials-er-cpe-metrics.yaml",
        "ccx-essentials-pr-cpe-metrics.yaml",
        "ccx-pr-cpe-metrics.yaml",
        "ccx-premium-au-cpe-metrics.yaml",
        "ccx-premium-ep-cpe-metrics.yaml",
        "ccx-premium-pe-cpe-metrics.yaml",
        "cp4ba-cpe-metrics.yaml",
        # "cp4ba-ccx-premium-au-cpe-addon-metrics.yaml",  # DBACLD-261229: disabled for 26.0.1 GA — re-enable ~Oct 9
        # "cp4ba-ccx-premium-ep-cpe-addon-metrics.yaml",  # DBACLD-261229: disabled for 26.0.1 GA — re-enable ~Oct 9
        # "cp4ba-ccx-premium-pe-cpe-addon-metrics.yaml",  # DBACLD-261229: disabled for 26.0.1 GA — re-enable ~Oct 9
    ],
    "GRAPHQL": [
        "ccx-ar-graphql-metrics.yaml",
        "ccx-au-graphql-metrics.yaml",
        "ccx-ee-graphql-metrics.yaml",
        "ccx-ep-graphql-metrics.yaml",
        "ccx-er-graphql-metrics.yaml",
        "ccx-pr-graphql-metrics.yaml",
        "cp4ba-graphql-metrics.yaml",
    ],
    "CMIS": [
        "ccx-ar-cmis-metrics.yaml",
        "ccx-au-cmis-metrics.yaml",
        "ccx-ee-cmis-metrics.yaml",
        "ccx-ep-cmis-metrics.yaml",
        "ccx-er-cmis-metrics.yaml",
        "ccx-pr-cmis-metrics.yaml",
        "cp4ba-cmis-metrics.yaml",
    ],
}


class GenerateMetrics:
    """
    Generate usage metering metrics YAML files for deployed Content Cortex components.

    Copies ALL IBMServiceMeterDefinition descriptor files from the canonical
    descriptors/usage-metering/ccx-metrics/ directory for each deployed component,
    replacing the REPLACE_NAMESPACE placeholder with the actual deployment namespace.

    No license filtering is applied — all license variants are always included.
    Component filtering is still applied (CPE/GRAPHQL/CMIS must be deployed).

    Output structure:
      metrics/cpe/      — all CPE descriptor files
      metrics/graphql/  — all GraphQL descriptor files
      metrics/cmis/     — all CMIS descriptor files
    """

    def __init__(
        self,
        deployment_properties: dict,
        namespace: str,
        logger: Optional[Logger] = None,
    ):
        """
        Args:
            deployment_properties: Deployment config dict.
            namespace: Kubernetes namespace for the deployment.
            logger: Optional logger instance.
        """
        self._logger = logger
        self._deployment_properties = deployment_properties
        self._namespace = namespace

        # Descriptor source directory (container-samples repo)
        # Path: scripts/helper_scripts/generate/  →  ../../..  →  container-samples root
        script_dir = Path(__file__).parent  # .../scripts/helper_scripts/generate/
        repo_root = script_dir.parent.parent.parent  # container-samples root
        self._descriptors_dir = repo_root / "descriptors" / "usage-metering" / "ccx-metrics"

        # Output root: scripts/generatedFiles/<namespace>/metrics/
        scripts_dir = script_dir.parent.parent  # .../scripts/
        self._generated_folder = scripts_dir / "generatedFiles" / self._namespace / "metrics"
        self._generated_folder.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _log_info(self, message: str) -> None:
        if self._logger:
            self._logger.info(message)

    def _log_warning(self, message: str) -> None:
        if self._logger:
            self._logger.warning(message)

    def _log_error(self, message: str) -> None:
        if self._logger:
            self._logger.error(message)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_component_deployed(self, component: str) -> bool:
        """Return True if the component is enabled in the deployment properties."""
        return bool(self._deployment_properties.get(component, False))

    def _component_output_folder(self, component: str) -> Path:
        """Return (and create) the per-component subfolder under metrics/."""
        folder = self._generated_folder / component.lower()
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _copy_descriptor(self, descriptor_filename: str, component: str) -> bool:
        """
        Copy a single descriptor file into the component output folder,
        replacing REPLACE_NAMESPACE with the actual namespace.

        Returns True on success.
        """
        src = self._descriptors_dir / descriptor_filename
        if not src.exists():
            self._log_error(f"Descriptor not found: {src}")
            return False

        try:
            content = src.read_text(encoding="utf-8")
            content = content.replace(_NAMESPACE_PLACEHOLDER, self._namespace)
            dest = self._component_output_folder(component) / descriptor_filename
            dest.write_text(content, encoding="utf-8")
            self._log_info(f"✓ {component.lower()}/{descriptor_filename}")
            return True
        except Exception as exc:
            self._log_error(f"Error copying {descriptor_filename}: {exc}")
            return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_component_metrics(self, component: str) -> bool:
        """
        Copy all descriptor files for a specific component.

        Args:
            component: One of CPE, GRAPHQL, CMIS.

        Returns:
            True if all copies succeeded.
        """
        if not self._is_component_deployed(component):
            self._log_info(f"{component} is not deployed, skipping metrics generation")
            return True

        files = COMPONENT_DESCRIPTOR_MAP.get(component, [])
        if not files:
            self._log_warning(f"No descriptor files defined for component '{component}'")
            return True

        self._log_info(f"Generating {len(files)} metrics file(s) for {component}")
        results = [self._copy_descriptor(f, component) for f in files]
        return all(results)

    def generate_all_metrics(self) -> bool:
        """
        Copy all descriptor files for all deployed components.

        Returns:
            True if all copies succeeded.
        """
        self._log_info("Generating usage metering metrics for deployed components")

        components = ["CPE", "GRAPHQL", "CMIS"]
        results = []
        deployed = []

        for component in components:
            if self._is_component_deployed(component):
                deployed.append(component)
                results.append(self.generate_component_metrics(component))

        if not results:
            self._log_info("No components requiring metrics generation")
            return True

        if all(results):
            self._log_info(f"✓ All metrics generated for: {', '.join(deployed)}")
        else:
            failed = sum(1 for r in results if not r)
            self._log_warning(f"⚠ {failed} of {len(results)} component(s) had errors")

        return all(results)

    def get_license_info(self) -> dict:
        """Return a summary of the current configuration (license field kept for compatibility)."""
        raw_license = self._deployment_properties.get("LICENSE", "")
        return {
            "license": raw_license,
            "licenses": [t.strip() for t in raw_license.split(",") if t.strip()],
            "valid": True,  # no license validation in all-in-one mode
        }
