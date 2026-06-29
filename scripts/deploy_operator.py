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

import asyncio
import logging
import os
import toml
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List

import typer
import questionary
from rich import print
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, MofNCompleteColumn, \
    TimeElapsedColumn
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text
from typing_extensions import Annotated

from helper_scripts.deploy import deploy as d
from helper_scripts.gather import gather as g
from helper_scripts.gather import silent_gather as sg
from helper_scripts.helm.helm_deployer import HelmDeployer, HelmChartSource
from helper_scripts.utilities.interface import (
    clear, display_issues, display_prereq_passed, deploy_details, deploy_details_multi_operator,
    display_prereq_validation_table,
    display_config_validation_errors, display_operator_selection, display_operator_summary,
    create_deployment_header, create_phase_header, create_deployment_footer,
    display_toml_syntax_error,
)
from helper_scripts.utilities.questionary_utils import handle_cancelled_prompt
from helper_scripts.utilities.utilities import prereq_checks, read_version_toml, create_deployment_info, \
    create_version_info
from helper_scripts.utilities.config_models import validate_deploy_operator_config
from helper_scripts.utilities.operator_config import (
    OperatorType, get_all_operators, get_operator_metadata,
    validate_operator_dependencies, get_descriptor_files, calculate_total_resources
)
from helper_scripts.utilities.deployment_progress import (
    create_deployment_progress,
    display_deployment_complete,
    DeploymentPhase,
    DeploymentStep
)
from helper_scripts.utilities.kubernetes_utilites import KubernetesUtilities

__version__ = "26.0.0"

app = typer.Typer()
state = {
    "verbose": False,
    "logger": logging,
    "dev": False,
    "setup": None,
    "silent": False,
    "version": None,
    "dryrun": False,
    "validate": True,
    "tls_verify": True,
    "force": False,
    "helm_chart_source": "packaged"
}

console = Console(record=True)


def version_callback(value: bool):
    if value:
        print(f"IBM Content Cortex Deploy Operator CLI: {__version__}")
        raise typer.Exit()


def display_mode_version(mode: str, description: str):
    """
    Display the mode and version of the script with active flags in a modern, visually appealing format.
    
    Args:
        mode: The operation mode (e.g., "Deploy IBM Content Cortex Operator")
        description: Description of what the script does
    """
    clear(console)
    print()
    
    # Create header table with version and mode info
    header_table = Table.grid(padding=(0, 2))
    header_table.add_column(style="cyan", justify="left")
    header_table.add_column(style="white", justify="left")
    
    # Add version and mode rows
    header_table.add_row("Version:", f"[bold green]{__version__}[/bold green]")
    header_table.add_row("Mode:", f"[bold yellow]{mode}[/bold yellow]")
    header_table.add_row("", f"[dim]{description}[/dim]")
    
    # Add Helm chart source if available
    if "helm_chart_source" in state:
        chart_source = state["helm_chart_source"]
        # Format chart source display
        source_display = {
            "github": "📦 GitHub (Public)",
            "packaged": "📁 Packaged (Local)",
            "local": "📂 Local (Unpacked)",
            "public": "🌐 Public Helm Repo",
            "url": "🔗 Direct URL"
        }.get(chart_source, chart_source)
        
        # Add dev mode indicator if using GitHub in dev mode
        if chart_source == "github" and state.get("dev"):
            source_display = "📦 GitHub (Internal Dev)"
        
        header_table.add_row("", "")  # Empty row for spacing
        header_table.add_row("Chart Source:", f"[bold cyan]{source_display}[/bold cyan]")
    
    # Collect active flags
    active_flags = []
    if state["dryrun"]:
        active_flags.append("🔍 Dry Run")
        state["logger"].info("Dry Run is enabled")
    
    if state["dev"]:
        active_flags.append("🔧 Development Mode")
        state["logger"].info("Development Mode is enabled")
    
    if state["silent"]:
        active_flags.append("🤫 Silent Mode")
        state["logger"].info("Silent Mode is enabled")
    
    if not state["validate"]:
        active_flags.append("⚠️  Validation Disabled")
        state["logger"].info("Validation of entitlement key and private registry is disabled")
    
    if not state["tls_verify"]:
        active_flags.append("🔓 TLS Verification Disabled")
        state["logger"].info("TLS Verification Disabled for Podman Operations")
    
    # Add active flags if any
    if active_flags:
        header_table.add_row("", "")  # Empty row for spacing
        for flag in active_flags:
            header_table.add_row("", f"[bold magenta]{flag}[/bold magenta]")
    
    # Log script details
    log_msg = f"Version: {__version__}\nMode: {mode}\n{description}"
    if active_flags:
        log_msg += "\n\n" + "\n".join(active_flags)
    state["logger"].info(f"Script details: \n{log_msg}")
    
    # Create the main panel with modern styling
    print(Panel(
        header_table,
        title="[bold white]🚀 IBM Content Cortex Deploy Operator CLI[/bold white]",
        border_style="bright_blue",
        padding=(1, 2),
        expand=False
    ))
    print()


def setup_logger(file_log_level):
    # Create a logger object
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Setup console logger
    shell_handler = RichHandler(show_time=False, show_path=False)
    shell_handler.setLevel(file_log_level)
    formatter_rich = logging.Formatter("%(message)s")
    shell_handler.setFormatter(formatter_rich)

    # Setup file logger
    file_handler = logging.FileHandler("deployoperator.log")
    file_handler.setLevel(logging.DEBUG)
    formatter_file = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)-100s - %(filename)s:%(lineno)d", "%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(formatter_file)

    # Add handlers to the logger
    logger.addHandler(shell_handler)
    logger.addHandler(file_handler)

    return logger


