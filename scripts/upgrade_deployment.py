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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

import questionary
import typer
from pydantic import ValidationError
from rich import print
from rich import box
from rich.console import Console, Group
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn,
    TaskProgressColumn, MofNCompleteColumn, TimeElapsedColumn
)
from rich.prompt import Confirm
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from typing_extensions import Annotated

from helper_scripts.gather import gather as g
from helper_scripts.gather import silent_gather as sg
from helper_scripts.utilities.questionary_utils import safe_questionary_prompt, handle_cancelled_prompt
from helper_scripts.helm.helm_deployer import HelmDeployer, HelmChartSource
from helper_scripts.upgrade import upgrade as u
from helper_scripts.utilities.config_models import validate_deploy_operator_config, validate_upgradedeployment_config
from helper_scripts.utilities.deployment_progress import (
    create_deployment_progress,
    display_deployment_complete,
    DeploymentPhase,
    DeploymentStep
)
from helper_scripts.utilities.interface import (
    clear, display_issues, display_prereq_passed,
    upgrade_details, upgrade_deployment_details,
    display_config_validation_errors,
    create_deployment_header,
    create_phase_header,
    display_prereq_validation_table,
    display_toml_syntax_error,
)
from helper_scripts.utilities.operator_config import (
    OperatorType, get_operator_metadata, get_descriptor_files,
    get_all_operators, get_required_operators, validate_operator_dependencies,
    calculate_total_resources
)
from helper_scripts.utilities.kubernetes_utilites import KubernetesUtilities
from helper_scripts.utilities.utilities import (
    prereq_checks, read_version_toml, create_deployment_info,
    create_version_info, create_current_operator_info
)

__version__ = "26.1.0"

# ---------------------------------------------------------------------------
# DBACLD-261229 feature gate
# Set False for 26.0.1 GA (Sept 29).  Flip to True ~Oct 9 to re-enable the
# CP4BA Premium Add-On confirm question and CCx.CP4BA.<metric>.Premium tokens.
# ---------------------------------------------------------------------------
_CP4BA_PREMIUM_ADDON_ENABLED = False

app = typer.Typer(invoke_without_command=True, no_args_is_help=False)

state = {
    "verbose": False,
    "silent": False,
    "logger": logging,
    "setup": None,
    "upgrade": None,
    "version_details": {},
    "deployment_details": {},
    "dev": False,
    "dryrun": False,
    "tls_verify": True,
    "validate": True,
    "use_olm": False,
    "helm_chart_source": "packaged"
}

console = Console(record=True)


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
    file_handler = logging.FileHandler("upgradedeployment.log")
    file_handler.setLevel(logging.DEBUG)
    formatter_file = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)-100s - %(filename)s:%(lineno)d", "%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(formatter_file)

    # Add handlers to the logger
    logger.addHandler(shell_handler)
    logger.addHandler(file_handler)

    return logger


def version_callback(value: bool):
    if value:
        print(f"IBM Content Cortex Upgrade CLI: {__version__}")
        raise typer.Exit()


# Create a function to display the mode and version
def display_mode_version(mode: str, description: str):
    """
    Display the mode and version of the script with active flags in a modern, visually appealing format.
    
    Args:
        mode: The operation mode (e.g., "Operator Upgrade")
        description: Description of what the script does
    """
    print()
    
    # Create header table with version and mode info
    header_table = Table.grid(padding=(0, 2))
    header_table.add_column(style="cyan", justify="left")
    header_table.add_column(style="white", justify="left")
    
    # Add version and mode rows
    header_table.add_row("Version:", f"[bold green]{__version__}[/bold green]")
    header_table.add_row("Mode:", f"[bold yellow]{mode}[/bold yellow]")
    header_table.add_row("", f"[dim]{description}[/dim]")
    
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
    
    if state["verbose"]:
        active_flags.append("📢 Verbose Logging")
        state["logger"].info("Verbose Logging is enabled")
    
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
        title="[bold white]⬆️  IBM Content Cortex Upgrade CLI[/bold white]",
        border_style="bright_blue",
        padding=(1, 2),
        expand=False
    ))
    print()


