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
Helm deployer module for Content Cortex operators.
Manages Helm-based operator deployments with support for packaged charts and public repos.
"""

import json
import logging
import os
import subprocess
import tempfile
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from ..utilities.kubernetes_utilites import KubernetesUtilities
from ..utilities.deployment_progress import DeploymentPhase, DeploymentStep
from ..utilities.utilities import read_version_toml


class HelmChartSource(str, Enum):
    """Source types for Helm charts."""
    LOCAL = "local"           # Local directory charts
    PACKAGED = "packaged"     # Pre-packaged .tgz files
    PUBLIC_REPO = "public"    # Public Helm repository (default: GitHub)
    URL = "url"               # Direct URL to chart package
    GITHUB = "github"         # GitHub releases (public or internal)


def build_operator_charts_from_version(version_data: Optional[Dict] = None, logger: Optional[logging.Logger] = None) -> Dict:
    """
    Build OPERATOR_CHARTS dictionary dynamically from version.toml data.
    
    Args:
        version_data: Dictionary containing version data from version.toml.
                     If None, will attempt to read from default location.
        logger: Logger instance for logging messages
        
    Returns:
        Dict: OPERATOR_CHARTS dictionary with chart information populated from version.toml
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    # If no version data provided, try to read from default location
    if version_data is None:
        version_path = Path.cwd().parent / "version.toml"
        if not version_path.exists():
            version_path = Path.cwd().parent.parent / "version.toml"
        
        if version_path.exists():
            version_data = read_version_toml(str(version_path), logger)
        
        # If still None, use empty dict
        if version_data is None:
            logger.warning("version.toml not found, using default hardcoded versions")
            version_data = {}
    
    # Extract versions and chart names from version.toml with safe access
    content_version = version_data.get("content", {}).get("VERSION", "26.0.0") if version_data else "26.0.0"
    content_chart_name = version_data.get("content", {}).get("HELM_CHART_NAME", "ibm-content-operator") if version_data else "ibm-content-operator"
    
    ai_services_version = version_data.get("ai-services", {}).get("VERSION", "26.0.0") if version_data else "26.0.0"
    ai_services_chart_name = version_data.get("ai-services", {}).get("HELM_CHART_NAME", "ibm-ccx-ai-services-operator") if version_data else "ibm-ccx-ai-services-operator"
    
    license_service_version = version_data.get("license-service", {}).get("VERSION", "4.2.23") if version_data else "4.2.23"
    license_service_chart_name = version_data.get("license-service", {}).get("HELM_CHART_NAME", "ibm-licensing-cluster-scoped") if version_data else "ibm-licensing-cluster-scoped"
    
    usage_metering_version = version_data.get("usage-metering", {}).get("VERSION", "1.0.6") if version_data else "1.0.6"
    usage_metering_chart_name = version_data.get("usage-metering", {}).get("HELM_CHART_NAME", "ibm-usage-metering") if version_data else "ibm-usage-metering"
    
    # GitHub URLs for chart downloads
    # Production: https://ibm-ecm.github.io/ibm-content-cortex-containers/charts
    # Internal Dev GitHub: raw.github.ibm.com/ecm-container-service/container-samples/gh-pages
    public_github_base = "https://ibm-ecm.github.io/ibm-content-cortex-containers/charts"
    dev_github_base = "https://raw.github.ibm.com/ecm-container-service/container-samples/gh-pages"
    
    # Build the operator charts dictionary with versions and chart names from TOML
    operator_charts = {
        "content": {
            "chart_name": content_chart_name,
            "packaged_file": f"{content_chart_name}-{content_version}.tgz",
            "local_path": "content-operator",
            "display_name": "IBM Content Operator",
            "requires_package": True,
            "mandatory": False,
            "crd_name": "fncmclusters.fncm.ibm.com",
            "github_url": f"{public_github_base}/{content_chart_name}-{content_version}.tgz",
            "github_dev_url": f"{dev_github_base}/{content_chart_name}-{content_version}.tgz"
        },
        "ai-services": {
            "chart_name": ai_services_chart_name,
            "packaged_file": f"{ai_services_chart_name}-{ai_services_version}.tgz",
            "local_path": "ai-services-operator",
            "display_name": "IBM AI Services Operator",
            "requires_package": True,
            "mandatory": False,
            "crd_name": "ccxaiservices.ccxaiservices.operator.ibm.com",
            "github_url": f"{public_github_base}/{ai_services_chart_name}-{ai_services_version}.tgz",
            "github_dev_url": f"{dev_github_base}/{ai_services_chart_name}-{ai_services_version}.tgz"
        },
        "license-service": {
            "chart_name": license_service_chart_name,
            "display_name": "IBM License Service Operator",
            "public_repo": "ibm-helm",
            "public_chart": license_service_chart_name,
            "packaged_file": f"{license_service_chart_name}-{license_service_version}.tgz",
            "requires_package": False,
            "mandatory": True,
            "crd_names": [
                "ibmlicensingdefinitions.operator.ibm.com",
                "ibmlicensingmetadatas.operator.ibm.com",
                "ibmlicensingquerysources.operator.ibm.com",
                "ibmlicensings.operator.ibm.com"
            ],
            "cluster_role_names": [
                "ibm-license-service",
                "ibm-license-service-restricted",
                "ibm-licensing-default-reader",
                "ibm-licensing-operator",
                "ibm-licensing-opreqs-role"
            ],
            "cluster_role_binding_names": [
                "ibm-license-service",
                "ibm-license-service-restricted",
                "ibm-licensing-default-reader",
                "ibm-licensing-operator",
                "ibm-license-service-cluster-monitoring-view",
                "ibm-licensing-opreqs-role-binding"
            ],
            "github_url": f"{public_github_base}/{license_service_chart_name}-{license_service_version}.tgz",
            "github_dev_url": f"{dev_github_base}/{license_service_chart_name}-{license_service_version}.tgz"
        },
        "usage-metering": {
            "chart_name": usage_metering_chart_name,
            "display_name": "IBM Usage Metering Operator",
            "public_repo": "ibm-helm",
            "public_chart": usage_metering_chart_name,
            "packaged_file": f"{usage_metering_chart_name}-{usage_metering_version}.tgz",
            "requires_package": False,
            "mandatory": True,
            "crd_names": [
                "ibmusagemeterings.operator.ibm.com",
                "ibmservicemeterdefinitions.operator.ibm.com"
            ],
            "github_url": f"{public_github_base}/{usage_metering_chart_name}-{usage_metering_version}.tgz",
            "github_dev_url": f"{dev_github_base}/{usage_metering_chart_name}-{usage_metering_version}.tgz"
        }
    }
    
    logger.info(f"Built OPERATOR_CHARTS from version.toml:")
    logger.info(f"  content: {content_chart_name} v{content_version}")
    logger.info(f"  ai-services: {ai_services_chart_name} v{ai_services_version}")
    logger.info(f"  license-service: {license_service_chart_name} v{license_service_version}")
    logger.info(f"  usage-metering: {usage_metering_chart_name} v{usage_metering_version}")
    
    return operator_charts