def detect_existing_installations(namespace: str, logger, console) -> dict:
    """
    Detect existing operator installations (both OLM and Helm-based).
    
    Args:
        namespace: Target namespace to check
        logger: Logger instance
        console: Rich console instance
        
    Returns:
        Dictionary with detection results containing:
        - has_olm: bool
        - has_helm: bool
        - olm_resources: dict with CSVs and catalogs
        - helm_releases: list of detected Helm releases
        - operator_deployment: dict with deployment details
    """
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.live import Live
    import subprocess
    import json
    
    k8s_utils = KubernetesUtilities(logger)
    
    result = {
        'has_olm': False,
        'has_helm': False,
        'has_yaml': False,
        'olm_resources': {
            'csvs': [],
            'catalogs': [],
            'additional_catalogs': []
        },
        'helm_releases': [],
        'operator_deployment': None,
        'deployment_type': None
    }
    
    # Create progress display
    progress_table = Table.grid(padding=(0, 2))
    progress_table.add_column(style="cyan", width=40)
    progress_table.add_column(style="white")
    
    with Live(progress_table, console=console, refresh_per_second=10) as live:
        # Step 1: Check for operator deployment
        progress_table = Table.grid(padding=(0, 2))
        progress_table.add_column(style="cyan", width=40)
        progress_table.add_column(style="white")
        progress_table.add_row(
            "[bold cyan]🔍 Detecting System State[/bold cyan]",
            "[dim](1/4)[/dim]"
        )
        progress_table.add_row("", "")
        progress_table.add_row("[cyan]Checking:[/cyan]", "[white]Operator Deployment[/white]")
        live.update(progress_table)
        
        try:
            operator_details = k8s_utils.get_operator_details(namespace, deployment_name='ibm-fncm-operator')
            if operator_details:
                result['operator_deployment'] = operator_details
                deployment_type = operator_details.get('type', 'YAML')
                result['deployment_type'] = deployment_type
                
                # Set has_yaml flag if deployment type is YAML
                if deployment_type == 'YAML':
                    result['has_yaml'] = True
                    logger.info(f"Found YAML-based operator deployment: {operator_details.get('deployment', 'unknown')}")
                else:
                    logger.info(f"Found operator deployment: {operator_details.get('deployment', 'unknown')}")
        except Exception as e:
            logger.debug(f"No operator deployment found: {e}")
        
        # Step 2: Detect OLM resources
        progress_table = Table.grid(padding=(0, 2))
        progress_table.add_column(style="cyan", width=40)
        progress_table.add_column(style="white")
        progress_table.add_row(
            "[bold cyan]🔍 Detecting System State[/bold cyan]",
            "[dim](2/4)[/dim]"
        )
        progress_table.add_row("", "")
        progress_table.add_row("[cyan]Checking:[/cyan]", "[white]OLM Resources[/white]")
        live.update(progress_table)
        
        try:
            # Only detect OLM resources for Content Cortex operators
            csv_prefixes = [
                "ibm-fncm-operator",
                "ibm-content-operator",
                "ibm-ccx-ai-services-operator",
                "ibm-licensing-operator",
                "ibm-usage-metering"
            ]
            olm_resources = k8s_utils.detect_olm_resources(namespace, csv_prefixes=csv_prefixes)
            if olm_resources['has_olm']:
                result['has_olm'] = True
                result['olm_resources'] = olm_resources
                logger.info(f"Detected Content Cortex OLM resources: {len(olm_resources['csvs'])} CSVs, {len(olm_resources['catalogs'])} catalogs")
        except Exception as e:
            logger.debug(f"Error detecting OLM resources: {e}")
        
        # Step 3: Check for Helm releases
        progress_table = Table.grid(padding=(0, 2))
        progress_table.add_column(style="cyan", width=40)
        progress_table.add_column(style="white")
        progress_table.add_row(
            "[bold cyan]🔍 Detecting System State[/bold cyan]",
            "[dim](3/4)[/dim]"
        )
        progress_table.add_row("", "")
        progress_table.add_row("[cyan]Checking:[/cyan]", "[white]Helm Releases[/white]")
        live.update(progress_table)
        
        # Check for all possible operator Helm releases
        operator_release_names = [
            'ibm-content-operator',
            'ibm-ccx-ai-services-operator',
            'ibm-usage-metering',
            'ibm-licensing-cluster-scoped'
        ]
        
        for release_name in operator_release_names:
            try:
                # Check in primary namespace
                cmd_result = subprocess.run(
                    ["helm", "list", "-n", namespace, "-o", "json"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                
                releases = json.loads(cmd_result.stdout)
                for release in releases:
                    if release.get("name") == release_name:
                        result['has_helm'] = True
                        result['helm_releases'].append({
                            'name': release_name,
                            'namespace': namespace,
                            'chart': release.get('chart', ''),
                            'status': release.get('status', ''),
                            'version': release.get('chart', '').split('-')[-1] if release.get('chart') else 'unknown'
                        })
                        logger.info(f"Found Helm release: {release_name} in {namespace}")
                
                # Also check ibm-licensing namespace for licensing operator
                if release_name == 'ibm-licensing-cluster-scoped':
                    cmd_result = subprocess.run(
                        ["helm", "list", "-n", "ibm-licensing", "-o", "json"],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    releases = json.loads(cmd_result.stdout)
                    for release in releases:
                        if release.get("name") == release_name:
                            result['has_helm'] = True
                            result['helm_releases'].append({
                                'name': release_name,
                                'namespace': 'ibm-licensing',
                                'chart': release.get('chart', ''),
                                'status': release.get('status', ''),
                                'version': release.get('chart', '').split('-')[-1] if release.get('chart') else 'unknown'
                            })
                            logger.info(f"Found Helm release: {release_name} in ibm-licensing")
            except Exception as e:
                logger.debug(f"Error checking Helm release {release_name}: {e}")
        
        # Step 4: Complete
        progress_table = Table.grid(padding=(0, 2))
        progress_table.add_column(style="cyan", width=40)
        progress_table.add_column(style="white")
        progress_table.add_row(
            "[bold cyan]🔍 Detecting System State[/bold cyan]",
            "[dim](4/4)[/dim]"
        )
        progress_table.add_row("", "")
        progress_table.add_row("[cyan]Status:[/cyan]", "[green]Detection Complete[/green]")
        live.update(progress_table)
    
    return result

def detect_operator_installation_type(namespace: str, k8s_utils, logger) -> dict:
    """
    Detect the type of FNCM operator installation (OLM, YAML, or both).
    
    Args:
        namespace: Target namespace to check
        k8s_utils: KubernetesUtilities instance
        logger: Logger instance
        
    Returns:
        Dictionary with detection results:
        {
            'has_olm': bool,
            'has_yaml': bool,
            'deployment_name': str or None,
            'deployment_details': dict or None
        }
    """
    result = {
        'has_olm': False,
        'has_yaml': False,
        'deployment_name': None,
        'deployment_details': None
    }
    
    # Check for FNCM operator deployment
    operator_name = 'ibm-fncm-operator'
    
    try:
        logger.info(f"Checking for operator deployment: {operator_name}")
        operator_details = k8s_utils.get_operator_details(namespace, deployment_name=operator_name)
        
        if operator_details:
            logger.info(f"Found operator deployment: {operator_name}")
            result['deployment_details'] = operator_details
            result['deployment_name'] = operator_name
            
            # Check deployment type from operator_details
            deployment_type = operator_details.get('type', 'YAML')
            
            if deployment_type == 'OLM':
                result['has_olm'] = True
                logger.info(f"Detected OLM-based operator: {operator_name}")
            else:
                result['has_yaml'] = True
                logger.info(f"Detected YAML-based operator: {operator_name}")
        else:
            logger.info("No existing FNCM operator deployment detected")
            
    except Exception as e:
        logger.debug(f"No operator deployment found with name {operator_name}: {e}")
    
    return result


def cleanup_yaml_deployment(namespace: str, logger, console, tracker=None, live=None, deployment_name: str | None = None) -> bool:
    """
    Remove YAML-based FNCM operator deployment (non-OLM installation).
    
    This function removes FNCM operator resources that were installed via YAML manifests,
    including the deployment and RBAC resources.
    CRDs and Custom Resources are preserved. License Service is not affected.
    
    Args:
        namespace: Target namespace
        logger: Logger instance
        console: Rich console instance
        tracker: Optional deployment tracker for live updates
        live: Optional live display context
        deployment_name: Name of the operator deployment to remove (default: ibm-fncm-operator)
        
    Returns:
        True if cleanup succeeded
    """
    logger.info("Starting YAML-based FNCM operator deployment cleanup")
    
    k8s_utils = KubernetesUtilities(logger)
    
    if not deployment_name:
        deployment_name = 'ibm-fncm-operator'
    
    try:
        current_progress = 10
        
        if tracker and live:
            tracker.update_cluster_setup(
                task_name="Detecting YAML-based FNCM operator deployment",
                progress=int(current_progress),
                phase=DeploymentPhase.PREPARING
            )
            live.update(tracker.create_progress_display())
        
        # Check if deployment exists
        try:
            operator_details = k8s_utils.get_operator_details(namespace, deployment_name=deployment_name)
            if not operator_details:
                logger.info("No YAML-based operator deployment found")
                if tracker and live:
                    tracker.update_cluster_setup(
                        task_name="No YAML-based FNCM operator found",
                        progress=100,
                        phase=DeploymentPhase.PREPARING
                    )
                    live.update(tracker.create_progress_display())
                return True
            logger.info(f"Found YAML-based operator deployment: {deployment_name}")
        except Exception:
            logger.info("No YAML-based operator deployment found")
            if tracker and live:
                tracker.update_cluster_setup(
                    task_name="No YAML-based FNCM operator found",
                    progress=100,
                    phase=DeploymentPhase.PREPARING
                )
                live.update(tracker.create_progress_display())
            return True
        
        current_progress = 20
        
        # 1. Delete operator deployment
        if tracker and live:
            tracker.update_cluster_setup(
                task_name=f"Removing YAML FNCM operator deployment: {deployment_name}",
                progress=int(current_progress),
                phase=DeploymentPhase.PREPARING
            )
            live.update(tracker.create_progress_display())
        
        try:
            k8s_utils.delete_operator_deployment(namespace=namespace, name=deployment_name)
            logger.info(f"Deleted operator deployment: {deployment_name}")
        except Exception as e:
            logger.warning(f"Error deleting operator deployment {deployment_name}: {e}")
        
        current_progress = 50
        
        # 2. Delete RBAC resources (role, rolebinding, service account)
        if tracker and live:
            tracker.update_cluster_setup(
                task_name=f"Removing FNCM RBAC resources for {deployment_name}",
                progress=int(current_progress),
                phase=DeploymentPhase.PREPARING
            )
            live.update(tracker.create_progress_display())
        
        try:
            k8s_utils.delete_role_binding(namespace=namespace, name=deployment_name)
            logger.info(f"Deleted role binding: {deployment_name}")
        except Exception as e:
            logger.warning(f"Error deleting role binding {deployment_name}: {e}")
        
        try:
            k8s_utils.delete_role(namespace=namespace, name=deployment_name)
            logger.info(f"Deleted role: {deployment_name}")
        except Exception as e:
            logger.warning(f"Error deleting role {deployment_name}: {e}")
        
        try:
            k8s_utils.delete_service_account(namespace=namespace, name=deployment_name)
            logger.info(f"Deleted service account: {deployment_name}")
        except Exception as e:
            logger.warning(f"Error deleting service account {deployment_name}: {e}")
        
        current_progress = 80
        
        # Note: We preserve CRDs and Custom Resources - only remove operator deployment and RBAC
        
        logger.info("YAML-based FNCM operator cleanup completed successfully")
        
        if tracker and live:
            tracker.update_cluster_setup(
                task_name="YAML FNCM operator cleanup complete",
                progress=90,
                phase=DeploymentPhase.PREPARING
            )
            live.update(tracker.create_progress_display())
        
        return True
        
    except Exception as e:
        logger.error(f"YAML FNCM operator cleanup failed: {e}")
        
        if tracker and live:
            tracker.update_cluster_setup(
                task_name=f"YAML FNCM cleanup failed: {str(e)[:50]}",
                progress=50,
                phase=DeploymentPhase.FAILED
            )
            live.update(tracker.create_progress_display())
        
        return False


def cleanup_olm_deployment(namespace: str, logger, console, tracker=None, live=None, additional_namespaces=None, remove_licensing_olm=False) -> bool:
    """
    Remove old OLM-based FNCM operator deployment including catalog and subscription.
    
    This function removes FNCM operator OLM resources. License Service OLM resources
    are only removed if remove_licensing_olm=True.
    
    Args:
        namespace: Primary target namespace
        logger: Logger instance
        console: Rich console instance
        tracker: Optional deployment tracker for live updates
        live: Optional live display context
        additional_namespaces: Optional list of additional namespaces to check (e.g., ['ibm-licensing'])
        remove_licensing_olm: Whether to remove IBM Licensing OLM installation (default: False)
        
    Returns:
        True if cleanup succeeded
    """
    logger.info("Starting OLM FNCM operator deployment cleanup")
    
    k8s_utils = KubernetesUtilities(logger)
    
    # Build list of namespaces to check
    namespaces_to_check = [namespace]
    if additional_namespaces:
        namespaces_to_check.extend(additional_namespaces)
    
    # Detect OLM resources first
    logger.info(f"Detecting OLM resources in namespaces: {', '.join(namespaces_to_check)}")
    
    if tracker and live:
        tracker.update_cluster_setup(
            task_name=f"Detecting FNCM OLM resources in {len(namespaces_to_check)} namespace(s)",
            progress=10,
            phase=DeploymentPhase.PREPARING
        )
        live.update(tracker.create_progress_display())
    
    # Collect OLM resources from all namespaces
    all_olm_resources = {
        "csvs": [],
        "catalogs": [],
        "additional_catalogs": [],
        "has_olm": False,
        "namespaces": {}
    }
    
    for ns in namespaces_to_check:
        logger.info(f"Checking namespace: {ns}")
        ns_resources = k8s_utils.detect_olm_resources(ns)
        
        if ns_resources["has_olm"]:
            all_olm_resources["has_olm"] = True
            all_olm_resources["namespaces"][ns] = ns_resources
            
            # Add namespace info to each resource
            for csv in ns_resources["csvs"]:
                csv["cleanup_namespace"] = ns
                all_olm_resources["csvs"].append(csv)
            
            for catalog in ns_resources["catalogs"]:
                catalog["cleanup_namespace"] = ns
                all_olm_resources["catalogs"].append(catalog)
            
            for catalog in ns_resources["additional_catalogs"]:
                all_olm_resources["additional_catalogs"].append(catalog)
    
    olm_resources = all_olm_resources
    
    # Log detected resources
    if olm_resources["has_olm"]:
        csv_count = len(olm_resources["csvs"])
        catalog_count = len(olm_resources["catalogs"])
        external_catalog_count = len(olm_resources["additional_catalogs"])
        
        logger.info(f"Detected {csv_count} CSV(s), {catalog_count} CatalogSource(s), {external_catalog_count} external CatalogSource(s)")
        
        if tracker and live:
            tracker.update_cluster_setup(
                task_name=f"FNCM OLM cleanup required: {csv_count} CSV(s), {catalog_count + external_catalog_count} CatalogSource(s)",
                progress=20,
                phase=DeploymentPhase.PREPARING
            )
            live.update(tracker.create_progress_display())
    else:
        logger.info("No OLM resources detected")
        if tracker and live:
            tracker.update_cluster_setup(
                task_name="No FNCM OLM resources detected",
                progress=20,
                phase=DeploymentPhase.PREPARING
            )
            live.update(tracker.create_progress_display())
        return True  # Nothing to clean up
    
    try:
        current_progress = 30
        progress_increment = 60 / max(1, (len(olm_resources["csvs"]) + len(olm_resources["catalogs"]) +
                                          len(olm_resources["additional_catalogs"]) + 4))
        
        # 1. Delete ClusterServiceVersions (CSVs) - only FNCM and optionally Licensing
        fncm_csv_prefixes = ["ibm-fncm-operator"]
        licensing_csv_prefixes = ["ibm-licensing-operator"]
        
        if olm_resources["csvs"]:
            for csv in olm_resources["csvs"]:
                csv_name = csv["name"]
                csv_ns = csv.get("cleanup_namespace", namespace)
                
                # Determine if we should delete this CSV
                should_delete = False
                csv_type = "unknown"
                
                # Check if CSV name starts with any FNCM prefix
                for prefix in fncm_csv_prefixes:
                    if csv_name.startswith(prefix):
                        should_delete = True
                        csv_type = "fncm-operator"
                        break
                
                # Check if CSV name starts with any Licensing prefix
                if not should_delete:
                    for prefix in licensing_csv_prefixes:
                        if csv_name.startswith(prefix):
                            if remove_licensing_olm:
                                should_delete = True
                                csv_type = "IBM Licensing"
                            else:
                                logger.info(f"Preserving IBM Licensing CSV '{csv_name}' in {csv_ns}")
                            break
                
                if should_delete:
                    if tracker and live:
                        tracker.update_cluster_setup(
                            task_name=f"Removing {csv_type} CSV: {csv_name[:35]}... ({csv_ns})",
                            progress=int(current_progress),
                            phase=DeploymentPhase.PREPARING
                        )
                        live.update(tracker.create_progress_display())
                    
                    try:
                        k8s_utils.delete_clusterserviceversion(csv_name=csv_name, namespace=csv_ns)
                        logger.info(f"Deleted {csv_type} CSV: {csv_name} from {csv_ns}")
                    except Exception as e:
                        logger.warning(f"Error deleting CSV {csv_name} from {csv_ns}: {e}")
                elif csv_type == "unknown":
                    logger.info(f"Skipping non-target CSV '{csv_name}' in {csv_ns}")
                
                current_progress += progress_increment
        else:
            logger.info("No CSVs found to delete")
        
        # 2. Delete subscriptions based on configuration
        fncm_subscription_names = ["ibm-fncm-operator"]
        licensing_subscription_names = ["ibm-licensing-operator", "ibm-licensing-operator-app"]
        
        for ns in namespaces_to_check:
            if tracker and live:
                tracker.update_cluster_setup(
                    task_name=f"Removing FNCM operator subscription ({ns})",
                    progress=int(current_progress),
                    phase=DeploymentPhase.PREPARING
                )
                live.update(tracker.create_progress_display())
            
            try:
                subscription_details = k8s_utils.get_subscription(namespace=ns)
                if subscription_details:
                    subscription_name = subscription_details.get("name", "")
                    
                    # Determine if we should delete this subscription
                    should_delete = False
                    subscription_type = "unknown"
                    
                    if subscription_name in fncm_subscription_names:
                        should_delete = True
                        subscription_type = "fncm-operator"
                    elif subscription_name in licensing_subscription_names:
                        if remove_licensing_olm:
                            should_delete = True
                            subscription_type = "IBM Licensing"
                        else:
                            logger.info(f"Preserving IBM Licensing subscription '{subscription_name}' in {ns}")
                    
                    if should_delete:
                        k8s_utils.delete_subscription(namespace=ns, name=subscription_name)
                        logger.info(f"Deleted {subscription_type} subscription: {subscription_name} from {ns}")
                    elif subscription_type == "unknown":
                        logger.info(f"Skipping non-target subscription '{subscription_name}' in {ns}")
                else:
                    logger.info(f"No subscription found in {ns}")
            except Exception as e:
                logger.warning(f"Error deleting subscription from {ns}: {e}")
        
        current_progress += progress_increment
        
        # 3. Delete catalog sources based on configuration
        fncm_catalog_names = ["ibm-fncm-operator-catalog"]
        licensing_catalog_names = ["ibm-licensing-catalog", "ibm-licensing-operator-catalog"]
        
        if olm_resources["catalogs"]:
            for catalog in olm_resources["catalogs"]:
                catalog_name = catalog["name"]
                catalog_ns = catalog.get("cleanup_namespace", catalog["namespace"])
                
                # Determine if we should delete this catalog
                should_delete = False
                catalog_type = "unknown"
                
                if catalog_name in fncm_catalog_names:
                    should_delete = True
                    catalog_type = "fncm-operator"
                elif catalog_name in licensing_catalog_names:
                    if remove_licensing_olm:
                        should_delete = True
                        catalog_type = "IBM Licensing"
                    else:
                        logger.info(f"Preserving IBM Licensing catalog '{catalog_name}' in {catalog_ns}")
                
                if should_delete:
                    if tracker and live:
                        tracker.update_cluster_setup(
                            task_name=f"Removing {catalog_type} catalog: {catalog_name[:30]}... ({catalog_ns})",
                            progress=int(current_progress),
                            phase=DeploymentPhase.PREPARING
                        )
                        live.update(tracker.create_progress_display())
                    
                    try:
                        k8s_utils.delete_catalog_source(namespace=catalog_ns, name=catalog_name)
                        logger.info(f"Deleted {catalog_type} catalog source: {catalog_name} from {catalog_ns}")
                    except Exception as e:
                        logger.warning(f"Error deleting catalog source {catalog_name} from {catalog_ns}: {e}")
                elif catalog_type == "unknown":
                    logger.info(f"Skipping non-target catalog '{catalog_name}' in {catalog_ns}")
                
                current_progress += progress_increment
        
        # 4. Skip deletion of external catalog sources (e.g., in openshift-marketplace)
        # External catalogs are preserved to avoid affecting other operators
        if olm_resources["additional_catalogs"]:
            logger.info(f"Skipping {len(olm_resources['additional_catalogs'])} external catalog source(s) - preserving shared catalogs")
            for catalog in olm_resources["additional_catalogs"]:
                catalog_name = catalog["name"]
                catalog_ns = catalog["namespace"]
                logger.info(f"Preserving external catalog '{catalog_name}' in {catalog_ns}")
        
        # Fallback: Try common catalog names if none were detected (only in target namespaces)
        if not olm_resources["catalogs"]:
            if tracker and live:
                tracker.update_cluster_setup(
                    task_name="Checking for common operator catalogs",
                    progress=int(current_progress),
                    phase=DeploymentPhase.PREPARING
                )
                live.update(tracker.create_progress_display())
            
            # Only check target namespaces (not openshift-marketplace)
            all_check_ns = namespaces_to_check
            
            # Build list of catalogs to check based on configuration
            catalogs_to_check = list(fncm_catalog_names)
            if remove_licensing_olm:
                catalogs_to_check.extend(licensing_catalog_names)
            
            for cat_ns in all_check_ns:
                for cat_name in catalogs_to_check:
                    try:
                        k8s_utils.delete_catalog_source(namespace=cat_ns, name=cat_name)
                        logger.info(f"Deleted catalog source {cat_name} from {cat_ns}")
                    except Exception:
                        pass
        
        current_progress += progress_increment
        
        # 5. Delete operator deployments from all checked namespaces
        for ns in namespaces_to_check:
            if tracker and live:
                tracker.update_cluster_setup(
                    task_name=f"Removing FNCM operator deployment ({ns})",
                    progress=int(current_progress),
                    phase=DeploymentPhase.PREPARING
                )
                live.update(tracker.create_progress_display())
            
            try:
                k8s_utils.delete_operator_deployment(namespace=ns, name="ibm-fncm-operator")
                logger.info(f"Deleted operator deployment ibm-fncm-operator from {ns}")
            except Exception as e:
                logger.debug(f"No deployment ibm-fncm-operator found in {ns}: {e}")
        
        current_progress += progress_increment
        
        # 6. Delete RBAC resources from all checked namespaces
        for ns in namespaces_to_check:
            if tracker and live:
                tracker.update_cluster_setup(
                    task_name=f"Removing FNCM RBAC resources ({ns})",
                    progress=int(current_progress),
                    phase=DeploymentPhase.PREPARING
                )
                live.update(tracker.create_progress_display())
            
            try:
                # Try common operator names
                for op_name in ["ibm-fncm-operator", "ibm-licensing-operator"]:
                    try:
                        k8s_utils.delete_role_binding(namespace=ns, name=op_name)
                        k8s_utils.delete_role(namespace=ns, name=op_name)
                        k8s_utils.delete_service_account(namespace=ns, name=op_name)
                        logger.info(f"Deleted RBAC resources for {op_name} from {ns}")
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Error deleting RBAC resources from {ns}: {e}")
        
        logger.info("OLM FNCM operator cleanup completed successfully")
        
        if tracker and live:
            tracker.update_cluster_setup(
                task_name="FNCM OLM cleanup complete",
                progress=90,
                phase=DeploymentPhase.PREPARING
            )
            live.update(tracker.create_progress_display())
        
        return True
        
    except Exception as e:
        logger.error(f"OLM FNCM operator cleanup failed: {e}")
        
        if tracker and live:
            tracker.update_cluster_setup(
                task_name=f"FNCM OLM cleanup failed: {str(e)[:50]}",
                progress=50,
                phase=DeploymentPhase.FAILED
            )
            live.update(tracker.create_progress_display())
        
        return False



def display_system_dashboard(detection_results: dict, namespace: str, console, logger, operator_status: dict = None) -> None:
    """
    Display a comprehensive dashboard of the current system state using rich library.
    
    Args:
        detection_results: Results from detect_existing_installations
        namespace: Target namespace
        console: Rich console instance
        logger: Logger instance
        operator_status: Optional dict tracking operator installation status and versions
    """
    console.print()
    console.print()
    
    # Create main dashboard panel
    dashboard_content = []
    
    # System Overview Section with Operator Versions
    overview_table = Table(show_header=False, box=None, padding=(0, 2))
    overview_table.add_column(style="cyan bold", width=25)
    overview_table.add_column(style="white")
    
    overview_table.add_row("Target Namespace:", f"[cyan]{namespace}[/cyan]")
    
    # Determine overall status
    if detection_results['has_olm'] or detection_results['has_helm'] or detection_results['has_yaml']:
        status_icon = "✓"
        status_text = "[green]Existing Installation Detected[/green]"
    else:
        status_icon = "○"
        status_text = "[yellow]No Existing Installation[/yellow]"
    
    overview_table.add_row("Installation Status:", f"{status_icon} {status_text}")
    
    # Add operator status information for all 4 operators
    overview_table.add_row("", "")  # Spacer
    overview_table.add_row("[bold]Operator Status:[/bold]", "")
    
    # Define all operators we track
    all_operators = {
        'content': 'Content Operator',
        'ai-services': 'AI Services Operator',
        'licensing': 'Licensing Operator',
        'usage-metering': 'Usage Metering Operator'
    }
    
    # Show status for each operator
    if operator_status:
        for op_key, op_name in all_operators.items():
            if op_key in operator_status:
                op_info = operator_status[op_key]
                version = op_info.get('current_version', 'unknown')
                is_current = op_info.get('is_current', False)
                
                if is_current:
                    overview_table.add_row(f"  • {op_name}:", f"[green]✓ {version}[/green]")
                else:
                    overview_table.add_row(f"  • {op_name}:", f"[yellow]⚠ {version} (needs upgrade)[/yellow]")
            else:
                overview_table.add_row(f"  • {op_name}:", "[dim]○ Not installed[/dim]")
    else:
        # If no operator_status, fall back to showing detected releases
        if detection_results['has_helm'] and detection_results['helm_releases']:
            detected_ops = set()
            for release in detection_results['helm_releases']:
                if 'content' in release['name']:
                    overview_table.add_row(f"  • Content Operator:", f"[green]{release['version']}[/green]")
                    detected_ops.add('content')
                elif 'ai-services' in release['name']:
                    overview_table.add_row(f"  • AI Services Operator:", f"[green]{release['version']}[/green]")
                    detected_ops.add('ai-services')
                elif 'licensing' in release['name']:
                    overview_table.add_row(f"  • Licensing Operator:", f"[green]{release['version']}[/green]")
                    detected_ops.add('licensing')
                elif 'usage-metering' in release['name']:
                    overview_table.add_row(f"  • Usage Metering Operator:", f"[green]{release['version']}[/green]")
                    detected_ops.add('usage-metering')
            
            # Show not installed for operators not detected
            for op_key, op_name in all_operators.items():
                if op_key not in detected_ops:
                    overview_table.add_row(f"  • {op_name}:", "[dim]○ Not installed[/dim]")
        else:
            # No operators installed
            for op_name in all_operators.values():
                overview_table.add_row(f"  • {op_name}:", "[dim]○ Not installed[/dim]")
    
    dashboard_content.append(Panel(
        overview_table,
        title="[bold white]📊 System Overview[/bold white]",
        border_style="cyan",
        padding=(1, 2)
    ))
    
    # Installation Details Section
    details_table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
    details_table.add_column("Type", style="cyan", width=20)
    details_table.add_column("Status", style="white", width=15)
    details_table.add_column("Details", style="dim", width=60)
    
    # OLM Installation - filter to only show Content Cortex operators
    if detection_results['has_olm']:
        olm_csvs = detection_results['olm_resources']['csvs']
        olm_catalogs = detection_results['olm_resources']['catalogs']
        
        # Filter catalog sources to only count Content Cortex operators
        content_cortex_catalog_prefixes = [
            'ibm-fncm-operator',
            'ibm-content-operator',
            'ibm-ccx-ai-services-operator',
            'ibm-licensing-operator',
            'ibm-usage-metering'
        ]
        
        filtered_catalogs = [
            catalog for catalog in olm_catalogs
            if any(catalog['name'].startswith(prefix) for prefix in content_cortex_catalog_prefixes)
        ]
        
        # Only show OLM as detected if we have relevant CSVs or filtered catalogs
        if len(olm_csvs) > 0 or len(filtered_catalogs) > 0:
            olm_details = f"{len(olm_csvs)} CSV(s), {len(filtered_catalogs)} CatalogSource(s)"
            details_table.add_row(
                "OLM-based",
                "[green]✓ Detected[/green]",
                olm_details
            )
        else:
            # No relevant OLM resources found after filtering
            details_table.add_row(
                "OLM-based",
                "[dim]Not found[/dim]",
                ""
            )
    else:
        details_table.add_row(
            "OLM-based",
            "[dim]Not found[/dim]",
            ""
        )
    
    # Helm Installation
    if detection_results['has_helm']:
        helm_count = len(detection_results['helm_releases'])
        helm_details = f"{helm_count} Helm release(s) found"
        details_table.add_row(
            "Helm-based",
            "[green]✓ Detected[/green]",
            helm_details
        )
    else:
        details_table.add_row(
            "Helm-based",
            "[dim]Not found[/dim]",
            ""
        )
    
    # YAML-based Deployment (only show if deployment exists AND is not OLM)
    if detection_results['operator_deployment']:
        deploy_type = detection_results['deployment_type']
        deploy_name = detection_results['operator_deployment'].get('deployment', 'unknown')
        
        # Only show as YAML-based if it's not OLM (OLM deployments are shown in OLM section)
        if deploy_type != 'OLM':
            details_table.add_row(
                "YAML-based",
                "[green]✓ Detected[/green]",
                f"{deploy_name}"
            )
        else:
            # OLM deployment - don't show in YAML section
            details_table.add_row(
                "YAML-based",
                "[dim]Not found[/dim]",
                ""
            )
    else:
        details_table.add_row(
            "YAML-based",
            "[dim]Not found[/dim]",
            ""
        )
    
    dashboard_content.append(Panel(
        details_table,
        title="[bold white]🔍 Installation Details[/bold white]",
        border_style="cyan",
        padding=(1, 2)
    ))
    
    # Detailed Resources Section (if any found)
    if detection_results['has_olm'] or detection_results['has_helm']:
        resources_content = []
        
        # OLM Resources - only show if there are relevant CSVs or catalogs
        if detection_results['has_olm']:
            olm_csvs = detection_results['olm_resources']['csvs']
            olm_catalogs = detection_results['olm_resources']['catalogs']
            
            # Filter catalog sources to only show Content Cortex operators
            content_cortex_catalog_prefixes = [
                'ibm-fncm-operator',
                'ibm-content-operator',
                'ibm-ccx-ai-services-operator',
                'ibm-licensing-operator',
                'ibm-usage-metering'
            ]
            
            filtered_catalogs = [
                catalog for catalog in olm_catalogs
                if any(catalog['name'].startswith(prefix) for prefix in content_cortex_catalog_prefixes)
            ]
            
            # Only show OLM Resources panel if we have CSVs or filtered catalogs
            if len(olm_csvs) > 0 or len(filtered_catalogs) > 0:
                olm_table = Table(show_header=True, header_style="bold yellow", box=None, padding=(0, 1))
                olm_table.add_column("Resource Type", style="yellow", width=20)
                olm_table.add_column("Name", style="white", width=50)
                olm_table.add_column("Namespace", style="cyan", width=20)
                
                for csv in olm_csvs:
                    olm_table.add_row("CSV", csv['name'], namespace)
                
                for catalog in filtered_catalogs:
                    olm_table.add_row("CatalogSource", catalog['name'], namespace)
                
                resources_content.append(Panel(
                    olm_table,
                    title="[bold yellow]📦 OLM Resources[/bold yellow]",
                    border_style="yellow",
                    padding=(1, 2)
                ))
        
        # Helm Releases
        if detection_results['has_helm']:
            helm_table = Table(show_header=True, header_style="bold green", box=None, padding=(0, 1))
            helm_table.add_column("Release Name", style="green", width=35)
            helm_table.add_column("Chart", style="white", width=40)
            helm_table.add_column("Status", style="cyan", width=15)
            helm_table.add_column("Namespace", style="dim", width=20)
            
            for release in detection_results['helm_releases']:
                status_color = "green" if release['status'] == 'deployed' else "yellow"
                helm_table.add_row(
                    release['name'],
                    release['chart'],
                    f"[{status_color}]{release['status']}[/{status_color}]",
                    release['namespace']
                )
            
            resources_content.append(Panel(
                helm_table,
                title="[bold green]⎈ Helm Releases[/bold green]",
                border_style="green",
                padding=(1, 2)
            ))
        
        if resources_content:
            dashboard_content.extend(resources_content)
    
    # Installation Plan Section
    plan_table = Table(show_header=False, box=None, padding=(0, 2))
    plan_table.add_column(style="white", width=100)
    
    # Check if there are actually relevant OLM resources (after filtering)
    has_relevant_olm = False
    if detection_results['has_olm']:
        olm_csvs = detection_results['olm_resources']['csvs']
        olm_catalogs = detection_results['olm_resources']['catalogs']
        
        # Filter catalogs to only Content Cortex operators
        content_cortex_catalog_prefixes = [
            'ibm-fncm-operator',
            'ibm-content-operator',
            'ibm-ccx-ai-services-operator',
            'ibm-licensing-operator',
            'ibm-usage-metering'
        ]
        
        filtered_catalogs = [
            catalog for catalog in olm_catalogs
            if any(catalog['name'].startswith(prefix) for prefix in content_cortex_catalog_prefixes)
        ]
        
        has_relevant_olm = len(olm_csvs) > 0 or len(filtered_catalogs) > 0
    
    if has_relevant_olm:
        plan_table.add_row("[green]✓[/green]  OLM installation detected - will be automatically migrated to Helm")
    elif detection_results.get('has_yaml', False):
        plan_table.add_row("[green]✓[/green]  YAML installation detected - will be automatically migrated to Helm")
    elif detection_results['has_helm']:
        # Check if we have operator status information
        if operator_status:
            # Count operators by status
            all_op_keys = ['content', 'ai-services', 'licensing', 'usage-metering']
            needs_upgrade = sum(1 for op in operator_status.values() if op.get('needs_action', False))
            needs_install = sum(1 for op_key in all_op_keys if op_key not in operator_status)
            all_current = all(op.get('is_current', False) for op in operator_status.values())
            
            # Build message based on what needs to be done
            if needs_install > 0 and needs_upgrade > 0:
                plan_table.add_row(f"[blue]ℹ[/blue]  Existing Helm installation detected - {needs_install} operator(s) will be installed, {needs_upgrade} operator(s) will be upgraded")
            elif needs_install > 0:
                plan_table.add_row(f"[blue]ℹ[/blue]  Existing Helm installation detected - {needs_install} operator(s) will be installed")
            elif needs_upgrade > 0:
                plan_table.add_row(f"[blue]ℹ[/blue]  Existing Helm installation detected - {needs_upgrade} operator(s) will be upgraded")
            elif all_current and len(operator_status) == len(all_op_keys):
                plan_table.add_row("[green]✓[/green]  All operators are at target version - no action needed")
            else:
                plan_table.add_row("[blue]ℹ[/blue]  Existing Helm installation detected - deployment will upgrade existing releases")
        else:
            plan_table.add_row("[blue]ℹ[/blue]  Existing Helm installation detected - deployment will upgrade existing releases")
    else:
        plan_table.add_row("[green]✓[/green]  No existing installation - proceeding with fresh deployment")
    
    dashboard_content.append(Panel(
        plan_table,
        title="[bold white]📋 Installation Plan[/bold white]",
        border_style="blue",
        padding=(1, 2)
    ))
    
    # Display all dashboard sections
    for section in dashboard_content:
        console.print(section)
        console.print()
    
    logger.info("System dashboard displayed successfully")


def _handle_chart_validation_and_download(state: dict, console, version_data: dict) -> None:
    """
    Handle Helm chart validation and download after operator selection.
    
    This function validates that required Helm charts exist (for packaged/local sources)
    or downloads them (for GitHub/public repo sources) with a modern UI.
    
    Args:
        state: Application state dictionary
        console: Rich console for output
        version_data: Version data from version.toml
        
    Raises:
        typer.Exit: If chart validation fails
    """
    from helper_scripts.helm.helm_deployer import HelmDeployer, HelmChartSource
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    
    # Determine which operators need chart download
    # Skip operators that are already at the correct version (unless --force is used)
    operators_to_check = []
    operators_skipped = []
    operator_status = state.get("operator_status", {})
    force_mode = state.get("force", False)
    
    if hasattr(state["setup"], 'selected_operators') and state["setup"].selected_operators:
        for op in state["setup"].selected_operators:
            op_value = op.value
            
            # Map operator type to status key
            status_key_map = {
                'content': 'content',
                'ai-services': 'ai-services',
                'usage-metering': 'usage-metering',
                'license-service': 'licensing'
            }
            status_key = status_key_map.get(op_value, op_value)
            
            # Check if operator is already at correct version (skip check if force mode)
            if not force_mode and status_key in operator_status and operator_status[status_key].get('is_current', False):
                operators_skipped.append(op_value)
                state["logger"].info(f"Skipping chart download for {op_value} - already at target version")
            else:
                operators_to_check.append(op_value)
                if force_mode and status_key in operator_status and operator_status[status_key].get('is_current', False):
                    state["logger"].info(f"Force mode: Will download/validate chart for {op_value} despite being current")
                else:
                    state["logger"].info(f"Will download/validate chart for {op_value}")
    else:
        operators_to_check = ["content"]
    
    # If all operators are current, skip chart download entirely (unless --force is used)
    if not operators_to_check and not force_mode:
        console.print()
        console.print(Panel.fit(
            "[green]✓ All Selected Operators Up-to-Date[/green]\n\n"
            "All selected operators are already at the target version.\n"
            "Skipping Helm chart download.\n\n"
            f"[dim]Operators at target version: {', '.join([op.replace('-', ' ').title() for op in operators_skipped])}[/dim]",
            border_style="green",
            title="[bold green]Chart Management[/bold green]"
        ))
        console.print()
        state["logger"].info("All operators current - skipping chart download")
        return
    
    # Show which operators are being skipped
    if operators_skipped:
        console.print()
        console.print(Panel.fit(
            f"[green]✓ Skipping Chart Download[/green]\n\n"
            f"The following operators are already at target version:\n"
            + "\n".join([f"  • {op.replace('-', ' ').title()}" for op in operators_skipped]),
            border_style="green",
            title="[bold green]Already Up-to-Date[/bold green]"
        ))
        console.print()
    
    # Map chart source string to enum
    source_map = {
        "packaged": HelmChartSource.PACKAGED,
        "local": HelmChartSource.LOCAL,
        "public": HelmChartSource.PUBLIC_REPO,
        "url": HelmChartSource.URL,
        "github": HelmChartSource.GITHUB
    }
    chart_source_enum = source_map.get(state["helm_chart_source"], HelmChartSource.GITHUB)
    
    # Initialize HelmDeployer
    state["logger"].info("Initializing Helm deployer for chart validation...")
    helm_deployer = HelmDeployer(
        logger=state["logger"],
        console=console,
        version_data=version_data,
        dev_mode=state.get("dev", False),
        github_token=os.environ.get('GITHUB_TOKEN')
    )
    
    # Display chart validation/download header
    console.print()
    console.print(Panel.fit(
        "[bold cyan]📦 Helm Chart Validation[/bold cyan]\n\n"
        f"[cyan]Chart Source:[/cyan] {state['helm_chart_source']}\n"
        f"[cyan]Operators:[/cyan] {', '.join([op.replace('-', ' ').title() for op in operators_to_check])}",
        border_style="cyan",
        title="[bold cyan]Chart Management[/bold cyan]"
    ))
    console.print()
    
    # Handle different chart sources
    if chart_source_enum in [HelmChartSource.GITHUB, HelmChartSource.PUBLIC_REPO, HelmChartSource.URL]:
        # Download charts with progress indicator
        console.print("[cyan]📥 Downloading Helm charts...[/cyan]\n")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task("[cyan]Downloading charts...", total=len(operators_to_check))
            
            all_downloaded = True
            failed_downloads = []
            
            for operator_type in operators_to_check:
                if operator_type not in helm_deployer.OPERATOR_CHARTS:
                    state["logger"].warning(f"Unknown operator type: {operator_type}")
                    progress.advance(task)
                    continue
                
                op_config = helm_deployer.OPERATOR_CHARTS[operator_type]
                progress.update(task, description=f"[cyan]Downloading {op_config['display_name']}...")
                
                try:
                    # Download chart
                    chart_path = None
                    if chart_source_enum == HelmChartSource.GITHUB:
                        chart_path = helm_deployer._download_chart_from_github(operator_type, op_config)
                    elif chart_source_enum == HelmChartSource.PUBLIC_REPO:
                        chart_path = helm_deployer._download_from_public_repo(operator_type, op_config)
                    
                    if chart_path:
                        state["logger"].info(f"✓ Downloaded chart for {operator_type}")
                    else:
                        all_downloaded = False
                        failed_downloads.append(operator_type)
                        state["logger"].error(f"Failed to download chart for {operator_type}")
                
                except Exception as e:
                    all_downloaded = False
                    failed_downloads.append(operator_type)
                    state["logger"].error(f"Exception downloading chart for {operator_type}: {e}")
                
                progress.advance(task)
        
        console.print()
        if all_downloaded:
            console.print(Panel.fit(
                f"[bold green]✓ Successfully downloaded {len(operators_to_check)} chart(s)[/bold green]\n\n"
                "[green]All required Helm charts are ready for deployment[/green]",
                border_style="green",
                title="[bold green]✓ Charts Ready[/bold green]"
            ))
            state["logger"].info("✓ All charts downloaded successfully")
        else:
            console.print(Panel.fit(
                f"[bold red]✗ Failed to download {len(failed_downloads)} chart(s)[/bold red]\n\n"
                "[red]The following charts could not be downloaded:[/red]\n" +
                "\n".join([f"  • {op}" for op in failed_downloads]) + "\n\n"
                "[bold yellow]⚠️  Helm deployment cannot proceed without required charts[/bold yellow]\n\n"
                "[white]Possible solutions:[/white]\n"
                "  [cyan]1.[/cyan] Check your internet connection\n"
                "  [cyan]2.[/cyan] Verify GitHub token if using private repositories\n"
                "  [cyan]3.[/cyan] Try using local/packaged charts instead\n"
                "  [cyan]4.[/cyan] Check the logs for detailed error information",
                border_style="red",
                title="[bold red]✗ Chart Download Failed - Deployment Aborted[/bold red]"
            ))
            state["logger"].error(f"Chart download failed for: {failed_downloads}")
            state["logger"].error("DEPLOYMENT ABORTED: Cannot proceed without required Helm charts")
            raise typer.Exit(code=1)
    
    elif chart_source_enum in [HelmChartSource.PACKAGED, HelmChartSource.LOCAL]:
        # Validate local/packaged charts exist
        source_display = "packaged (.tgz)" if chart_source_enum == HelmChartSource.PACKAGED else "local (unpacked)"
        console.print(f"[cyan]🔍 Validating {source_display} charts in [bold]{helm_deployer.chart_base_path}[/bold]...[/cyan]\n")
        
        charts_exist, missing_charts = helm_deployer.check_helm_charts_exist(
            operators=operators_to_check,
            chart_source=chart_source_enum
        )
        
        if not charts_exist:
            state["logger"].error(f"Missing {len(missing_charts)} required Helm charts")
            helm_deployer.display_missing_charts(missing_charts, chart_source_enum)
            console.print()
            console.print(Panel.fit(
                "[bold yellow]⚠️  Helm deployment cannot proceed without required charts[/bold yellow]\n\n"
                "[white]Possible solutions:[/white]\n"
                "  [cyan]1.[/cyan] Download charts using GitHub/public source mode\n"
                "  [cyan]2.[/cyan] Ensure charts are in the correct directory\n"
                "  [cyan]3.[/cyan] Verify chart names match expected format\n"
                "  [cyan]4.[/cyan] Check file permissions on chart directory",
                border_style="yellow",
                title="[bold yellow]⚠️  Deployment Aborted[/bold yellow]"
            ))
            state["logger"].error("DEPLOYMENT ABORTED: Cannot proceed without required Helm charts")
            raise typer.Exit(code=1)
        
        # Display success message
        console.print(Panel.fit(
            f"[bold green]✓ All {len(operators_to_check)} required chart(s) found and validated[/bold green]\n\n"
            "[green]Charts are ready for deployment[/green]",
            border_style="green",
            title="[bold green]✓ Charts Validated[/bold green]"
        ))
        state["logger"].info("✓ All required Helm charts found and validated")
    
    console.print()


def _display_modern_validation_summary(
    results: dict,
    health_metrics: dict,
    logger: logging.Logger
) -> None:
    """Delegate to the shared display_prereq_validation_table in interface.py."""
    display_prereq_validation_table(results, health_metrics)


def _handle_prerequisite_validation(
    missing_tools: list[str],
    files: list[str],
    results: dict,
    logger: logging.Logger
) -> None:
    """
    Handle prerequisite validation results and exit if validation fails.
    Uses modern ValidationDisplay for consistent UX.
    
    Args:
        missing_tools: List of missing prerequisite tools
        files: List of missing required files
        results: Dictionary of prerequisite check results
        logger: Logger instance
        
    Raises:
        typer.Exit: If prerequisites are missing (exit code 1)
    """
    from helper_scripts.validate.validation_display import ValidationDisplay, ValidationStatus
    
    has_missing_items = bool(missing_tools or files)
    
    if has_missing_items:
        logger.info("Prerequisites failed. Displaying missing tools and files.")
        
        # Check if Helm version is invalid and use modern validation display
        if results.get("helm_version_invalid"):
            console = Console()
            display = ValidationDisplay(console)
            
            # Add validation test for Helm version
            display.add_test("helm_version", "Helm Version Check", "Prerequisites", 1)
            display.start()
            display.start_test("helm_version")
            
            found_version = results.get("helm_version_found", "unknown")
            display.complete_test(
                "helm_version",
                success=False,
                message=f"Helm version {found_version} is not supported",
                failure_reason=f"Helm version {found_version} is not supported. Required: 4.x or above",
                remediation=(
                    "Install Helm 4.x or above:\n"
                    "1. Visit https://helm.sh/docs/intro/install/ for installation instructions\n"
                    "2. For macOS: brew install helm\n"
                    "3. For Linux: Download from https://github.com/helm/helm/releases\n"
                    "4. Verify installation: helm version"
                )
            )
            
            display.stop()
            display.display_failures()
            raise typer.Exit(code=1)
        
        # Note: Helm chart validation is now performed AFTER operator selection
        # in _handle_chart_validation_and_download() to only check selected operators
        
        # Standard error display for other missing tools
        layout = display_issues(tools=missing_tools, descriptors=files)
        print(layout)
        raise typer.Exit(code=1)
    
    logger.info("Prerequisites passed.")


def _handle_health_checks(
    logger: logging.Logger,
    results: dict,
    namespace: str = ""
) -> tuple[bool, list[str], dict]:
    """
    Perform and handle pre-deployment permission checks with user confirmation.
    Returns permission metrics for combined display.
    
    Args:
        logger: Logger instance
        results: Prerequisite check results
        namespace: Target namespace for deployment
        
    Returns:
        Tuple of (success, warnings, metrics)
        
    Raises:
        typer.Exit: If permission checks fail and user cancels (exit code 1)
    """
    # Create KubernetesUtilities instance BEFORE try-catch to ensure connection check happens first
    # This will raise an exception immediately if no K8s connection is available
    k8s_utils = KubernetesUtilities(logger=logger)
    
    # Verify connection was established
    if not k8s_utils.connected:
        logger.error("No Kubernetes connection available")
        print(Panel.fit(
            "❌ No Kubernetes connection available. Please ensure you have access to a Kubernetes cluster.",
            style="bold red",
            border_style="red"
        ))
        raise typer.Exit(code=1)
    
    try:
        # For Helm deployment, check basic permissions only (exclude OLM-specific)
        logger.info("Performing permission checks for Helm deployment (excluding OLM permissions)")
        health_success, health_warnings, health_metrics = k8s_utils.check_user_permissions(
            namespace,
            skip_olm_permissions=True
        )
        
        # Display modern combined validation summary
        _display_modern_validation_summary(results, health_metrics, logger)
        
        # Handle warnings or failures
        if not health_success:
            print(Panel.fit(
                "❌ Permission checks failed. Review the validation summary above.",
                style="bold red",
                border_style="red"
            ))
            print()
            
            should_continue = questionary.confirm(
                "Do you want to continue anyway?",
                default=False
            ).ask()
            
            # Handle cancellation
            should_continue = handle_cancelled_prompt(should_continue, "Deployment cancelled by user")

            if not should_continue:
                logger.info("User cancelled deployment due to failed permission checks")
                raise typer.Exit(code=1)
            
            logger.warning("User chose to continue despite failed permission checks")
            
        elif health_warnings:
            print(Panel.fit(
                "⚠️  Validation passed with warnings. Review the summary above.",
                style="bold yellow",
                border_style="yellow"
            ))
            print()
            logger.info("Permission checks passed with warnings - proceeding with deployment")
        else:
            print(Panel.fit(
                "✓ All validation checks passed successfully!",
                style="bold green",
                border_style="green"
            ))
            print()
            logger.info("All validation checks passed")
        
        return health_success, health_warnings, health_metrics
            
    except typer.Exit:
        # Re-raise typer exits
        raise
    except Exception as e:
        logger.error(f"Error during permission checks: {str(e)}")
        print(Panel.fit(
            f"❌ Permission check error: {str(e)}",
            style="bold red",
            border_style="red"
        ))
        print()
        
        should_continue = questionary.confirm(
            "Continue anyway?",
            default=False
        ).ask()
        
        # Handle cancellation
        should_continue = handle_cancelled_prompt(should_continue, "Deployment cancelled by user")

        if not should_continue:
            logger.info("User cancelled deployment due to permission check error")
            raise typer.Exit(code=1)
        
        return False, [str(e)], {}


def display_health_check_results(success: bool, warnings: list[str], metrics: dict) -> None:
    """
    Display comprehensive pre-deployment health check results with metrics.
    
    Args:
        success: Whether health checks passed
        warnings: List of warning messages
        metrics: Dictionary containing cluster metrics
    """
    from rich.columns import Columns
    from rich.console import Group
    
    # Create status panel
    if success and not warnings:
        status_panel = Panel.fit("✓ All Health Checks Passed", style="bold green")
    elif success and warnings:
        status_panel = Panel.fit("⚠️  Health Checks Passed with Warnings", style="bold yellow")
    else:
        status_panel = Panel.fit("✗ Health Checks Failed", style="bold red")
    
    # Create metrics table
    metrics_table = Table(title="Cluster Metrics", show_header=True, header_style="bold cyan")
    metrics_table.add_column("Metric", style="cyan", no_wrap=True)
    metrics_table.add_column("Value", style="magenta")
    metrics_table.add_column("Status", style="green")
    
    # Add cluster accessibility
    cluster_status = "✓ Connected" if metrics.get("cluster_accessible") else "✗ Not Connected"
    metrics_table.add_row(
        "Cluster Connection",
        cluster_status,
        "✓" if metrics.get("cluster_accessible") else "✗"
    )
    
    # Add Kubernetes version
    if metrics.get("k8s_version"):
        metrics_table.add_row("Kubernetes Version", metrics["k8s_version"], "ℹ")
    
    # Add node count
    node_count = metrics.get("nodes_count", 0)
    node_status = "✓" if node_count > 0 else "✗"
    metrics_table.add_row("Nodes", str(node_count), node_status)
    
    # Add CPU resources
    cpu = metrics.get("total_cpu", 0.0)
    cpu_status = "✓" if cpu >= 2 else "⚠️" if cpu >= 1 else "✗"
    metrics_table.add_row("Total CPU", f"{cpu:.2f} cores", cpu_status)
    
    # Add memory resources
    memory = metrics.get("total_memory", 0.0)
    memory_status = "✓" if memory >= 4 else "⚠️" if memory >= 2 else "✗"
    metrics_table.add_row("Total Memory", f"{memory:.2f} Gi", memory_status)
    
    # Add storage classes
    storage_classes = metrics.get("storage_classes", [])
    storage_status = "✓" if storage_classes else "⚠️"
    storage_value = f"{len(storage_classes)} available" if storage_classes else "None found"
    metrics_table.add_row("Storage Classes", storage_value, storage_status)
    
    # Add namespace status if checked
    if metrics.get("namespace_exists") is not None:
        ns_status = "✓ Exists" if metrics["namespace_exists"] else "ℹ Will be created"
        metrics_table.add_row("Target Namespace", ns_status, "ℹ")
    
    # Create warnings panel if there are warnings
    warning_panels = []
    if warnings:
        warning_text = "\n".join(warnings)
        warning_panel = Panel.fit(
            warning_text,
            title="⚠️  Warnings",
            border_style="yellow"
        )
        warning_panels.append(warning_panel)
    
    # Layout the display
    print(status_panel)
    print()
    print(metrics_table)
    
    if warning_panels:
        print()
        for panel in warning_panels:
            print(panel)
    
    print()


def display_planned_operations(deployment_details: dict, version_details: dict, deployment_type: str) -> None:
    """
    Display what operations would be performed in a dry-run.
    
    Args:
        deployment_details: Dictionary containing deployment configuration
        version_details: Dictionary containing version information
        deployment_type: Type of deployment (olm or cncf)
    """
    print()
    print(Panel.fit("Dry-Run Mode: Planned Operations", style="yellow"))
    print()
    
    operations_table = Table(title="Operations That Would Be Executed", show_header=True, header_style="bold cyan")
    operations_table.add_column("Step", style="cyan", width=8)
    operations_table.add_column("Operation", style="white")
    operations_table.add_column("Details", style="green")
    
    # Cluster Setup Operations
    operations_table.add_row("1", "Create/Verify Namespace", version_details.get("namespace", "N/A"))
    operations_table.add_row("2", "Create Image Pull Secret", "Using entitlement key or private registry credentials")
    
    # Deployment-specific operations
    if deployment_type == "olm":
        operations_table.add_row("3", "Apply Catalog Source", deployment_details.get("catalogSource", "N/A"))
        operations_table.add_row("4", "Create Operator Group", f"Namespace: {version_details.get('namespace', 'N/A')}")
        operations_table.add_row("5", "Create Subscription", f"Channel: {deployment_details.get('channel', 'N/A')}")
        operations_table.add_row("6", "Wait for Operator", "OLM will deploy operator automatically")
    else:
        operations_table.add_row("3", "Apply CRD", "fncm_v1_fncm_crd.yaml")
        operations_table.add_row("4", "Create Service Account", "service_account.yaml")
        operations_table.add_row("5", "Create Role & RoleBinding", "role.yaml, role_binding.yaml")
        operations_table.add_row("6", "Deploy Operator", "operator.yaml")
    
    print(operations_table)
    print()
    
    # Resource requirements
    resources_table = Table(title="Estimated Resource Requirements", show_header=True, header_style="bold magenta")
    resources_table.add_column("Resource", style="cyan")
    resources_table.add_column("Requirement", style="yellow")
    
    resources_table.add_row("CPU", "500m (operator pod)")
    resources_table.add_row("Memory", "512Mi (operator pod)")
    resources_table.add_row("Storage", "Minimal (operator logs only)")
    resources_table.add_row("Estimated Time", "2-5 minutes")
    
    print(resources_table)
    print()


def display_deployment_summary(success: bool, deployment_type: str, namespace: str, operator_name: str) -> None:
    """
    Display a summary after deployment completion.
    
    Args:
        success: Whether deployment was successful
        deployment_type: Type of deployment (olm or cncf)
        namespace: Kubernetes namespace
        operator_name: Name of the operator deployment
    """
    print()
    if success:
        print(Panel.fit("✓ Deployment Completed Successfully", style="bold green"))
        print()
        
        next_steps = Table(title="Next Steps", show_header=False, box=None)
        next_steps.add_column("Step", style="cyan", width=3)
        next_steps.add_column("Action", style="white")
        
        next_steps.add_row("1.", f"Verify operator is running: kubectl get pods -n {namespace}")
        next_steps.add_row("2.", f"Check operator logs: kubectl logs -n {namespace} deployment/{operator_name}")
        next_steps.add_row("3.", "Create your Custom Resource (CR) to deploy CCx and AI Services components")
        next_steps.add_row("4.", "Monitor deployment: kubectl get fncm -n {namespace}")
        
        print(next_steps)
        print()
        
        # Rollback information
        rollback_panel = Panel.fit(
            f"[bold yellow]Rollback Instructions:[/bold yellow]\n\n"
            f"If you need to remove this deployment:\n"
            f"  python3 clean_deployment.py --namespace {namespace}\n\n"
            f"Or manually:\n"
            f"  kubectl delete deployment {operator_name} -n {namespace}\n"
            f"  kubectl delete namespace {namespace}",
            title="Rollback Information",
            border_style="yellow"
        )
        print(rollback_panel)
    else:
        print(Panel.fit("✗ Deployment Failed", style="bold red"))
        print()
        
        troubleshooting = Table(title="Troubleshooting Steps", show_header=False, box=None)
        troubleshooting.add_column("Step", style="cyan", width=3)
        troubleshooting.add_column("Action", style="white")
        
        troubleshooting.add_row("1.", f"Check operator logs: kubectl logs -n {namespace} deployment/{operator_name}")
        troubleshooting.add_row("2.", f"Check events: kubectl get events -n {namespace} --sort-by='.lastTimestamp'")
        troubleshooting.add_row("3.", "Review deployoperator.log for detailed error messages")
        troubleshooting.add_row("4.", "Verify prerequisites: python3 deploy_operator.py --help")
        
        print(troubleshooting)
    print()


def deploy_with_helm(namespace: str, operators: List[str], chart_source: str, version_data: dict = None) -> bool:  # type: ignore
    """
    Deploy operators using Helm charts with live progress tracking and parallel support.
    
    Args:
        namespace: Target namespace
        operators: List of operator types to deploy
        chart_source: Helm chart source type
        version_data: Version data from version.toml
        
    Returns:
        True if all deployments succeeded
    """
    import asyncio
    import subprocess
    from concurrent.futures import ThreadPoolExecutor
    from helper_scripts.utilities.deployment_progress import (
        create_deployment_progress,
        display_deployment_complete,
        DeploymentPhase,
        DeploymentStep
    )
    from helper_scripts.utilities.operator_config import OperatorType
    from helper_scripts.utilities.kubernetes_utilites import KubernetesUtilities
    
    # ============================================================
    # SAFETY CHECK: Verify charts before proceeding
    # ============================================================
    state["logger"].info("Performing pre-deployment chart validation...")
    
    # HelmDeployer will automatically use project_root/helm-charts if no path specified
    # Pass version_data so it can build OPERATOR_CHARTS dynamically
    # Pass dev_mode and github_token for GitHub chart downloads
    helm_deployer = HelmDeployer(
        logger=state["logger"],
        console=console,
        version_data=version_data,
        dev_mode=state.get("dev", False),
        github_token=os.environ.get('GITHUB_TOKEN')
    )
    
    # Map chart source string to enum for validation
    source_map = {
        "packaged": HelmChartSource.PACKAGED,
        "local": HelmChartSource.LOCAL,
        "public": HelmChartSource.PUBLIC_REPO,
        "url": HelmChartSource.URL,
        "github": HelmChartSource.GITHUB
    }
    chart_source_enum = source_map.get(chart_source, HelmChartSource.GITHUB)
    
    # Verify charts exist before attempting deployment
    # This is a safety check in case validation was somehow bypassed
    if chart_source_enum in [HelmChartSource.PACKAGED, HelmChartSource.LOCAL]:
        charts_exist, missing_charts = helm_deployer.check_helm_charts_exist(
            operators=operators,
            chart_source=chart_source_enum
        )
        
        if not charts_exist:
            state["logger"].error("CRITICAL: Required Helm charts are missing - deployment cannot proceed")
            console.print()
            console.print(Panel.fit(
                "[bold red]✗ CRITICAL ERROR: Required Helm Charts Missing[/bold red]\n\n"
                f"[red]Missing {len(missing_charts)} chart(s):[/red]\n" +
                "\n".join([f"  • {chart}" for chart in missing_charts]) + "\n\n"
                "[yellow]This should have been caught during validation.[/yellow]\n"
                "[yellow]Please report this issue if you see this message.[/yellow]",
                border_style="red",
                title="[bold red]✗ Deployment Aborted[/bold red]"
            ))
            return False
    
    state["logger"].info("✓ Pre-deployment chart validation passed")
    
    # Get CRD and ClusterRole skip/force decisions from state (set earlier in deploy() function before user confirmation)
    skip_crd_for_operators = state.get("skip_crd_for_operators", {})
    skip_cluster_role_for_operators = state.get("skip_cluster_role_for_operators", {})
    force_crd_takeover_for_operators = state.get("force_crd_takeover_for_operators", {})
    force_rbac_takeover_for_operators = state.get("force_rbac_takeover_for_operators", {})
    
    # Convert operator strings to OperatorType enums
    operator_types = []
    operator_string_map = {}  # Map OperatorType to string for helm_deployer
    operators_to_process = list(operators)  # Create a copy to modify
    
    # Remove any cluster-scoped chart references if present (no longer used)
    if "usage-metering-cluster-scoped" in operators_to_process:
        operators_to_process.remove("usage-metering-cluster-scoped")
        state["logger"].info("Removed usage-metering-cluster-scoped from operators list (CRDs now applied directly)")
    
    for op in operators_to_process:
        try:
            # Map helm operator names to OperatorType enum values
            op_map = {
                "content": "content",
                "ai-services": "ai-services",
                "license-service": "license-service",
                "usage-metering": "usage-metering"
            }
            enum_value = op_map.get(op, op)
            operator_type_enum = OperatorType(enum_value)
            operator_types.append(operator_type_enum)
            operator_string_map[operator_type_enum] = op
        except ValueError:
            state["logger"].warning(f"Unknown operator type: {op}")
    
    if not operator_types:
        state["logger"].error("No valid operators selected")
        return False
    
    # Check if parallel deployment is enabled
    parallel_deployment = getattr(state["setup"], 'parallel_deployment', False) and len(operator_types) > 1
    
    # Create deployment tracker with live updates
    tracker, live = create_deployment_progress(
        operators=operator_types,
        parallel=parallel_deployment,
        console=console
    )
    
    # Display header
    console.print("\n")
    console.print(Panel.fit(
        "[bold cyan]Starting Helm Deployment[/bold cyan]",
        border_style="cyan"
    ))
    console.print()
    
    all_success = True
    executor = None
    
    # Temporarily disable console logging during live display to prevent UI distortion
    # Keep file logging active for debugging
    logger = state["logger"]
    console_handlers = [h for h in logger.handlers if isinstance(h, RichHandler)]
    for handler in console_handlers:
        logger.removeHandler(handler)
    
    try:
        with live:
            # Initialize all operators
            for operator_type in operator_types:
                tracker.start_operator(operator_type)
            live.update(tracker.create_progress_display())
            
            # Phase 1: Cluster Setup (shared across all operators)
            # This creates namespace, entitlement secret, and any shared prerequisites
            state["logger"].info("Starting cluster setup phase")
            tracker.update_cluster_setup(
                task_name="Creating namespace and prerequisites",
                progress=0,
                phase=DeploymentPhase.PREPARING
            )
            live.update(tracker.create_progress_display())
            
            # Create Kubernetes utilities for cluster setup
            k8s_utils = KubernetesUtilities(state["logger"])
            
            # ═══════════════════════════════════════════════════════════════════════
            # UPGRADE/MIGRATION PHASE: Handle existing operator installations
            # ═══════════════════════════════════════════════════════════════════════
            # Check if this is an upgrade scenario (existing operators need migration)
            # Get operator installation info from state (detected earlier in deploy() function)
            operator_install_info = state.get("operator_install_info", {
                'has_olm': False,
                'has_yaml': False,
                'deployment_name': None
            })
            
            cleanup_performed = False
            
            # Check for and cleanup OLM-based operator deployment first
            if operator_install_info.get('has_olm', False):
                state["logger"].info("OLM-based FNCM operator detected - migration to Helm required")
                tracker.update_cluster_setup(
                    task_name="Migrating FNCM operator from OLM to Helm",
                    progress=5,
                    phase=DeploymentPhase.PREPARING
                )
                live.update(tracker.create_progress_display())
                
                # Include ibm-licensing namespace for license service cleanup
                additional_namespaces = ["ibm-licensing"]
                
                cleanup_success = cleanup_olm_deployment(
                    namespace=namespace,
                    logger=state["logger"],
                    console=console,
                    tracker=tracker,
                    live=live,
                    additional_namespaces=additional_namespaces,
                    remove_licensing_olm=state.get("remove_licensing_olm", False)
                )
                if not cleanup_success:
                    state["logger"].error("FNCM OLM cleanup failed - cannot proceed with Helm deployment")
                    return False
                cleanup_performed = True
                
                state["logger"].info("✓ FNCM OLM to Helm migration cleanup complete")
            
            # Check for and cleanup YAML-based operator deployment
            if operator_install_info.get('has_yaml', False):
                state["logger"].info("YAML-based FNCM operator detected - migration to Helm required")
                tracker.update_cluster_setup(
                    task_name="Migrating FNCM operator from YAML to Helm",
                    progress=10 if not cleanup_performed else 15,
                    phase=DeploymentPhase.PREPARING
                )
                live.update(tracker.create_progress_display())
                
                yaml_deployment_name = operator_install_info.get('deployment_name')
                cleanup_success = cleanup_yaml_deployment(
                    namespace=namespace,
                    logger=state["logger"],
                    console=console,
                    tracker=tracker,
                    live=live,
                    deployment_name=yaml_deployment_name
                )
                if not cleanup_success:
                    state["logger"].error("FNCM YAML operator cleanup failed - cannot proceed with Helm deployment")
                    return False
                cleanup_performed = True
                
                state["logger"].info("✓ FNCM YAML to Helm migration cleanup complete")
            
            # If cleanup was performed, add a brief pause to ensure resources are fully removed
            if cleanup_performed:
                import time
                state["logger"].info("Waiting for cleanup to complete...")
                tracker.update_cluster_setup(
                    task_name="Finalizing cleanup",
                    progress=20,
                    phase=DeploymentPhase.PREPARING
                )
                live.update(tracker.create_progress_display())
                time.sleep(3)  # Brief pause to ensure Kubernetes processes the deletions
                state["logger"].info("✓ FNCM operator migration cleanup complete - proceeding with Helm deployment")
            
            # ═══════════════════════════════════════════════════════════════════════
            # HANDLE OLM LICENSING REPLACEMENT (if user chose to replace)
            # ═══════════════════════════════════════════════════════════════════════
            # OLM detection and user decision already happened before chart download
            # If user chose to replace OLM licensing, clean it up now
            if state.get("replace_olm_licensing", False) and "license-service" in [operator_string_map.get(op, op.value) for op in operator_types]:
                # User chose to replace - clean up OLM resources
                from helper_scripts.utilities.kubernetes_utilites import KubernetesUtilities
                k8s_utils = KubernetesUtilities(state["logger"])
                
                licensing_olm_check = k8s_utils.detect_olm_resources(
                    "ibm-licensing",
                    csv_prefixes=["ibm-licensing-operator"]
                )
                
                if licensing_olm_check["has_olm"]:
                    tracker.update_cluster_setup(
                        task_name="Checking for IBM Licensing OLM",
                        progress=5,
                        phase=DeploymentPhase.PREPARING
                    )
                    live.update(tracker.create_progress_display())
                    state["logger"].info("Cleaning up OLM-based IBM Licensing installation")
                    tracker.update_cluster_setup(
                        task_name="Removing OLM-based IBM Licensing",
                        progress=15,
                        phase=DeploymentPhase.PREPARING
                    )
                    live.update(tracker.create_progress_display())
                    
                    try:
                        # Remove IBM Licensing OLM resources
                        licensing_csv_prefixes = ["ibm-licensing-operator"]
                        licensing_subscription_names = ["ibm-licensing-operator", "ibm-licensing-operator-app"]
                        licensing_catalog_names = ["ibm-licensing-catalog", "ibm-licensing-operator-catalog"]
                        
                        # Delete CSVs
                        for csv in licensing_olm_check.get("csvs", []):
                            csv_name = csv["name"]
                            for prefix in licensing_csv_prefixes:
                                if csv_name.startswith(prefix):
                                    try:
                                        k8s_utils.delete_clusterserviceversion(csv_name=csv_name, namespace="ibm-licensing")
                                        state["logger"].info(f"Deleted IBM Licensing CSV: {csv_name}")
                                    except Exception as e:
                                        state["logger"].warning(f"Error deleting CSV {csv_name}: {e}")
                                    break
                        
                        # Delete subscription
                        try:
                            subscription_details = k8s_utils.get_subscription(namespace="ibm-licensing")
                            if subscription_details:
                                subscription_name = subscription_details.get("name", "")
                                if subscription_name in licensing_subscription_names:
                                    k8s_utils.delete_subscription(namespace="ibm-licensing", name=subscription_name)
                                    state["logger"].info(f"Deleted IBM Licensing subscription: {subscription_name}")
                        except Exception as e:
                            state["logger"].warning(f"Error deleting subscription: {e}")
                        
                        # Delete catalog sources
                        for catalog in licensing_olm_check.get("catalogs", []):
                            catalog_name = catalog["name"]
                            if catalog_name in licensing_catalog_names:
                                try:
                                    k8s_utils.delete_catalog_source(namespace="ibm-licensing", name=catalog_name)
                                    state["logger"].info(f"Deleted IBM Licensing catalog: {catalog_name}")
                                except Exception as e:
                                    state["logger"].warning(f"Error deleting catalog {catalog_name}: {e}")
                        
                        # Delete operator deployment
                        try:
                            k8s_utils.delete_operator_deployment(namespace="ibm-licensing")
                            state["logger"].info("Deleted IBM Licensing operator deployment")
                        except Exception as e:
                            state["logger"].warning(f"Error deleting operator deployment: {e}")
                        
                        state["logger"].info("OLM-based IBM Licensing cleanup complete")
                        tracker.update_cluster_setup(
                            task_name="IBM Licensing OLM cleanup complete",
                            progress=20,
                            phase=DeploymentPhase.PREPARING
                        )
                        live.update(tracker.create_progress_display())
                        
                    except Exception as e:
                        state["logger"].error(f"Failed to clean up OLM-based IBM Licensing: {e}")
                        tracker.update_cluster_setup(
                            task_name="IBM Licensing OLM cleanup failed",
                            progress=15,
                            phase=DeploymentPhase.FAILED
                        )
                        live.update(tracker.create_progress_display())
                        return False
            
            # Create namespace if it doesn't exist
            try:
                tracker.update_cluster_setup(
                    task_name="Creating namespace",
                    progress=25,
                    phase=DeploymentPhase.PREPARING
                )
                live.update(tracker.create_progress_display())
                
                if not k8s_utils.check_namespace_exists(namespace):
                    k8s_utils.create_namespace(namespace)
                    state["logger"].info(f"Created namespace: {namespace}")
                else:
                    state["logger"].info(f"Namespace already exists: {namespace}")
                
                tracker.update_cluster_setup(
                    task_name="Namespace ready",
                    progress=40,
                    completed=True
                )
                live.update(tracker.create_progress_display())
            except Exception as e:
                state["logger"].error(f"Failed to create namespace: {e}")
                tracker.update_cluster_setup(
                    task_name="Failed to create namespace",
                    progress=25,
                    phase=DeploymentPhase.FAILED
                )
                live.update(tracker.create_progress_display())
                return False
            
            # Create ibm-entitlement-key secret
            try:
                import base64
                from kubernetes import client
                
                tracker.update_cluster_setup(
                    task_name="Creating IBM Entitlement Registry secret",
                    progress=55,
                    phase=DeploymentPhase.PREPARING
                )
                live.update(tracker.create_progress_display())
                
                # Check if secret already exists
                core_v1 = k8s_utils.core_v1
                secret_exists = False
                try:
                    core_v1.read_namespaced_secret(name="ibm-entitlement-key", namespace=namespace)
                    secret_exists = True
                    state["logger"].info("Secret 'ibm-entitlement-key' already exists")
                except client.ApiException as e:
                    if e.status == 404:
                        secret_exists = False
                
                if not secret_exists:
                    # Determine which registry credentials to use
                    if hasattr(state["setup"], 'private_registry_valid') and state["setup"].private_registry_valid:
                        # Use private registry credentials
                        state["logger"].info(f"Creating image pull secret for private registry: {state['setup'].private_registry_full_server}")
                        data = {
                            '.dockerconfigjson': base64.b64encode(
                                bytes(
                                    '{{"auths": {{"{}": {{"username": "{}", "password": "{}", "email": "example@example.com"}}}}}}'.format(
                                        state["setup"].private_registry_full_server,
                                        state["setup"].private_registry_username,
                                        state["setup"].private_registry_password),
                                    'utf-8'
                                )
                            ).decode('utf-8')
                        }
                    else:
                        # Use IBM Entitlement Registry credentials
                        state["logger"].info('Creating image pull secret for IBM Entitlement Registry')
                        registry = getattr(state["setup"], 'registry', 'cp.icr.io')
                        entitlement_key = state["setup"].entitlement_key
                        data = {
                            '.dockerconfigjson': base64.b64encode(
                                bytes(
                                    '{{"auths": {{"{}": {{"username": "{}", "password": "{}", "email": "example@example.com"}}}}}}'.format(
                                        registry, "cp", entitlement_key),
                                    'utf-8'
                                )
                            ).decode('utf-8')
                        }
                    
                    # Create Docker registry secret object
                    secret = client.V1Secret(
                        api_version="v1",
                        data=data,
                        kind="Secret",
                        metadata=client.V1ObjectMeta(name="ibm-entitlement-key"),
                        type="kubernetes.io/dockerconfigjson"
                    )
                    core_v1.create_namespaced_secret(namespace=namespace, body=secret)
                    state["logger"].info("Secret 'ibm-entitlement-key' created successfully")
                
                tracker.update_cluster_setup(
                    task_name="Image pull secret ready",
                    progress=65,
                    completed=True
                )
                live.update(tracker.create_progress_display())
            except Exception as e:
                state["logger"].error(f"Failed to create ibm-entitlement-key secret: {e}")
                tracker.update_cluster_setup(
                    task_name="Failed to create secret",
                    progress=55,
                    phase=DeploymentPhase.FAILED
                )
                live.update(tracker.create_progress_display())
                return False
            
            # Create license-advisor and usage-metering secrets based on airgap configuration
            # Only create if Software Central upload is enabled (connected deployment)
            airgap_config = state.get("airgap_config", {})
            enable_software_central = airgap_config.get('enable_software_central', False)
            
            if enable_software_central:
                # Create ibm-ccx-ums-secret with entitlement key as token
                try:
                    tracker.update_cluster_setup(
                        task_name="Creating IBM CCX UMS secret",
                        progress=70,
                        phase=DeploymentPhase.PREPARING
                    )
                    live.update(tracker.create_progress_display())
                    
                    # Check if secret already exists
                    ums_secret_exists = False
                    try:
                        core_v1.read_namespaced_secret(name="ibm-ccx-ums-secret", namespace=namespace)
                        ums_secret_exists = True
                        state["logger"].info("Secret 'ibm-ccx-ums-secret' already exists")
                    except client.ApiException as e:
                        if e.status == 404:
                            ums_secret_exists = False
                    
                    if not ums_secret_exists:
                        # Get the entitlement key
                        entitlement_key = state["setup"].entitlement_key
                        
                        # Create Opaque secret with token key
                        ums_secret_data = {
                            'token': base64.b64encode(entitlement_key.encode('utf-8')).decode('utf-8')
                        }
                        
                        ums_secret = client.V1Secret(
                            api_version="v1",
                            data=ums_secret_data,
                            kind="Secret",
                            metadata=client.V1ObjectMeta(name="ibm-ccx-ums-secret"),
                            type="Opaque"
                        )
                        core_v1.create_namespaced_secret(namespace=namespace, body=ums_secret)
                        state["logger"].info("Secret 'ibm-ccx-ums-secret' created successfully")
                    
                    tracker.update_cluster_setup(
                        task_name="UMS secret ready",
                        progress=75,
                        completed=True
                    )
                    live.update(tracker.create_progress_display())
                except Exception as e:
                    state["logger"].error(f"Failed to create ibm-ccx-ums-secret: {e}")
                    tracker.update_cluster_setup(
                        task_name="Failed to create UMS secret",
                        progress=70,
                        phase=DeploymentPhase.FAILED
                    )
                    live.update(tracker.create_progress_display())
                    return False
                
                # Create ibm-ccx-ls-secret in ibm-licensing namespace with entitlement key as token
                try:
                    tracker.update_cluster_setup(
                        task_name="Creating IBM CCX License Service secret",
                        progress=80,
                        phase=DeploymentPhase.PREPARING
                    )
                    live.update(tracker.create_progress_display())
                    
                    # Ensure ibm-licensing namespace exists
                    try:
                        core_v1.read_namespace("ibm-licensing")
                        state["logger"].info("Namespace 'ibm-licensing' already exists")
                    except client.ApiException as e:
                        if e.status == 404:
                            # Create ibm-licensing namespace
                            namespace_body = client.V1Namespace(
                                metadata=client.V1ObjectMeta(name="ibm-licensing")
                            )
                            core_v1.create_namespace(body=namespace_body)
                            state["logger"].info("Created namespace 'ibm-licensing' for License Service secret")
                    
                    # Check if secret already exists
                    ls_secret_exists = False
                    try:
                        core_v1.read_namespaced_secret(name="ibm-ccx-ls-secret", namespace="ibm-licensing")
                        ls_secret_exists = True
                        state["logger"].info("Secret 'ibm-ccx-ls-secret' already exists in ibm-licensing namespace")
                    except client.ApiException as e:
                        if e.status == 404:
                            ls_secret_exists = False
                    
                    if not ls_secret_exists:
                        # Get the entitlement key
                        entitlement_key = state["setup"].entitlement_key
                        
                        # Create Opaque secret with token key
                        ls_secret_data = {
                            'entitlementKey': base64.b64encode(entitlement_key.encode('utf-8')).decode('utf-8')
                        }
                        
                        ls_secret = client.V1Secret(
                            api_version="v1",
                            data=ls_secret_data,
                            kind="Secret",
                            metadata=client.V1ObjectMeta(name="ibm-ccx-ls-secret"),
                            type="Opaque"
                        )
                        core_v1.create_namespaced_secret(namespace="ibm-licensing", body=ls_secret)
                        state["logger"].info("Secret 'ibm-ccx-ls-secret' created successfully in ibm-licensing namespace")
                    
                    tracker.update_cluster_setup(
                        task_name="License Service secret ready",
                        progress=85,
                        completed=True
                    )
                    live.update(tracker.create_progress_display())
                except Exception as e:
                    state["logger"].error(f"Failed to create ibm-ccx-ls-secret: {e}")
                    tracker.update_cluster_setup(
                        task_name="Failed to create License Service secret",
                        progress=80,
                        phase=DeploymentPhase.FAILED
                    )
                    live.update(tracker.create_progress_display())
                    return False
            else:
                # Airgapped deployment - skip secret creation
                state["logger"].info("Airgapped deployment detected - skipping license-advisor and usage-metering secret creation")
                state["logger"].info("Software Central upload disabled - license and usage data must be uploaded manually")
                tracker.update_cluster_setup(
                    task_name="Secrets skipped (airgapped)",
                    progress=85,
                    completed=True
                )
                live.update(tracker.create_progress_display())
            
            # Mark cluster setup as complete
            tracker.complete_cluster_setup()
            live.update(tracker.create_progress_display())
            state["logger"].info("Cluster setup phase complete")
            
            # Phase 2: Deploy operators (parallel or sequential)
            def deploy_single_operator(operator_type):
                """Deploy a single operator with Helm."""
                operator_string = operator_string_map[operator_type]
                state["logger"].info(f"Deploying operator: {operator_type.value}")
                
                # Update tracker - preparing
                tracker.update_operator(
                    operator_type,
                    phase=DeploymentPhase.PREPARING,
                    step=DeploymentStep.NAMESPACE_SETUP,
                    progress=10
                )
                live.update(tracker.create_progress_display())
                
                # Determine if we should skip CRD installation for this operator
                skip_crd = skip_crd_for_operators.get(operator_string, False)
                
                # Determine if we should skip ClusterRole creation for this operator
                skip_cluster_role = skip_cluster_role_for_operators.get(operator_string, False)
                
                # Determine if we should force takeover for CRDs or RBAC
                force_crd_takeover = force_crd_takeover_for_operators.get(operator_string, False)
                force_rbac_takeover = force_rbac_takeover_for_operators.get(operator_string, False)
                
                # Prepare custom values for specific operators
                custom_values = None
                
                # Check if using private registry in airgap deployment
                airgap_config = state.get("airgap_config", {})
                use_private_registry = airgap_config.get('use_private_registry', False)
                private_registry_details = airgap_config.get('private_registry_details', {})
                
                if operator_string == "usage-metering":
                    # Add Software Central configuration for usage-metering
                    custom_values = {
                        "ibmUsageMetering": {
                            "spec": {
                                "sender": {
                                    "softwareCentral": {
                                        "enable": True,
                                        "entitlementKeySecret": "ibm-ccx-ums-secret"
                                    }
                                }
                            }
                        }
                    }
                    state["logger"].info("Adding Software Central configuration to usage-metering deployment")
                    
                    # Override image registry for usage-metering when using private registry
                    if use_private_registry:
                        # Build registry base URL (host:port) without path for imagePullPrefix
                        # Usage metering uses: global.imagePullPrefix + "/" + imageRegistryNamespaceOperator/Operand
                        private_registry_host = private_registry_details.get('host', '')
                        private_registry_port = private_registry_details.get('port', '')
                        
                        if private_registry_host:
                            # Construct base registry URL (without path)
                            if private_registry_port:
                                registry_base = f"{private_registry_host}:{private_registry_port}"
                            else:
                                registry_base = private_registry_host
                            
                            custom_values["global"] = {
                                "imagePullPrefix": registry_base
                            }
                            
                            # Set the namespace paths (these get appended to imagePullPrefix)
                            # For example: cp.stg.icr.io + "/" + cp = cp.stg.icr.io/cp
                            private_registry_path = private_registry_details.get('path', '')
                            if private_registry_path:
                                # Ensure ibmUsageMetering key exists before adding nested keys
                                if "ibmUsageMetering" not in custom_values:
                                    custom_values["ibmUsageMetering"] = {}
                                custom_values["ibmUsageMetering"]["imageRegistryNamespaceOperator"] = private_registry_path
                                custom_values["ibmUsageMetering"]["imageRegistryNamespaceOperand"] = private_registry_path
                            else:
                                # If no path specified, use empty string so images are pulled from registry root
                                if "ibmUsageMetering" not in custom_values:
                                    custom_values["ibmUsageMetering"] = {}
                                custom_values["ibmUsageMetering"]["imageRegistryNamespaceOperator"] = ""
                                custom_values["ibmUsageMetering"]["imageRegistryNamespaceOperand"] = ""
                            
                            state["logger"].info(f"Overriding usage-metering image registry - base: {registry_base}, path: {private_registry_path}")
                elif operator_string == "license-service":
                    # Add Software Central configuration for license-service
                    custom_values = {
                        "ibmLicensing": {
                            "spec": {
                                "softwareCentral": {
                                    "enable": True,
                                    "entitlementKeySecret": "ibm-ccx-ls-secret"
                                }
                            }
                        }
                    }
                    state["logger"].info("Adding Software Central configuration to license-service deployment")
                    
                    # Override image registry for license-service when using private registry
                    if use_private_registry:
                        # Build registry base URL (host:port) without path for imagePullPrefix
                        # License service uses: global.imagePullPrefix + "/" + imageRegistryNamespaceOperator/Operand
                        private_registry_host = private_registry_details.get('host', '')
                        private_registry_port = private_registry_details.get('port', '')
                        
                        if private_registry_host:
                            # Construct base registry URL (without path)
                            if private_registry_port:
                                registry_base = f"{private_registry_host}:{private_registry_port}"
                            else:
                                registry_base = private_registry_host
                            
                            custom_values["global"] = {
                                "imagePullPrefix": registry_base
                            }
                            
                            # Set the namespace paths (these get appended to imagePullPrefix)
                            # For example: cp.stg.icr.io + "/" + cp = cp.stg.icr.io/cp
                            private_registry_path = private_registry_details.get('path', '')
                            if private_registry_path:
                                # Ensure ibmLicensing key exists before adding nested keys
                                if "ibmLicensing" not in custom_values:
                                    custom_values["ibmLicensing"] = {}
                                custom_values["ibmLicensing"]["imageRegistryNamespaceOperator"] = private_registry_path
                                custom_values["ibmLicensing"]["imageRegistryNamespaceOperand"] = private_registry_path
                            else:
                                # If no path specified, use empty string so images are pulled from registry root
                                if "ibmLicensing" not in custom_values:
                                    custom_values["ibmLicensing"] = {}
                                custom_values["ibmLicensing"]["imageRegistryNamespaceOperator"] = ""
                                custom_values["ibmLicensing"]["imageRegistryNamespaceOperand"] = ""
                            
                            state["logger"].info(f"Overriding license-service image registry - base: {registry_base}, path: {private_registry_path}")
                elif operator_string == "ai-services":
                    # Check if using private registry in airgap deployment
                    if use_private_registry:
                        # Override image repository for AI Services operator when using private registry
                        private_registry_details = airgap_config.get('private_registry_details', {})
                        private_registry_server = private_registry_details.get('full_server', '')
                        
                        if private_registry_server:
                            # Build the full image repository path
                            # full_server already includes the path (e.g., cp.stg.icr.io/cp)
                            # Just append the operator image name
                            image_repository = f"{private_registry_server}/ibm-ccx-ai-services-operator"
                            
                            custom_values = {
                                "image": {
                                    "repository": image_repository
                                }
                            }
                            state["logger"].info(f"Overriding AI Services operator image repository for private registry: {image_repository}")
                    # Check if dev mode is enabled to use staging repository
                    elif state.get("dev", False):
                        # Use staging repository for dev mode
                        staging_registry = "cp.stg.icr.io/cp"
                        image_repository = f"{staging_registry}/ibm-ccx-ai-services-operator"
                        
                        custom_values = {
                            "image": {
                                "repository": image_repository
                            }
                        }
                        state["logger"].info(f"Dev mode enabled - using staging repository for AI Services operator: {image_repository}")
                elif operator_string == "content":
                    # Check if using private registry in airgap deployment
                    if use_private_registry:
                        # Override image repository for Content operator when using private registry
                        private_registry_details = airgap_config.get('private_registry_details', {})
                        private_registry_server = private_registry_details.get('full_server', '')
                        
                        if private_registry_server:
                            # Build the full image repository path
                            # full_server already includes the path (e.g., cp.stg.icr.io/cp)
                            # Just append the operator image name
                            image_repository = f"{private_registry_server}/icp4a-content-operator"
                            
                            custom_values = {
                                "image": {
                                    "repository": image_repository
                                }
                            }
                            state["logger"].info(f"Overriding Content operator image repository for private registry: {image_repository}")
                    # Check if dev mode is enabled to use staging repository
                    elif state.get("dev", False):
                        # Use staging repository for dev mode
                        staging_registry = "cp.stg.icr.io/cp"
                        image_repository = f"{staging_registry}/icp4a-content-operator"
                        
                        custom_values = {
                            "image": {
                                "repository": image_repository
                            }
                        }
                        state["logger"].info(f"Dev mode enabled - using staging repository for Content operator: {image_repository}")
                
                # Deploy operator
                success = helm_deployer.deploy_operator(
                    operator_type=operator_string,
                    namespace=namespace,
                    chart_source=chart_source_enum,
                    values=custom_values,
                    create_cluster_role=not skip_cluster_role,  # Skip ClusterRole if user chose to
                    install_crd=not skip_crd,  # Skip CRD if user chose to
                    force=force_crd_takeover or force_rbac_takeover,  # Use --force if taking over resources
                    force_conflicts=force_crd_takeover or force_rbac_takeover,  # Use --force-conflicts if taking over
                    dry_run=state["dryrun"],
                    wait=True,
                    timeout="10m",
                    live=live,
                    tracker=tracker,
                    operator_type_enum=operator_type
                )
                
                # Mark as complete
                if success:
                    tracker.complete_operator(operator_type, success=True)
                else:
                    tracker.complete_operator(
                        operator_type,
                        success=False,
                        error="Helm deployment failed"
                    )
                
                live.update(tracker.create_progress_display())
                return success
            
            # Deploy operators in parallel or sequential mode
            if parallel_deployment and len(operator_types) > 1:
                # Calculate max workers based on number of parallel tasks
                total_parallel_tasks = len(operator_types)
                max_workers = min(
                    getattr(state["setup"], "max_parallel_workers", total_parallel_tasks),
                    total_parallel_tasks)
                    
                async def deploy_operators_parallel():
                    loop = asyncio.get_running_loop()
                    nonlocal executor
                    executor = ThreadPoolExecutor(max_workers=max_workers)
                    try:
                        tasks = []
                        
                        # Add all operators as individual tasks
                        for operator_type in operator_types:
                            tasks.append(loop.run_in_executor(executor, deploy_single_operator, operator_type))
                        
                        results = await asyncio.gather(*tasks)
                        return all(results)
                    except asyncio.CancelledError:
                        state["logger"].info("Async tasks cancelled, shutting down executor...")
                        if executor:
                            executor.shutdown(wait=False)
                            executor = None
                        raise
                    finally:
                        if executor:
                            executor.shutdown(wait=True)
                            executor = None
                
                try:
                    parallel_success = asyncio.run(deploy_operators_parallel())
                    all_success = all_success and parallel_success
                except KeyboardInterrupt:
                    raise  # Re-raise to be caught by outer handler
            else:
                # Sequential deployment
                for operator_type in operator_types:
                    success = deploy_single_operator(operator_type)
                    if not success:
                        all_success = False
    
    except KeyboardInterrupt:
        state["logger"].warning("Deployment interrupted by user (Ctrl+C)")
        console.print()
        console.print(Panel.fit(
            "⚠️  Deployment interrupted by user\n\n"
            "Cleaning up resources and shutting down gracefully...",
            title="[bold yellow]Keyboard Interrupt[/bold yellow]",
            border_style="yellow"
        ))
        
        # Shutdown executor if it exists
        if executor:
            state["logger"].info("Shutting down thread pool executor...")
            executor.shutdown(wait=False)
        
        # Mark incomplete operators as failed
        for operator_type in operator_types:
            if not tracker.statuses[operator_type].is_complete:
                tracker.complete_operator(
                    operator_type,
                    success=False,
                    error="Interrupted by user"
                )
        
        # Update display one final time
        if live._started:
            live.update(tracker.create_progress_display())
        
        console.print()
        
        # Show summary of what was completed vs interrupted
        completed_count = sum(1 for op in operator_types if tracker.statuses[op].is_successful)
        interrupted_count = len(operator_types) - completed_count
        
        if completed_count > 0:
            summary_msg = (
                f"⚠️  Deployment interrupted by user\n\n"
                f"[green]✓[/green] {completed_count} operator(s) deployed successfully\n"
                f"[yellow]⚠[/yellow] {interrupted_count} operator(s) interrupted\n\n"
                f"See detailed status below."
            )
        else:
            summary_msg = (
                f"⚠️  Deployment interrupted by user\n\n"
                f"All {interrupted_count} operator(s) were interrupted before completion.\n\n"
                f"See detailed status below."
            )
        
        console.print(Panel.fit(
            summary_msg,
            title="[bold yellow]Deployment Interrupted[/bold yellow]",
            border_style="yellow"
        ))
        
        return False
    
    finally:
        # Ensure Live display is properly stopped
        try:
            if live._started:
                live.stop()
        except Exception as e:
            state["logger"].warning(f"Error stopping live display: {e}")
        
        # Restore console logging handlers
        for handler in console_handlers:
            logger.addHandler(handler)
        
        # Generate README and display deployment folder - ALWAYS run this even if some deployments failed
        # This ensures users have documentation for successful deployments
        if hasattr(helm_deployer, 'generated_values_files') and helm_deployer.generated_values_files:
            try:
                # Generate README file with deployment details
                if hasattr(helm_deployer, 'deployment_folder'):
                    helm_deployer._generate_deployment_readme(
                        deployment_folder=helm_deployer.deployment_folder,
                        namespace=namespace,
                        operators=list(helm_deployer.generated_values_files.keys()),
                        chart_source=chart_source
                    )
                
                console.print()
                console.print(Panel.fit(
                    "[bold cyan]📁 Deployment Values Folder[/bold cyan]\n\n"
                    f"[white]All Helm values files have been saved to:[/white]\n"
                    f"[bold green]{helm_deployer.deployment_folder}[/bold green]\n\n"
                    "[white]This folder contains:[/white]\n"
                    "[cyan]•[/cyan] Values files for each deployed operator\n"
                    "[cyan]•[/cyan] README.md with deployment details and useful commands\n\n"
                    "[white]Deployed operators:[/white]\n" +
                    "\n".join([
                        f"[cyan]  •[/cyan] [bold]{op_type}[/bold]: {values_file.name}"
                        for op_type, values_file in helm_deployer.generated_values_files.items()
                    ]) + "\n\n"
                    "[yellow]📖 See README.md in the folder for:[/yellow]\n"
                    "[dim]  • Upgrade commands for each operator\n"
                    "  • Useful Helm commands (status, history, rollback)\n"
                    "  • Instructions for modifying values[/dim]",
                    border_style="cyan",
                    title="[bold cyan]✓ Deployment Files Saved[/bold cyan]"
                ))
                state["logger"].info(f"Deployment folder created: {helm_deployer.deployment_folder}")
                state["logger"].info("Helm values files generated:")
                for op_type, values_file in helm_deployer.generated_values_files.items():
                    state["logger"].info(f"  {op_type}: {values_file}")
            except Exception as e:
                state["logger"].error(f"Failed to generate deployment documentation: {e}")
                # Don't fail the entire deployment if README generation fails
    
    # Display completion summary
    display_deployment_complete(tracker, console)
    
    return all_success


def deploy() -> None:
    """
    Deploy the IBM Content Cortex Operator.
    
    This function orchestrates the deployment process by:
    1. Validating required descriptor files exist
    2. Checking prerequisites (connection, podman)
    3. Gathering deployment configuration (interactive or silent mode)
    4. Executing the operator deployment
    
    Raises:
        SystemExit: If prerequisites fail or user cancels deployment
    """
    # Store original signal handler for restoration
    original_sigint_handler = signal.getsignal(signal.SIGINT)
    
    def graceful_exit_handler(signum, frame):
        """Handle SIGINT (Ctrl+C) gracefully."""
        state["logger"].warning("Received interrupt signal (Ctrl+C)")
        # Restore original handler to allow force quit on second Ctrl+C
        signal.signal(signal.SIGINT, original_sigint_handler)
        raise KeyboardInterrupt()
    
    # Install graceful exit handler
    signal.signal(signal.SIGINT, graceful_exit_handler)
    # Get descriptor files from centralized operator configuration
    # This leverages the existing operator_config module for consistency
    try:
        content_descriptor_files = get_descriptor_files(OperatorType.CONTENT)
    except Exception as e:
        state["logger"].error(f"Failed to retrieve descriptor files: {e}")
        console.print(Panel(
            f"[red]✗[/red] Unable to load operator configuration.\n"
            f"Error: {str(e)}",
            title="Configuration Error",
            border_style="red"
        ))
        raise typer.Exit(code=1)
    
    # Build required descriptor files mapping for validation
    # This structure supports future multi-operator deployments
    required_descriptor_files = {
        OperatorType.CONTENT.value: content_descriptor_files
    }
    
    # Resolve descriptor base path with fallback logic
    descriptor_path = Path.cwd().parent / "descriptors"
    if not descriptor_path.exists():
        # Fallback for different execution contexts
        descriptor_path = Path(__file__).parent.parent / "descriptors"
        if not descriptor_path.exists():
            state["logger"].error(f"Descriptor directory not found: {descriptor_path}")
            console.print(Panel(
                f"[red]✗[/red] Descriptor directory not found.\n"
                f"Expected location: {descriptor_path}\n"
                f"Please ensure you're running from the correct directory.",
                title="Directory Error",
                border_style="red"
            ))
            raise typer.Exit(code=1)

    # Read version configuration
    version_path = Path.cwd().parent / "version.toml"
    if not version_path.exists():
        version_path = Path.cwd().parent.parent / "version.toml"

    if version_path.exists():
        version_data = read_version_toml(str(version_path), state["logger"])
    else:
        state["logger"].warning("version.toml not found, proceeding without version data")
        version_data = {}

    # Validate prerequisites (tools only, not files yet)
    # File validation will happen after deployment type selection
    # Helm CLI is always required (only Helm deployments supported)
    checks = ["connection", "helm"]
    # Note: Helm chart validation happens AFTER operator selection in _handle_chart_validation_and_download()
    
    missing_tools, results, files = prereq_checks(
        logger=state["logger"],
        prereqs=checks,
        files=[],  # Don't validate files yet - deployment type not selected
        helm_chart_source=state["helm_chart_source"]  # Pass chart source for validation
    )

    # Validate prerequisites and display results (tools only)
    _handle_prerequisite_validation(
        missing_tools=missing_tools,
        files=[],  # No file validation at this stage
        results=results,
        logger=state["logger"]
    )
    
    # Perform health checks before gathering configuration (interactive mode only)
    if not state["silent"]:
        health_success, health_warnings, health_metrics = _handle_health_checks(
            logger=state["logger"],
            results=results,
            namespace=""  # Will be populated after namespace collection
        )
    
    if not state["silent"]:
        state["setup"] = g.GatherOptions(state["logger"], console, script_type="deploy", dev=state["dev"], tls_verify=state["tls_verify"])
        state["setup"].podman_available = results["podman"]
        state["setup"].helm_chart_source = state["helm_chart_source"]  # Store Helm chart source
        state["setup"].collect_license_model(version_data)
        
        # ============================================================
        # STEP 1: COLLECT NAMESPACE FIRST
        # ============================================================
        # Collect namespace before detection so we know which namespace to scan
        state["setup"].collect_namespace()
        
        # ============================================================
        # STEP 2: DETECT EXISTING INSTALLATIONS AND VERSION COMPARISON
        # ============================================================
        # Detect existing operator installations (OLM, Helm, YAML) BEFORE operator selection
        # This provides users with full context about their current system state
        # Note: Detection runs for both Helm and OLM deployment modes
        state["logger"].info("Detecting existing operator installations...")
        
        # Get namespace from setup (now it's been collected)
        target_namespace = state["setup"].namespace
        
        # Detect existing installations
        detection_results = detect_existing_installations(
            namespace=target_namespace,
            logger=state["logger"],
            console=console
        )
        
        # Store detection results in state for later use
        
        # Detect operator installation type (OLM/YAML/Helm) for upgrade/migration
        # This is used for Helm deployments to handle migration from OLM or YAML
        state["logger"].info("Detecting operator installation type for upgrade/migration...")
        if True:  # Always run for Helm deployments
            from helper_scripts.utilities.kubernetes_utilites import KubernetesUtilities
            k8s_utils_for_detection = KubernetesUtilities(state["logger"])
            operator_install_info = detect_operator_installation_type(
                namespace=target_namespace,
                k8s_utils=k8s_utils_for_detection,
                logger=state["logger"]
            )
            
            # Store installation info in state for deploy_with_helm() to use
            state["operator_install_info"] = operator_install_info
            
            # Log detection results
            if operator_install_info['has_olm']:
                state["logger"].info(f"✓ Detected OLM-based operator: {operator_install_info.get('deployment_name', 'unknown')}")
            if operator_install_info['has_yaml']:
                state["logger"].info(f"✓ Detected YAML-based operator: {operator_install_info.get('deployment_name', 'unknown')}")
            if not operator_install_info['has_olm'] and not operator_install_info['has_yaml']:
                state["logger"].info("No legacy operator installation detected (fresh install or Helm-based)")
        state["detection_results"] = detection_results
        
        # ============================================================
        # STEP 3: VERSION COMPARISON AND OPERATOR TRACKING
        # ============================================================
        # Get target version from version_data
        target_version = version_data.get("version", "26.0.0") if version_data else "26.0.0"
        
        # Define expected versions for each operator type from version.toml
        # Each operator may have its own version scheme
        operator_target_versions = {
            'content': version_data.get("content", {}).get("version", target_version) if version_data else target_version,
            'ai-services': version_data.get("ai-services", {}).get("version", target_version) if version_data else target_version,
            'usage-metering': version_data.get("usage-metering", {}).get("version", "1.0.6") if version_data else "1.0.6",
            'licensing': version_data.get("license-service", {}).get("version", "4.2.23") if version_data else "4.2.23"
        }
        
        # Track operator status: which are current, which need install/upgrade
        # Perform version tracking for Helm deployments
        operator_status = {}

        if detection_results['has_helm']:
                helm_releases = detection_results['helm_releases']
                
                # Map of operator release names to their types
                operator_map = {
                    'ibm-content-operator': 'content',
                    'ibm-ccx-ai-services-operator': 'ai-services',
                    'ibm-usage-metering': 'usage-metering',
                    'ibm-licensing-cluster-scoped': 'licensing'
                }
                
                # Check versions of detected operators
                for release in helm_releases:
                    release_name = release['name']
                    release_version = release['version']
                    
                    # Extract base version (remove build metadata like +20260525.133324.0)
                    base_version = release_version.split('+')[0] if '+' in release_version else release_version
                    
                    if release_name in operator_map:
                        operator_type = operator_map[release_name]
                        
                        # Get the target version for this specific operator
                        operator_target = operator_target_versions.get(operator_type, target_version)
                        
                        # Check if version matches target (compare only major.minor.patch)
                        is_current = (base_version == operator_target or base_version.startswith(operator_target))
                        
                        operator_status[operator_type] = {
                            'installed': True,
                            'current_version': base_version,
                            'is_current': is_current,
                            'needs_action': not is_current,
                            'action': 'none' if is_current else 'upgrade',
                            'target_version': operator_target
                        }
                        
                        if is_current:
                            state["logger"].info(f"{release_name} is at target version {base_version} - will skip")
                        else:
                            state["logger"].info(f"{release_name} is at version {base_version}, target is {operator_target} - needs upgrade")
        
        # Check for OLM resources (CSVs) that indicate installed operators
        # This runs for BOTH Helm and OLM deployment modes to detect existing installations
        if detection_results.get('has_olm'):
            olm_csvs = detection_results.get('olm_resources', {}).get('csvs', [])
            
            # Map CSV prefixes to operator types (including legacy ibm-fncm-operator)
            csv_operator_map = {
                'ibm-fncm-operator': 'content',  # Legacy operator name
                'ibm-content-operator': 'content',
                'ibm-ccx-ai-services-operator': 'ai-services',
                'ibm-licensing-operator': 'licensing',
                'ibm-usage-metering': 'usage-metering'
            }
            
            for csv in olm_csvs:
                csv_name = csv.get('name', '')
                csv_version = csv.get('version', 'unknown')
                
                # Check which operator this CSV represents
                for csv_prefix, operator_type in csv_operator_map.items():
                    if csv_name.startswith(csv_prefix):
                        # Only add if not already tracked (Helm takes precedence)
                        if operator_type not in operator_status:
                            # Try to get version from CSV object first (most reliable)
                            current_version = csv_version
                            
                            # If version is still unknown, try extracting from CSV name
                            if current_version == 'unknown':
                                # Extract version from CSV name (e.g., ibm-fncm-operator.v57.0.1)
                                version_match = csv_name.split('.v')
                                if len(version_match) > 1:
                                    current_version = version_match[1]
                            
                            # Get target version for this operator
                            operator_target = operator_target_versions.get(operator_type, target_version)
                            
                            # Helm deployment - needs migration from OLM to Helm
                            operator_status[operator_type] = {
                                'installed': True,
                                'current_version': current_version,
                                'is_current': False,  # Always needs upgrade for OLM->Helm migration
                                'needs_action': True,
                                'action': 'upgrade',  # Will trigger migration
                                'target_version': operator_target,
                                'installation_type': 'OLM'
                            }
                            state["logger"].info(f"Detected OLM-based FNCM operator {csv_prefix} at version {current_version} - needs migration to Helm")
                            break
        
            # Check for YAML-based ibm-fncm-operator (legacy Content Operator) if not already detected via OLM
            if operator_install_info.get('has_yaml') and 'content' not in operator_status:
                deployment_name = operator_install_info.get('deployment_name')
                if deployment_name == 'ibm-fncm-operator':
                    # Get version from operator deployment if available
                    deployment_details = operator_install_info.get('deployment_details', {})
                    current_version = deployment_details.get('version', 'unknown')
                    
                    # If version is still unknown and we have detection results with operator deployment
                    if current_version == 'unknown' and detection_results.get('operator_deployment'):
                        current_version = detection_results['operator_deployment'].get('version', 'unknown')
                    
                    # Get target version for content operator
                    content_target = operator_target_versions.get('content', target_version)
                    
                    # Mark as needing upgrade (YAML to Helm migration)
                    operator_status['content'] = {
                        'installed': True,
                        'current_version': current_version,
                        'is_current': False,  # Always needs upgrade for YAML
                        'needs_action': True,
                        'action': 'upgrade',  # Will trigger migration
                        'target_version': content_target,
                        'installation_type': 'YAML'
                    }
                    
                    state["logger"].info(f"Detected YAML-based FNCM operator {deployment_name} at version {current_version} - needs migration to Helm")
        
        # Store operator status in state for later use
        state["operator_status"] = operator_status
        state["target_version"] = target_version
        
        # ============================================================
        # STEP 4: DISPLAY SYSTEM DASHBOARD WITH VERSION INFO
        # ============================================================
        # Display comprehensive system dashboard with operator status
        # This runs for both Helm and OLM deployment modes
        display_system_dashboard(
            detection_results=detection_results,
            namespace=target_namespace,
            console=console,
            logger=state["logger"],
            operator_status=operator_status
        )
            
        # ============================================================
        # CHECK IF ALL OPERATORS ARE CURRENT - EXIT IF NO ACTION NEEDED
        # ============================================================
        # Check if all operators are at target version
        if True:  # Always check for Helm deployments
            all_current = all(
                status.get("status") == "current"
                for status in operator_status.values()
            )
            
            # Get all possible operator keys
            all_op_keys = ['content', 'ai-services', 'usage-metering', 'licensing']
            
            # If all operators are current and we have status for all of them, exit gracefully
            if all_current and len(operator_status) == len(all_op_keys) and operator_status:
                if not state.get("force", False):
                    state["logger"].info("All operators are at target version - no deployment needed")
                    console.print()
                    console.print(Panel.fit(
                        "[bold green]✓ All Operators Current[/bold green]\n\n"
                        "All operators are already at the target version.\n"
                        "No deployment or upgrade is needed.\n\n"
                        "[dim]Use --force to redeploy anyway.[/dim]",
                        title="[bold green]✓ System Up to Date[/bold green]",
                        border_style="green"
                    ))
                    console.print()
                    state["logger"].info("Exiting - system is up to date")
                    raise typer.Exit(code=0)
                else:
                    state["logger"].info("Force flag enabled - proceeding with redeployment despite operators being current")
                    console.print()
                    console.print(Panel.fit(
                        "[bold yellow]⚠ Force Redeployment[/bold yellow]\n\n"
                        "All operators are already at the target version, but\n"
                        "--force flag is enabled. Proceeding with redeployment.",
                        title="[bold yellow]⚠ Forced Redeployment Mode[/bold yellow]",
                        border_style="yellow"
                    ))
                    console.print()
            
            # If OLM installation detected, show migration message
            # Check if there are actually relevant OLM resources (after filtering)
            has_relevant_olm = False
            if detection_results.get('has_olm'):
                olm_csvs = detection_results.get('olm_resources', {}).get('csvs', [])
                olm_catalogs = detection_results.get('olm_resources', {}).get('catalogs', [])
                
                # Filter catalogs to only Content Cortex operators
                content_cortex_catalog_prefixes = [
                    'ibm-fncm-operator',
                    'ibm-content-operator',
                    'ibm-ccx-ai-services-operator',
                    'ibm-licensing-operator',
                    'ibm-usage-metering'
                ]
                
                filtered_catalogs = [
                    catalog for catalog in olm_catalogs
                    if any(catalog['name'].startswith(prefix) for prefix in content_cortex_catalog_prefixes)
                ]
                
                has_relevant_olm = len(olm_csvs) > 0 or len(filtered_catalogs) > 0
            
            if has_relevant_olm:
                console.print(Panel.fit(
                    "[green]✓ OLM Installation Detected[/green]\n\n"
                    "An OLM-based operator installation was detected in your cluster.\n"
                    "The deployment will automatically migrate from OLM to Helm.\n\n"
                    "[cyan]Migration Process:[/cyan]\n"
                    "  1. OLM resources will be safely removed\n"
                    "  2. CRDs and Custom Resources will be preserved\n"
                    "  3. Helm-based operators will be deployed\n\n"
                    "[dim]This is a one-time migration that ensures a smooth transition.[/dim]",
                    title="[bold green]✓ Automatic OLM to Helm Migration[/bold green]",
                    border_style="green"
                ))
                console.print()
            elif detection_results.get('has_yaml') and operator_install_info.get('deployment_name') == 'ibm-fncm-operator':
                # Check if we have a YAML-based legacy operator
                console.print(Panel.fit(
                    "[green]✓ YAML Installation Detected[/green]\n\n"
                    "A YAML-based operator installation was detected in your cluster.\n"
                    "The deployment will automatically migrate from YAML to Helm.\n\n"
                    "[cyan]Migration Process:[/cyan]\n"
                    "  1. YAML resources will be safely removed\n"
                    "  2. CRDs and Custom Resources will be preserved\n"
                    "  3. Helm-based operators will be deployed\n\n"
                    "[dim]This is a one-time migration that ensures a smooth transition.[/dim]",
                    title="[bold green]✓ Automatic YAML to Helm Migration[/bold green]",
                    border_style="green"
                ))
                console.print()
        
        # ============================================================
        # STEP 5: OPERATOR SELECTION (AUTO-SELECT OR PROMPT)
        # ============================================================
        # Check if both Content AND AI Services are installed
        # If either is missing, show operator selection prompt
        # If both are present, auto-select operators needing action
        content_installed = 'content' in operator_status
        ai_services_installed = 'ai-services' in operator_status
        should_auto_select = content_installed and ai_services_installed
        
        if should_auto_select:
            state["logger"].info("Core operators detected - auto-selecting operators needing action")
            
            # Count operators by action needed
            ops_to_install = []
            ops_to_upgrade = []
            ops_current = []
            
            for op_key, op_info in operator_status.items():
                if op_info.get('is_current'):
                    ops_current.append(op_key)
                elif op_info.get('needs_action'):
                    ops_to_upgrade.append(op_key)
            
            # Check which operators are not installed
            all_op_keys = ['content', 'ai-services', 'licensing', 'usage-metering']
            for op_key in all_op_keys:
                if op_key not in operator_status:
                    ops_to_install.append(op_key)
            
            # Auto-select only operators that need action (install or upgrade)
            # Map operator keys to OperatorType enum
            op_key_to_type = {
                'content': OperatorType.CONTENT,
                'ai-services': OperatorType.AI_SERVICES,
                'licensing': OperatorType.LICENSE_ADVISOR,
                'usage-metering': OperatorType.USAGE_METERING
            }
            
            selected_ops = []
            for op_key in ops_to_install + ops_to_upgrade:
                if op_key in op_key_to_type:
                    selected_ops.append(op_key_to_type[op_key])
            
            # If no operators need action, exit gracefully (unless --force is used)
            if not selected_ops:
                if not state.get("force", False):
                    state["logger"].info("No operators need action - all are at target version")
                    console.print()
                    console.print(Panel.fit(
                        "[bold green]✓ All Operators Current[/bold green]\n\n"
                        "All operators are already at the target version.\n"
                        "No deployment or upgrade is needed.\n\n"
                        "[dim]Use --force to redeploy anyway.[/dim]",
                        title="[bold green]✓ System Up to Date[/bold green]",
                        border_style="green"
                    ))
                    console.print()
                    state["logger"].info("Exiting - system is up to date")
                    raise typer.Exit(code=0)
                else:
                    # Force flag enabled - redeploy all operators
                    state["logger"].info("Force flag enabled - redeploying all operators despite being current")
                    console.print()
                    console.print(Panel.fit(
                        "[bold yellow]⚠ Force Redeployment[/bold yellow]\n\n"
                        "All operators are already at the target version, but\n"
                        "--force flag is enabled. Proceeding with redeployment of all operators.",
                        title="[bold yellow]⚠ Forced Redeployment Mode[/bold yellow]",
                        border_style="yellow"
                    ))
                    console.print()
                    # Add all operators to selected_ops for redeployment
                    selected_ops = [
                        op_key_to_type['content'],
                        op_key_to_type['ai-services'],
                        op_key_to_type['licensing'],
                        op_key_to_type['usage-metering']
                    ]
                    # Mark all as needing upgrade for force deployment
                    ops_to_upgrade = ['content', 'ai-services', 'licensing', 'usage-metering']
                    ops_to_install = []
                    ops_current = []
            
            state["setup"].selected_operators = selected_ops
            state["logger"].info(f"Auto-selected operators needing action: {[op.value for op in selected_ops]}")
            
            # Build generic message based on what needs to be done
            action_parts = []
            if ops_to_install:
                action_parts.append(f"[cyan]{len(ops_to_install)} operator(s) will be installed[/cyan]")
            if ops_to_upgrade:
                action_parts.append(f"[yellow]{len(ops_to_upgrade)} operator(s) will be upgraded[/yellow]")
            if ops_current and not state.get("force", False):
                action_parts.append(f"[green]{len(ops_current)} operator(s) already current[/green]")
            
            action_summary = ", ".join(action_parts) if action_parts else "No action needed"
            
            message = (
                "[green]✓ Existing Deployment Detected[/green]\n\n"
                "Core operators are already installed.\n\n"
                f"Action Plan: {action_summary}"
            )
            
            console.print()
            console.print(Panel.fit(
                message,
                title="[bold green]Operator Configuration[/bold green]",
                border_style="green"
            ))
            console.print()
        else:
            # Prompt for operator selection if Content or AI Services is missing
            state["logger"].info("Core operators not fully installed - prompting for operator selection")
            state["setup"].collect_operator_type(operator_status=state.get("operator_status"))
            
            # ============================================================
            # CHECK IF ALL SELECTED OPERATORS ARE CURRENT - EXIT IF NO ACTION NEEDED
            # ============================================================
            # After operator selection, check if all selected operators are already at target version
            if hasattr(state["setup"], 'selected_operators') and state["setup"].selected_operators:
                operators_to_deploy = []
                operator_status = state.get("operator_status", {})
                
                # Map operator types to status keys
                op_type_to_key = {
                    'content': 'content',
                    'ai-services': 'ai-services',
                    'license-service': 'licensing',
                    'usage-metering': 'usage-metering'
                }
                
                # Check each selected operator
                for op in state["setup"].selected_operators:
                    op_value = op.value
                    status_key = op_type_to_key.get(op_value, op_value)
                    
                    # If operator is in status and is current, it will be skipped
                    if status_key in operator_status:
                        if not operator_status[status_key].get('is_current', False):
                            operators_to_deploy.append(op_value)
                    else:
                        # Operator not in status means it needs to be installed
                        operators_to_deploy.append(op_value)
                
                # If no operators need deployment, exit gracefully (unless --force is used)
                if not operators_to_deploy:
                    if not state.get("force", False):
                        state["logger"].info("All selected operators are at target version - no deployment needed")
                        console.print()
                        console.print(Panel.fit(
                            "[bold green]✓ All Operators Current[/bold green]\n\n"
                            "All selected operators are already at the target version.\n"
                            "No deployment or upgrade is needed.\n\n"
                            "[dim]Use --force to redeploy anyway.[/dim]",
                            title="[bold green]✓ System Up to Date[/bold green]",
                            border_style="green"
                        ))
                        console.print()
                        state["logger"].info("Exiting - system is up to date")
                        raise typer.Exit(code=0)
                    else:
                        # Force flag enabled - redeploy selected operators
                        state["logger"].info("Force flag enabled - redeploying selected operators despite being current")
                        console.print()
                        console.print(Panel.fit(
                            "[bold yellow]⚠ Force Redeployment[/bold yellow]\n\n"
                            "Selected operators are already at the target version, but\n"
                            "--force flag is enabled. Proceeding with redeployment.",
                            title="[bold yellow]⚠ Forced Redeployment Mode[/bold yellow]",
                            border_style="yellow"
                        ))
                        console.print()
                        # Add all selected operators to deploy list
                        operators_to_deploy = [op.value for op in state["setup"].selected_operators]
                        state["logger"].info(f"Force-deploying selected operators: {operators_to_deploy}")
        
        # ============================================================
        # STEP 4: DISPLAY MIGRATION/UPGRADE WARNING PANEL
        # ============================================================
        # Show migration panel if OLM or YAML installation detected
        # This appears BEFORE airgap configuration to inform users early
        # Use detection_results instead of operator_install_info for accurate detection
        detection_results = state.get("detection_results", {})
        has_olm = detection_results.get("has_olm", False)
        has_yaml = detection_results.get("has_yaml", False)
        
        # Debug logging
        state["logger"].info(f"Migration panel check (before airgap) - detection_results: {detection_results}")
        state["logger"].info(f"Migration panel check (before airgap) - has_olm: {has_olm}, has_yaml: {has_yaml}")
        
        if has_olm or has_yaml:
            # Build migration message based on what was detected
            migration_types = []
            if has_olm:
                migration_types.append("OLM")
            if has_yaml:
                migration_types.append("YAML")
            
            migration_desc = " and ".join(migration_types)
            
            # Show migration warning
            migration_steps = []
            step_num = 1
            if has_olm:
                migration_steps.append(f"  [yellow]{step_num}.[/yellow] Remove old FNCM OLM deployment (catalog, subscription)")
                step_num += 1
            if has_yaml:
                migration_steps.append(f"  [yellow]{step_num}.[/yellow] Remove old FNCM YAML-based operator deployment")
                step_num += 1
            migration_steps.append(f"  [yellow]{step_num}.[/yellow] Install FNCM operators using Helm charts")
            
            print(Panel(
                f"[bold red]⚠️  IMPORTANT: FNCM Operator Migration from {migration_desc} to Helm[/bold red]\n\n"
                "[bold white]This upgrade will:[/bold white]\n"
                + "\n".join(migration_steps) + "\n\n"
                "[bold white]What will be preserved:[/bold white]\n"
                "  [green]✓[/green] Custom Resource Definitions (CRDs) will [bold green]NOT[/bold green] be removed\n"
                "  [green]✓[/green] Your existing Custom Resources (CRs) will remain intact\n"
                "  [green]✓[/green] All deployed workloads will continue running\n"
                "  [green]✓[/green] IBM License Service (if installed) will remain unchanged\n\n"
                "[bold yellow]Before proceeding:[/bold yellow]\n"
                "  [cyan]•[/cyan] Ensure you have backed up your configuration\n"
                "  [cyan]•[/cyan] Review the upgrade plan above carefully\n"
                "  [cyan]•[/cyan] Verify namespace and operator versions are correct\n\n"
                "[bold cyan]After operator upgrade:[/bold cyan]\n"
                "  [cyan]•[/cyan] Your FNCM operators will be managed by Helm\n"
                "  [cyan]•[/cyan] Use [white]helm list -n <namespace>[/white] to view releases",
                title="[bold yellow]⚠️  Upgrade Warning[/bold yellow]",
                border_style="yellow",
                padding=(1, 2),
                expand=False
            ))
            print()
        
        # ============================================================
        # STEP 5: COLLECT AIRGAP CONFIGURATION
        # ============================================================
        airgap_config = state["setup"].collect_airgap_configuration()
        
        # Store airgap config in state for use in Phase 1 secret creation
        state["airgap_config"] = airgap_config
        
        # ============================================================
        # CHECK FOR EXISTING IBM LICENSING OLM INSTALLATION
        # ============================================================
        # Check BEFORE chart download - if license-service OLM exists and user wants to keep it,
        # we can skip downloading the license-service chart entirely
        if hasattr(state["setup"], 'selected_operators'):
            # Check if license-service is in the selected operators
            has_license_service = any(
                op == OperatorType.LICENSE_ADVISOR
                for op in state["setup"].selected_operators
            )
            
            if has_license_service:
                from helper_scripts.utilities.kubernetes_utilites import KubernetesUtilities
                k8s_utils = KubernetesUtilities(state["logger"])
                
                state["logger"].info("Checking for existing IBM Licensing OLM installation...")
                licensing_check = k8s_utils.detect_olm_resources(
                    "ibm-licensing",
                    csv_prefixes=["ibm-licensing-operator"]
                )
                
                if licensing_check["has_olm"]:
                    state["logger"].info("IBM Licensing OLM installation detected")
                    
                    console.print()
                    console.print(Panel.fit(
                        "[yellow]ℹ️  Existing IBM Licensing Installation Detected[/yellow]\n\n"
                        "An OLM-based IBM Licensing operator is already installed in the [cyan]ibm-licensing[/cyan] namespace.\n\n"
                        "[bold]Choose how to proceed:[/bold]\n"
                        "  • [cyan]Keep OLM installation[/cyan] - Skip Helm deployment of License Service (recommended if working)\n"
                        "  • [cyan]Replace with Helm[/cyan] - Remove OLM installation and deploy with Helm\n"
                        "  • [cyan]Cancel deployment[/cyan] - Exit to review manually",
                        title="[bold yellow]IBM Licensing Deployment Decision[/bold yellow]",
                        border_style="yellow"
                    ))
                    
                    # Display detected OLM resources
                    if licensing_check["csvs"]:
                        console.print("\n[bold]Detected OLM Resources:[/bold]")
                        for csv in licensing_check["csvs"]:
                            console.print(f"  • CSV: [cyan]{csv['name']}[/cyan]")
                    
                    try:
                        choice = questionary.select(
                            "How should we handle the existing IBM Licensing installation?",
                            choices=[
                                questionary.Choice("Keep OLM installation (skip Helm deployment)", value="keep", shortcut_key="k"),
                                questionary.Choice("Replace with Helm deployment", value="replace", shortcut_key="r"),
                                questionary.Choice("Cancel deployment", value="cancel", shortcut_key="c")
                            ],
                            default="keep"
                        ).ask()
                        
                        # Handle cancellation (Ctrl+C/ESC returns None)
                        choice = handle_cancelled_prompt(choice, "Licensing installation handling cancelled by user")
                    except Exception:
                        # Fallback if questionary fails
                        keep = Confirm.ask(
                            "Keep existing OLM-based IBM Licensing installation?",
                            default=True
                        )
                        choice = "keep" if keep else "replace"
                    
                    if choice == "cancel":
                        console.print("\n[yellow]Deployment cancelled by user[/yellow]")
                        raise typer.Exit(code=0)
                    elif choice == "keep":
                        # Remove license-service from selected operators
                        state["setup"].selected_operators = [
                            op for op in state["setup"].selected_operators
                            if op != OperatorType.LICENSE_ADVISOR
                        ]
                        state["keep_olm_licensing"] = True
                        console.print("[green]✓[/green] Will keep OLM-based IBM Licensing installation")
                        console.print("[dim]  License Service chart download and Helm deployment will be skipped[/dim]")
                        state["logger"].info("User chose to keep OLM-based IBM Licensing - removed from deployment list")
                    else:  # replace
                        state["keep_olm_licensing"] = False
                        state["replace_olm_licensing"] = True
                        console.print("[yellow]⚠[/yellow] Will replace OLM installation with Helm")
                        console.print("[dim]  OLM resources will be removed during deployment[/dim]")
                        state["logger"].info("User chose to replace OLM-based IBM Licensing with Helm")
                    
                    console.print()
                else:
                    state["logger"].info("No IBM Licensing OLM installation detected")
                    state["keep_olm_licensing"] = False
        
        # ============================================================
        # HELM CHART VALIDATION/DOWNLOAD (After migration panel and OLM check)
        # ============================================================
        # Now that operators are selected (and potentially modified based on OLM detection),
        # validate/download charts for the remaining operators
        # Always use Helm deployment
        _handle_chart_validation_and_download(
            state=state,
            console=console,
            version_data=version_data
        )
        
        # Private catalog not needed for Helm deployments
        state["setup"]._private_catalog = False
    else:
        silent_path = str(Path("silent_config") / "silent_install_deployoperator.toml")
        
        # Validate configuration with Pydantic before proceeding
        state["logger"].info(f"Validating configuration file: {silent_path}")
        try:
            import toml
            with open(silent_path, 'r') as f:
                config_dict = toml.load(f)

            success, validated_config, validation_errors = validate_deploy_operator_config(config_dict)

            if not success:
                print(display_config_validation_errors(validation_errors, silent_path))
                exit(1)

            state["logger"].info("✓ Configuration validated successfully")
            
        except FileNotFoundError:
            print(Panel.fit(f"❌ Configuration file not found: {silent_path}", style="bold red"))
            exit(1)
        except toml.TomlDecodeError as e:
            print(display_toml_syntax_error(e, silent_path))
            exit(1)
        except Exception as e:
            state["logger"].error(f"Unexpected error loading configuration: {str(e)}")
            print(Panel.fit(f"❌ Unexpected error: {str(e)}", style="bold red"))
            exit(1)
        
        # Proceed with silent gather after validation
        state["setup"] = sg.SilentGatherOptions(state["logger"],
                                                silent_path, script_type="deploy", dev=state["dev"], tls_verify=state["tls_verify"])
        state["setup"].podman_available = results["podman"]
        state["setup"].silent_parse_deploy_operator_file(state["validate"], version_data)
        
        # ============================================================
        # CHECK FOR EXISTING IBM LICENSING OLM INSTALLATION (Silent mode)
        # ============================================================
        # Check BEFORE chart download - if license-service OLM exists,
        # automatically skip it in silent mode (keep existing OLM)
        if hasattr(state["setup"], 'selected_operators'):
            # Check if license-service is in the selected operators
            has_license_service = any(
                op == OperatorType.LICENSE_ADVISOR
                for op in state["setup"].selected_operators
            )
            
            if has_license_service:
                from helper_scripts.utilities.kubernetes_utilites import KubernetesUtilities
                k8s_utils = KubernetesUtilities(state["logger"])
                
                state["logger"].info("Checking for existing IBM Licensing OLM installation (silent mode)...")
                licensing_check = k8s_utils.detect_olm_resources(
                    "ibm-licensing",
                    csv_prefixes=["ibm-licensing-operator"]
                )
                
                if licensing_check["has_olm"]:
                    # In silent mode, automatically keep existing OLM installation
                    state["logger"].info("IBM Licensing OLM detected - will keep existing installation (silent mode)")
                    console.print("[yellow]ℹ️[/yellow] Existing IBM Licensing OLM detected - keeping existing installation")
                    
                    # Remove license-service from selected operators
                    state["setup"].selected_operators = [
                        op for op in state["setup"].selected_operators
                        if op != OperatorType.LICENSE_ADVISOR
                    ]
                    state["keep_olm_licensing"] = True
                    state["logger"].info("Removed license-service from deployment list (silent mode - keeping OLM)")
                else:
                    state["logger"].info("No IBM Licensing OLM installation detected (silent mode)")
                    state["keep_olm_licensing"] = False
        
        # ============================================================
        # HELM CHART VALIDATION/DOWNLOAD (Silent mode - after config loaded and OLM check)
        # ============================================================
        # Always use Helm deployment
        _handle_chart_validation_and_download(
            state=state,
            console=console,
            version_data=version_data
        )

    deployment_details = create_deployment_info(state["setup"], version_data, use_helm=True)
    state["logger"].info(f"Created deployment details: {deployment_details}")
    version_details = create_version_info(state["setup"], version_data)
    state["logger"].info(f"Created version details: {version_details}")

    clear(console)
    # Always use enhanced multi-operator display (even for single operator)
    if hasattr(state["setup"], 'selected_operators') and len(state["setup"].selected_operators) > 0:
        layout = deploy_details_multi_operator(
            deployment_details,
            version_details,
            state["setup"].selected_operators,
            version_data,
            operator_status=state.get("operator_status")  # Pass operator status for filtering
        )
    else:
        # Fallback to single operator display only if no operators selected (shouldn't happen)
        layout = deploy_details(deployment_details, version_details)
    print(layout)

    # ============================================================
    # CHECK IF ALL OPERATORS ARE SKIPPED - EXIT IF NO ACTION NEEDED
    # ============================================================
    # After displaying deployment configuration, check if any operators will actually be deployed
    # If all are skipped (already at target version), exit gracefully
    if hasattr(state["setup"], 'selected_operators') and state["setup"].selected_operators:
        operators_to_deploy = []
        operator_status = state.get("operator_status", {})
        
        state["logger"].info(f"Checking if operators need deployment. Operator status: {operator_status}")
        state["logger"].info(f"Selected operators: {[op.value for op in state['setup'].selected_operators]}")
        
        # Map operator types to status keys
        op_type_to_key = {
            'content': 'content',
            'ai-services': 'ai-services',
            'license-service': 'licensing',
            'usage-metering': 'usage-metering'
        }
        
        # Check each selected operator to see if it needs deployment
        for op in state["setup"].selected_operators:
            op_value = op.value
            status_key = op_type_to_key.get(op_value, op_value)
            
            state["logger"].info(f"Checking operator {op_value} (status_key: {status_key})")
            
            # If operator is in status and is current, it will be skipped
            if status_key in operator_status:
                is_current = operator_status[status_key].get('is_current', False)
                state["logger"].info(f"  - Found in status, is_current: {is_current}")
                if not is_current:
                    operators_to_deploy.append(op_value)
                    state["logger"].info(f"  - Added to deploy list (needs upgrade)")
                else:
                    state["logger"].info(f"  - Skipped (already current)")
            else:
                # Operator not in status means it needs to be installed
                operators_to_deploy.append(op_value)
                state["logger"].info(f"  - Not in status, added to deploy list (needs install)")
        
        state["logger"].info(f"Operators to deploy: {operators_to_deploy}")
        
        # If no operators need deployment, exit gracefully (unless --force is used)
        if not operators_to_deploy:
            if not state.get("force", False):
                state["logger"].info("All selected operators are at target version - no deployment needed")
                console.print()
                console.print(Panel.fit(
                    "[bold green]✓ All Operators Current[/bold green]\n\n"
                    "All selected operators are already at the target version.\n"
                    "No deployment or upgrade is needed.\n\n"
                    "[dim]Use --force to redeploy anyway.[/dim]",
                    title="[bold green]✓ System Up to Date[/bold green]",
                    border_style="green"
                ))
                console.print()
                state["logger"].info("Exiting - system is up to date")
                raise typer.Exit(code=0)
            else:
                # Force flag enabled - redeploy selected operators
                state["logger"].info("Force flag enabled - redeploying selected operators despite being current")
                console.print()
                console.print(Panel.fit(
                    "[bold yellow]⚠ Force Redeployment[/bold yellow]\n\n"
                    "Selected operators are already at the target version, but\n"
                    "--force flag is enabled. Proceeding with redeployment.",
                    title="[bold yellow]⚠ Forced Redeployment Mode[/bold yellow]",
                    border_style="yellow"
                ))
                console.print()
                # Add all selected operators to deploy list
                operators_to_deploy = [op.value for op in state["setup"].selected_operators]
                state["logger"].info(f"Force-deploying selected operators: {operators_to_deploy}")

    # ============================================================
    # Initialize HelmDeployer for CRD checks (if using Helm)
    # ============================================================
    # Chart validation already happened after operator selection
    helm_deployer = None
    # Always initialize HelmDeployer for CRD checks
    state["logger"].info("Initializing Helm deployer for CRD checks...")
    helm_deployer = HelmDeployer(
        logger=state["logger"],
        console=console,
        version_data=version_data,
        dev_mode=state.get("dev", False),
        github_token=os.environ.get('GITHUB_TOKEN')
    )
    
    # ============================================================
    # SIMPLIFIED CRD CHECK (Before deployment confirmation)
    # ============================================================
    # Only check if CRDs exist, then prompt user for ownership decision
    skip_crd_for_operators = {}
    force_crd_takeover_for_operators = {}
    
    if not state["silent"] and helm_deployer is not None:
        # Determine which operators will be deployed (filter out operators already at target version unless --force)
        operators_to_check = []
        operator_status = state.get("operator_status", {})
        force_mode = state.get("force", False)
        
        # Map operator types to status keys
        status_key_map = {
            'content': 'content',
            'ai-services': 'ai-services',
            'usage-metering': 'usage-metering',
            'license-service': 'licensing'
        }
        
        if hasattr(state["setup"], 'selected_operators') and state["setup"].selected_operators:
            # Filter by status - only check CRDs for operators that will be deployed (unless force mode)
            for op in state["setup"].selected_operators:
                op_value = op.value
                status_key = status_key_map.get(op_value, op_value)
                
                # Only check CRDs if operator needs action (not already current) OR force mode is enabled
                if status_key in operator_status:
                    if not operator_status[status_key].get('is_current', False):
                        operators_to_check.append(op_value)
                        state["logger"].info(f"Will check CRDs for {op_value} - needs action")
                    elif force_mode:
                        operators_to_check.append(op_value)
                        state["logger"].info(f"Force mode: Will check CRDs for {op_value} - forcing redeployment")
                    else:
                        state["logger"].info(f"Skipping CRD check for {op_value} - already at target version")
                else:
                    # Operator not in status (new install)
                    operators_to_check.append(op_value)
                    state["logger"].info(f"Will check CRDs for {op_value} - new installation")
        else:
            operators_to_check = ["content"]
        
        state["logger"].info(f"Operators to check for CRDs: {operators_to_check}")
        
        # Check for existing CRDs
        state["logger"].info("Checking for existing CRDs...")
        crd_status = helm_deployer.check_existing_crds(operators_to_check)
        
        # Filter to only operators with existing CRDs
        existing_crds = {op: info for op, info in crd_status.items() if info is not None}
        
        if existing_crds:
            # Display detected CRDs
            table = Table(title="📋 Existing CRDs Detected", show_header=True, border_style="yellow")
            table.add_column("Operator", style="cyan")
            table.add_column("CRD Name", style="white")
            table.add_column("Version", style="green")
            
            for operator_type, crd_data in existing_crds.items():
                op_config = helm_deployer.OPERATOR_CHARTS.get(operator_type, {})
                crd_list = crd_data if isinstance(crd_data, list) else [crd_data]
                
                for crd_info in crd_list:
                    table.add_row(
                        op_config.get('display_name', operator_type),
                        crd_info.get("name", "unknown"),
                        crd_info.get("version", "unknown")
                    )
            
            console.print(table)
            console.print()
            
            console.print(Panel.fit(
                "[yellow]ℹ️  Existing CRDs Detected[/yellow]\n\n"
                "One or more Custom Resource Definitions (CRDs) already exist in the cluster.\n\n"
                "[bold]Choose how to proceed:[/bold]\n"
                "  • [cyan]Let Helm take ownership[/cyan] - Helm will manage these CRDs (recommended)\n"
                "  • [cyan]Skip CRD installation[/cyan] - Keep existing CRDs as-is\n"
                "  • [cyan]Cancel deployment[/cyan] - Exit to review manually",
                title="[bold yellow]CRD Management Decision[/bold yellow]",
                border_style="yellow"
            ))
            
            # Prompt for each operator with existing CRDs
            for operator_type, crd_data in existing_crds.items():
                op_config = helm_deployer.OPERATOR_CHARTS.get(operator_type, {})
                crd_list = crd_data if isinstance(crd_data, list) else [crd_data]
                
                # Display CRDs for this operator
                console.print(f"\n[bold cyan]Operator:[/bold cyan] {op_config.get('display_name', operator_type)}")
                for crd_info in crd_list:
                    console.print(f"  • [dim]{crd_info.get('name', 'unknown')}[/dim]")
                
                choice = questionary.select(
                    f"How should Helm handle CRDs for {op_config.get('display_name', operator_type)}?",
                    choices=[
                        questionary.Choice(
                            "Let Helm take ownership (recommended)",
                            value="takeover",
                            shortcut_key="t"
                        ),
                        questionary.Choice(
                            "Skip CRD installation",
                            value="skip",
                            shortcut_key="s"
                        ),
                        questionary.Choice(
                            "Cancel deployment",
                            value="cancel",
                            shortcut_key="c"
                        )
                    ],
                    default="takeover"
                ).ask()
                
                # Handle cancellation (Ctrl+C/ESC returns None)
                choice = handle_cancelled_prompt(choice, "CRD management cancelled by user")
                
                if choice == "cancel":
                    console.print("\n[yellow]Deployment cancelled by user[/yellow]")
                    exit(1)
                elif choice == "skip":
                    skip_crd_for_operators[operator_type] = True
                    force_crd_takeover_for_operators[operator_type] = False
                    console.print(f"[green]✓[/green] Will skip CRD installation for {operator_type}")
                else:  # takeover
                    skip_crd_for_operators[operator_type] = False
                    force_crd_takeover_for_operators[operator_type] = True
                    console.print(f"[green]✓[/green] Helm will take ownership of CRDs for {operator_type}")
            
            console.print()
    elif state["silent"] and helm_deployer is not None:
        # Silent mode: check CRDs and auto-skip if they exist
        operators_to_check = []
        if hasattr(state["setup"], 'selected_operators') and state["setup"].selected_operators:
            for op in state["setup"].selected_operators:
                operators_to_check.append(op.value)
        else:
            operators_to_check = ["content"]
        
        state["logger"].info("Checking for existing CRDs (silent mode)...")
        crd_status = helm_deployer.check_existing_crds(operators_to_check)
        
        existing_crds = {op: info for op, info in crd_status.items() if info is not None}
        if existing_crds:
            state["logger"].warning("Silent mode: Existing CRDs detected, will skip CRD installation")
            for operator_type in existing_crds.keys():
                skip_crd_for_operators[operator_type] = True
                force_crd_takeover_for_operators[operator_type] = False
    
    # Store CRD skip and force decisions in state for use in deploy_with_helm
    state["skip_crd_for_operators"] = skip_crd_for_operators
    state["force_crd_takeover_for_operators"] = force_crd_takeover_for_operators
    
    # Note: Cluster RBAC detection removed - Helm will handle RBAC automatically
    # Initialize empty dictionaries for backward compatibility
    skip_cluster_role_for_operators = {}
    force_rbac_takeover_for_operators = {}
    state["skip_cluster_role_for_operators"] = skip_cluster_role_for_operators
    state["force_rbac_takeover_for_operators"] = force_rbac_takeover_for_operators

    if not state["silent"]:
        print()
        # Use questionary for better interactive experience
        try:
            start_deploy = questionary.confirm(
                "Do you want to proceed with the IBM Content Cortex Operator Deployment?",
                default=True,
                auto_enter=False
            ).ask()
        except Exception:
            # Fallback to rich Confirm if questionary fails
            start_deploy = Confirm.ask("Do you want to proceed with the IBM Content Cortex Operator Deployment?",
                                      default=True)

        if not start_deploy:
            state["logger"].info("User cancelled deployment")
            print(Panel.fit("Deployment cancelled by user", style="yellow"))
            exit(1)
    
    # ============================================================
    # HELM DEPLOYMENT PATH
    # ============================================================
    state["logger"].info("Using Helm deployment method")
    console.print(Panel.fit(
        "[bold cyan]Deployment Method: Helm Charts[/bold cyan]\n"
        "Using Helm for operator deployment",
        border_style="cyan"
    ))
    
    # Determine which operators to deploy (filter out operators already at target version unless --force)
    operators_to_deploy = []
    operator_status = state.get("operator_status", {})
    force_mode = state.get("force", False)
    
    # Map operator types to status keys
    status_key_map = {
        'content': 'content',
        'ai-services': 'ai-services',
        'usage-metering': 'usage-metering',
        'license-service': 'licensing'
    }
    
    if hasattr(state["setup"], 'selected_operators') and state["setup"].selected_operators:
        # Multi-operator deployment - filter by status (unless force mode)
        for op in state["setup"].selected_operators:
            op_value = op.value
            status_key = status_key_map.get(op_value, op_value)
            
            # Only deploy if operator needs action (not already current) OR force mode is enabled
            if status_key in operator_status:
                if not operator_status[status_key].get('is_current', False):
                    operators_to_deploy.append(op_value)
                    state["logger"].info(f"Will deploy {op_value} - needs action")
                elif force_mode:
                    operators_to_deploy.append(op_value)
                    state["logger"].info(f"Force mode: Will deploy {op_value} - already at target version {operator_status[status_key].get('current_version')} but forcing redeployment")
                else:
                    state["logger"].info(f"Skipping {op_value} - already at target version {operator_status[status_key].get('current_version')}")
            else:
                # Operator not in status (new install)
                operators_to_deploy.append(op_value)
                state["logger"].info(f"Will deploy {op_value} - new installation")
    else:
        # Single operator deployment - default to content
        operators_to_deploy = ["content"]
    
    state["logger"].info(f"Final operators to deploy: {operators_to_deploy}")
    
    # ═══════════════════════════════════════════════════════════════════════
    # DRY-RUN MODE: Exit before Helm deployment (prevents all cluster changes)
    # ═══════════════════════════════════════════════════════════════════════
    if state["dryrun"]:
        state["logger"].info("Dry-run mode: Displaying planned Helm deployment operations")
        console.print()
        console.print(Panel.fit(
            "[bold cyan]Dry-Run Mode: Planned Helm Deployment[/bold cyan]\n\n"
            f"[white]Namespace:[/white] {state['setup'].namespace}\n"
            f"[white]Operators:[/white] {', '.join(operators_to_deploy)}\n"
            f"[white]Chart Source:[/white] {state['helm_chart_source']}\n\n"
            "[yellow]The following operations would be performed:[/yellow]\n"
            "  • Detect and migrate existing operator installations (if any)\n"
            "  • Create namespace (if not exists)\n"
            "  • Create IBM Entitlement Registry secret\n"
            "  • Deploy operator(s) via Helm charts\n"
            "  • Apply CRDs and RBAC resources\n\n"
            "[bold green]✓ No changes were made to the cluster[/bold green]",
            border_style="yellow",
            title="[bold yellow]🔍 Dry Run Complete[/bold yellow]"
        ))
        raise typer.Exit(code=0)
    
    # Execute Helm deployment
    success = deploy_with_helm(
        namespace=state["setup"].namespace,
        operators=operators_to_deploy,
        chart_source=state["helm_chart_source"],
        version_data=version_data
    )
    
    # Note: Detailed deployment summary is already displayed by display_deployment_complete()
    # in deploy_with_helm() at line 2950, which provides comprehensive status for each operator
    # including partial failures, error details, and troubleshooting guidance.
    
    if not success:
        # Exit with error code if deployment failed
        raise typer.Exit(code=1)
    
def main(version: Annotated[bool, typer.Option(
    "--version", help="Show version and exit.",
    callback=version_callback, is_eager=True)] = False,
         silent: Annotated[bool, typer.Option(
             help="Enable Silent Install (no prompts).",
             rich_help_panel="Customization and Utils")] = False,
         verbose: Annotated[bool, typer.Option(
             help="Enable verbose logging.",
             rich_help_panel="Customization and Utils")] = False,
         tls_verify: Annotated[bool, typer.Option(
             help="Enable TLS verification for Podman operations.",
             rich_help_panel="Customization and Utils")] = True,
         dryrun: Annotated[bool, typer.Option(
             help="Perform a dry run",
             rich_help_panel="Customization and Utils")] = False,
         validate: Annotated[bool, typer.Option(
                help="Disable validation of entitlement key or private registry.",
                rich_help_panel="Customization and Utils")] = True,
         force: Annotated[bool, typer.Option(
                help="Force redeployment even if operators are already at target version.",
                rich_help_panel="Customization and Utils")] = False,
         helm_chart_source: Annotated[str, typer.Option(
                help="Helm chart source: 'github' (default - downloads from GitHub), 'packaged' (local files), 'local' (unpacked charts), 'public' (Helm repo), or 'url'.",
                rich_help_panel="Deployment Method")] = "github",
         dev: Annotated[bool, typer.Option(
                help="Enable dev mode to use internal GitHub repository (requires GITHUB_TOKEN environment variable)",
                rich_help_panel="Deployment Method",
                hidden=True)] = False,
         ):
    """
    IBM Content Cortex Operator Deployment CLI.
    """
    if verbose:
        state["verbose"] = True
        FILE_LOG_LEVEL = logging.DEBUG
    else:
        FILE_LOG_LEVEL = logging.WARNING

    state["logger"] = setup_logger(FILE_LOG_LEVEL)

    if silent:
        state["silent"] = True

    if dev:
        state["dev"] = True

    if dryrun:
        state["dryrun"] = True

    if not validate:
        state["validate"] = False

    if not tls_verify:
        state["tls_verify"] = False
    
    if force:
        state["force"] = True
    
    state["helm_chart_source"] = helm_chart_source

    clear(console)
    display_mode_version("Deploy IBM Content Cortex Operator",
                         "Install IBM Content Cortex Operator")
    
    # Display what will be deployed
    info_text = Text()
    info_text.append("This mode will deploy:\n\n", style="bold white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("IBM Content Cortex Operator (via Helm)\n", style="white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Operator Custom Resource Definitions (CRDs)\n", style="white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Required RBAC roles and bindings\n", style="white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Operator deployment and service account\n", style="white")
    # OLM is no longer supported - removed conditional
    
    print(Panel(
        info_text,
        title="[bold white]📦 Operator Deployment[/bold white]",
        border_style="green",
        padding=(1, 2)
    ))
    print()
    
    deploy()


if __name__ == "__main__":
    typer.run(main)