def _handle_chart_validation_and_download(state: dict, console, version_data: dict, selected_operators: list) -> None:
    """
    Handle Helm chart validation and download after operator selection.
    
    This function validates that required Helm charts exist (for packaged/local sources)
    or downloads them (for GitHub/public repo sources) with a modern UI.
    
    Args:
        state: Application state dictionary
        console: Rich console for output
        version_data: Version data from version.toml
        selected_operators: List of selected OperatorType enums
        
    Raises:
        typer.Exit: If chart validation fails
    """
    from helper_scripts.helm.helm_deployer import HelmDeployer, HelmChartSource
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    
    # Convert selected operators to strings
    operators_to_check = [op.value for op in selected_operators]
    
    # Map chart source string to enum
    source_map = {
        "packaged": HelmChartSource.PACKAGED,
        "local": HelmChartSource.LOCAL,
        "public": HelmChartSource.PUBLIC_REPO,
        "url": HelmChartSource.URL,
        "github": HelmChartSource.GITHUB
    }
    chart_source = state.get("helm_chart_source", "packaged")
    chart_source_enum = source_map.get(chart_source, HelmChartSource.PACKAGED)
    
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
        f"[cyan]Chart Source:[/cyan] {chart_source}\n"
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
                "[green]All required Helm charts are ready for upgrade[/green]",
                border_style="green",
                title="[bold green]✓ Charts Ready[/bold green]"
            ))
            state["logger"].info("✓ All charts downloaded successfully")
        else:
            console.print(Panel.fit(
                f"[bold red]✗ Failed to download {len(failed_downloads)} chart(s)[/bold red]\n\n"
                "[red]The following charts could not be downloaded:[/red]\n" +
                "\n".join([f"  • {op}" for op in failed_downloads]) + "\n\n"
                "[bold yellow]⚠️  Helm upgrade cannot proceed without required charts[/bold yellow]\n\n"
                "[white]Possible solutions:[/white]\n"
                "  [cyan]1.[/cyan] Check your internet connection\n"
                "  [cyan]2.[/cyan] Verify GitHub token if using private repositories\n"
                "  [cyan]3.[/cyan] Try using local/packaged charts instead\n"
                "  [cyan]4.[/cyan] Check the logs for detailed error information",
                border_style="red",
                title="[bold red]✗ Chart Download Failed - Upgrade Aborted[/bold red]"
            ))
            state["logger"].error(f"Chart download failed for: {failed_downloads}")
            state["logger"].error("UPGRADE ABORTED: Cannot proceed without required Helm charts")
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
                "[bold yellow]⚠️  Helm upgrade cannot proceed without required charts[/bold yellow]\n\n"
                "[white]Possible solutions:[/white]\n"
                "  [cyan]1.[/cyan] Download charts using GitHub/public source mode\n"
                "  [cyan]2.[/cyan] Ensure charts are in the correct directory\n"
                "  [cyan]3.[/cyan] Verify chart names match expected format\n"
                "  [cyan]4.[/cyan] Check file permissions on chart directory",
                border_style="yellow",
                title="[bold yellow]⚠️  Upgrade Aborted[/bold yellow]"
            ))
            state["logger"].error("UPGRADE ABORTED: Cannot proceed without required Helm charts")
            raise typer.Exit(code=1)
        
        # Display success message
        console.print(Panel.fit(
            f"[bold green]✓ All {len(operators_to_check)} required chart(s) found and validated[/bold green]\n\n"
            "[green]Charts are ready for upgrade[/green]",
            border_style="green",
            title="[bold green]✓ Charts Validated[/bold green]"
        ))
        state["logger"].info("✓ All required Helm charts found and validated")
    
    console.print()


def _handle_prerequisite_validation(
    missing_tools: List[str],
    files: List[str],
    results: dict,
    logger: logging.Logger
) -> None:
    """
    Handle prerequisite validation results and exit if validation fails.
    Uses the centralized display_issues function for consistent UX.
    
    Args:
        missing_tools: List of missing prerequisite tools
        files: List of missing required files
        results: Dictionary of prerequisite check results
        logger: Logger instance
        
    Raises:
        typer.Exit: If prerequisites are missing (exit code 1)
    """
    has_missing_items = bool(missing_tools or files)
    
    if has_missing_items:
        logger.info("Prerequisites failed. Displaying missing tools and files.")
        
        # Check if Helm Charts are missing and show special message
        if "Helm Charts" in missing_tools and "helm_charts_missing" in results:
            from pathlib import Path
            console_local = Console()
            console_local.print("\n[red]✗ Missing Required Helm Charts (for packaged source):[/red]\n")
            
            for chart in results["helm_charts_missing"]:
                console_local.print(f"  [red]✗[/red] {chart}")
            
            console_local.print(f"\n[yellow]📁 Charts must be placed in:[/yellow] {Path.cwd().parent / 'helm-charts'}/")
            console_local.print("\n[cyan]💡 Resolution Options:[/cyan]")
            console_local.print("  1. [bold]Use default packaged source[/bold] (recommended): Ensure .tgz files are in helm-charts/")
            console_local.print("     Or use [bold]--helm-chart-source github[/bold] to download automatically")
            console_local.print("  2. Download the required chart packages and place them in the helm-charts/ directory")
            console_local.print("  3. Use [bold]--helm-chart-source local[/bold] if you have unpacked chart directories")
            console_local.print("  4. Use [bold]--helm-chart-source public[/bold] to download from public Helm repositories")
            console_local.print("\n[cyan]📚 For more information, see:[/cyan] HELM_CHART_SOURCES.md\n")
            raise typer.Exit(code=1)
        
        # Use centralized display_issues function for consistent UX
        layout = display_issues(tools=missing_tools, descriptors=files)
        print(layout)
        raise typer.Exit(code=1)
    
    logger.info("Prerequisites passed.")


