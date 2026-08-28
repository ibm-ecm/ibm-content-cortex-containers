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

import datetime
import logging
import os
import re
import shutil
import tarfile
import toml
from datetime import datetime

import typer
import click
import questionary
from questionary import Style
from rich import print
from rich.console import Console
from rich.live import Live
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import (BarColumn, Progress,
                           SpinnerColumn, TaskProgressColumn, TextColumn,
                           TimeElapsedColumn)
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text
from typing_extensions import Annotated
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

from helper_scripts.gather import gather as g
from helper_scripts.gather import silent_gather as sg
from helper_scripts.mustgather import mustgather as mg
from helper_scripts.utilities import kubernetes_utilites as k
from helper_scripts.utilities.config_models import validate_mustgather_config
from helper_scripts.utilities.interface import (
    clear,
    display_issues,
    display_prereq_passed, mustgather_details, mustgather_network_results,
    display_config_validation_errors, display_prereq_validation_table,
    display_toml_syntax_error)
from helper_scripts.utilities.utilities import prereq_checks

__version__ = "26.0.0"

app = typer.Typer()

state = {
    "verbose": False,
    "silent": False,
    "logger": logging,
    "dev": False,
    "setup": None,
    "image_details": "",
    "dryrun": False
}

console = Console(record=True)


def setup_logger(file_log_level):
    # Create a logger object
    logger = logging.getLogger()
    logger.setLevel(file_log_level)

    # Setup console logger
    shell_handler = RichHandler(show_time=False, show_path=False)
    shell_handler.setLevel(logging.WARNING)
    formatter_rich = logging.Formatter("%(message)s")
    shell_handler.setFormatter(formatter_rich)

    # Setup file logger
    file_handler = logging.FileHandler("must_gather.log")
    file_handler.setLevel(file_log_level)
    formatter_file = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)-100s - %(filename)s:%(lineno)d", "%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(formatter_file)

    # Add handlers to the logger
    logger.addHandler(shell_handler)
    logger.addHandler(file_handler)

    return logger


def version_callback(value: bool):
    if value:
        print(f"IBM Content Cortex MustGather CLI: {__version__}")
        raise typer.Exit()