class HelmDeployer:
    """
    Manages Helm-based operator deployments for Content Cortex.
    
    Supports multiple chart sources:
    - Local unpacked charts
    - Packaged .tgz charts
    - Public Helm repositories
    - Direct URLs to chart packages
    
    Note: OPERATOR_CHARTS is now built dynamically from version.toml in __init__
          License Service and Usage Metering are ALWAYS installed (mandatory)
          Content and AI Services are selectable (optional)
    """
    
    def __init__(self,
                 chart_base_path: Optional[str] = None,
                 logger: Optional[logging.Logger] = None,
                 console: Optional[Console] = None,
                 version_data: Optional[Dict] = None,
                 dev_mode: bool = False,
                 github_token: Optional[str] = None):
        """
        Initialize Helm deployer.
        
        Args:
            chart_base_path: Base path for local Helm charts (defaults to project_root/helm-charts)
            logger: Logger instance
            console: Rich console instance
            version_data: Version data from version.toml (if None, will be loaded automatically)
            dev_mode: Enable dev mode to use internal GitHub repository
            github_token: GitHub token for authentication (required for internal dev repo)
        """
        # Default to helm-charts directory at project root (parent of scripts/)
        if chart_base_path is None:
            # Get the project root: scripts/helper_scripts/helm/helm_deployer.py
            # .parent = scripts/helper_scripts/helm/
            # .parent.parent = scripts/helper_scripts/
            # .parent.parent.parent = scripts/
            # .parent.parent.parent.parent = container-samples/ (project root)
            script_dir = Path(__file__).resolve().parent.parent.parent.parent
            self.chart_base_path = script_dir / "helm-charts"
        else:
            self.chart_base_path = Path(chart_base_path)
        self.logger = logger or logging.getLogger(__name__)
        self.console = console or Console()
        self.kube = KubernetesUtilities(self.logger)
        self.dev_mode = dev_mode
        self.github_token = github_token or os.environ.get('GITHUB_TOKEN')
        
        # Build OPERATOR_CHARTS dynamically from version.toml
        self.OPERATOR_CHARTS = build_operator_charts_from_version(version_data, self.logger)
        
        # Log mode
        if self.dev_mode:
            self.logger.info("Dev mode enabled - using internal GitHub repository")
            if not self.github_token:
                self.logger.warning("No GitHub token provided - authentication may fail for internal repository")
        else:
            self.logger.info("Using public GitHub repository for Helm charts")
        
    def validate_prerequisites(self, namespace: str, operators: Optional[List[str]] = None,
                              chart_source: HelmChartSource = HelmChartSource.PACKAGED) -> Tuple[bool, List[str]]:
        """
        Validate all prerequisites for Helm deployment.
        
        Args:
            namespace: Target namespace
            operators: List of operators to deploy (for package validation)
            chart_source: Chart source type
            
        Returns:
            Tuple of (all_passed: bool, issues: List[str])
            Issues are prefixed with [CRITICAL] or [WARNING] to indicate severity
        """
        issues = []
        
        # Check Helm installation - CRITICAL
        if not self._check_helm():
            issues.append("[CRITICAL] Helm is not installed or not in PATH")
        else:
            # Check Helm version - CRITICAL
            version = self._get_helm_version()
            if version:
                self.logger.info(f"Helm version: {version}")
                if not self._is_helm_version_compatible(version):
                    issues.append(f"[CRITICAL] Helm version {version} is not compatible. Required: 4.x or above")
        
        # Check packaged charts ONLY if explicitly using packaged source
        # Skip this check for github/public/url sources as they download charts automatically
        if chart_source == HelmChartSource.PACKAGED and operators:
            missing_packages = self._check_packaged_charts(operators)
            if missing_packages:
                for pkg in missing_packages:
                    issues.append(f"[WARNING] Missing packaged chart: helm-charts/{pkg}")
                issues.append("[INFO] Tip: Use --helm-chart-source github to download charts automatically")
        
        # Check namespace exists - WARNING (script can create it)
        if not self._check_namespace(namespace):
            issues.append(f"[WARNING] Namespace '{namespace}' does not exist")
        
        # Check image pull secret - WARNING (script can create it)
        if not self._check_secret(namespace, "ibm-entitlement-key"):
            issues.append(f"[WARNING] Image pull secret 'ibm-entitlement-key' not found in namespace '{namespace}'")
        
        # Only fail if there are CRITICAL issues
        has_critical = any("[CRITICAL]" in issue for issue in issues)
        return not has_critical, issues
    
    def display_prerequisites_status(self, namespace: str) -> bool:
        """
        Display prerequisites validation status with rich formatting.
        
        Args:
            namespace: Target namespace
            
        Returns:
            True if all prerequisites passed
        """
        all_passed, issues = self.validate_prerequisites(namespace)
        
        table = Table(title="Helm Deployment Prerequisites", show_header=True)
        table.add_column("Check", style="cyan")
        table.add_column("Status", style="bold")
        table.add_column("Details")
        
        # Helm check
        helm_ok = self._check_helm()
        helm_version = self._get_helm_version() if helm_ok else "N/A"
        table.add_row(
            "Helm CLI",
            "[green]✓ Installed[/green]" if helm_ok else "[red]✗ Missing[/red]",
            helm_version if helm_ok else "Install Helm 4.x+"
        )
        
        # Kubernetes API check
        k8s_ok = self._check_kubernetes_connection()
        table.add_row(
            "Kubernetes API",
            "[green]✓ Connected[/green]" if k8s_ok else "[red]✗ Not Connected[/red]",
            "API accessible" if k8s_ok else "Check kubeconfig"
        )
        
        # Namespace check
        ns_ok = self._check_namespace(namespace)
        table.add_row(
            f"Namespace '{namespace}'",
            "[green]✓ Exists[/green]" if ns_ok else "[yellow]⚠ Missing[/yellow]",
            "Ready" if ns_ok else "Will be created"
        )
        
        # Secret check
        secret_ok = self._check_secret(namespace, "ibm-entitlement-key")
        table.add_row(
            "Image Pull Secret",
            "[green]✓ Found[/green]" if secret_ok else "[red]✗ Missing[/red]",
            "ibm-entitlement-key" if secret_ok else "Create secret first"
        )
        
        self.console.print(table)
        
        if not all_passed:
            self.console.print("\n[yellow]⚠ Prerequisites Issues:[/yellow]")
            for issue in issues:
                self.console.print(f"  • {issue}")
        
        return all_passed
    
    def check_existing_crds(self, operators: List[str]) -> Dict[str, Dict]:
        """
        Check if CRDs for the specified operators already exist in the cluster.
        
        Args:
            operators: List of operator types to check
            
        Returns:
            Dictionary mapping operator type to CRD info (or None if not found)
        """
        crd_status = {}
        
        for operator_type in operators:
            if operator_type not in self.OPERATOR_CHARTS:
                continue
            
            op_config = self.OPERATOR_CHARTS[operator_type]
            
            # Support both single crd_name and multiple crd_names
            crd_names = []
            if "crd_names" in op_config:
                crd_names = op_config["crd_names"]
            elif "crd_name" in op_config:
                crd_names = [op_config["crd_name"]]
            
            if not crd_names:
                # No CRDs for this operator
                crd_status[operator_type] = None
                continue
            
            # Check if any CRDs exist (store list of found CRDs)
            found_crds = []
            for crd_name in crd_names:
                if self.kube.check_crd_exists(crd_name):
                    crd_info = self.kube.get_crd_info(crd_name)
                    found_crds.append(crd_info)
                    self.logger.info(f"Found existing CRD: {crd_name}")
                else:
                    self.logger.info(f"CRD not found: {crd_name}")
            
            # Store list of found CRDs or None if none found
            crd_status[operator_type] = found_crds if found_crds else None
        
        return crd_status
    
    def pre_download_all_charts(self, operators: List[str], chart_source: HelmChartSource) -> Tuple[bool, List[str]]:
        """
        Pre-download all required Helm charts before starting deployment.
        
        This ensures all charts are available even if one deployment fails,
        preventing cascading failures where subsequent charts are never downloaded.
        
        Args:
            operators: List of operator types to download charts for
            chart_source: The Helm chart source type being used
            
        Returns:
            Tuple of (all_downloaded: bool, failed_downloads: List[str])
        """
        if chart_source not in [HelmChartSource.GITHUB, HelmChartSource.PUBLIC_REPO, HelmChartSource.URL]:
            # Only download for sources that support it
            self.logger.info(f"Chart source {chart_source} doesn't require pre-download")
            return True, []
        
        self.console.print("\n[cyan]📥 Pre-downloading Helm Charts...[/cyan]")
        
        downloaded = []
        failed = []
        
        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=self.console
        ) as progress:
            task = progress.add_task("[cyan]Downloading charts...", total=len(operators))
            
            for operator_type in operators:
                if operator_type not in self.OPERATOR_CHARTS:
                    self.logger.warning(f"Unknown operator type: {operator_type}")
                    progress.advance(task)
                    continue
                
                op_config = self.OPERATOR_CHARTS[operator_type]
                progress.update(task, description=f"[cyan]Downloading {op_config['display_name']}...")
                
                try:
                    # Download chart
                    chart_path = None
                    if chart_source == HelmChartSource.GITHUB:
                        chart_path = self._download_chart_from_github(operator_type, op_config)
                    elif chart_source == HelmChartSource.PUBLIC_REPO:
                        # For public repo, we'll use helm pull
                        chart_path = self._download_from_public_repo(operator_type, op_config)
                    
                    if chart_path:
                        downloaded.append(operator_type)
                        self.logger.info(f"Successfully pre-downloaded chart for {operator_type}")
                    else:
                        failed.append(operator_type)
                        self.logger.error(f"Failed to pre-download chart for {operator_type}")
                
                except Exception as e:
                    failed.append(operator_type)
                    self.logger.error(f"Exception pre-downloading chart for {operator_type}: {e}")
                
                progress.advance(task)
        
        # Display results
        if downloaded:
            self.console.print(f"[green]✓[/green] Successfully downloaded {len(downloaded)} chart(s)")
        
        if failed:
            self.console.print(f"[red]✗[/red] Failed to download {len(failed)} chart(s):")
            for op in failed:
                op_config = self.OPERATOR_CHARTS.get(op, {})
                self.console.print(f"  • {op_config.get('display_name', op)}")
        
        return len(failed) == 0, failed
    
    def _download_from_public_repo(self, operator_type: str, op_config: Dict) -> Optional[str]:
        """
        Download chart from public Helm repository using helm pull.
        
        Args:
            operator_type: Type of operator
            op_config: Operator configuration dictionary
            
        Returns:
            Path to downloaded chart file or None if download failed
        """
        import subprocess
        
        repo_name = op_config.get("public_repo", "ibm-helm")
        chart_name = op_config.get("public_chart", op_config["chart_name"])
        
        # Create download directory inside scripts folder
        scripts_dir = Path(__file__).resolve().parent.parent.parent
        download_dir = scripts_dir / ".downloads"
        download_dir.mkdir(exist_ok=True)
        
        filename = op_config.get("packaged_file", f"{chart_name}.tgz")
        local_path = download_dir / filename
        
        try:
            # Remove existing file
            if local_path.exists():
                local_path.unlink()
            
            # Use helm pull to download
            cmd = [
                'helm', 'pull',
                f'{repo_name}/{chart_name}',
                '--destination', str(download_dir)
            ]
            
            self.logger.info(f"Executing: {' '.join(cmd)}")
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            
            if local_path.exists():
                self.logger.info(f"Chart downloaded successfully: {local_path}")
                return str(local_path)
            else:
                self.logger.error(f"Chart file not found after download: {local_path}")
                return None
                
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Helm pull failed: {e.stderr}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error downloading from public repo: {e}")
            return None
    
    def check_helm_charts_exist(self, operators: List[str], chart_source: HelmChartSource) -> Tuple[bool, List[str]]:
        """
        Check if required Helm charts exist for packaged or local chart sources.
        
        This validation is only performed for PACKAGED and LOCAL chart sources,
        as other sources (GITHUB, PUBLIC_REPO, URL) download charts automatically.
        
        Args:
            operators: List of operator types to check
            chart_source: The Helm chart source type being used
            
        Returns:
            Tuple of (all_exist: bool, missing_charts: List[str])
            missing_charts contains user-friendly error messages for each missing chart
        """
        # Only validate for packaged and local sources
        if chart_source not in [HelmChartSource.PACKAGED, HelmChartSource.LOCAL]:
            self.logger.info(f"Skipping chart existence check for source type: {chart_source.value}")
            return True, []
        
        missing_charts = []
        
        for operator_type in operators:
            if operator_type not in self.OPERATOR_CHARTS:
                self.logger.warning(f"Unknown operator type: {operator_type}")
                continue
            
            op_config = self.OPERATOR_CHARTS[operator_type]
            
            if chart_source == HelmChartSource.PACKAGED:
                # Check for packaged .tgz file
                packaged_file = op_config.get("packaged_file")
                if not packaged_file:
                    self.logger.warning(f"No packaged file defined for operator: {operator_type}")
                    continue
                
                chart_path = self.chart_base_path / packaged_file
                if not chart_path.exists():
                    missing_charts.append(
                        f"[red]✗[/red] {op_config.get('display_name', operator_type)}: "
                        f"Missing packaged chart '{packaged_file}' in {self.chart_base_path}"
                    )
                    self.logger.error(f"Missing packaged chart: {chart_path}")
                else:
                    self.logger.info(f"✓ Found packaged chart: {chart_path}")
            
            elif chart_source == HelmChartSource.LOCAL:
                # Check for local unpacked chart directory
                local_path = op_config.get("local_path")
                if not local_path:
                    self.logger.warning(f"No local path defined for operator: {operator_type}")
                    continue
                
                chart_dir = self.chart_base_path / local_path
                chart_yaml = chart_dir / "Chart.yaml"
                
                if not chart_dir.exists():
                    missing_charts.append(
                        f"[red]✗[/red] {op_config.get('display_name', operator_type)}: "
                        f"Missing local chart directory '{local_path}' in {self.chart_base_path}"
                    )
                    self.logger.error(f"Missing local chart directory: {chart_dir}")
                elif not chart_yaml.exists():
                    missing_charts.append(
                        f"[red]✗[/red] {op_config.get('display_name', operator_type)}: "
                        f"Local chart directory exists but missing Chart.yaml in {chart_dir}"
                    )
                    self.logger.error(f"Missing Chart.yaml in: {chart_dir}")
                else:
                    self.logger.info(f"✓ Found local chart: {chart_dir}")
        
        return len(missing_charts) == 0, missing_charts
    
    def display_missing_charts(self, missing_charts: List[str], chart_source: HelmChartSource) -> None:
        """
        Display missing Helm charts in a formatted panel with remediation guidance.
        
        Args:
            missing_charts: List of missing chart error messages
            chart_source: The chart source type being used
        """
        if not missing_charts:
            return
        
        # Build error message with prominent header
        error_lines = ["[bold red]❌ ERROR: Missing Required Helm Charts[/bold red]\n"]
        error_lines.append("[red]Deployment cannot proceed without the following Helm charts:[/red]\n")
        
        for chart_msg in missing_charts:
            error_lines.append(f"  {chart_msg}")
        
        error_lines.append("\n[bold yellow]⚠️  Required Action:[/bold yellow]")
        
        if chart_source == HelmChartSource.PACKAGED:
            error_lines.append(
                "  [yellow]1.[/yellow] Ensure packaged chart files (.tgz) are in the [cyan]helm-charts/[/cyan] directory"
            )
            error_lines.append(
                "  [yellow]2.[/yellow] Download charts from the appropriate source (GitHub releases, etc.)"
            )
            error_lines.append(
                "  [yellow]3.[/yellow] Or use [cyan]--helm-chart-source github[/cyan] to download automatically"
            )
        elif chart_source == HelmChartSource.LOCAL:
            error_lines.append(
                "  [yellow]1.[/yellow] Ensure unpacked chart directories exist in [cyan]helm-charts/[/cyan]"
            )
            error_lines.append(
                "  [yellow]2.[/yellow] Each chart directory must contain a valid [cyan]Chart.yaml[/cyan] file"
            )
            error_lines.append(
                "  [yellow]3.[/yellow] Or use [cyan]--helm-chart-source packaged[/cyan] for .tgz files"
            )
            error_lines.append(
                "  [yellow]4.[/yellow] Or use [cyan]--helm-chart-source github[/cyan] to download automatically"
            )
        
        self.console.print()
        self.console.print(Panel(
            "\n".join(error_lines),
            title="[bold red]❌ HELM CHART VALIDATION FAILED[/bold red]",
            border_style="red",
            padding=(1, 2),
            expand=False
        ))
        self.console.print()
    
    def display_crd_status(self, crd_status: Dict[str, Dict]) -> None:
        """
        Display CRD status in a formatted table.
        
        Args:
            crd_status: Dictionary of CRD status from check_existing_crds()
        """
        if not any(crd_status.values()):
            # No existing CRDs found
            return
        
        table = Table(title="Existing CRDs Detected", show_header=True, border_style="yellow")
        table.add_column("Operator", style="cyan")
        table.add_column("CRD Name", style="white")
        table.add_column("Version", style="green")
        table.add_column("Managed By", style="magenta")
        table.add_column("Created", style="blue")
        
        for operator_type, crd_data in crd_status.items():
            if crd_data:
                op_config = self.OPERATOR_CHARTS.get(operator_type, {})
                # Handle both single CRD (dict) and multiple CRDs (list)
                crd_list = crd_data if isinstance(crd_data, list) else [crd_data]
                
                for crd_info in crd_list:
                    table.add_row(
                        op_config.get("display_name", operator_type),
                        crd_info.get("name", "unknown"),
                        crd_info.get("version", "unknown"),
                        crd_info.get("managed_by", "unknown"),
                        str(crd_info.get("created", "unknown"))[:19]  # Truncate timestamp
                    )
        
        self.console.print()
        self.console.print(table)
    
    def display_all_crd_status(self, crd_status: Dict[str, Dict]) -> None:
        """
        Display ALL detected CRDs (including Helm-managed ones) for visibility.
        Shows a comprehensive status table with clear indicators for management status.
        
        Args:
            crd_status: Dictionary of CRD status from check_existing_crds()
        """
        if not any(crd_status.values()):
            # No existing CRDs found
            return
        
        table = Table(
            title="📋 CRD Detection Summary - All Operators",
            show_header=True,
            border_style="cyan",
            title_style="bold cyan"
        )
        table.add_column("Operator", style="cyan", no_wrap=True)
        table.add_column("CRD Name", style="white")
        table.add_column("Version", style="green", justify="center")
        table.add_column("Managed By", style="magenta", justify="center")
        table.add_column("OLM", style="yellow", justify="center")
        table.add_column("Status", style="yellow", justify="center")
        table.add_column("Created", style="blue", justify="center")
        
        helm_managed_count = 0
        conflict_count = 0
        olm_managed_count = 0
        
        for operator_type, crd_data in crd_status.items():
            if crd_data:
                op_config = self.OPERATOR_CHARTS.get(operator_type, {})
                # Handle both single CRD (dict) and multiple CRDs (list)
                crd_list = crd_data if isinstance(crd_data, list) else [crd_data]
                
                for crd_info in crd_list:
                    managed_by = crd_info.get("managed_by", "unknown")
                    olm_managed = crd_info.get("olm_managed", False)
                    field_managers = crd_info.get("field_managers", [])
                    is_helm_managed = managed_by.lower() == "helm"
                    
                    # Determine if there's a conflict (same logic as deploy_operator.py)
                    # KEY FIX: If managed by Helm, NO conflict regardless of OLM label
                    has_conflict = False
                    if is_helm_managed:
                        # Helm is managing it - no conflict regardless of OLM label
                        has_conflict = False
                    elif olm_managed:
                        # OLM label present and NOT managed by Helm - conflict
                        has_conflict = True
                    elif len(field_managers) > 1:
                        # Multiple managers - conflict
                        has_conflict = True
                    elif len(field_managers) == 1 and field_managers[0].lower() != "helm":
                        # Single non-Helm manager - conflict
                        has_conflict = True
                    
                    if olm_managed:
                        olm_managed_count += 1
                    
                    if is_helm_managed and not has_conflict:
                        helm_managed_count += 1
                        status_icon = "[green]✓ Ready[/green]"
                    elif has_conflict:
                        conflict_count += 1
                        status_icon = "[yellow]⚠ Conflict Detected[/yellow]"
                    else:
                        status_icon = "[dim]Unknown[/dim]"
                    
                    olm_indicator = "[yellow]Yes[/yellow]" if olm_managed else "[dim]No[/dim]"
                    
                    table.add_row(
                        op_config.get("display_name", operator_type),
                        crd_info.get("name", "unknown"),
                        crd_info.get("version", "unknown"),
                        managed_by,
                        olm_indicator,
                        status_icon,
                        str(crd_info.get("created", "unknown"))[:19]  # Truncate timestamp
                    )
        
        self.console.print()
        self.console.print(table)
        
        # Display summary panel
        summary_lines = []
        if helm_managed_count > 0:
            summary_lines.append(f"[green]✓[/green] {helm_managed_count} CRD(s) already managed by Helm - [green]No action needed[/green]")
        if conflict_count > 0:
            summary_lines.append(f"[yellow]⚠[/yellow] {conflict_count} CRD(s) have ownership conflicts - [yellow]User decision required[/yellow]")
        if olm_managed_count > 0:
            summary_lines.append(f"[yellow]ℹ[/yellow] {olm_managed_count} CRD(s) have 'olm.managed: true' label")
        
        if summary_lines:
            self.console.print(Panel(
                "\n".join(summary_lines),
                title="[bold cyan]CRD Status Summary[/bold cyan]",
                border_style="cyan",
                padding=(0, 2)
            ))
        self.console.print()
    
    def check_existing_cluster_rbac(self, operators: List[str]) -> Dict[str, Optional[List[Dict]]]:
        """
        Check if ClusterRoles and ClusterRoleBindings for the specified operators already exist in the cluster.
        
        Args:
            operators: List of operator types to check
            
        Returns:
            Dict mapping operator type to list of RBAC resource info dicts (or None if no resources)
            Each resource info dict contains: name, type (ClusterRole/ClusterRoleBinding), managed_by
        """
        from kubernetes import client
        from kubernetes.client.rest import ApiException
        
        rbac_status = {}
        
        for operator_type in operators:
            if operator_type not in self.OPERATOR_CHARTS:
                continue
                
            op_config = self.OPERATOR_CHARTS[operator_type]
            cluster_role_names = op_config.get("cluster_role_names", [])
            cluster_role_binding_names = op_config.get("cluster_role_binding_names", [])
            
            if not cluster_role_names and not cluster_role_binding_names:
                # Operator doesn't define cluster RBAC resources
                rbac_status[operator_type] = None
                continue
            
            found_resources = []
            api = client.RbacAuthorizationV1Api()
            
            # Check ClusterRoles
            for cluster_role_name in cluster_role_names:
                try:
                    cluster_role = api.read_cluster_role(name=cluster_role_name)
                    
                    # Extract management info
                    labels = cluster_role.metadata.labels or {}  # type: ignore
                    managed_by = labels.get('app.kubernetes.io/managed-by', 'unknown')
                    
                    # Check field managers to detect partial ownership
                    managed_fields = cluster_role.metadata.managed_fields or []  # type: ignore
                    helm_owns_rules = False
                    actual_field_manager = 'unknown'
                    field_managers_list = []
                    
                    # Extract all field managers
                    for field in managed_fields:
                        if field.manager and field.manager not in field_managers_list:
                            field_managers_list.append(field.manager)
                        if field.fields_v1 and 'f:rules' in str(field.fields_v1):
                            actual_field_manager = field.manager
                            if field.manager == 'helm':
                                helm_owns_rules = True
                    
                    # Determine ownership status
                    if managed_by == 'Helm' and helm_owns_rules:
                        ownership_status = 'Helm (full)'
                    elif managed_by == 'Helm' and not helm_owns_rules:
                        ownership_status = f'Helm (partial - fields owned by {actual_field_manager})'
                    else:
                        ownership_status = managed_by
                    
                    found_resources.append({
                        "name": cluster_role_name,
                        "type": "ClusterRole",
                        "managed_by": ownership_status,
                        "partial_ownership": (managed_by == 'Helm' and not helm_owns_rules),
                        "field_managers": field_managers_list
                    })
                    
                    self.logger.debug(f"Found existing ClusterRole: {cluster_role_name} (managed by: {ownership_status})")
                    
                except ApiException as e:
                    if e.status == 404:
                        # ClusterRole doesn't exist
                        self.logger.debug(f"ClusterRole {cluster_role_name} not found")
                    else:
                        self.logger.warning(f"Error checking ClusterRole {cluster_role_name}: {e}")
            
            # Check ClusterRoleBindings
            for binding_name in cluster_role_binding_names:
                try:
                    binding = api.read_cluster_role_binding(name=binding_name)
                    
                    # Extract management info
                    labels = binding.metadata.labels or {}  # type: ignore
                    managed_by = labels.get('app.kubernetes.io/managed-by', 'unknown')
                    
                    # Check field managers to detect partial ownership
                    managed_fields = binding.metadata.managed_fields or []  # type: ignore
                    helm_owns_subjects = False
                    actual_field_manager = 'unknown'
                    field_managers_list = []
                    
                    # Extract all field managers
                    for field in managed_fields:
                        if field.manager and field.manager not in field_managers_list:
                            field_managers_list.append(field.manager)
                        if field.fields_v1 and 'f:subjects' in str(field.fields_v1):
                            actual_field_manager = field.manager
                            if field.manager == 'helm':
                                helm_owns_subjects = True
                    
                    # Determine ownership status
                    if managed_by == 'Helm' and helm_owns_subjects:
                        ownership_status = 'Helm (full)'
                    elif managed_by == 'Helm' and not helm_owns_subjects:
                        ownership_status = f'Helm (partial - fields owned by {actual_field_manager})'
                    else:
                        ownership_status = managed_by
                    
                    found_resources.append({
                        "name": binding_name,
                        "type": "ClusterRoleBinding",
                        "managed_by": ownership_status,
                        "partial_ownership": (managed_by == 'Helm' and not helm_owns_subjects),
                        "field_managers": field_managers_list
                    })
                    
                    self.logger.debug(f"Found existing ClusterRoleBinding: {binding_name} (managed by: {ownership_status})")
                    
                except ApiException as e:
                    if e.status == 404:
                        # ClusterRoleBinding doesn't exist
                        self.logger.debug(f"ClusterRoleBinding {binding_name} not found")
                    else:
                        self.logger.warning(f"Error checking ClusterRoleBinding {binding_name}: {e}")
            
            # Only add to status if we found at least one resource
            if found_resources:
                rbac_status[operator_type] = found_resources
            else:
                rbac_status[operator_type] = None
        
        return rbac_status
    
    def display_cluster_rbac_status(self, rbac_status: Dict[str, Optional[List[Dict]]]):
        """Display existing ClusterRole and ClusterRoleBinding status in a formatted table."""
        if not any(rbac_status.values()):
            # No existing RBAC resources found
            return
            
        table = Table(title="Existing Cluster RBAC Resources Detected", show_header=True, border_style="yellow")
        table.add_column("Operator", style="cyan")
        table.add_column("Resource Type", style="blue")
        table.add_column("Resource Name", style="white")
        table.add_column("Managed By", style="magenta")
        
        for operator_type, resource_list in rbac_status.items():
            if resource_list is None:
                continue
                
            op_config = self.OPERATOR_CHARTS.get(operator_type, {})
            operator_name = op_config.get("display_name", operator_type)
            
            for i, resource_info in enumerate(resource_list):
                resource_name = resource_info.get("name", "unknown")
                resource_type = resource_info.get("type", "unknown")
                managed_by = resource_info.get("managed_by", "unknown")
                partial_ownership = resource_info.get("partial_ownership", False)
                
                # Only show operator name on first row
                op_display = operator_name if i == 0 else ""
                
                # Highlight partial ownership with warning color
                if partial_ownership:
                    managed_by_display = f"[yellow]{managed_by}[/yellow]"
                else:
                    managed_by_display = managed_by
                
                table.add_row(op_display, resource_type, resource_name, managed_by_display)
        
        self.console.print()
        self.console.print(table)
        
        # Check if any resources have partial ownership
        has_partial = any(
            resource.get("partial_ownership", False)
            for resources in rbac_status.values()
            if resources
            for resource in resources
        )
        
        if has_partial:
            self.console.print()
            self.console.print("[yellow]⚠ Warning:[/yellow] Resources marked with [yellow]'Helm (partial - fields owned by X)'[/yellow] have Helm metadata")
            self.console.print("   but the actual resource fields are still owned by another field manager.")
            self.console.print("   If you choose 'Let Helm take ownership', these resources will be forcefully adopted.")
        
        self.console.print()
        self.console.print()
    
    def deploy_operator(self,
                       operator_type: str,
                       namespace: str,
                       chart_source: HelmChartSource = HelmChartSource.PACKAGED,
                       release_name: Optional[str] = None,
                       values: Optional[Dict] = None,
                       chart_url: Optional[str] = None,
                       create_cluster_role: bool = True,
                       install_crd: bool = True,
                       force: bool = False,
                       force_conflicts: bool = False,
                       dry_run: bool = False,
                       wait: bool = True,
                       timeout: str = "5m",
                       live=None,
                       tracker=None,
                       operator_type_enum=None,
                       force_reinstall: bool = False,
                       skip_crd_adoption: bool = False) -> bool:
        """
        Deploy an operator using Helm.
        
        Args:
            operator_type: Type of operator (content, ai-services, fncm, etc.)
            namespace: Target namespace
            chart_source: Source type for the Helm chart
            release_name: Helm release name (defaults to chart name)
            values: Custom values to override
            chart_url: URL for chart (when using URL source)
            create_cluster_role: Create cluster-level RBAC
            install_crd: Install CRDs
            force: Use --take-ownership flag to take ownership of existing resources
            force_conflicts: Use --force-conflicts flag to resolve field manager conflicts
            dry_run: Perform dry run only
            wait: Wait for deployment to complete
            timeout: Timeout for deployment
            live: Optional Live display for real-time updates
            tracker: Optional deployment tracker
            operator_type_enum: Optional OperatorType enum for tracking
            force_reinstall: Force reinstall by uninstalling existing release first
            skip_crd_adoption: Skip CRD adoption (when user chose to skip CRD installation)
            
        Returns:
            True if deployment succeeded
        """
        if operator_type not in self.OPERATOR_CHARTS:
            self.console.print(f"[red]✗[/red] Unknown operator type: {operator_type}")
            return False
        
        op_config = self.OPERATOR_CHARTS[operator_type]
        release_name = release_name or op_config["chart_name"]
        
        # Ensure ibm-licensing namespace exists for License Service operator
        if operator_type == "license-service" and not dry_run:
            self.logger.info("License Service operator detected - ensuring ibm-licensing namespace exists")
            try:
                from kubernetes import client
                core_v1 = client.CoreV1Api()
                
                # Check if ibm-licensing namespace exists
                try:
                    core_v1.read_namespace("ibm-licensing")
                    self.logger.info("Namespace 'ibm-licensing' already exists")
                    if not live:
                        self.console.print("[green]✓[/green] Namespace 'ibm-licensing' already exists")
                except client.ApiException as e:
                    if e.status == 404:
                        # Create ibm-licensing namespace
                        namespace_body = client.V1Namespace(
                            metadata=client.V1ObjectMeta(name="ibm-licensing")
                        )
                        core_v1.create_namespace(body=namespace_body)
                        self.logger.info("Created namespace 'ibm-licensing' for License Service")
                        if not live:
                            self.console.print("[green]✓[/green] Created namespace 'ibm-licensing' for License Service")
                    else:
                        raise
                
                # Apply License Service CRD before helm install
                self.logger.info("Applying License Service CRD before helm installation")
                if not live:
                    self.console.print("[cyan]Applying License Service CRD...[/cyan]")
                
                # Get the path to the CRD file
                # From: scripts/helper_scripts/helm/helm_deployer.py
                # To: container-samples/descriptors/license-service/licensing_v1_licensing_crd.yaml
                project_root = Path(__file__).resolve().parent.parent.parent.parent
                crd_file = project_root / "descriptors" / "license-service" / "licensing_v1_licensing_crd.yaml"
                
                if not crd_file.exists():
                    self.logger.error(f"License Service CRD file not found: {crd_file}")
                    if not live:
                        self.console.print(f"[red]✗[/red] CRD file not found: {crd_file}")
                    return False
                
                # Apply the CRD using Kubernetes Python client
                import yaml
                from kubernetes import client as k8s_client, utils
                
                # Read the CRD YAML file
                with open(crd_file, 'r') as f:
                    crd_yaml = yaml.safe_load_all(f)
                    
                    # Apply each document in the YAML file
                    api_client = k8s_client.ApiClient()
                    for crd_doc in crd_yaml:
                        if crd_doc is None:
                            continue
                        
                        try:
                            # Use utils.create_from_dict to apply the CRD
                            utils.create_from_dict(api_client, crd_doc)
                            crd_name = crd_doc.get('metadata', {}).get('name', 'unknown')
                            self.logger.info(f"Applied CRD: {crd_name}")
                        except utils.FailToCreateError as e:
                            # Check if it's because the CRD already exists
                            if hasattr(e, 'api_exceptions') and e.api_exceptions:
                                for api_ex in e.api_exceptions:
                                    if api_ex.status == 409:  # Conflict - already exists
                                        crd_name = crd_doc.get('metadata', {}).get('name', 'unknown')
                                        self.logger.info(f"CRD already exists: {crd_name}, updating...")
                                        # Try to update instead
                                        try:
                                            api_instance = k8s_client.ApiextensionsV1Api(api_client)
                                            api_instance.replace_custom_resource_definition(
                                                name=crd_name,
                                                body=crd_doc
                                            )
                                            self.logger.info(f"Updated CRD: {crd_name}")
                                        except Exception as update_ex:
                                            self.logger.warning(f"Could not update CRD {crd_name}: {update_ex}")
                                    else:
                                        raise
                            else:
                                raise
                
                self.logger.info("License Service CRD applied successfully")
                if not live:
                    self.console.print("[green]✓[/green] License Service CRD applied successfully")
                    
            except Exception as e:
                self.logger.error(f"Failed to ensure ibm-licensing namespace exists or apply CRD: {e}")
                if not live:
                    self.console.print(f"[red]✗[/red] Failed to create ibm-licensing namespace or apply CRD: {e}")
                return False
        
        # Handle Usage Metering CRD application (similar to License Service)
        if operator_type == "usage-metering" and not dry_run:
            try:
                # Apply Usage Metering CRD before helm install
                self.logger.info("Applying Usage Metering CRD before helm installation")
                if not live:
                    self.console.print("[cyan]Applying Usage Metering CRD...[/cyan]")
                
                # Get the path to the CRD file
                # From: scripts/helper_scripts/helm/helm_deployer.py
                # To: container-samples/descriptors/usage-metering/ibmusagemeterings_v1_ibmusagemeterings_crd.yaml
                project_root = Path(__file__).resolve().parent.parent.parent.parent
                crd_file = project_root / "descriptors" / "usage-metering" / "ibmusagemeterings_v1_ibmusagemeterings_crd.yaml"
                
                if not crd_file.exists():
                    self.logger.error(f"Usage Metering CRD file not found: {crd_file}")
                    if not live:
                        self.console.print(f"[red]✗[/red] CRD file not found: {crd_file}")
                    return False
                
                # Apply the CRD using Kubernetes Python client
                import yaml
                from kubernetes import client as k8s_client, utils
                
                # Read the CRD YAML file
                with open(crd_file, 'r') as f:
                    crd_yaml = yaml.safe_load_all(f)
                    
                    # Apply each document in the YAML file
                    api_client = k8s_client.ApiClient()
                    for crd_doc in crd_yaml:
                        if crd_doc is None:
                            continue
                        
                        try:
                            # Use utils.create_from_dict to apply the CRD
                            utils.create_from_dict(api_client, crd_doc)
                            crd_name = crd_doc.get('metadata', {}).get('name', 'unknown')
                            self.logger.info(f"Applied CRD: {crd_name}")
                        except utils.FailToCreateError as e:
                            # Check if it's because the CRD already exists
                            if hasattr(e, 'api_exceptions') and e.api_exceptions:
                                for api_ex in e.api_exceptions:
                                    if api_ex.status == 409:  # Conflict - already exists
                                        crd_name = crd_doc.get('metadata', {}).get('name', 'unknown')
                                        self.logger.info(f"CRD already exists: {crd_name}, updating...")
                                        # Try to update instead
                                        try:
                                            api_instance = k8s_client.ApiextensionsV1Api(api_client)
                                            api_instance.replace_custom_resource_definition(
                                                name=crd_name,
                                                body=crd_doc
                                            )
                                            self.logger.info(f"Updated CRD: {crd_name}")
                                        except Exception as update_ex:
                                            self.logger.warning(f"Could not update CRD {crd_name}: {update_ex}")
                                    else:
                                        raise
                            else:
                                raise
                
                self.logger.info("Usage Metering CRD applied successfully")
                if not live:
                    self.console.print("[green]✓[/green] Usage Metering CRD applied successfully")
                    
            except Exception as e:
                self.logger.error(f"Failed to apply Usage Metering CRD: {e}")
                if not live:
                    self.console.print(f"[red]✗[/red] Failed to apply Usage Metering CRD: {e}")
                return False
        
        # Only print if not using live display
        if not live:
            self.console.print(f"\n[cyan]Deploying {op_config['display_name']}...[/cyan]")
        
        # Check for existing release and handle conflicts
        # Always attempt CRD adoption unless explicitly skipped
        # Note: install_crd=False means "don't install NEW CRDs", but we should still adopt existing ones
        # For RBAC: Only adopt if user chose to let Helm manage RBAC (create_cluster_role=True)
        if not dry_run:
            conflict_handled = self._handle_release_conflicts(
                release_name=release_name,
                namespace=namespace,
                operator_type=operator_type,
                force_reinstall=force_reinstall,
                skip_crd_adoption=skip_crd_adoption,  # Only skip if explicitly requested
                skip_rbac_adoption=not create_cluster_role,  # Skip RBAC adoption if using existing RBAC
                live=live
            )
            if not conflict_handled:
                self.logger.error(f"Failed to handle conflicts for release {release_name}")
                return False
        
        # Determine chart path based on source
        chart_path = self._resolve_chart_path(operator_type, chart_source, chart_url)
        if not chart_path:
            return False
        
        # Generate values YAML file (unless dry run)
        values_file = None
        if not dry_run:
            # Get or create deployment ID for this deployment session
            if not hasattr(self, 'deployment_id'):
                from datetime import datetime
                self.deployment_id = f"deployment-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            values_file = self._generate_values_yaml(
                operator_type=operator_type,
                namespace=namespace,
                values=values,
                create_cluster_role=create_cluster_role,
                install_crd=install_crd,
                user_namespace=namespace,
                deployment_id=self.deployment_id
            )
            if values_file:
                self.logger.info(f"Generated Helm values file: {values_file}")
                # Store values file path and deployment folder for later retrieval
                if not hasattr(self, 'generated_values_files'):
                    self.generated_values_files = {}
                    self.deployment_folder = values_file.parent
                self.generated_values_files[operator_type] = values_file
        
        # Build Helm install command
        cmd = self._build_helm_install_command(
            release_name=release_name,
            chart_path=chart_path,
            namespace=namespace,
            values=values,
            create_cluster_role=create_cluster_role,
            install_crd=install_crd,
            force=force,
            force_conflicts=force_conflicts,
            dry_run=dry_run,
            wait=wait,
            timeout=timeout,
            operator_type=operator_type,
            user_namespace=namespace,  # Pass user's namespace for watchNamespace setting
            values_file=values_file  # Pass generated values file
        )
        
        # Execute deployment with live updates if available
        return self._execute_helm_command(
            cmd,
            f"deploy {op_config['display_name']}",
            live=live,
            tracker=tracker,
            operator_type=operator_type_enum
        )
    
    def upgrade_operator(self,
                        operator_type: str,
                        namespace: str,
                        chart_source: HelmChartSource = HelmChartSource.PACKAGED,
                        release_name: Optional[str] = None,
                        values: Optional[Dict] = None,
                        chart_url: Optional[str] = None,
                        wait: bool = True,
                        timeout: str = "5m") -> bool:
        """
        Upgrade an existing operator deployment.
        
        Args:
            operator_type: Type of operator
            namespace: Target namespace
            chart_source: Source type for the Helm chart
            release_name: Helm release name
            values: Custom values to override
            chart_url: URL for chart (when using URL source)
            wait: Wait for upgrade to complete
            timeout: Timeout for upgrade
            
        Returns:
            True if upgrade succeeded
        """
        if operator_type not in self.OPERATOR_CHARTS:
            self.console.print(f"[red]✗[/red] Unknown operator type: {operator_type}")
            return False
        
        op_config = self.OPERATOR_CHARTS[operator_type]
        release_name = release_name or op_config["chart_name"]
        
        self.console.print(f"\n[cyan]Upgrading {op_config['display_name']}...[/cyan]")
        
        # Determine chart path
        chart_path = self._resolve_chart_path(operator_type, chart_source, chart_url)
        if not chart_path:
            return False
        
        # Build Helm upgrade command
        cmd = [
            'helm', 'upgrade', release_name, chart_path,
            '--namespace', namespace,
            '--install',  # Install if not exists
            '--server-side', 'true',  # Use server-side apply to avoid field manager conflicts
        ]
        
        if values:
            for key, value in values.items():
                cmd.extend(['--set', f'{key}={value}'])
        
        if wait:
            cmd.extend(['--wait', '--timeout', timeout])
        
        return self._execute_helm_command(cmd, f"upgrade {op_config['display_name']}")
    
    def uninstall_operator(self,
                          operator_type: str,
                          namespace: str,
                          release_name: Optional[str] = None,
                          keep_crd: bool = False) -> bool:
        """
        Uninstall an operator deployment.
        
        Args:
            operator_type: Type of operator
            namespace: Target namespace
            release_name: Helm release name
            keep_crd: Keep CRDs after uninstall
            
        Returns:
            True if uninstall succeeded
        """
        if operator_type not in self.OPERATOR_CHARTS:
            self.console.print(f"[red]✗[/red] Unknown operator type: {operator_type}")
            return False
        
        op_config = self.OPERATOR_CHARTS[operator_type]
        release_name = release_name or op_config["chart_name"]
        
        self.console.print(f"\n[cyan]Uninstalling {op_config['display_name']}...[/cyan]")
        
        cmd = ['helm', 'uninstall', release_name, '--namespace', namespace]
        
        if keep_crd:
            cmd.append('--keep-history')
        
        return self._execute_helm_command(cmd, f"uninstall {op_config['display_name']}")
    
    def list_releases(self, namespace: str) -> List[Dict]:
        """
        List Helm releases in namespace.
        
        Args:
            namespace: Target namespace
            
        Returns:
            List of release information dictionaries
        """
        cmd = ['helm', 'list', '--namespace', namespace, '--output', 'json']
        
        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True
            )
            return json.loads(result.stdout) if result.stdout else []
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to list releases: {e.stderr}")
            return []
        except json.JSONDecodeError:
            self.logger.error("Failed to parse Helm list output")
            return []
    
    def get_release_status(self, release_name: str, namespace: str) -> Optional[Dict]:
        """
        Get status of a specific Helm release.
        
        Args:
            release_name: Name of the release
            namespace: Target namespace
            
        Returns:
            Release status dictionary or None
        """
        cmd = ['helm', 'status', release_name, '--namespace', namespace, '--output', 'json']
        
        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True
            )
            return json.loads(result.stdout) if result.stdout else None
        except subprocess.CalledProcessError:
            return None
        except json.JSONDecodeError:
            self.logger.error("Failed to parse Helm status output")
            return None
    
    def _resolve_chart_path(self,
                           operator_type: str,
                           chart_source: HelmChartSource,
                           chart_url: Optional[str] = None) -> Optional[str]:
        """
        Resolve the chart path based on source type.
        
        Args:
            operator_type: Type of operator
            chart_source: Source type for chart
            chart_url: URL for chart (when using URL source)
            
        Returns:
            Chart path or None if resolution failed
        """
        op_config = self.OPERATOR_CHARTS[operator_type]
        
        if chart_source == HelmChartSource.LOCAL:
            # Use local unpacked chart
            chart_path = self.chart_base_path / op_config["local_path"]
            if not chart_path.exists():
                self.console.print(f"[red]✗[/red] Local chart not found: {chart_path}")
                return None
            return str(chart_path)
        
        elif chart_source == HelmChartSource.PACKAGED:
            # Use packaged .tgz file
            if "packaged_file" not in op_config:
                self.console.print(f"[red]✗[/red] No packaged chart available for {operator_type}")
                return None
            chart_path = self.chart_base_path / op_config["packaged_file"]
            if not chart_path.exists():
                self.console.print(f"[red]✗[/red] Packaged chart not found: {chart_path}")
                return None
            return str(chart_path)
        
        elif chart_source == HelmChartSource.PUBLIC_REPO:
            # Use public Helm repository
            if "public_repo" not in op_config or "public_chart" not in op_config:
                self.console.print(f"[red]✗[/red] No public repo configured for {operator_type}")
                return None
            return f"{op_config['public_repo']}/{op_config['public_chart']}"
        
        elif chart_source == HelmChartSource.GITHUB:
            # Download from GitHub (public or internal dev)
            return self._download_chart_from_github(operator_type, op_config)
        
        elif chart_source == HelmChartSource.URL:
            # Use direct URL
            if not chart_url:
                self.console.print("[red]✗[/red] Chart URL not provided")
                return None
            return chart_url
        
        return None
    
    def _download_chart_from_github(self, operator_type: str, op_config: Dict) -> Optional[str]:
        """
        Download Helm chart from GitHub (public or internal dev repository).
        
        Args:
            operator_type: Type of operator
            op_config: Operator configuration dictionary
            
        Returns:
            Path to downloaded chart file or None if download failed
        """
        # Select URL based on dev mode
        if self.dev_mode:
            if "github_dev_url" not in op_config:
                self.console.print(f"[red]✗[/red] No dev GitHub URL configured for {operator_type}")
                return None
            url = op_config["github_dev_url"]
            self.logger.info(f"Downloading chart from internal dev repository: {url}")
        else:
            if "github_url" not in op_config:
                self.console.print(f"[red]✗[/red] No GitHub URL configured for {operator_type}")
                return None
            url = op_config["github_url"]
            self.logger.info(f"Downloading chart from public GitHub: {url}")
        
        # Create temp directory for downloaded charts inside scripts folder
        scripts_dir = Path(__file__).resolve().parent.parent.parent
        download_dir = scripts_dir / ".downloads"
        download_dir.mkdir(exist_ok=True)
        
        # Extract filename from URL
        filename = op_config.get("packaged_file", f"{operator_type}.tgz")
        local_path = download_dir / filename
        
        try:
            # Remove any previously downloaded chart so we always fetch the latest artifact
            if local_path.exists():
                self.logger.info(f"Removing cached chart before download: {local_path}")
                local_path.unlink()
            
            # Prepare headers for authentication
            headers = {}
            if self.dev_mode and self.github_token:
                headers['Authorization'] = f'token {self.github_token}'
                self.logger.debug("Using GitHub token for authentication")
            
            # Download the chart
            self.console.print(f"[cyan]ℹ[/cyan] Downloading {op_config['display_name']} chart from GitHub...")
            response = requests.get(url, headers=headers, timeout=30, stream=True)
            response.raise_for_status()
            
            # Save to file
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            self.logger.info(f"Chart downloaded successfully: {local_path}")
            self.console.print(f"[green]✓[/green] Chart downloaded: {filename}")
            return str(local_path)
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                self.console.print(f"[red]✗[/red] Authentication failed. GitHub token required for internal repository.")
                self.logger.error(f"Authentication failed for {url}: {e}")
            elif e.response.status_code == 404:
                self.console.print(f"[red]✗[/red] Chart not found at {url}")
                self.logger.error(f"Chart not found: {e}")
            else:
                self.console.print(f"[red]✗[/red] HTTP error downloading chart: {e}")
                self.logger.error(f"HTTP error: {e}")
            return None
        except requests.exceptions.RequestException as e:
            self.console.print(f"[red]✗[/red] Error downloading chart: {e}")
            self.logger.error(f"Download error: {e}")
            return None
        except Exception as e:
            self.console.print(f"[red]✗[/red] Unexpected error: {e}")
            self.logger.error(f"Unexpected error downloading chart: {e}")
            return None
    
    def _flatten_dict(self, d: Dict, parent_key: str = '', sep: str = '.') -> Dict:
        """
        Flatten a nested dictionary into dot notation for Helm --set flags.
        
        Args:
            d: Dictionary to flatten
            parent_key: Parent key for recursion
            sep: Separator for keys (default: '.')
            
        Returns:
            Flattened dictionary with dot-notation keys
            
        Example:
            Input: {'a': {'b': {'c': 1}}}
            Output: {'a.b.c': 1}
        """
        items = []
        for k, v in d.items():
            new_key = f'{parent_key}{sep}{k}' if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)
    
    def _generate_values_yaml(self,
                             operator_type: str,
                             namespace: str,
                             values: Optional[Dict],
                             create_cluster_role: bool,
                             install_crd: bool,
                             user_namespace: Optional[str] = None,
                             deployment_id: Optional[str] = None) -> Optional[Path]:
        """
        Generate a YAML values file for Helm deployment.
        
        This creates a reusable values file that customers can use for future
        manual upgrades, improving traceability and repeatability.
        
        Args:
            operator_type: Type of operator
            namespace: Target namespace
            values: Custom values to include
            create_cluster_role: Whether to create cluster-level RBAC
            install_crd: Whether to install CRDs
            user_namespace: User's selected namespace (for watchNamespace)
            deployment_id: Unique deployment identifier for folder organization
            
        Returns:
            Path to generated YAML file or None if generation failed
        """
        import yaml
        from datetime import datetime
        
        # Create deployment-specific directory with namespace subfolder
        scripts_dir = Path(__file__).resolve().parent.parent.parent
        
        # Use deployment_id if provided, otherwise create timestamp-based folder
        if deployment_id:
            deployment_folder = deployment_id
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            deployment_folder = f"deployment-{timestamp}"
        
        # Structure: CCxHelm/<namespace>/<deployment-timestamp>/
        values_dir = scripts_dir / "CCxHelm" / namespace / deployment_folder
        values_dir.mkdir(parents=True, exist_ok=True)
        
        # Build complete values dictionary
        helm_values = {}
        
        # Add RBAC configuration
        helm_values['rbac'] = {
            'enabled': create_cluster_role,
            'createClusterRole': create_cluster_role,
            'createClusterRoleBinding': create_cluster_role
        }
        
        # Add CRD configuration
        helm_values['crd'] = {
            'install': install_crd
        }
        
        # Add operator-specific configurations
        if operator_type == "license-service":
            helm_values['ibmLicensing'] = {
                'namespace': 'ibm-licensing',
                'watchNamespace': 'ibm-licensing'
            }
        
        # Merge custom values (these override defaults)
        if values:
            self._deep_merge(helm_values, values)
        
        # Generate filename (no timestamp needed since folder is timestamped)
        filename = f"{operator_type}-values.yaml"
        values_file = values_dir / filename
        
        try:
            # Write YAML file with header comment
            with open(values_file, 'w') as f:
                f.write(f"# Helm values file for {operator_type}\n")
                f.write(f"# Generated: {datetime.now().isoformat()}\n")
                f.write(f"# Namespace: {namespace}\n")
                f.write(f"#\n")
                f.write(f"# This file can be used for future manual upgrades:\n")
                f.write(f"#   helm upgrade {operator_type} <chart> -f {filename} -n {namespace}\n")
                f.write(f"#\n\n")
                yaml.dump(helm_values, f, default_flow_style=False, sort_keys=False)
            
            self.logger.info(f"Generated values file: {values_file}")
            return values_file
            
        except Exception as e:
            self.logger.error(f"Failed to generate values file: {e}")
            return None
    
    def _deep_merge(self, base: Dict, update: Dict) -> None:
        """
        Deep merge update dict into base dict (modifies base in place).
        
        Args:
            base: Base dictionary to merge into
            update: Dictionary with updates to merge
        """
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value
    
    def _generate_deployment_readme(self,
                                   deployment_folder: Path,
                                   namespace: str,
                                   operators: List[str],
                                   chart_source: str) -> None:
        """
        Generate a README file in the deployment folder with deployment details and useful commands.
        
        Args:
            deployment_folder: Path to the deployment folder
            namespace: Target namespace
            operators: List of deployed operators
            chart_source: Helm chart source used
        """
        from datetime import datetime
        
        readme_file = deployment_folder / "README.md"
        
        try:
            with open(readme_file, 'w') as f:
                f.write(f"# Helm Deployment - {deployment_folder.name}\n\n")
                f.write(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(f"**Namespace**: `{namespace}`\n\n")
                f.write(f"**Chart Source**: `{chart_source}`\n\n")
                
                f.write("## Deployed Operators\n\n")
                for op in operators:
                    op_config = self.OPERATOR_CHARTS.get(op, {})
                    display_name = op_config.get('display_name', op)
                    chart_name = op_config.get('chart_name', op)
                    f.write(f"- **{display_name}** (`{chart_name}`)\n")
                    f.write(f"  - Values file: `{op}-values.yaml`\n")
                
                f.write("\n## Values Files\n\n")
                f.write("This folder contains Helm values files for each deployed operator. ")
                f.write("These files capture the exact configuration used during deployment and can be used for:\n\n")
                f.write("- Future manual upgrades\n")
                f.write("- Disaster recovery\n")
                f.write("- Configuration auditing\n")
                f.write("- Replicating deployments across environments\n\n")
                
                f.write("## Upgrade Commands\n\n")
                f.write("Use these commands to upgrade operators with the saved values files:\n\n")
                
                for op in operators:
                    op_config = self.OPERATOR_CHARTS.get(op, {})
                    chart_name = op_config.get('chart_name', op)
                    display_name = op_config.get('display_name', op)
                    
                    # Determine namespace for upgrade command
                    if op == "license-service":
                        upgrade_namespace = "ibm-licensing"
                    else:
                        upgrade_namespace = namespace
                    
                    f.write(f"### {display_name}\n\n")
                    f.write("```bash\n")
                    f.write(f"# Upgrade {display_name}\n")
                    f.write(f"helm upgrade {chart_name} <chart-path> \\\n")
                    f.write(f"  --values {op}-values.yaml \\\n")
                    f.write(f"  --namespace {upgrade_namespace}\n")
                    f.write("```\n\n")
                
                f.write("## Useful Helm Commands\n\n")
                
                f.write("### Check Release Status\n\n")
                f.write("```bash\n")
                for op in operators:
                    op_config = self.OPERATOR_CHARTS.get(op, {})
                    chart_name = op_config.get('chart_name', op)
                    if op == "license-service":
                        check_namespace = "ibm-licensing"
                    else:
                        check_namespace = namespace
                    f.write(f"helm status {chart_name} -n {check_namespace}\n")
                f.write("```\n\n")
                
                f.write("### View Release History\n\n")
                f.write("```bash\n")
                for op in operators:
                    op_config = self.OPERATOR_CHARTS.get(op, {})
                    chart_name = op_config.get('chart_name', op)
                    if op == "license-service":
                        hist_namespace = "ibm-licensing"
                    else:
                        hist_namespace = namespace
                    f.write(f"helm history {chart_name} -n {hist_namespace}\n")
                f.write("```\n\n")
                
                f.write("### Get Current Values\n\n")
                f.write("```bash\n")
                for op in operators:
                    op_config = self.OPERATOR_CHARTS.get(op, {})
                    chart_name = op_config.get('chart_name', op)
                    if op == "license-service":
                        get_namespace = "ibm-licensing"
                    else:
                        get_namespace = namespace
                    f.write(f"helm get values {chart_name} -n {get_namespace}\n")
                f.write("```\n\n")
                
                f.write("### Rollback to Previous Version\n\n")
                f.write("```bash\n")
                for op in operators:
                    op_config = self.OPERATOR_CHARTS.get(op, {})
                    chart_name = op_config.get('chart_name', op)
                    if op == "license-service":
                        rollback_namespace = "ibm-licensing"
                    else:
                        rollback_namespace = namespace
                    f.write(f"# Rollback {op_config.get('display_name', op)}\n")
                    f.write(f"helm rollback {chart_name} -n {rollback_namespace}\n\n")
                f.write("```\n\n")
                
                f.write("### Dry Run Upgrade\n\n")
                f.write("Test an upgrade without applying changes:\n\n")
                f.write("```bash\n")
                for op in operators:
                    op_config = self.OPERATOR_CHARTS.get(op, {})
                    chart_name = op_config.get('chart_name', op)
                    if op == "license-service":
                        dryrun_namespace = "ibm-licensing"
                    else:
                        dryrun_namespace = namespace
                    f.write(f"helm upgrade {chart_name} <chart-path> \\\n")
                    f.write(f"  --values {op}-values.yaml \\\n")
                    f.write(f"  --namespace {dryrun_namespace} \\\n")
                    f.write(f"  --dry-run\n\n")
                f.write("```\n\n")
                
                f.write("## Modifying Values\n\n")
                f.write("To customize the deployment:\n\n")
                f.write("1. Copy the values file:\n")
                f.write("   ```bash\n")
                f.write("   cp <operator>-values.yaml my-custom-values.yaml\n")
                f.write("   ```\n\n")
                f.write("2. Edit `my-custom-values.yaml` with your changes\n\n")
                f.write("3. Upgrade with custom values:\n")
                f.write("   ```bash\n")
                f.write("   helm upgrade <release> <chart> -f my-custom-values.yaml -n <namespace>\n")
                f.write("   ```\n\n")
                
                f.write("## Notes\n\n")
                f.write("- Keep these files in version control for audit trail\n")
                f.write("- Review values before upgrading to ensure compatibility\n")
                f.write("- Always test upgrades in non-production environments first\n")
                f.write("- Backup your cluster before major upgrades\n\n")
                
                f.write("## Support\n\n")
                f.write("For issues or questions:\n")
                f.write("- Check deployment logs in `scripts/logs/`\n")
                f.write("- Review Helm release status with commands above\n")
                f.write("- Contact IBM Content Cortex support with these values files\n")
            
            self.logger.info(f"Generated deployment README: {readme_file}")
            
        except Exception as e:
            self.logger.error(f"Failed to generate deployment README: {e}")
    
    def _build_helm_install_command(self,
                                   release_name: str,
                                   chart_path: str,
                                   namespace: str,
                                   values: Optional[Dict],
                                   create_cluster_role: bool,
                                   install_crd: bool,
                                   force: bool,
                                   force_conflicts: bool,
                                   dry_run: bool,
                                   wait: bool,
                                   timeout: str,
                                   operator_type: Optional[str] = None,
                                   user_namespace: Optional[str] = None,
                                   values_file: Optional[Path] = None) -> List[str]:
        """
        Build Helm install command with all options.
        
        Args:
            release_name: Name of the Helm release
            chart_path: Path to the Helm chart
            namespace: Target namespace
            values: Custom values to override
            create_cluster_role: Create cluster-level RBAC
            install_crd: Install CRDs
            force: Use --take-ownership flag to take ownership of existing resources
            force_conflicts: Use --force-conflicts flag to resolve field manager conflicts
            dry_run: Perform dry run only
            wait: Wait for deployment to complete
            timeout: Timeout for deployment
            operator_type: Type of operator (for special handling)
            user_namespace: User's selected namespace (for watchNamespace)
            values_file: Path to values YAML file (if generated)
            
        Returns:
            List of command arguments for Helm
        """
        # For License Service, install in ibm-licensing namespace but watch user's namespace
        if operator_type == "license-service":
            install_namespace = "ibm-licensing"
        else:
            install_namespace = namespace
        
        cmd = [
            'helm', 'upgrade', '--install', release_name, chart_path,
            '--namespace', install_namespace,
            '--create-namespace',
        ]
        
        # Use values file if provided (preferred method)
        if values_file and values_file.exists():
            cmd.extend(['--values', str(values_file)])
            self.logger.info(f"Using values file: {values_file}")
        else:
            # Fallback to --set commands (legacy method)
            # Handle RBAC resource creation
            if create_cluster_role:
                # Create RBAC resources - Helm will manage them
                cmd.extend(['--set', 'rbac.enabled=true'])
                cmd.extend(['--set', 'rbac.createClusterRole=true'])
                cmd.extend(['--set', 'rbac.createClusterRoleBinding=true'])
            else:
                # Skip RBAC resource creation - use existing resources
                cmd.extend(['--set', 'rbac.enabled=false'])
                cmd.extend(['--set', 'rbac.createClusterRole=false'])
                cmd.extend(['--set', 'rbac.createClusterRoleBinding=false'])
            
            # Handle CRD installation
            cmd.extend(['--set', f'crd.install={str(install_crd).lower()}'])
            
            # For License Service operator, set namespace to ibm-licensing and watchNamespace to ibm-licensing
            if operator_type == "license-service":
                # License Service is installed in ibm-licensing namespace
                cmd.extend(['--set', 'ibmLicensing.namespace=ibm-licensing'])
                # And watches only the ibm-licensing namespace
                cmd.extend(['--set', 'ibmLicensing.watchNamespace=ibm-licensing'])
            
            if values:
                # Flatten nested dictionaries into dot notation for Helm
                flattened_values = self._flatten_dict(values)
                for key, value in flattened_values.items():
                    cmd.extend(['--set', f'{key}={value}'])
        
        # If install_crd is False, add --skip-crds to tell Helm to completely ignore CRDs
        # This prevents Helm from trying to manage existing CRDs
        if not install_crd:
            cmd.append('--skip-crds')
        
        # Add force flags if taking over resource management from other systems
        # License Service ALWAYS uses these flags to handle CRD ownership
        if force or operator_type == "license-service":
            cmd.append('--take-ownership')
            self.logger.info("Using --take-ownership flag to take ownership of existing resources")
        
        if force_conflicts or operator_type == "license-service":
            cmd.append('--force-conflicts')
            cmd.extend(['--server-side', 'true'])
            self.logger.info("Using --force-conflicts and --server-side flags to resolve field manager conflicts")
        
        if dry_run:
            cmd.append('--dry-run')
        
        if wait:
            cmd.extend(['--wait', '--timeout', timeout])
        
        return cmd
    
    def _extract_clean_error_message(self, stderr: str, stdout: Optional[str] = None) -> str:
        """
        Extract a clean, user-friendly error message from Helm output.
        
        Args:
            stderr: Standard error output from Helm
            stdout: Standard output from Helm
            
        Returns:
            Clean error message suitable for user display
        """
        # Common error patterns and their clean messages
        error_patterns = {
            'context canceled': 'Deployment was cancelled or timed out',
            'connection refused': 'Cannot connect to Kubernetes cluster',
            'forbidden': 'Insufficient permissions',
            'not found': 'Resource not found',
            'already exists': 'Resource already exists',
            'invalid': 'Invalid configuration',
            'timeout': 'Operation timed out',
            'failed to pull image': 'Image pull failed - check registry credentials',
            'ImagePullBackOff': 'Image pull failed - check image name and credentials',
            'CrashLoopBackOff': 'Pod is crashing - check pod logs',
            'OOMKilled': 'Pod ran out of memory',
        }
        
        # Combine stderr and stdout for analysis
        full_output = stderr
        if stdout:
            full_output += "\n" + stdout
        
        full_output_lower = full_output.lower()
        
        # Check for known patterns
        for pattern, clean_msg in error_patterns.items():
            if pattern.lower() in full_output_lower:
                return clean_msg
        
        # Extract first meaningful error line
        lines = stderr.split('\n')
        for line in lines:
            line = line.strip()
            if line and not line.startswith('level='):
                # Remove ANSI codes and clean up
                clean_line = line.replace('Error: ', '').replace('UPGRADE FAILED: ', '')
                if len(clean_line) > 10:  # Meaningful message
                    return clean_line[:200]  # Limit length
        
        # Fallback to generic message
        return "Helm deployment failed - check logs for details"
    
    def _execute_helm_command(self, cmd: List[str], operation: str,
                             live=None, tracker=None, operator_type=None) -> bool:
        """
        Execute a Helm command with progress indication.
        
        Args:
            cmd: Command to execute
            operation: Description of operation
            live: Optional Live display for real-time updates
            tracker: Optional deployment tracker
            operator_type: Optional operator type for tracking
            
        Returns:
            True if command succeeded
        """
        # If live display and tracker provided, use live updates
        if live and tracker and operator_type:
            try:
                # Don't log to console during live display - it distorts the UI
                # Only log to file if file handler is configured
                
                # Log command execution to file
                self.logger.info(f"Executing: {' '.join(cmd)}")
                
                # Update tracker to show deployment in progress
                tracker.update_operator(
                    operator_type,
                    phase=DeploymentPhase.DEPLOYING,
                    step=DeploymentStep.OPERATOR_DEPLOYMENT,
                    progress=50
                )
                live.update(tracker.create_progress_display())
                
                result = subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True
                )
                
                # Log success to file
                self.logger.info(f"{operation} completed successfully")
                if result.stdout:
                    self.logger.debug(f"Helm output: {result.stdout}")
                
                # Update tracker to show success
                tracker.update_operator(
                    operator_type,
                    phase=DeploymentPhase.COMPLETED,
                    progress=100
                )
                live.update(tracker.create_progress_display())
                
                return True
            except subprocess.CalledProcessError as e:
                # Log detailed error to file
                error_msg = e.stderr if e.stderr else str(e)
                self.logger.error("=" * 80)
                self.logger.error(f"HELM DEPLOYMENT FAILED: {operation}")
                self.logger.error("=" * 80)
                self.logger.error(f"Command: {' '.join(cmd)}")
                self.logger.error(f"Exit Code: {e.returncode}")
                self.logger.error(f"Error Output:\n{error_msg}")
                if e.stdout:
                    self.logger.error(f"Standard Output:\n{e.stdout}")
                self.logger.error("=" * 80)
                
                # Extract clean error message for user display
                clean_error = self._extract_clean_error_message(error_msg, e.stdout)
                
                # Store full error details for later retrieval
                full_error_details = {
                    'command': ' '.join(cmd),
                    'exit_code': e.returncode,
                    'stderr': error_msg,
                    'stdout': e.stdout if e.stdout else '',
                    'clean_message': clean_error
                }
                
                # Update tracker to show failure with clean error and full details
                tracker.update_operator(
                    operator_type,
                    phase=DeploymentPhase.FAILED,
                    error=clean_error,
                    error_details=full_error_details
                )
                live.update(tracker.create_progress_display())
                return False
        else:
            # Fallback to simple progress spinner
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console
            ) as progress:
                task = progress.add_task(f"{operation}...", total=None)
                
                try:
                    self.logger.info(f"Executing: {' '.join(cmd)}")
                    result = subprocess.run(
                        cmd,
                        check=True,
                        capture_output=True,
                        text=True
                    )
                    progress.update(task, completed=True)
                    self.console.print(f"[green]✓[/green] {operation} completed successfully")
                    
                    if result.stdout:
                        self.logger.debug(f"Helm output: {result.stdout}")
                    
                    return True
                except subprocess.CalledProcessError as e:
                    progress.update(task, completed=True)
                    
                    # Log detailed error to file
                    error_msg = e.stderr if e.stderr else str(e)
                    self.logger.error("=" * 80)
                    self.logger.error(f"HELM DEPLOYMENT FAILED: {operation}")
                    self.logger.error("=" * 80)
                    self.logger.error(f"Command: {' '.join(cmd)}")
                    self.logger.error(f"Exit Code: {e.returncode}")
                    self.logger.error(f"Error Output:\n{error_msg}")
                    if e.stdout:
                        self.logger.error(f"Standard Output:\n{e.stdout}")
                    self.logger.error("=" * 80)
                    
                    # Extract clean error message
                    clean_error = self._extract_clean_error_message(error_msg, e.stdout)
                    
                    # Display clean error to console
                    self.console.print(f"[red]✗[/red] {operation} failed: {clean_error}")
                    self.console.print("[yellow]ℹ[/yellow] See logs for detailed error information")
                    return False
    
    def _check_helm(self) -> bool:
        """Check if Helm is installed."""
        try:
            subprocess.run(
                ['helm', 'version'],
                check=True,
                capture_output=True
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    def _get_helm_version(self) -> Optional[str]:
        """Get Helm version string."""
        try:
            result = subprocess.run(
                ['helm', 'version', '--short'],
                check=True,
                capture_output=True,
                text=True
            )
            return result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
    
    def _is_helm_version_compatible(self, version: str) -> bool:
        """Check if Helm version is compatible (4.x+)."""
        try:
            # Extract version number (e.g., "v4.0.0" -> "4.0.0")
            version_num = version.lstrip('v').split('+')[0]
            major = int(version_num.split('.')[0])
            return major >= 4
        except (ValueError, IndexError):
            return False
    
    def _check_kubectl(self) -> bool:
        """Check if kubectl is installed and can connect."""
        try:
            subprocess.run(
                ['kubectl', 'version', '--client'],
                check=True,
                capture_output=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    def _check_namespace(self, namespace: str) -> bool:
        """Check if namespace exists using Kubernetes Python client."""
        try:
            from kubernetes import client
            v1 = client.CoreV1Api()
            v1.read_namespace(name=namespace)
            return True
        except Exception:
            return False
    
    def _check_secret(self, namespace: str, secret_name: str) -> bool:
        """Check if secret exists in namespace using Kubernetes Python client."""
        try:
            from kubernetes import client
            v1 = client.CoreV1Api()
            v1.read_namespaced_secret(name=secret_name, namespace=namespace)
            return True
        except Exception:
            return False
    
    def _check_secret_kubectl(self, namespace: str, secret_name: str) -> bool:
        """Check if secret exists in namespace using kubectl (fallback)."""
        try:
            subprocess.run(
                ['kubectl', 'get', 'secret', secret_name, '-n', namespace],
                check=True,
                capture_output=True
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def _check_kubernetes_connection(self) -> bool:
        """Check if Kubernetes API is accessible using Python client."""
        try:
            from kubernetes import client
            v1 = client.CoreV1Api()
            v1.list_namespace(limit=1)
            return True
        except Exception:
            return False
    def _handle_release_conflicts(self,
                                  release_name: str,
                                  namespace: str,
                                  operator_type: str,
                                  force_reinstall: bool = False,
                                  skip_crd_adoption: bool = False,
                                  skip_rbac_adoption: bool = False,
                                  live=None) -> bool:
        """
        Handle conflicts with existing Helm releases, CRDs, and RBAC resources.
        
        This method addresses common Helm installation errors:
        1. "release name already in use" - existing Helm release
        2. CRD ownership conflicts - CRDs managed by different tools
        3. ClusterRole/ClusterRoleBinding conflicts - RBAC resources managed by different tools
        3. CRD metadata annotation errors - missing Helm annotations
        
        Args:
            release_name: Name of the Helm release
            namespace: Target namespace
            operator_type: Type of operator being deployed
            force_reinstall: If True, uninstall existing release
            skip_crd_adoption: If True, skip CRD adoption (user chose to skip CRD installation)
            live: Optional Live display for updates
            
        Returns:
            True if conflicts were handled successfully
        """
        # Check if release already exists
        existing_release = self.get_release_status(release_name, namespace)
        
        if existing_release:
            status = existing_release.get('info', {}).get('status', 'unknown')
            # Only log when not using live display to avoid UI distortion
            if not live:
                self.logger.warning(f"Release '{release_name}' already exists with status: {status}")
            
            if force_reinstall:
                if not live:
                    self.logger.info(f"Force reinstall enabled - uninstalling existing release '{release_name}'")
                    self.console.print(f"[yellow]⚠[/yellow] Uninstalling existing release '{release_name}'...")
                
                if not self.uninstall_operator(operator_type, namespace, release_name, keep_crd=True):
                    if not live:
                        self.logger.error(f"Failed to uninstall existing release '{release_name}'")
                    return False
            else:
                # Try to adopt the release using upgrade --install
                if not live:
                    self.logger.info(f"Attempting to upgrade existing release '{release_name}'")
                    self.console.print(f"[yellow]⚠[/yellow] Release exists - will attempt upgrade instead of install")
                return True
        
        # Check and handle CRD conflicts
        # Only attempt CRD adoption if user chose to let Helm manage CRDs
        if not skip_crd_adoption and operator_type in self.OPERATOR_CHARTS:
            op_config = self.OPERATOR_CHARTS[operator_type]
            
            # Support both single crd_name and multiple crd_names
            crd_names = []
            if "crd_names" in op_config:
                crd_names = op_config["crd_names"]
            elif "crd_name" in op_config:
                crd_names = [op_config["crd_name"]]
            
            # Handle each CRD
            for crd_name in crd_names:
                if not self._handle_crd_conflicts(crd_name, release_name, namespace, live):
                    if not live:
                        self.logger.warning(f"CRD conflict handling failed for {crd_name}, but continuing...")
                    # Don't fail - let Helm handle it with --force if needed
        elif skip_crd_adoption and not live:
            self.logger.info(f"Skipping CRD adoption for {operator_type} (user chose to skip CRD installation)")
        
        # Check and handle ClusterRole/ClusterRoleBinding conflicts
        # Only attempt adoption if user chose to let Helm manage RBAC resources
        if not skip_rbac_adoption and operator_type in self.OPERATOR_CHARTS:
            op_config = self.OPERATOR_CHARTS[operator_type]
            
            # Get ClusterRole names if defined
            cluster_role_names = op_config.get("cluster_role_names", [])
            
            # Handle each ClusterRole
            for cluster_role_name in cluster_role_names:
                if not self._handle_cluster_role_conflicts(cluster_role_name, release_name, namespace, live):
                    if not live:
                        self.logger.warning(f"ClusterRole conflict handling failed for {cluster_role_name}, but continuing...")
                    # Don't fail - let Helm handle it with --force if needed
            
            # Get ClusterRoleBinding names if defined
            cluster_role_binding_names = op_config.get("cluster_role_binding_names", [])
            
            # Handle each ClusterRoleBinding
            for binding_name in cluster_role_binding_names:
                if not self._handle_cluster_role_binding_conflicts(binding_name, release_name, namespace, live):
                    if not live:
                        self.logger.warning(f"ClusterRoleBinding conflict handling failed for {binding_name}, but continuing...")
                    # Don't fail - let Helm handle it with --force if needed
        elif skip_rbac_adoption and not live:
            self.logger.info(f"Skipping RBAC adoption for {operator_type} (user chose to use existing RBAC resources)")
        
        return True
    
    def _handle_cluster_role_conflicts(self,
                                       cluster_role_name: str,
                                       release_name: str,
                                       namespace: str,
                                       live=None) -> bool:
        """
        Handle ClusterRole ownership and metadata conflicts.
        
        Similar to CRD handling, but for ClusterRoles that may already exist
        and need to be adopted by Helm.
        
        Args:
            cluster_role_name: Name of the ClusterRole
            release_name: Helm release name
            namespace: Target namespace
            live: Optional Live display
            
        Returns:
            True if ClusterRole conflicts were resolved
        """
        try:
            from kubernetes import client
            from kubernetes.client.rest import ApiException
            
            api = client.RbacAuthorizationV1Api()
            
            # Check if ClusterRole exists
            try:
                cluster_role = api.read_cluster_role(name=cluster_role_name)
            except ApiException as e:
                if e.status == 404:
                    # ClusterRole doesn't exist - no conflict
                    return True
                raise
            
            # Check ClusterRole ownership metadata
            if not cluster_role.metadata:  # type: ignore
                return True
                
            labels = cluster_role.metadata.labels or {}  # type: ignore
            annotations = cluster_role.metadata.annotations or {}  # type: ignore
            
            managed_by = labels.get('app.kubernetes.io/managed-by', '')
            has_helm_release = 'meta.helm.sh/release-name' in annotations
            has_helm_namespace = 'meta.helm.sh/release-namespace' in annotations
            
            # Check field managers to see if Helm actually owns the resource fields
            managed_fields = cluster_role.metadata.managed_fields or []  # type: ignore
            helm_owns_rules = False
            for field in managed_fields:
                if field.manager == 'helm' and field.fields_v1 and 'f:rules' in str(field.fields_v1):
                    helm_owns_rules = True
                    break
            
            # If ClusterRole has Helm metadata AND Helm owns the rules field, no action needed
            if managed_by == 'Helm' and has_helm_release and has_helm_namespace and helm_owns_rules:
                if not live:
                    self.logger.debug(f"ClusterRole {cluster_role_name} already fully managed by Helm")
                return True
            
            # ClusterRole needs adoption if:
            # 1. Not managed by Helm at all, OR
            # 2. Has Helm metadata but Helm doesn't own the actual fields (partial ownership)
            needs_adoption = (
                (managed_by != 'Helm') or
                (managed_by == 'Helm' and not helm_owns_rules)
            )
            
            if needs_adoption:
                if managed_by and managed_by != 'Helm':
                    self.logger.warning(
                        f"ClusterRole {cluster_role_name} is managed by '{managed_by}' (not Helm). "
                        f"Attempting to adopt it for Helm management."
                    )
                    if not live:
                        self.console.print(
                            f"[yellow]⚠[/yellow] ClusterRole {cluster_role_name} managed by '{managed_by}' - adopting for Helm"
                        )
                elif managed_by == 'Helm' and not helm_owns_rules:
                    self.logger.warning(
                        f"ClusterRole {cluster_role_name} has Helm metadata but fields owned by other manager. "
                        f"Forcing field ownership transfer to Helm."
                    )
                    if not live:
                        self.console.print(
                            f"[yellow]⚠[/yellow] ClusterRole {cluster_role_name} has partial Helm ownership - forcing full adoption"
                        )
                self.logger.info(f"Adopting ClusterRole {cluster_role_name} for Helm management (release={release_name}, namespace={namespace})")
                
                # Update labels
                if not labels:
                    labels = {}
                labels['app.kubernetes.io/managed-by'] = 'Helm'
                
                # CRITICAL: Remove OLM label if present to prevent future conflicts
                if 'olm.managed' in labels:
                    self.logger.info(f"Removing 'olm.managed' label from ClusterRole {cluster_role_name}")
                    del labels['olm.managed']
                    if not live:
                        self.console.print(f"[yellow]ℹ[/yellow] Removed OLM label from ClusterRole {cluster_role_name}")
                
                # Update annotations
                if not annotations:
                    annotations = {}
                annotations['meta.helm.sh/release-name'] = release_name
                annotations['meta.helm.sh/release-namespace'] = namespace
                
                # Patch the ClusterRole using Server-Side Apply to force field manager ownership
                cluster_role.metadata.labels = labels  # type: ignore
                cluster_role.metadata.annotations = annotations  # type: ignore
                
                try:
                    # Use the Kubernetes API client directly with Server-Side Apply
                    # We need to use the raw API with the correct content-type header
                    from kubernetes import client as k8s_client
                    
                    # Update the ClusterRole object with new metadata
                    cluster_role.metadata.labels = labels  # type: ignore
                    cluster_role.metadata.annotations = annotations  # type: ignore
                    
                    # Get the API client
                    api_client = api.api_client
                    
                    # Prepare the request with SSA headers
                    # Server-Side Apply requires application/apply-patch+yaml content type
                    # and fieldManager and force query parameters
                    path = f"/apis/rbac.authorization.k8s.io/v1/clusterroles/{cluster_role_name}"
                    query_params = [
                        ('fieldManager', 'helm-adoption-script'),
                        ('force', 'true')  # Force conflicts - take ownership from other managers
                    ]
                    
                    # Convert the ClusterRole to dict for patching
                    body = api_client.sanitize_for_serialization(cluster_role)
                    
                    # Make the PATCH request with SSA
                    response = api_client.call_api(
                        path,
                        'PATCH',
                        query_params=query_params,
                        body=body,
                        _preload_content=False,
                        _return_http_data_only=True,
                        header_params={'Content-Type': 'application/apply-patch+yaml'}
                    )
                    
                    self.logger.info(f"Successfully adopted ClusterRole {cluster_role_name} for Helm management using SSA")
                    if not live:
                        self.console.print(f"[green]✓[/green] Adopted ClusterRole {cluster_role_name} for Helm management")
                    return True
                    
                except Exception as e:
                    self.logger.error(f"Failed to patch ClusterRole {cluster_role_name} with SSA: {e}")
                    if not live:
                        self.console.print(f"[yellow]⚠[/yellow] Could not adopt ClusterRole {cluster_role_name}: {str(e)}")
                    # Return True anyway - let Helm try with its own conflict resolution
                    return True
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error handling ClusterRole conflicts for {cluster_role_name}: {e}")
            # Return True to continue - let Helm handle it
            return True
    
    def _handle_cluster_role_binding_conflicts(self,
                                               binding_name: str,
                                               release_name: str,
                                               namespace: str,
                                               live=None) -> bool:
        """
        Handle ClusterRoleBinding ownership and metadata conflicts.
        
        Similar to ClusterRole handling, but for ClusterRoleBindings that may already exist
        and need to be adopted by Helm.
        
        Args:
            binding_name: Name of the ClusterRoleBinding
            release_name: Helm release name
            namespace: Target namespace
            live: Optional Live display
            
        Returns:
            True if ClusterRoleBinding conflicts were resolved
        """
        try:
            from kubernetes import client
            from kubernetes.client.rest import ApiException
            
            api = client.RbacAuthorizationV1Api()
            
            # Check if ClusterRoleBinding exists
            try:
                binding = api.read_cluster_role_binding(name=binding_name)
            except ApiException as e:
                if e.status == 404:
                    # ClusterRoleBinding doesn't exist - no conflict
                    return True
                raise
            
            # Check ClusterRoleBinding ownership metadata
            if not binding.metadata:  # type: ignore
                return True
                
            labels = binding.metadata.labels or {}  # type: ignore
            annotations = binding.metadata.annotations or {}  # type: ignore
            
            managed_by = labels.get('app.kubernetes.io/managed-by', '')
            has_helm_release = 'meta.helm.sh/release-name' in annotations
            has_helm_namespace = 'meta.helm.sh/release-namespace' in annotations
            
            # Check field managers to see if Helm actually owns the resource fields
            managed_fields = binding.metadata.managed_fields or []  # type: ignore
            helm_owns_subjects = False
            for field in managed_fields:
                if field.manager == 'helm' and field.fields_v1 and 'f:subjects' in str(field.fields_v1):
                    helm_owns_subjects = True
                    break
            
            # If ClusterRoleBinding has Helm metadata AND Helm owns the subjects field, no action needed
            if managed_by == 'Helm' and has_helm_release and has_helm_namespace and helm_owns_subjects:
                if not live:
                    self.logger.debug(f"ClusterRoleBinding {binding_name} already fully managed by Helm")
                return True
            
            # ClusterRoleBinding needs adoption if:
            # 1. Not managed by Helm at all, OR
            # 2. Has Helm metadata but Helm doesn't own the actual fields (partial ownership)
            needs_adoption = (
                (managed_by != 'Helm') or
                (managed_by == 'Helm' and not helm_owns_subjects)
            )
            
            if needs_adoption:
                if managed_by and managed_by != 'Helm':
                    self.logger.warning(
                        f"ClusterRoleBinding {binding_name} is managed by '{managed_by}' (not Helm). "
                        f"Attempting to adopt it for Helm management."
                    )
                    if not live:
                        self.console.print(
                            f"[yellow]⚠[/yellow] ClusterRoleBinding {binding_name} managed by '{managed_by}' - adopting for Helm"
                        )
                elif managed_by == 'Helm' and not helm_owns_subjects:
                    self.logger.warning(
                        f"ClusterRoleBinding {binding_name} has Helm metadata but fields owned by other manager. "
                        f"Forcing field ownership transfer to Helm."
                    )
                    if not live:
                        self.console.print(
                            f"[yellow]⚠[/yellow] ClusterRoleBinding {binding_name} has partial Helm ownership - forcing full adoption"
                        )
                
                self.logger.info(f"Adopting ClusterRoleBinding {binding_name} for Helm management (release={release_name}, namespace={namespace})")
                
                # Update labels
                if not labels:
                    labels = {}
                labels['app.kubernetes.io/managed-by'] = 'Helm'
                
                # CRITICAL: Remove OLM label if present to prevent future conflicts
                if 'olm.managed' in labels:
                    self.logger.info(f"Removing 'olm.managed' label from ClusterRoleBinding {binding_name}")
                    del labels['olm.managed']
                    if not live:
                        self.console.print(f"[yellow]ℹ[/yellow] Removed OLM label from ClusterRoleBinding {binding_name}")
                
                # Update annotations
                if not annotations:
                    annotations = {}
                annotations['meta.helm.sh/release-name'] = release_name
                annotations['meta.helm.sh/release-namespace'] = namespace
                
                # Patch the ClusterRoleBinding using Server-Side Apply to force field manager ownership
                binding.metadata.labels = labels  # type: ignore
                binding.metadata.annotations = annotations  # type: ignore
                
                try:
                    # Use the Kubernetes API client directly with Server-Side Apply
                    # We need to use the raw API with the correct content-type header
                    from kubernetes import client as k8s_client
                    
                    # Update the ClusterRoleBinding object with new metadata
                    binding.metadata.labels = labels  # type: ignore
                    binding.metadata.annotations = annotations  # type: ignore
                    
                    # Get the API client
                    api_client = api.api_client
                    
                    # Prepare the request with SSA headers
                    # Server-Side Apply requires application/apply-patch+yaml content type
                    # and fieldManager and force query parameters
                    path = f"/apis/rbac.authorization.k8s.io/v1/clusterrolebindings/{binding_name}"
                    query_params = [
                        ('fieldManager', 'helm-adoption-script'),
                        ('force', 'true')  # Force conflicts - take ownership from other managers
                    ]
                    
                    # Convert the ClusterRoleBinding to dict for patching
                    body = api_client.sanitize_for_serialization(binding)
                    
                    # Make the PATCH request with SSA
                    response = api_client.call_api(
                        path,
                        'PATCH',
                        query_params=query_params,
                        body=body,
                        _preload_content=False,
                        _return_http_data_only=True,
                        header_params={'Content-Type': 'application/apply-patch+yaml'}
                    )
                    
                    self.logger.info(f"Successfully adopted ClusterRoleBinding {binding_name} for Helm management using SSA")
                    if not live:
                        self.console.print(f"[green]✓[/green] Adopted ClusterRoleBinding {binding_name} for Helm management")
                    return True
                    
                except Exception as e:
                    self.logger.error(f"Failed to patch ClusterRoleBinding {binding_name} with SSA: {e}")
                    if not live:
                        self.console.print(f"[yellow]⚠[/yellow] Could not adopt ClusterRoleBinding {binding_name}: {str(e)}")
                    # Return True anyway - let Helm try with its own conflict resolution
                    return True
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error handling ClusterRoleBinding conflicts for {binding_name}: {e}")
            # Return True to continue - let Helm handle it
            return True
    
    def _handle_crd_conflicts(self,
                             crd_name: str,
                             release_name: str,
                             namespace: str,
                             live=None) -> bool:
        """
        Handle CRD ownership and metadata conflicts.
        
        Addresses:
        - CRDs managed by OLM/catalog that conflict with Helm
        - Missing Helm metadata annotations
        - Incorrect managed-by labels
        
        Args:
            crd_name: Name of the CRD
            release_name: Helm release name
            namespace: Target namespace
            live: Optional Live display
            
        Returns:
            True if CRD conflicts were resolved
        """
        try:
            from kubernetes import client
            from kubernetes.client.rest import ApiException
            
            api = client.ApiextensionsV1Api()
            
            # Check if CRD exists
            try:
                crd = api.read_custom_resource_definition(name=crd_name)
            except ApiException as e:
                if e.status == 404:
                    # CRD doesn't exist - no conflict
                    return True
                raise
            
            # Check CRD ownership metadata
            if not crd.metadata:  # type: ignore
                return True
                
            labels = crd.metadata.labels or {}  # type: ignore
            annotations = crd.metadata.annotations or {}  # type: ignore
            
            managed_by = labels.get('app.kubernetes.io/managed-by', '')
            has_helm_release = 'meta.helm.sh/release-name' in annotations
            has_helm_namespace = 'meta.helm.sh/release-namespace' in annotations
            
            # If CRD is already managed by Helm with correct metadata, no action needed
            if managed_by == 'Helm' and has_helm_release and has_helm_namespace:
                # Only log when not using live display
                if not live:
                    self.logger.debug(f"CRD {crd_name} already has correct Helm metadata")
                return True
            
            # CRD exists but not managed by Helm or has incorrect metadata
            if managed_by and managed_by != 'Helm':
                self.logger.warning(
                    f"CRD {crd_name} is managed by '{managed_by}' (not Helm). "
                    f"Attempting to adopt it for Helm management."
                )
                if not live:
                    self.console.print(
                        f"[yellow]⚠[/yellow] CRD {crd_name} managed by '{managed_by}' - adopting for Helm"
                    )
            
            # Add/update Helm metadata to adopt the CRD
            if not has_helm_release or not has_helm_namespace:
                self.logger.info(f"Adding Helm metadata to CRD {crd_name} (release={release_name}, namespace={namespace})")
                
                # Update labels
                if not labels:
                    labels = {}
                labels['app.kubernetes.io/managed-by'] = 'Helm'
                
                # CRITICAL: Remove OLM label if present to prevent future conflicts
                if 'olm.managed' in labels:
                    self.logger.info(f"Removing 'olm.managed' label from CRD {crd_name}")
                    del labels['olm.managed']
                    if not live:
                        self.console.print(f"[yellow]ℹ[/yellow] Removed OLM label from CRD {crd_name}")
                
                # Update annotations
                if not annotations:
                    annotations = {}
                annotations['meta.helm.sh/release-name'] = release_name
                annotations['meta.helm.sh/release-namespace'] = namespace
                
                # Patch the CRD
                crd.metadata.labels = labels  # type: ignore
                crd.metadata.annotations = annotations  # type: ignore
                
                try:
                    api.patch_custom_resource_definition(
                        name=crd_name,
                        body=crd
                    )
                    self.logger.info(f"Successfully adopted CRD {crd_name} for Helm management")
                    if not live:
                        self.console.print(f"[green]✓[/green] Adopted CRD {crd_name} for Helm management")
                    return True
                except ApiException as e:
                    self.logger.error(f"Failed to patch CRD {crd_name}: {e}")
                    if not live:
                        self.console.print(f"[yellow]⚠[/yellow] Could not adopt CRD {crd_name}: {e.reason}")
                    # Return True anyway - let Helm try with its own conflict resolution
                    return True
            
            return True
            
        except Exception as e:
            if not live:
                self.logger.error(f"Error handling CRD conflicts for {crd_name}: {e}")
            # Don't fail the deployment - let Helm handle it
            return True
    
    
    def _check_packaged_charts(self, operators: List[str]) -> List[str]:
        """
        Check if required packaged Helm charts exist.
        
        Args:
            operators: List of operator types to check
            
        Returns:
            List of missing package filenames
        """
        missing = []
        
        for operator_type in operators:
            if operator_type not in self.OPERATOR_CHARTS:
                continue
                
            op_config = self.OPERATOR_CHARTS[operator_type]
            
            # Check if this operator requires a packaged chart
            if op_config.get("requires_package", False):
                if "packaged_file" in op_config:
                    package_path = self.chart_base_path / op_config["packaged_file"]
                    if not package_path.exists():
                        missing.append(op_config["packaged_file"])
                        # Silent check - error will be displayed by prerequisite validation
        
        return missing
        try:
            # Try to list namespaces to verify connection
            self.kube.core_v1.list_namespace(limit=1)
            return True
        except Exception as e:
            self.logger.debug(f"Kubernetes API connection check failed: {e}")
            return False