def run_deployment_upgrade():
    """
    Run the deployment upgrade for an IBM Content Cortex deployment.

    Handles three scenarios:
    - Content only (FNCMCluster CR present, CCXAIServices absent)
    - AI Services only (CCXAIServices CR present, FNCMCluster absent)
    - Combined (both CRs present)

    For each detected CR:
    - Backs up the current deployed CR configuration
    - Deep-merges it against the full template to pick up new spec fields
    - Applies version and license updates
    - Saves the upgraded CR to CCxUpgrade/<namespace>/CustomResources/

    Content-specific steps (metrics generation) are only run when the
    FNCMCluster CR is present.  All generated files are saved in the
    CCxUpgrade/<namespace> folder and applied to the cluster automatically.
    """
    _content_present = state["upgrade"]._cr_present
    _ai_svcs_present = state["upgrade"]._ai_services_cr_present

    # Defensive gate — should already have been caught by main(), but kept as a
    # safety net in case run_deployment_upgrade() is called directly in tests.
    if not _content_present and not _ai_svcs_present:
        print()
        print(Panel(
            f"[bold red]✗ No IBM Content Cortex Deployment Found[/bold red]\n\n"
            f"No deployment found in namespace: [cyan]{state['setup']._namespace}[/cyan]\n\n"
            f"[bold white]At least one of the following must exist:[/bold white]\n"
            f"  • FNCMCluster (Content Operator)\n"
            f"  • CCXAIServices (AI Services Operator)\n\n"
            f"[yellow]💡 Tip:[/yellow]\n"
            f"  [cyan]kubectl get fncmclusters -n {state['setup']._namespace}[/cyan]\n"
            f"  [cyan]kubectl get ccxaiservices -n {state['setup']._namespace}[/cyan]",
            title="[bold red]❌ Deployment Not Found[/bold red]",
            border_style="red",
            padding=(1, 2),
            expand=False,
        ))
        state["logger"].error(
            f"No FNCMCluster or CCXAIServices CR found in namespace {state['setup']._namespace}")
        raise typer.Exit(code=1)

    # ── License is already resolved: collected in main() before namespace/Upgrade init.
    # In silent mode it comes from the TOML config; in interactive mode it was collected
    # by collect_license_model() + prompt_license_selection() before collect_namespace().
    # Propagate to the Upgrade object and fall back to a safe default only if somehow absent.
    if not state.get("selected_license"):
        state["logger"].warning("No license model in state — using default: CP4BA.Prod")
        state["selected_license"] = "CP4BA.Prod"
    state["upgrade"].selected_license = state["selected_license"]

    # ── Show which CRs were detected ─────────────────────────────────────────
    if not state["silent"]:
        from rich.text import Text as _T
        _det = _T()
        _det.append("Detected deployments in namespace ", style="white")
        _det.append(state["setup"]._namespace, style="bold cyan")
        _det.append(":\n\n", style="white")
        _det.append("  ✓ " if _content_present  else "  – ", style="bold green" if _content_present  else "dim")
        _det.append("FNCMCluster (Content Operator)\n",    style="white" if _content_present  else "dim")
        _det.append("  ✓ " if _ai_svcs_present  else "  – ", style="bold green" if _ai_svcs_present  else "dim")
        _det.append("CCXAIServices (AI Services Operator)", style="white" if _ai_svcs_present else "dim")
        print()
        print(Panel(_det, title="[bold cyan]Detected CRs[/bold cyan]",
                    border_style="cyan", padding=(1, 2), expand=False))

    print()
    # Display deployment phases overview
    if not state["silent"]:
        display_deployment_phases()
    
    state["upgrade"].prepare_upgrade_cr()
    # If 5.7.0 upgrade, download the network policies
    if state["version_details"]["version"] in ["5.7.0"]:
        state["upgrade"].collect_network_policy_info()

    # Get per-CR update lists and folder path
    content_update_list    = state["upgrade"].updates_list
    ai_services_update_list = state["upgrade"].ai_updates_list
    folder_path = state["upgrade"].download_location

    print()
    deployment_info = upgrade_deployment_details(
        content_update_list, ai_services_update_list, state["version_details"], folder_path)
    print(deployment_info)
    print()

    if not state["silent"]:
        proceed = questionary.confirm(
            "Do you want to continue and prepare the deployed system for upgrade?",
            default=True,
            auto_enter=False,
        ).ask()
        if not proceed:
            # Covers both False (answered No) and None (Ctrl+C / ESC)
            print()
            print(Panel.fit(
                "[yellow]⚠️  Upgrade Cancelled[/yellow]\n\n"
                "The deployment upgrade has been cancelled by user request.\n"
                "No changes have been made to your deployment.",
                border_style="yellow"
            ))
            raise typer.Exit(code=0)

    print()
    prereq_steps()

    if not state["dryrun"]:
        print()
        print(Panel(
            "[bold white]🚀 Starting IBM Content Cortex Deployment Upgrade[/bold white]\n\n"
            "[cyan]Phase:[/cyan] Deployment Custom Resource Upgrade\n"
            "[cyan]Namespace:[/cyan] " + state['setup']._namespace + "\n"
            "[cyan]Target Version:[/cyan] " + state["version_details"].get("version", "26.0.0"),
            title="[bold cyan]Deployment Upgrade In Progress[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
            expand=False
        ))
        print()
        state["logger"].info(f"Starting IBM Content Cortex Deployment Upgrade")
        
        # Call methods directly - they now handle their own UI with live-updating tables
        if state["version_details"]["version"] in ["5.7.0"]:
            state["upgrade"].update_network_policy(progress=None)
        state["upgrade"].remove_custom_ssl_secrets(progress=None)
        state["upgrade"].apply_upgraded_cr(progress=None)
    else:
        # Dry-run: CR files have been prepared and saved but nothing was applied.
        folder_path = state["upgrade"].download_location
        print()
        print(Panel(
            "[bold yellow]🔍 Dry Run Complete — No Changes Applied[/bold yellow]\n\n"
            "[white]The upgrade was simulated successfully. "
            "The upgraded CR file(s) have been saved for review but "
            "[bold]no changes were made[/bold] to your live deployment.\n\n"
            "[cyan]Generated files:[/cyan] " + folder_path + "\n\n"
            "[dim]Re-run without [bold]--dryrun[/bold] to apply the upgrade.[/dim]",
            title="[bold yellow]Dry Run Summary[/bold yellow]",
            border_style="yellow",
            padding=(1, 2),
            expand=False,
        ))
        print()
        state["logger"].info("Dry-run complete — no changes applied to the cluster")