def display_mode_version(mode: str, description: str):
    """
    Display the mode and version of the script with active flags in a modern, visually appealing format.
    
    Args:
        mode: The operation mode (e.g., "Gather All", "Gather Network Policies")
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
    
    # Collect active flags
    active_flags = []
    
    if state["silent"]:
        active_flags.append("🤫 Silent Mode")
    
    if state["verbose"]:
        active_flags.append("📢 Verbose Logging")
    
    if state["dryrun"]:
        active_flags.append("🧪 Dry Run Mode")
    
    # Add active flags if any
    if active_flags:
        header_table.add_row("", "")  # Empty row for spacing
        for flag in active_flags:
            header_table.add_row("", f"[bold magenta]{flag}[/bold magenta]")
    
    # Create the main panel with modern styling
    print(Panel(
        header_table,
        title="[bold white]📦 IBM Content Cortex MustGather CLI[/bold white]",
        border_style="bright_blue",
        padding=(1, 2),
        expand=False
    ))
    print()




# Function to filter deployments based on component
def filter_deployments(deployment, component):
    if component in deployment:
        return True
    return False


def create_mustgather_folder(progress, platform, components, collect_sensitive_data, cr_present=True,
                             operator_present=True):
    state["logger"].info("Creating MustGather folder")

    if os.path.exists(os.path.join(os.getcwd(), "MustGather")):
        shutil.rmtree(os.path.join(os.getcwd(), "MustGather"))

    mustgather_folder = os.path.join(os.getcwd(), "MustGather")

    os.mkdir(mustgather_folder)
    state["logger"].info(f"Created MustGather folder: {mustgather_folder}")

    state["logger"].info(f"Creating MustGather components subfolders")

    folder_names = [
        "cluster"
    ]

    if operator_present:
        folder_names.append("operator")

    if cr_present:
        folder_names.append("deployments")
        folder_names.append("services")
        folder_names.append("pvcs")
        folder_names.append("storageclasses")

        if platform == "other":
            folder_names.append("ingresses")
        else:
            folder_names.append("routes")

        folder_names.extend(components)

        if collect_sensitive_data:
            folder_names.extend(["secrets", "configmaps"])

    for folder_name in folder_names:
        os.mkdir(
            os.path.join(
                mustgather_folder,
                folder_name,
            )
        )
    
    state["logger"].info(f"Created MustGather components subfolders")
    return mustgather_folder



# Function to tar the mustgather folder
def tar_mustgather_folder(mustgather_folder, progress, namespace):
    try:
        namespace_no_spaces = re.sub(r"\s+", "", namespace)
        state["logger"].info(f"Generating MustGather tarfile")
        now = datetime.now()
        dt_string = now.strftime("%Y-%m-%d_%H-%M")
        tar_file_name = mustgather_folder + "_"  + namespace_no_spaces + "_" + dt_string + ".tar.gz"

        # Check if tar file exists move it to a backup folder
        if os.path.exists(tar_file_name):
            if not os.path.exists(os.path.join(os.getcwd(), "backups")):
                os.mkdir(os.path.join(os.getcwd(), "backups"))
            now = datetime.now()
            dt_string = now.strftime("%Y-%m-%d_%H-%M")
            shutil.move(tar_file_name, os.path.join(os.getcwd(), "backups",
                                                    "MustGather_" + namespace_no_spaces + "_" + dt_string + ".tar.gz"))

        with tarfile.open(tar_file_name, "w:gz") as tar:
            tar.add(mustgather_folder, arcname=os.path.basename(mustgather_folder))
        state["logger"].info(f"Generated MustGather tarfile: {tar_file_name}")
        shutil.rmtree(mustgather_folder)
        state["logger"].info(f"Removed MustGather folder: {mustgather_folder}")
    except Exception as e:
        state["logger"].exception("Unable to tar logs, caught %s Exiting...", e)

@app.callback(invoke_without_command=True)
def main(
        version: Annotated[bool, typer.Option(
            "--version", help="Show version and exit.",
            callback=version_callback, is_eager=True)] = None,
        verbose: Annotated[bool, typer.Option(
            help="Enable verbose logging.",
            rich_help_panel="Customization and Utils")] = False,
        silent: Annotated[bool, typer.Option(
            help="Enable Silent Install (no prompts).",
            rich_help_panel="Customization and Utils")] = False,
        dryrun: Annotated[bool, typer.Option(
            help="Perform Dry Run of the mustgather script",
            rich_help_panel="Customization and Utils")] = False):

    if click.get_current_context().invoked_subcommand == "networkpolicy":
        return
    """
    IBM Content Cortex MustGather
    """
    # Set up logger FIRST before any display functions
    if verbose:
        state["verbose"] = True
        FILE_LOG_LEVEL = logging.DEBUG
    else:
        FILE_LOG_LEVEL = logging.INFO

    state["logger"] = setup_logger(FILE_LOG_LEVEL)

    if silent:
        state["silent"] = True

    if dryrun:
        state["dryrun"] = True
    
    # Now display the mode/version with flags properly set
    display_mode_version("Gather All",
                         "IBM Content Cortex MustGather for Container Deployment")
    
    # Display what will be collected
    info_text = Text()
    info_text.append("This mode will collect:\n\n", style="bold white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Cluster and namespace information\n", style="white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Operator deployment details\n", style="white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Custom Resource configurations\n", style="white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Pod logs and events\n", style="white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Service and networking details\n", style="white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Storage and PVC information\n", style="white")
    
    print(Panel(
        info_text,
        title="[bold white]📦 MustGather Collection[/bold white]",
        border_style="cyan",
        padding=(1, 2)
    ))
    print()
    
    # Log script details after logger is set up
    log_msg = f"Version: {__version__}\nMode: Gather All\nIBM Content Cortex MustGather for Container Deployment"
    active_flags = []
    if state["silent"]:
        active_flags.append("Silent Mode is enabled")
    if state["verbose"]:
        active_flags.append("Verbose Logging is enabled")
    if state["dryrun"]:
        active_flags.append("Dry Run Mode is enabled")
    if active_flags:
        log_msg += "\n\n" + "\n".join(active_flags)
    state["logger"].info(f"Script details: \n{log_msg}")

    checks = ["connection"]

    state["logger"].info(f"Checking prerequisites")
    missing_tools, results, files = prereq_checks(logger=state["logger"], prereqs=checks)

    # Print table of prerequisites that are missing
    if len(missing_tools) > 0 or len(files) > 0:
        layout = display_issues(tools=missing_tools, descriptors=files)
        print(layout)
        state["logger"].info(f"All prerequisites did not pass.")
        exit(1)
    else:
        state["logger"].info(f"All prerequisites passed.")
        display_prereq_validation_table(results)

    if state["silent"]:
        # this is the user details object which does pre-checks and collects some necessary details
        state["logger"].info(f"Executing in silent mode.")
        silent_path = os.path.join("silent_config", "silent_install_mustgather.toml")

        # Validate configuration with Pydantic before proceeding
        state["logger"].info(f"Validating silent mustgather configuration: {silent_path}")
        try:
            import toml as _toml
            with open(silent_path, 'r') as _f:
                _config_dict = _toml.load(_f)
            _success, _, _validation_errors = validate_mustgather_config(_config_dict)
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

        setup = sg.SilentGatherOptions(state["logger"], silent_path, script_type="must_gather")
        setup.silent_parse_mustgather_operator_file()
    else:
        setup = g.GatherOptions(state["logger"], console, script_type="must_gather")
        setup.collect_namespace()
        setup.collect_sensitive_data()

    namespace = setup.namespace
    collect_sensitive_data = setup.sensitive_collect

    kube = k.KubernetesUtilities(state["logger"])
    
    # Prompt user to select which operator(s) to collect data for
    if not state["silent"]:
        print()
        print(Panel.fit(
            "[bold cyan]Operator Selection[/bold cyan]\n\n"
            "Select which operator(s) you want to collect MustGather data for.\n"
            "You can select one or both operators using the space bar.",
            style="cyan",
            title="[bold]MustGather Configuration[/bold]"
        ))
        print()
        
        operator_choices = questionary.checkbox(
            "Which operator(s) do you want to collect data for? (Use space to select, enter to confirm)",
            choices=[
                questionary.Choice(
                    title="Content Operator - IBM Content Cortex (CCx)",
                    value="content",
                    checked=True  # Default to content operator
                ),
                questionary.Choice(
                    title="AI Services Operator - Content Cortex AI capabilities",
                    value="ai-services"
                )
            ],
            style=Style([
                ('selected', 'fg:green bold'),
                ('pointer', 'fg:cyan bold'),
                ('highlighted', 'fg:cyan'),
                ('answer', 'fg:green bold'),
                ('checkbox', 'fg:cyan bold'),
                ('checkbox-selected', 'fg:green bold')
            ])
        ).ask()
        
        if operator_choices is None or len(operator_choices) == 0:
            state["logger"].warning("No operator selected by user")
            raise typer.Exit(code=1)
        
        selected_operators = operator_choices
    else:
        # In silent mode, use operator selection from the TOML configuration
        selected_operators = setup._selected_operators
    
    state["logger"].info(f"Selected operators: {', '.join(selected_operators)}")
    
    # Collect operator details for all selected operators using multi-threading
    all_operator_details = {}
    
    if len(selected_operators) > 1:
        # Multi-threaded collection for multiple operators
        print()
        print(Panel.fit(
            "[bold cyan]Collecting Operator Details[/bold cyan]\n\n"
            "Using parallel collection for multiple operators...",
            style="cyan",
            title="[bold]Multi-Operator Collection[/bold]"
        ))
        print()
        
        # Track operator status
        operator_status = {op: "⏳ Pending..." for op in selected_operators}
        status_lock = Lock()
        
        def create_status_table():
            """Create a fresh table with current status"""
            table = Table(
                title="🔄 Operator Collection Progress",
                show_header=True,
                header_style="bold cyan",
                border_style="cyan"
            )
            table.add_column("Operator", style="cyan", width=30)
            table.add_column("Status", style="white", width=20)
            
            for op in selected_operators:
                op_display = "Content Operator" if op == "content" else "AI Services Operator"
                status_text = operator_status[op]
                if "Complete" in status_text:
                    style = "green"
                elif "Collecting" in status_text:
                    style = "yellow"
                elif "Error" in status_text or "Not Found" in status_text:
                    style = "red"
                else:
                    style = "yellow"
                table.add_row(op_display, Text(status_text, style=style))
            return table
        
        # Use Live display for real-time updates
        with Live(create_status_table(), console=console, refresh_per_second=4) as live:
            with ThreadPoolExecutor(max_workers=len(selected_operators)) as executor:
                # Submit collection tasks
                future_to_operator = {}
                for selected_operator in selected_operators:
                    state["logger"].info(f"Submitting collection task for {selected_operator}")
                    
                    if selected_operator == "content":
                        operator_deployment = "ibm-content-operator"
                    elif selected_operator == "ai-services":
                        operator_deployment = "ibm-ccx-ai-services-operator"
                    else:
                        operator_deployment = "ibm-content-operator"
                    
                    # Update status to collecting
                    with status_lock:
                        operator_status[selected_operator] = "🔄 Collecting..."
                        live.update(create_status_table())
                    
                    # Get operator details in thread
                    future = executor.submit(
                        kube.get_operator_details,
                        namespace,
                        operator_deployment
                    )
                    future_to_operator[future] = (selected_operator, operator_deployment)
                
                # Collect results as they complete
                for future in as_completed(future_to_operator):
                    selected_operator, operator_deployment = future_to_operator[future]
                    try:
                        operator_details = future.result()
                        if operator_details:
                            operator_details["operator_type"] = selected_operator
                            all_operator_details[selected_operator] = operator_details
                            state["logger"].info(f"Found {selected_operator} operator: {operator_deployment}")
                            
                            # Update status to complete
                            with status_lock:
                                operator_status[selected_operator] = "✓ Complete"
                                live.update(create_status_table())
                        else:
                            state["logger"].warning(f"{selected_operator} operator not found: {operator_deployment}")
                            
                            # Update status to not found
                            with status_lock:
                                operator_status[selected_operator] = "⚠ Not Found"
                                live.update(create_status_table())
                    except Exception as e:
                        state["logger"].exception(f"Error collecting {selected_operator} operator: {e}")
                        
                        # Update status to error
                        with status_lock:
                            operator_status[selected_operator] = "✗ Error"
                            live.update(create_status_table())
        
        print()
        print(Panel.fit("✓ Operator collection complete", style="green"))
        print()
    else:
        # Single operator - use original sequential approach
        for selected_operator in selected_operators:
            state["logger"].info(f"Collecting Operator details for {selected_operator}")
            if selected_operator == "content":
                operator_deployment = "ibm-content-operator"
            elif selected_operator == "ai-services":
                operator_deployment = "ibm-ccx-ai-services-operator"
            else:
                operator_deployment = "ibm-content-operator"
            
            operator_details = kube.get_operator_details(namespace, operator_deployment)
            if operator_details:
                operator_details["operator_type"] = selected_operator
                all_operator_details[selected_operator] = operator_details
                state["logger"].info(f"Found {selected_operator} operator: {operator_deployment}")
            else:
                state["logger"].warning(f"{selected_operator} operator not found in namespace: {operator_deployment}")
    
    # For backward compatibility, use the first operator's details as primary
    operator_present = len(all_operator_details) > 0
    operator_details = list(all_operator_details.values())[0] if operator_present else {}
    
    # Collect CR details (shared across operators)
    state["logger"].info(f"Collecting CR details")
    custom_resources = kube.get_deployment_cr(namespace=namespace, logger=state["logger"])
    components = []
    deployment_details = {}

    if len(custom_resources) == 0:
        cr_present = False
        print("[prompt.invalid] No custom resources found.")
        state["logger"].info(f"No custom resources found.")
    else:
        cr_present = True
        deployment_details = kube.cr_details
        version = deployment_details["version"]
        deployments = deployment_details["components"]

        if not state["silent"]:
            state["logger"].info(f"Collecting mustgather components.")
            setup.collect_mustgather_components(deployments, selected_operators)
            components = list(setup.components)
            state["logger"].info(f"Components for mustgather: {components}")

        else:
            components = list(setup.components)

    # Pass all operator details to summary display
    summary = mustgather_details(deployment_details, components, all_operator_details, selected_operators)

    print()
    print(summary)

    # Build operator-aware text for messages
    if len(selected_operators) == 2:
        operator_text = "Content & AI Services Operators"
    elif "ai-services" in selected_operators:
        operator_text = "AI Services Operator"
    else:
        operator_text = "Content Operator"
    
    if not state["silent"]:
        proceed = questionary.confirm(
            f"🚀 Ready to collect MustGather data for {operator_text}. Proceed?",
            default=True,
            style=Style([
                ('question', 'fg:cyan bold'),
                ('answer', 'fg:green bold')
            ])
        ).ask()
        
        if not proceed:
            state["logger"].warning("MustGather cancelled by user")
            print()
            print(Panel.fit("❌ MustGather Collection Cancelled", style="yellow"))
            raise typer.Exit(code=1)
    
    if state["dryrun"]:
        print()
        print(Panel.fit("✓ Dry Run Complete - No Data Collected", style="green"))
        exit()
    
    # Build operator-aware start message
    start_msg = f"🔄 Starting MustGather Collection\n{operator_text}"
    
    print()
    print(Panel.fit(start_msg, style="bold cyan", border_style="cyan"))
    state["logger"].info(f"Starting MustGather for {operator_text}")

    # Initialize status tracking for Live display
    collection_status = {
        "Cluster Info": {"status": "⏳ Pending", "details": ""},
        "Operator Info": {"status": "⏳ Pending", "details": ""},
        "Deployment Artifacts": {"status": "⏳ Pending", "details": ""},
        "Component Logs": {"status": "⏳ Pending", "details": ""},
        "Tar File": {"status": "⏳ Pending", "details": ""}
    }
    status_lock = Lock()
    
    def create_collection_status_table():
        """Create a fresh status table with current collection status"""
        table = Table(
            title="📦 MustGather Collection Progress",
            show_header=True,
            header_style="bold cyan",
            border_style="cyan",
            title_style="bold cyan"
        )
        table.add_column("Collection Phase", style="cyan", width=25)
        table.add_column("Status", style="white", width=20)
        table.add_column("Details", style="white", width=50)
        
        for phase, info in collection_status.items():
            status = info["status"]
            details = info["details"]
            
            if "Complete" in status or "✓" in status:
                style = "green"
            elif "Collecting" in status or "🔄" in status:
                style = "yellow"
            elif "Error" in status or "✗" in status:
                style = "red"
            else:
                style = "dim white"
            
            table.add_row(
                phase,
                Text(status, style=style),
                Text(details, style="dim white" if not details else "white")
            )
        return table
    
    # Prepare platform and resource details
    platform = "OCP"
    if operator_present and operator_details.get("type") == "YAML":
        platform = "other"
    
    # Prepare CR details if present
    resource_type_dict = None
    pod_count_dict = {}
    num_collections = 0
    
    # Separate Content and AI Services components
    content_components = [c for c in components if c not in ["coremcp", "reasoning"]]
    ai_services_components = [c for c in components if c in ["coremcp", "reasoning"]]
    
    if cr_present:
        cr_name = deployment_details["name"]
        platform = deployment_details["platform"]
        storage_class = deployment_details["storage_classes"]
        user_secrets = deployment_details["user_secrets"]
        user_configmaps = deployment_details["user_configmaps"]

        resource_type_dict = kube.list_namespace_resources(console=console,
                                                           namespace=namespace,
                                                           platform=platform,
                                                           filter=cr_name)

        # Calculate number of pods per component to be collected for Content components
        num_components = len(content_components)
        if num_components != 0:
            deployment_dict = {}
            for component in content_components:
                # Get deployments for each component
                state["logger"].info(f"Getting deployments for component: {component}")
                if component == "ban":
                    deployment_dict[component] = filter(lambda x: filter_deployments(x, "navigator"),
                                                        resource_type_dict["deployment"])
                else:
                    deployment_dict[component] = filter(lambda x: filter_deployments(x, component),
                                                        resource_type_dict["deployment"])

            for component in content_components:
                pod_count_dict[component] = []
                for deploy in deployment_dict[component]:
                    num_collections += 1
                    details_dict = {}
                    details_dict["deployment"] = deploy
                    pods = kube.get_pod_names_for_deployment(namespace, deploy)
                    init_containers = kube.get_init_containers_for_deployment(namespace, deploy)
                    details_dict["init_containers"] = init_containers
                    details_dict["pods"] = pods
                    details_dict["count"] = len(pods) if pods else 0
                    pod_count_dict[component].append(details_dict)
    
    # Handle AI Services components separately if AI Services operator is selected
    ai_services_cr_details = {}
    if "ai-services" in selected_operators and len(ai_services_components) > 0:
        state["logger"].info(f"Discovering AI Services CR and resources")
        ai_services_cr = kube.get_ai_services_cr(namespace, logger=state["logger"])
        
        if ai_services_cr and "metadata" in ai_services_cr:
            ai_services_cr_name = ai_services_cr["metadata"]["name"]
            state["logger"].info(f"Found AI Services CR: {ai_services_cr_name}")
            
            # Store AI Services CR details for later use
            ai_services_cr_details = {
                "name": ai_services_cr_name,
                "cr": ai_services_cr
            }
            
            # Discover AI Services resources using ownerReferences
            ai_services_resources = kube.list_namespace_resources(
                console=console,
                namespace=namespace,
                platform=platform,
                filter=ai_services_cr_name
            )
            
            deployments_found = ai_services_resources.get('deployment', [])
            state["logger"].info(f"Found {len(deployments_found)} AI Services deployments: {deployments_found}")
            
            # Merge AI Services resources into the main resource_type_dict
            # This ensures all AI Services artifacts (deployments, services, PVCs, secrets, configmaps, etc.) are collected
            if resource_type_dict:
                state["logger"].info(f"Merging AI Services resources into main resource collection")
                for resource_type, resources in ai_services_resources.items():
                    if resource_type in resource_type_dict:
                        # Merge and deduplicate
                        combined = list(set(resource_type_dict[resource_type] + resources))
                        resource_type_dict[resource_type] = combined
                        state["logger"].info(f"Merged {len(resources)} AI Services {resource_type}(s) - total now: {len(combined)}")
                    else:
                        resource_type_dict[resource_type] = resources
                        state["logger"].info(f"Added {len(resources)} AI Services {resource_type}(s)")
            else:
                # If no content resources, use AI Services resources as the base
                resource_type_dict = ai_services_resources
                state["logger"].info(f"Using AI Services resources as base resource collection")
            
            # Add AI Services user-created configmaps and secrets
            # These are not owned by the CR but are referenced by the deployment
            ai_services_user_configmaps = ["ibm-ai-services-integration-config"]
            ai_services_user_secrets = ["ibm-ai-services-oidc-secret", "ibm-ai-services-watsonx-secret"]
            
            state["logger"].info(f"Adding AI Services user-created configmaps: {ai_services_user_configmaps}")
            if resource_type_dict and "config_map" in resource_type_dict:
                resource_type_dict["config_map"].extend(ai_services_user_configmaps)
                resource_type_dict["config_map"] = list(set(resource_type_dict["config_map"]))
            elif resource_type_dict:
                resource_type_dict["config_map"] = ai_services_user_configmaps
            
            state["logger"].info(f"Adding AI Services user-created secrets: {ai_services_user_secrets}")
            if resource_type_dict and "secret" in resource_type_dict:
                resource_type_dict["secret"].extend(ai_services_user_secrets)
                resource_type_dict["secret"] = list(set(resource_type_dict["secret"]))
            elif resource_type_dict:
                resource_type_dict["secret"] = ai_services_user_secrets
            
            # Build deployment dict for AI Services components
            ai_deployment_dict = {}
            for component in ai_services_components:
                state["logger"].info(f"Getting deployments for AI Services component: {component}")
                # Map component names to deployment name patterns
                if component == "coremcp":
                    ai_deployment_dict[component] = [d for d in deployments_found if "core-mcp" in d.lower() or "coremcp" in d.lower()]
                    state["logger"].info(f"Found {len(ai_deployment_dict[component])} deployments for coremcp: {ai_deployment_dict[component]}")
                elif component == "reasoning":
                    ai_deployment_dict[component] = [d for d in deployments_found if "reasoning" in d.lower()]
                    state["logger"].info(f"Found {len(ai_deployment_dict[component])} deployments for reasoning: {ai_deployment_dict[component]}")
            
            # Build pod_count_dict for AI Services components
            for component in ai_services_components:
                pod_count_dict[component] = []
                for deploy in ai_deployment_dict.get(component, []):
                    num_collections += 1
                    details_dict = {}
                    details_dict["deployment"] = deploy
                    pods = kube.get_pod_names_for_deployment(namespace, deploy)
                    init_containers = kube.get_init_containers_for_deployment(namespace, deploy)
                    details_dict["init_containers"] = init_containers
                    details_dict["pods"] = pods
                    details_dict["count"] = len(pods) if pods else 0
                    pod_count_dict[component].append(details_dict)
                    state["logger"].info(f"Found {len(pods) if pods else 0} pods for {component} deployment: {deploy}")
        else:
            state["logger"].warning(f"AI Services CR not found in namespace {namespace}")
            print(f"[yellow]⚠ AI Services CR not found - AI Services components will not be collected[/yellow]")
    
    # Use Live display for real-time status updates
    print()
    with Live(create_collection_status_table(), console=console, refresh_per_second=4) as live:
        # Create MustGather folder
        mustgather_folder = create_mustgather_folder(None, platform, components, collect_sensitive_data,
                                                     cr_present, operator_present)
        
        must_gather = mg.MustGather(console, namespace, state["logger"], mustgather_folder, deployment_details,
                                    operator_details, kube)
        
        # Phase 1: Collect Cluster Info
        with status_lock:
            collection_status["Cluster Info"]["status"] = "🔄 Collecting..."
            collection_status["Cluster Info"]["details"] = "Cluster version, nodes, events..."
            live.update(create_collection_status_table())
        
        state["logger"].info(f"Collecting cluster information")
        must_gather.collect_cluster_info(None)
        
        with status_lock:
            collection_status["Cluster Info"]["status"] = "✓ Complete"
            collection_status["Cluster Info"]["details"] = "Version, nodes, events collected"
            live.update(create_collection_status_table())

        # Phase 2: Collect Operator Info for all selected operators
        if operator_present and len(all_operator_details) > 0:
            # Display appropriate operator name(s) based on selection
            if len(selected_operators) > 1:
                operator_display_name = "Content & AI Services Operators"
            elif "ai-services" in selected_operators:
                operator_display_name = "AI Services Operator"
            else:
                operator_display_name = "Content Operator"
            
            with status_lock:
                collection_status["Operator Info"]["status"] = "🔄 Collecting..."
                collection_status["Operator Info"]["details"] = f"Collecting {operator_display_name}..."
                live.update(create_collection_status_table())
            
            state["logger"].info(f"Collecting {operator_display_name} information")
            
            # Collect info for each operator separately
            for operator_type, op_details in all_operator_details.items():
                operator_name = "Content Operator" if operator_type == "content" else "AI Services Operator"
                state["logger"].info(f"Collecting {operator_name} information")
                
                # Collect RBAC Info
                with status_lock:
                    collection_status["Operator Info"]["details"] = f"{operator_name}: RBAC resources..."
                    live.update(create_collection_status_table())
                must_gather.collect_rbac_info(None, op_details)
                
                # Collect Operator Info
                with status_lock:
                    collection_status["Operator Info"]["details"] = f"{operator_name}: Deployment & logs..."
                    live.update(create_collection_status_table())
                must_gather.collect_operator_info(None, collect_sensitive_data, op_details)
            
            with status_lock:
                collection_status["Operator Info"]["status"] = "✓ Complete"
                collection_status["Operator Info"]["details"] = f"{operator_display_name} collected"
                live.update(create_collection_status_table())
        else:
            with status_lock:
                collection_status["Operator Info"]["status"] = "⊘ Skipped"
                collection_status["Operator Info"]["details"] = "No operator found"
                live.update(create_collection_status_table())
        
        # Phase 3: Collect Deployment Artifacts
        if cr_present and resource_type_dict:
            with status_lock:
                collection_status["Deployment Artifacts"]["status"] = "🔄 Collecting..."
                collection_status["Deployment Artifacts"]["details"] = "Custom Resource..."
                live.update(create_collection_status_table())
            
            # Download Content CR only if Content operator is selected
            if "content" in selected_operators:
                state["logger"].info(f"Downloading Content CR file")
                must_gather.write_cr_file(None, deployment_details["name"])
            
            # Download AI Services CR if AI Services operator is selected
            if "ai-services" in selected_operators:
                with status_lock:
                    collection_status["Deployment Artifacts"]["details"] = "AI Services Custom Resource..."
                    live.update(create_collection_status_table())
                state["logger"].info(f"Downloading AI Services CR file")
                # The method will fetch the CR and extract the actual name from metadata
                must_gather.write_ai_services_cr_file(None)

            # Collect all Deployments
            with status_lock:
                collection_status["Deployment Artifacts"]["details"] = f"Deployments ({len(resource_type_dict['deployment'])})..."
                live.update(create_collection_status_table())
            state["logger"].info(f"Collecting all deployments")
            if len(resource_type_dict["deployment"]) > 0:
                deployments = resource_type_dict["deployment"]
                must_gather.collect_deployment_info(None, deployments)

            # Collect all PodDisruptionBudget Info
            state["logger"].info(f"Collecting PodDisruptionBudget (PDB) information")
            if resource_type_dict.get("pod_disruption_budget"):
                with status_lock:
                    collection_status["Deployment Artifacts"]["details"] = "PodDisruptionBudgets..."
                    live.update(create_collection_status_table())
                pdbs = resource_type_dict["pod_disruption_budget"]
                must_gather.collect_pdb_info(None, pdbs)

            # Collect all HorizontalPodAutoscaler Info
            state["logger"].info(f"Collecting HorizontalPodAutoscaler (HPA) information")
            if resource_type_dict.get("horizontal_pod_autoscaler"):
                with status_lock:
                    collection_status["Deployment Artifacts"]["details"] = "HorizontalPodAutoscalers..."
                    live.update(create_collection_status_table())
                hpas = resource_type_dict["horizontal_pod_autoscaler"]
                must_gather.collect_hpa_info(None, hpas)

            # Collect all StorageClass Info
            with status_lock:
                collection_status["Deployment Artifacts"]["details"] = "Storage Classes & PVCs..."
                live.update(create_collection_status_table())
            state["logger"].info(f"Collecting all storage class information")
            if len(storage_class) > 0:
                must_gather.collect_storage_class_info(None, storage_class)

            # Collect all PersistentVolume Info
            state["logger"].info(f"Collecting persistent volume information")
            if len(resource_type_dict["persistent_volume_claim"]) > 0:
                pvcs = resource_type_dict["persistent_volume_claim"]
                must_gather.collect_pvc_info(None, pvcs)

            # Collect all Service Info
            with status_lock:
                collection_status["Deployment Artifacts"]["details"] = f"Services ({len(resource_type_dict['service'])})..."
                live.update(create_collection_status_table())
            state["logger"].info(f"Collecting services information")
            if len(resource_type_dict["service"]) > 0:
                services = resource_type_dict["service"]
                must_gather.collect_service_info(None, services)

            # Collect all NetworkPolicy Info
            with status_lock:
                collection_status["Deployment Artifacts"]["details"] = "Network Policies..."
                live.update(create_collection_status_table())
            state["logger"].info(f"Collecting network policy information")
            if len(resource_type_dict["network_policy"]) > 0:
                network_policies = resource_type_dict["network_policy"]
                must_gather.collect_network_policy_info(None, network_policies)

            if platform == "other":
                with status_lock:
                    collection_status["Deployment Artifacts"]["details"] = "Ingresses..."
                    live.update(create_collection_status_table())
                state["logger"].info(f"Collecting ingresses information")
                if len(resource_type_dict["ingress"]) > 0:
                    ingress = resource_type_dict["ingress"]
                    must_gather.collect_ingress_info(None, ingress)
            else:
                with status_lock:
                    collection_status["Deployment Artifacts"]["details"] = "Routes..."
                    live.update(create_collection_status_table())
                state["logger"].info(f"Collecting routes information")
                if len(resource_type_dict["routes"]) > 0:
                    routes = resource_type_dict["routes"]
                    must_gather.collect_route_info(None, routes)

            if collect_sensitive_data:
                with status_lock:
                    collection_status["Deployment Artifacts"]["details"] = "Secrets & ConfigMaps..."
                    live.update(create_collection_status_table())
                state["logger"].info(f"Collecting secrets information")
                secrets = resource_type_dict["secret"]
                secrets.extend(user_secrets)
                if len(secrets) > 0:
                    must_gather.collect_secret_info(None, secrets)

                state["logger"].info(f"Collecting ConfigMaps information")
                configmaps = resource_type_dict["config_map"]
                configmaps.extend(user_configmaps)
                if len(configmaps) > 0:
                    must_gather.collect_configmap_info(None, configmaps)
            
            with status_lock:
                collection_status["Deployment Artifacts"]["status"] = "✓ Complete"
                collection_status["Deployment Artifacts"]["details"] = f"{len(resource_type_dict['deployment'])} deployments, {len(resource_type_dict['service'])} services"
                live.update(create_collection_status_table())
        else:
            with status_lock:
                collection_status["Deployment Artifacts"]["status"] = "⊘ Skipped"
                collection_status["Deployment Artifacts"]["details"] = "No CR found"
                live.update(create_collection_status_table())
        
        # Phase 4: Collect Component Logs
        if len(components) > 0 and num_collections > 0:
            with status_lock:
                collection_status["Component Logs"]["status"] = f"🔄 Collecting (0/{num_collections})..."
                live.update(create_collection_status_table())
            
            collected_count = 0
            for component in components:
                if component == "ban":
                    if len(pod_count_dict[component]) == 0:
                        state["logger"].info(f"No Pods Found for Navigator")
                    else:
                        with status_lock:
                            collection_status["Component Logs"]["details"] = "Collecting Navigator logs..."
                            live.update(create_collection_status_table())
                        for deploy in pod_count_dict[component]:
                            must_gather.collect_ban_info(None, collect_sensitive_data,
                                                         deploy["pods"],
                                                         deploy["init_containers"])
                            collected_count += 1
                            with status_lock:
                                collection_status["Component Logs"]["status"] = f"🔄 Collecting ({collected_count}/{num_collections})..."
                                live.update(create_collection_status_table())
                
                if component == "cpe":
                    if len(pod_count_dict[component]) == 0:
                        state["logger"].info(f"No Pods Found for CPE")
                    else:
                        with status_lock:
                            collection_status["Component Logs"]["details"] = "Collecting CPE logs..."
                            live.update(create_collection_status_table())
                        for deploy in pod_count_dict[component]:
                            must_gather.collect_cpe_info(None,
                                                         collect_sensitive_data,
                                                         deploy["pods"],
                                                         deploy["init_containers"])
                            collected_count += 1
                            with status_lock:
                                collection_status["Component Logs"]["status"] = f"🔄 Collecting ({collected_count}/{num_collections})..."
                                live.update(create_collection_status_table())

                if component == "css":
                    if len(pod_count_dict[component]) == 0:
                        state["logger"].info(f"No Pods Found for CSS")
                    else:
                        with status_lock:
                            collection_status["Component Logs"]["details"] = "Collecting CSS logs..."
                            live.update(create_collection_status_table())
                        for i in range(len(pod_count_dict[component])):
                            must_gather.collect_css_info(None,
                                                         collect_sensitive_data,
                                                         pod_count_dict[component][i]["pods"],
                                                         pod_count_dict[component][i]["init_containers"], str(i + 1))
                            collected_count += 1
                            with status_lock:
                                collection_status["Component Logs"]["status"] = f"🔄 Collecting ({collected_count}/{num_collections})..."
                                live.update(create_collection_status_table())
                
                if component == "graphql":
                    if len(pod_count_dict[component]) == 0:
                        state["logger"].info(f"No Pods Found for GraphQL")
                    else:
                        with status_lock:
                            collection_status["Component Logs"]["details"] = "Collecting GraphQL logs..."
                            live.update(create_collection_status_table())
                        for deploy in pod_count_dict[component]:
                            must_gather.collect_graphql_info(None,
                                                             collect_sensitive_data,
                                                             deploy["pods"],
                                                             deploy["init_containers"])
                            collected_count += 1
                            with status_lock:
                                collection_status["Component Logs"]["status"] = f"🔄 Collecting ({collected_count}/{num_collections})..."
                                live.update(create_collection_status_table())
                
                if component == "cmis":
                    if len(pod_count_dict[component]) == 0:
                        state["logger"].info(f"No Pods Found for CMIS")
                    else:
                        with status_lock:
                            collection_status["Component Logs"]["details"] = "Collecting CMIS logs..."
                            live.update(create_collection_status_table())
                        for deploy in pod_count_dict[component]:
                            must_gather.collect_cmis_info(None,
                                                          collect_sensitive_data,
                                                          deploy["pods"],
                                                          deploy["init_containers"])
                            collected_count += 1
                            with status_lock:
                                collection_status["Component Logs"]["status"] = f"🔄 Collecting ({collected_count}/{num_collections})..."
                                live.update(create_collection_status_table())
                
                if component == "es":
                    if len(pod_count_dict[component]) == 0:
                        state["logger"].info(f"No Pods Found for External Share")
                    else:
                        with status_lock:
                            collection_status["Component Logs"]["details"] = "Collecting External Share logs..."
                            live.update(create_collection_status_table())
                        for deploy in pod_count_dict[component]:
                            must_gather.collect_es_info(None,
                                                        collect_sensitive_data,
                                                        deploy["pods"],
                                                        deploy["init_containers"])
                            collected_count += 1
                            with status_lock:
                                collection_status["Component Logs"]["status"] = f"🔄 Collecting ({collected_count}/{num_collections})..."
                                live.update(create_collection_status_table())
                
                if component == "tm":
                    if len(pod_count_dict[component]) == 0:
                        state["logger"].info(f"No Pods Found for Task Manager")
                    else:
                        with status_lock:
                            collection_status["Component Logs"]["details"] = "Collecting Task Manager logs..."
                            live.update(create_collection_status_table())
                        for deploy in pod_count_dict[component]:
                            must_gather.collect_tm_info(None,
                                                        collect_sensitive_data,
                                                        deploy["pods"],
                                                        deploy["init_containers"])
                            collected_count += 1
                            with status_lock:
                                collection_status["Component Logs"]["status"] = f"🔄 Collecting ({collected_count}/{num_collections})..."
                                live.update(create_collection_status_table())

                if component == "iccsap":
                    if len(pod_count_dict[component]) == 0:
                        state["logger"].info(f"No Pods Found for ICCSAP")
                    else:
                        with status_lock:
                            collection_status["Component Logs"]["details"] = "Collecting ICCSAP logs..."
                            live.update(create_collection_status_table())
                        for deploy in pod_count_dict[component]:
                            must_gather.collect_iccsap_info(None,
                                                            collect_sensitive_data,
                                                            deploy["pods"],
                                                            deploy["init_containers"])
                            collected_count += 1
                            with status_lock:
                                collection_status["Component Logs"]["status"] = f"🔄 Collecting ({collected_count}/{num_collections})..."
                                live.update(create_collection_status_table())

                if component == "ier":
                    if len(pod_count_dict[component]) == 0:
                        state["logger"].info(f"No Pods Found for IER")
                    else:
                        with status_lock:
                            collection_status["Component Logs"]["details"] = "Collecting IER logs..."
                            live.update(create_collection_status_table())
                        for deploy in pod_count_dict[component]:
                            must_gather.collect_ier_info(None,
                                                         collect_sensitive_data,
                                                         deploy["pods"],
                                                         deploy["init_containers"])
                            collected_count += 1
                            with status_lock:
                                collection_status["Component Logs"]["status"] = f"🔄 Collecting ({collected_count}/{num_collections})..."
                                live.update(create_collection_status_table())

                if component == "ccxmo":
                    if len(pod_count_dict[component]) == 0:
                        state["logger"].info(f"No Pods Found for CCXMO")
                    else:
                        with status_lock:
                            collection_status["Component Logs"]["details"] = "Collecting CCXMO logs..."
                            live.update(create_collection_status_table())
                        for deploy in pod_count_dict[component]:
                            must_gather.collect_ccxmo_info(None,
                                                           collect_sensitive_data,
                                                           deploy["pods"],
                                                           deploy["init_containers"])
                            collected_count += 1
                            with status_lock:
                                collection_status["Component Logs"]["status"] = f"🔄 Collecting ({collected_count}/{num_collections})..."
                                live.update(create_collection_status_table())
            
                if component == "coremcp":
                    if component not in pod_count_dict or len(pod_count_dict[component]) == 0:
                        state["logger"].info(f"No Pods Found for Core MCP")
                    else:
                        with status_lock:
                            collection_status["Component Logs"]["details"] = "Collecting Core MCP logs..."
                            live.update(create_collection_status_table())
                        for deploy in pod_count_dict[component]:
                            must_gather.collect_coremcp_info(None,
                                                           collect_sensitive_data,
                                                           deploy["pods"],
                                                           deploy["init_containers"])
                            collected_count += 1
                            with status_lock:
                                collection_status["Component Logs"]["status"] = f"🔄 Collecting ({collected_count}/{num_collections})..."
                                live.update(create_collection_status_table())

                if component == "reasoning":
                    if component not in pod_count_dict or len(pod_count_dict[component]) == 0:
                        state["logger"].info(f"No Pods Found for Reasoning Service")
                    else:
                        with status_lock:
                            collection_status["Component Logs"]["details"] = "Collecting Reasoning Service logs..."
                            live.update(create_collection_status_table())
                        for deploy in pod_count_dict[component]:
                            must_gather.collect_reasoning_info(None,
                                                             collect_sensitive_data,
                                                             deploy["pods"],
                                                             deploy["init_containers"])
                            collected_count += 1
                            with status_lock:
                                collection_status["Component Logs"]["status"] = f"🔄 Collecting ({collected_count}/{num_collections})..."
                                live.update(create_collection_status_table())
            
            with status_lock:
                collection_status["Component Logs"]["status"] = "✓ Complete"
                collection_status["Component Logs"]["details"] = f"{num_collections} component deployments collected"
                live.update(create_collection_status_table())
        else:
            if len(components) > 0:
                state["logger"].info(f"No Pods Found for Selected Components")
            with status_lock:
                collection_status["Component Logs"]["status"] = "⊘ Skipped"
                collection_status["Component Logs"]["details"] = "No components or pods found"
                live.update(create_collection_status_table())
        
        # Phase 5: Create Tar File
        with status_lock:
            collection_status["Tar File"]["status"] = "🔄 Creating..."
            collection_status["Tar File"]["details"] = f"Compressing {namespace} MustGather..."
            live.update(create_collection_status_table())
        
        tar_mustgather_folder(mustgather_folder, None, namespace)
        
        with status_lock:
            collection_status["Tar File"]["status"] = "✓ Complete"
            collection_status["Tar File"]["details"] = f"MustGather_{namespace}.tar.gz created"
            live.update(create_collection_status_table())
    
    # Final summary
    print()
    print(Panel.fit("✓ MustGather Collection Complete", style="bold green"))
    print()

@app.command()
def networkpolicy(apply: bool = typer.Option(False, help="Apply all generated network policies to the cluster")):
    """
    Collect the Network policy templates from the IBM Content Cortex Operator
    """
    # Set up logger FIRST
    state["logger"] = setup_logger(logging.INFO)
    
    display_mode_version("Gather Network Policies",
                        "IBM Content Cortex MustGather for Container Deployment")
    
    # Display what will be collected
    info_text = Text()
    info_text.append("This mode will collect:\n\n", style="bold white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Network policy templates from operator\n", style="white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Current network policy configurations\n", style="white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Generate deployment-specific policies\n", style="white")
    if apply:
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Apply policies to cluster\n", style="white")
    
    print(Panel(
        info_text,
        title="[bold white]🔒 Network Policy Collection[/bold white]",
        border_style="cyan",
        padding=(1, 2)
    ))
    print()

    checks = ["connection"]

    missing_tools, results, files = prereq_checks(logger=state["logger"], prereqs=checks)
    if len(missing_tools) > 0 or len(files) > 0:
        layout = display_issues(tools=missing_tools, descriptors=files)
        print(layout)
        exit(1)
    else:
        state["logger"].info(f"All prerequisites passed.")
        display_prereq_validation_table(results)

    setup = g.GatherOptions(state["logger"], console, script_type="must_gather")
    setup.collect_namespace()
    kube = k.KubernetesUtilities(state["logger"])
    deployment_details = {}

    # Collect Operator details
    operator_deployment = "ibm-content-operator"
    namespace = setup.namespace
    operator_details = kube.get_operator_details(namespace, operator_deployment)
    if operator_details['release'] not in ['5.7.0']:
        print(Text(f"Current operator release is {operator_details['release']}\n"
                f"Only operators from 5.7.0 and later releases will generate network policy templates", style="red"))
        raise typer.Exit()
    np_folder = os.path.join(os.getcwd(), "FNCMNetworkPolicies", namespace)
    must_gather = mg.MustGather(console, namespace, state["logger"], np_folder, deployment_details, operator_details, kube)
    if apply:
        if os.path.exists(np_folder):
            print()
            print(Panel.fit(Text(f"Found {os.path.basename(np_folder)} Folder. Applying existing network policies"), style="cyan"))
            print()
            state["logger"].info(f"Found {os.path.basename(np_folder)} Folder. Applying existing network policies")
            must_gather.auto_apply_networkpolicy()
        else:
            print()
            print(Panel.fit(Text(f"{os.path.basename(np_folder)} Folder not found. Starting Copying Network policy Templates"), style="cyan"))
            print()
            state["logger"].info(f"Folder: {os.path.basename(np_folder)} not found. Applying existing network policies")
            with Progress(SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        BarColumn(),
                        transient=True,
                        console=console) as progress:
                if operator_details:
                    task1 = progress.add_task("[cyan]Collect Network Policies", total=None)
                    state["logger"].info(f"Collecting network policies")
                    must_gather.collect_network_policy_templates(progress, operator_details) 
                    progress.update(task1, total=1, completed=1)
                else:
                    print(Panel.fit(Text("IBM Content Cortex Operator not found in namespace."),style="bold red"))
                    state["logger"].info(f"IBM Content Cortex Operator not found in namespace.")
                    raise typer.Exit()

            # Output Network Policy Template folder
            print()
            print(Panel.fit(Text("Applying downloaded network policies"), style="cyan"))
            state["logger"].info(f"Applying downloaded network policies")
            print()
            must_gather.auto_apply_networkpolicy()
        raise typer.Exit()

    else:        
        setup = g.GatherOptions(state["logger"], console, script_type="must_gather")
        setup.collect_namespace()
        kube = k.KubernetesUtilities(state["logger"])

        deployment_details = {}

        # Collect Operator details
        operator_deployment = "ibm-content-operator"
        namespace = setup.namespace
        operator_details = kube.get_operator_details(namespace, operator_deployment)
        if operator_details['release'] not in ['5.7.0']:
            print(Text(f"Current operator release is {operator_details['release']}\n"
                    f"Only operators from 5.7.0 and later releases will generate network policy templates", style="red"))
            raise typer.Exit()
        np_folder = os.path.join(os.getcwd(), "FNCMNetworkPolicies", namespace)

        must_gather = mg.MustGather(console, namespace, state["logger"], np_folder, deployment_details,operator_details, kube)
        if os.path.exists(np_folder):
            namespace_no_spaces = re.sub(r"\s+", "", namespace)
            now = datetime.now()
            dt_string = now.strftime("%Y-%m-%d_%H-%M")
            tar_file_name = os.getcwd() + "/backups/" + "FNCMNetworkPolicies" + "_"  + namespace_no_spaces + "_" + dt_string + ".tar.gz"
            if not os.path.exists(os.path.join(os.getcwd(), "backups")):
                os.mkdir(os.path.join(os.getcwd(), "backups"))
            try:
                with tarfile.open(tar_file_name, "w:gz") as tar:
                    tar.add(np_folder, arcname=os.path.basename(np_folder))
                    shutil.rmtree(np_folder)
            except Exception as e:
                 state["logger"].exception("Unable to tar network policies, caught %s Exiting...", e)

        if len(operator_details.get("pods", 0)) == 0:
            print()
            print(Panel.fit(Text("IBM Content Cortex Operator not found in namespace."), style="bold red"))
            state["logger"].info(f"IBM Content Cortex Operator not found in namespace.")
            raise typer.Exit()

        print()
        print(Panel.fit(Text("Starting Copying Network Policy Templates"), style="cyan"))
        print()
        state["logger"].info(f"Starting Copying Network Policy Templates")

        with Progress(SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    transient=True,
                    console=console) as progress:

            task1 = progress.add_task("[cyan]Collect Network Policies", total=None)
            must_gather.collect_network_policy_templates(progress,operator_details)
            progress.update(task1, total=1, completed=1)


        results = mustgather_network_results(np_folder, namespace)
        print(results)
        print()

        apply_networkpolicy = Confirm.ask("Do you want to apply the retrieved network policies to your cluster?", default=False)
        if apply_networkpolicy:
            state["logger"].info(f"Appliying the Network Policies.")
            must_gather.auto_apply_networkpolicy()
        raise typer.Exit()

if __name__ == "__main__":
    app()