def prompt_license_selection(license_type: str = None) -> str:
    """
    Prompt user to select the license metric for Content Cortex.

    When ``license_type`` is provided (pre-collected by collect_license_model in
    main()) the type step is skipped and only the metric prompt is shown — this
    avoids asking the user for their license type twice during an upgrade.

    Args:
        license_type: Pre-collected license type string: "Essentials", "Premium",
                      or "CP4BA".  When None the type prompt is shown first.

    Returns:
        str: Selected license model string written into sc_fncm_license_model
             (e.g., 'CCx.Ess.AU', 'CP4BA.Prod', 'CCx.CP4BA.Prod.Premium')
    """
    from enum import Enum

    class LicenseMetricCP4BA(Enum):
        NonProd = 1
        Prod = 2
        User = 3

    _qs_style = questionary.Style([
        ('qmark', 'fg:cyan bold'),
        ('question', 'bold'),
        ('answer', 'fg:cyan bold'),
        ('pointer', 'fg:cyan bold'),
        ('highlighted', 'fg:cyan'),
        ('selected', 'fg:green bold')
    ])

    try:
        # ── Step 1: License Type (skip when already collected by collect_license_model) ──
        if license_type is not None:
            # Type already collected — map to the internal key used below.
            _type_map = {"Essentials": "ESS", "Premium": "PREM", "CP4BA": "CP4BA"}
            model = _type_map.get(license_type, license_type)
            state["logger"].info(f"License type pre-selected from gather step: {license_type!r} → model={model!r}")
        else:
            license_type_info = Text()
            license_type_info.append("🏷  ", style="bold cyan")
            license_type_info.append("License Type Selection\n\n", style="bold cyan")
            license_type_info.append("Choose the license model that matches your entitlement:\n\n", style="white")
            license_type_info.append("  • ", style="cyan")
            license_type_info.append("Essentials", style="bold green")
            license_type_info.append(
                " - IBM Content Cortex Essentials license\n"
                "    Requires: Usage Metering only\n\n",
                style="white"
            )
            license_type_info.append("  • ", style="cyan")
            license_type_info.append("Premium", style="bold green")
            license_type_info.append(
                " - IBM Content Cortex Premium license\n"
                "    Requires: Usage Metering only\n\n",
                style="white"
            )
            license_type_info.append("  • ", style="cyan")
            license_type_info.append("CP4BA", style="bold green")
            license_type_info.append(
                " - Cloud Pak for Business Automation license\n"
                "    Requires: License Service + Usage Metering\n",
                style="white"
            )

            print()
            print(Panel(
                license_type_info,
                title="[bold white]License Model Configuration[/bold white]",
                border_style="cyan",
                padding=(1, 2)
            ))
            print()

            license_type_result = questionary.select(
                "Select a License Type:",
                choices=[
                    questionary.Choice("Essentials", value="ESS"),
                    questionary.Choice("Premium",    value="PREM"),
                    questionary.Choice("CP4BA",      value="CP4BA"),
                ],
                style=_qs_style
            ).ask()

            if license_type_result is None:
                print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                state["logger"].info("License selection cancelled by user")
                raise typer.Exit(code=0)

            model = license_type_result  # "ESS", "PREM", or "CP4BA"

        # ── Step 2: Metric selection ─────────────────────────────────────────
        is_ccx_cp4ba_premium_addon = False

        if model == "CP4BA":
            # DBACLD-261229: Step 2a — select the metric first
            metric_result = questionary.select(
                "Select a License Metric:",
                choices=[
                    questionary.Choice("NonProd", value=1),
                    questionary.Choice("Prod", value=2),
                    questionary.Choice("User", value=3)
                ],
                style=_qs_style
            ).ask()

            if metric_result is None:
                print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                state["logger"].info("License metric selection cancelled by user")
                raise typer.Exit(code=0)

            metric = LicenseMetricCP4BA(metric_result).name

            # DBACLD-261229: Premium Add-On question — gated off for 26.0.1 GA, re-enable ~Oct 9
            if _CP4BA_PREMIUM_ADDON_ENABLED:
                is_ccx_cp4ba_premium_addon = questionary.confirm(
                    "Do you have Content Cortex Add-On Premium for CP4BA license?",
                    default=False,
                    style=questionary.Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:green bold'),
                    ])
                ).ask()

                if is_ccx_cp4ba_premium_addon is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    state["logger"].info("License premium add-on selection cancelled by user")
                    raise typer.Exit(code=0)
            else:
                # Premium Add-On disabled for GA — always use the base CP4BA metric
                is_ccx_cp4ba_premium_addon = False

        elif model == "PREM":
            # Premium uses a multi-select checkbox — customers may hold multiple
            # entitlements (AU, EP, PE) and all selected tokens are written as a
            # comma-separated value into sc_fncm_license_model, matching the
            # fresh-install behaviour in gather_prerequisites.py.
            while True:
                prem_metric_results = questionary.checkbox(
                    "Select License Metric(s) (space to select, enter to confirm):",
                    choices=[
                        questionary.Choice("IBM Content Cortex Premium - Authorized User",       value=1),
                        questionary.Choice("IBM Content Cortex Premium - Eligible Participants", value=2),
                        questionary.Choice("IBM Content Cortex Premium - Employee",              value=3),
                    ],
                    style=_qs_style
                ).ask()

                if prem_metric_results is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    state["logger"].info("License metric selection cancelled by user")
                    raise typer.Exit(code=0)

                if not prem_metric_results:
                    print()
                    print("[prompt.invalid]You must select at least one license metric.")
                    print()
                    continue

                break

            _prem_metric_map = {1: "AU", 2: "EP", 3: "PE"}
            prem_tokens = [
                {"PREM.AU": "CCx.Pre.AU", "PREM.EP": "CCx.Pre.EP", "PREM.PE": "CCx.Pre.PE"}
                [f"PREM.{_prem_metric_map[v]}"]
                for v in prem_metric_results
            ]
            selected_license = ",".join(prem_tokens)

            print()
            print(Panel.fit(
                f"[green]✓[/green] Selected License Model: [bold cyan]{selected_license}[/bold cyan]",
                border_style="green"
            ))
            print()

            state["logger"].info(f"License model selected: {selected_license}")
            return selected_license

        else:  # ESS — multi-select, mirrors Premium behaviour
            # Customers may hold multiple Essentials entitlements; all selected
            # tokens are written as a comma-separated value into sc_fncm_license_model.
            _ess_token_map = {
                1: "CCx.AR",
                2: "CCx.PR",
                3: "CCx.ER",
                4: "CCx.Ess.AU",
                5: "CCx.Ess.EP",
                6: "CCx.EE",
            }

            while True:
                ess_metric_results = questionary.checkbox(
                    "Select License Metric(s) (space to select, enter to confirm):",
                    choices=[
                        questionary.Choice("IBM Content Cortex Restricted - Authorized",          value=1),
                        questionary.Choice("IBM Content Cortex Restricted - Eligible Participant", value=2),
                        questionary.Choice("IBM Content Cortex Restricted - Employee",             value=3),
                        questionary.Choice("IBM Content Cortex Essentials - Authorized User",      value=4),
                        questionary.Choice("IBM Content Cortex Essentials - Eligible Participants",value=5),
                        questionary.Choice("IBM Content Cortex Essentials - Employee",             value=6),
                    ],
                    style=_qs_style
                ).ask()

                if ess_metric_results is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    state["logger"].info("License metric selection cancelled by user")
                    raise typer.Exit(code=0)

                if not ess_metric_results:
                    print()
                    print("[prompt.invalid]You must select at least one license metric.")
                    print()
                    continue

                break

            ess_tokens = [_ess_token_map[v] for v in ess_metric_results]
            selected_license = ",".join(ess_tokens)

            print()
            print(Panel.fit(
                f"[green]✓[/green] Selected License Model: [bold cyan]{selected_license}[/bold cyan]",
                border_style="green"
            ))
            print()

            state["logger"].info(f"License model selected: {selected_license}")
            return selected_license

        # ── Map to sc_fncm_license_model token (CP4BA path only) ────────────
        license_mapping = {
            "CP4BA.NonProd": "CP4BA.NonProd",
            "CP4BA.Prod":    "CP4BA.Prod",
            "CP4BA.User":    "CP4BA.User",
        }
        # DBACLD-261229: when CP4BA Premium Add-On is confirmed, remap only the
        # CP4BA keys.  Essentials entries above are left untouched.
        if is_ccx_cp4ba_premium_addon:
            license_mapping.update({
                "CP4BA.NonProd": "CCx.CP4BA.NonProd.Premium",
                "CP4BA.Prod":    "CCx.CP4BA.Prod.Premium",
                "CP4BA.User":    "CCx.CP4BA.User.Premium",
            })

        combined_license = f"{model}.{metric}"
        selected_license = license_mapping.get(combined_license, combined_license)

        # ── Confirmation display ─────────────────────────────────────────────
        print()
        print(Panel.fit(
            f"[green]✓[/green] Selected License Model: [bold cyan]{selected_license}[/bold cyan]",
            border_style="green"
        ))
        print()

        state["logger"].info(f"License model selected: {selected_license}")
        return selected_license

    except (typer.Exit, KeyboardInterrupt):
        # Clean cancellation — already printed the ⚠ message above; just propagate.
        raise
    except Exception as e:
        state["logger"].exception(f"Exception in license selection: {str(e)}")
        raise


def convert_private_registry():
    print()
    print(Panel.fit(
        "[bold cyan]📦 Private Image Registry Configuration[/bold cyan]",
        border_style="cyan"
    ))
    print()
    
    registry_options = Table(show_header=False, box=None, padding=(0, 2))
    registry_options.add_column(style="cyan", width=3)
    registry_options.add_column(style="white")
    
    registry_options.add_row("1.", "[bold]Online[/bold] - Pull from IBM Entitlement Registry (cp.icr.io)")
    registry_options.add_row("", "[dim]• Requires IBM Entitlement Key[/dim]")
    registry_options.add_row("", "[dim]• Direct access to IBM registry[/dim]")
    registry_options.add_row("", "")
    registry_options.add_row("2.", "[bold]Private[/bold] - Pull from your Private Registry")
    registry_options.add_row("", "[dim]• Images must be pre-loaded[/dim]")
    registry_options.add_row("", "[dim]• Use for air-gapped environments[/dim]")
    
    print(registry_options)
    print()
    
    print(Panel.fit(
        "[bold yellow]ℹ️  Before using a Private Registry:[/bold yellow]\n\n"
        "Use the IBM Content Cortex Load Images CLI to push required images:\n"
        "[cyan]python3 load_images.py[/cyan]",
        border_style="yellow"
    ))
    print()
    
    try:
        private_registry = questionary.confirm(
            "Do you want to pull the IBM Content Cortex Operator image from a Private Registry?",
            default=False,
            auto_enter=False
        ).ask()
    except Exception:
        # Fallback to rich Confirm
        private_registry = Confirm.ask(
            "Do you want to pull the IBM Content Cortex Operator image from a Private Registry?",
            default=False
        )

    if private_registry:
        state["setup"].collect_verify_private_registry()

    return private_registry


def display_deployment_phases():
    """Display deployment upgrade phases overview without prompting."""
    print()
    print(Panel(
        "[bold white]📋 Deployment Upgrade Process Overview[/bold white]",
        border_style="cyan",
        padding=(0, 2)
    ))
    print()
    
    phases_table = Table(show_header=False, box=None, padding=(0, 2))
    phases_table.add_column(style="cyan bold", width=8)
    phases_table.add_column(style="white", width=80)
    
    phases_table.add_row(
        "Phase 1",
        "[bold white]Custom Resource Preparation[/bold white]\n"
        "[dim]• Analyze current deployment configuration[/dim]\n"
        "[dim]• Generate upgraded Custom Resource with new version[/dim]\n"
        "[dim]• Backup existing configuration files[/dim]"
    )
    phases_table.add_row("", "")
    
    phases_table.add_row(
        "Phase 2",
        "[bold white]Environment Preparation[/bold white]\n"
        "[dim]• Prepare environment for upgrade[/dim]\n"
        "[dim]• Validate cluster state[/dim]"
    )
    phases_table.add_row("", "")
    
    phases_table.add_row(
        "Phase 3",
        "[bold white]Apply Upgraded Custom Resource[/bold white]\n"
        "[dim]• Apply the upgraded Custom Resource to cluster[/dim]\n"
        "[dim]• Operator will reconcile and update deployment[/dim]\n"
        "[dim]• Monitor deployment progress[/dim]"
    )
    
    print(phases_table)
    print()
    
    print(Panel(
        "[bold yellow]⚠️  Important Notes:[/bold yellow]\n\n"
        "• This process upgrades the [bold]deployment layer[/bold] (Custom Resources)\n"
        "• A backup of your current configuration is highly recommended\n"
        "• Ensure you have completed all pre-upgrade preparation steps",
        border_style="yellow",
        padding=(1, 2),
        expand=False
    ))
    print()


def prereq_steps():
    backup_link = Text(
        "https://www.ibm.com/docs/en/IBM Content Cortex-p8-platform/5.6.0?topic=br-backing-up-data-in-your-IBM Content Cortex-p8-domain",
        style="https://www.ibm.com/docs/en/IBM Content Cortex-p8-platform/5.6.0?topic=br-backing-up-data-in-your-IBM Content Cortex-p8-domain")
    cbr_link = Text(
        "https://www.ibm.com/docs/en/IBM Content Cortex-p8-platform/5.6.0?topic=upgrade-stopping-content-search-services-index-dispatcher",
        style="https://www.ibm.com/docs/en/IBM Content Cortex-p8-platform/5.6.0?topic=upgrade-stopping-content-search-services-index-dispatcher")
    upgrade_prep = Text(
        "https://www.ibm.com/docs/en/IBM Content Cortex-p8-platform/5.6.0?topic=upgrade-checking-deployment-type-license",
        style="https://www.ibm.com/docs/en/IBM Content Cortex-p8-platform/5.6.0?topic=upgrade-checking-deployment-type-license")
    
    print()
    print(Panel(
        "[bold white]⚠️  Pre-Upgrade Preparation Checklist[/bold white]",
        border_style="yellow",
        padding=(0, 2)
    ))
    print()
    
    prep_table = Table(show_header=False, box=None, padding=(0, 2))
    prep_table.add_column(style="yellow bold", width=8)
    prep_table.add_column(style="white", width=80)
    
    prep_table.add_row(
        "Step 1",
        "[bold white]Backup Your IBM Content Cortex Data[/bold white]\n"
        "[dim]Before proceeding with the upgrade, ensure you have a complete backup[/dim]\n"
        f"[dim]📚 Documentation: {backup_link}[/dim]"
    )
    prep_table.add_row("", "")
    
    prep_table.add_row(
        "Step 2",
        "[bold white]Disable the CBR Dispatcher[/bold white]\n"
        "[dim]Stop Content Search Services Index Dispatcher before upgrade[/dim]\n"
        f"[dim]📚 Documentation: {cbr_link}[/dim]"
    )
    
    print(prep_table)
    print()
    if state["version_details"]["version"] in ["5.7.0"]:
        print(Panel.fit(
            "[bold yellow]📡 Network Policy Changes (5.7.0)[/bold yellow]\n\n"
            "• FNCM 5.7.0 Operator will not create or manage Network Policies\n"
            "• Existing policies will be backed up under [cyan]FNCMUpgrade/NetworkPolicies[/cyan]\n"
            "• If [cyan]sc_restricted_internet_access[/cyan] is enabled, the script will enable\n"
            "  [cyan]sc_generate_sample_network_policies[/cyan] in the custom resource\n"
            "• After deployment, use [cyan]mustgather.py networkpolicy[/cyan] to grab templates",
            border_style="yellow"
        ))
        print()
    print(Panel.fit(
        f"[bold yellow]⚠️  Multi-Deployment Clusters:[/bold yellow]\n\n"
        f"If you have other IBM Content Cortex Deployments on the same cluster,\n"
        f"ensure each custom resource is compatible with the new version.\n\n"
        f"[dim]See: {upgrade_prep}[/dim]",
        border_style="yellow"
    ))
    print()
    
    print(Panel(
        "[bold cyan]💡 Recommended: Run MustGather Before Upgrade[/bold cyan]\n\n"
        "Collect a comprehensive backup of all deployment files and configuration:\n\n"
        "[white]python3 mustgather.py[/white]\n\n"
        "[dim]This creates a timestamped backup of:[/dim]\n"
        "[dim]• Custom Resources and CRDs[/dim]\n"
        "[dim]• Operator configurations[/dim]\n"
        "[dim]• Pod logs and status[/dim]\n"
        "[dim]• Network policies and RBAC[/dim]",
        border_style="cyan",
        padding=(1, 2),
        expand=False
    ))
    print()
    if state["version_details"]["version"] in ["5.7.0"]:
        print(Panel(
            "[bold red]⚠️  IMPORTANT: Next Steps[/bold red]\n\n"
            "[bold white]Proceeding will perform the following actions:[/bold white]\n\n"
            "  [yellow]1.[/yellow] Remove owner references from existing network policies\n"
            "  [yellow]3.[/yellow] Apply the upgraded Custom Resource to the cluster\n\n"
            "[bold white]What will be preserved:[/bold white]\n"
            "  [green]✓[/green] All data in databases and object stores\n"
            "  [green]✓[/green] Persistent volumes and claims\n"
            "  [green]✓[/green] Secrets and ConfigMaps\n\n"
            "[bold yellow]Ensure you have:[/bold yellow]\n"
            "  [cyan]•[/cyan] Completed all backup procedures\n"
            "  [cyan]•[/cyan] Disabled CBR Dispatcher\n"
            "  [cyan]•[/cyan] Reviewed the upgrade documentation",
            title="[bold red]⚠️  Action Required[/bold red]",
            border_style="red",
            padding=(1, 2),
            expand=False
        ))
    else:
        print(Panel(
            "[bold red]⚠️  IMPORTANT: Next Steps[/bold red]\n\n"
            "[bold white]Proceeding will perform the following actions:[/bold white]\n\n"
            "  [yellow]1.[/yellow] Apply the upgraded Custom Resource to the cluster\n\n"
            "[bold white]What will be preserved:[/bold white]\n"
            "  [green]✓[/green] All data in databases and object stores\n"
            "  [green]✓[/green] Persistent volumes and claims\n"
            "  [green]✓[/green] Secrets and ConfigMaps\n\n"
            "[bold yellow]Ensure you have:[/bold yellow]\n"
            "  [cyan]•[/cyan] Completed all backup procedures\n"
            "  [cyan]•[/cyan] Disabled CBR Dispatcher\n"
            "  [cyan]•[/cyan] Reviewed the upgrade documentation",
            title="[bold red]⚠️  Action Required[/bold red]",
            border_style="red",
            padding=(1, 2),
            expand=False
        ))
    print()

    if not state["silent"]:
        try:
            proceed = questionary.confirm(
                "Have you completed the preparation steps and are ready to proceed with the upgrade?",
                default=False,
                auto_enter=False
            ).ask()
        except Exception:
            # Fallback to rich Confirm
            proceed = Confirm.ask(
                "Have you completed the preparation steps and are ready to proceed with the upgrade?",
                default=False
            )
        
        if not proceed:
            print(Panel(
                "[yellow]⚠️  Upgrade Cancelled[/yellow]\n\n"
                "The deployment upgrade has been cancelled by user request.\n"
                "No changes have been made to your deployment.\n\n"
                "[dim]You can restart the upgrade process at any time.[/dim]",
                border_style="yellow",
                padding=(1, 2)
            ))
            raise typer.Exit(code=0)



@app.callback(invoke_without_command=True)
def main(ctx: typer.Context,
         version: Annotated[Optional[bool], typer.Option(
             "--version", help="Show version and exit.",
             callback=version_callback, is_eager=True)] = None,
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
                rich_help_panel="Customization and Utils")] = True
         ):
    """
        IBM Content Cortex Deployment Upgrade CLI.
    """
    if verbose:
        state["verbose"] = True
        FILE_LOG_LEVEL = logging.DEBUG
    else:
        FILE_LOG_LEVEL = logging.WARNING

    if dryrun:
        state["dryrun"] = True

    if not tls_verify:
        state["tls_verify"] = False
    
    if not validate:
        state["validate"] = False
    
    state["logger"] = setup_logger(FILE_LOG_LEVEL)

    # Build descriptor file list for all 4 operators using operator_config
    # This ensures we check for all required files across the new structure:
    # - content-cortex/content/
    # - content-cortex/ai-services/
    # - license-service/
    # - usage-metering/
    
    # Determine which files to validate based on subcommand
    descriptor_path = os.path.join(os.path.dirname(os.getcwd()), "descriptors")
    required_files = []
    
    # Always run deployment upgrade (no subcommands)
    state["logger"].info(f"Upgrade of the Content Cortex Deployment")
    display_mode_version("Deployment Upgrade", "Upgrade for the Content Cortex Deployment")
    
    # Display what will be upgraded
    info_text = Text()
    info_text.append("This mode will upgrade:\n\n", style="bold white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Custom Resource (CR) configuration\n", style="white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Deployment workloads and services\n", style="white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Usage metering metrics\n", style="white")
    
    print(Panel(
        info_text,
        title="[bold white]⬆️  Deployment Upgrade[/bold white]",
        border_style="blue",
        padding=(1, 2)
    ))
    print()
    
    # CR templates needed for deployment upgrade.
    # Content full CR is always required (content CR upgrade is the primary path).
    required_files.append(os.path.join(descriptor_path, "content-cortex", "content", "ibm_content_full_cr.yaml"))
    # AI Services full CR is optional — only validate its presence if the file exists on disk so that
    # content-only environments without AI Services descriptors are not blocked at the prereq stage.
    _ai_full_cr_path = os.path.join(descriptor_path, "content-cortex", "ai-services", "ibm_ai_services_full_cr.yaml")
    if os.path.exists(_ai_full_cr_path):
        required_files.append(_ai_full_cr_path)

    # Validate prerequisites
    state["logger"].info(f"Checking pre-requisite tools")
    checks = ["connection"]
    
    missing_tools, results, files = prereq_checks(
        logger=state["logger"],
        prereqs=checks,
        files=required_files  # Validate CR template for deployment upgrades
    )

    # Use modern validation handling
    _handle_prerequisite_validation(
        missing_tools=missing_tools,
        files=files,
        results=results,
        logger=state["logger"]
    )
    display_prereq_validation_table(results)

    # Read Version File
    # Get path to version.toml in parent directory or parent of parent directory
    version_path = os.path.join(os.path.dirname(os.getcwd()), "version.toml")
    if not os.path.exists(version_path):
        version_path = os.path.join(os.path.dirname(os.path.dirname(os.getcwd())), "version.toml")

    if os.path.exists(version_path):
        version_data = read_version_toml(version_path, state["logger"])
    else:
        version_data = {}

    if silent:
        state["silent"] = True
        silent_path = os.path.join("silent_config", "silent_install_upgradedeployment.toml")

        # Validate configuration with Pydantic before proceeding
        state["logger"].info(f"Validating silent upgrade-deployment configuration: {silent_path}")
        try:
            import toml as _toml
            with open(silent_path, 'r') as _f:
                _config_dict = _toml.load(_f)
            _success, _, _validation_errors = validate_upgradedeployment_config(_config_dict)
            if not _success:
                print(display_config_validation_errors(_validation_errors, silent_path))
                raise typer.Exit(code=1)
            state["logger"].info("✓ Configuration validated successfully")
        except FileNotFoundError:
            print(Panel.fit(f"❌ Configuration file not found: {silent_path}", style="bold red"))
            raise typer.Exit(code=1)
        except typer.Exit:
            raise
        except toml.TomlDecodeError as _e:
            print(display_toml_syntax_error(_e, silent_path))
            raise typer.Exit(code=1)
        except Exception as _e:
            state["logger"].error(f"Unexpected error loading configuration: {str(_e)}")
            print(Panel.fit(f"❌ Unexpected error: {str(_e)}", style="bold red"))
            raise typer.Exit(code=1)

        state["setup"] = sg.SilentGatherOptions(state["logger"], silent_path,
                                                script_type="upgrade", dev=False, tls_verify=state["tls_verify"])
        state["setup"]._podman_available = results["podman"]
        state["setup"].silent_parse_upgrade_variables()
        state["selected_license"] = state["setup"]._selected_license
        # Pass required files to Upgrade class
        state["upgrade"] = u.Upgrade(console, state["setup"], state["logger"], silent=True,
                                     required_files=required_files,
                                     selected_license=state["selected_license"])

    else:
        state["setup"] = g.GatherOptions(state["logger"], console, script_type="upgrade", dev=False, tls_verify=state["tls_verify"])
        state["setup"]._podman_available = results["podman"]
        # Step 1: collect license type
        state["setup"].collect_license_model(version_data)
        # Step 2: collect license metric — before namespace so all license questions
        # are grouped together before any cluster interaction begins.
        _pre_type = getattr(state["setup"], "_license_model", None)
        state["selected_license"] = prompt_license_selection(license_type=_pre_type)
        # Step 3: collect namespace, then construct Upgrade (which checks cluster CRs)
        state["setup"].collect_namespace()

        # Pass required files to Upgrade class
        state["upgrade"] = u.Upgrade(console, state["setup"], state["logger"], required_files=required_files,
                                     selected_license=state["selected_license"])


    state["deployment_details"] = create_deployment_info(state["setup"], version_data)
    # Pass CR details to get platform information
    state["version_details"] = create_version_info(state["setup"], version_data, state["upgrade"]._cr_details)

    state["upgrade"].version_details = state["version_details"]
    state["upgrade"].deployment_details = state["deployment_details"]

    # At least one CR (FNCMCluster or CCXAIServices) must be present to proceed.
    _content_present  = state["upgrade"]._cr_present
    _ai_svcs_present  = state["upgrade"]._ai_services_cr_present
    if not _content_present and not _ai_svcs_present:
        print()
        print(Panel(
            f"[bold red]✗ No IBM Content Cortex Deployment Found[/bold red]\n\n"
            f"No deployment found in namespace: [cyan]{state['setup']._namespace}[/cyan]\n\n"
            f"[bold white]At least one of the following Custom Resources must exist:[/bold white]\n"
            f"  • FNCMCluster (Content Operator)\n"
            f"  • CCXAIServices (AI Services Operator)\n\n"
            f"[yellow]💡 Tip:[/yellow] Use these commands to verify:\n"
            f"  [cyan]kubectl get fncmclusters -n {state['setup']._namespace}[/cyan]\n"
            f"  [cyan]kubectl get ccxaiservices -n {state['setup']._namespace}[/cyan]",
            title="[bold red]❌ Deployment Not Found[/bold red]",
            border_style="red",
            padding=(1, 2),
            expand=False,
        ))
        state["logger"].error(
            f"No FNCMCluster or CCXAIServices CR found in namespace {state['setup']._namespace}")
        exit(1)

    # Run deployment upgrade
    run_deployment_upgrade()


if __name__ == "__main__":
    app()
