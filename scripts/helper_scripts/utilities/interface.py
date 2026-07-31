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

import os
import pathlib
import platform
from datetime import datetime
from enum import Enum
from typing import List

from rich.columns import Columns
from rich.console import Group
from rich.filesize import decimal
from rich.layout import Layout
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .prerequisites_utilites import parse_required_fields


def display_license_agreement(console, version_data: dict = None) -> bool:
    """
    Display the IBM Content Cortex license agreement and require acceptance.
    
    This function presents the license terms in a prominent, visually emphasized format
    and requires the user to explicitly accept before proceeding with operator installation.
    
    Args:
        console: Rich console instance for output
        version_data: Dictionary containing version information
        
    Returns:
        bool: True if license accepted, False otherwise
    """
    import questionary
    from questionary import Style
    from rich.prompt import Confirm
    
    # Clear screen for emphasis
    clear(console)
    
    # Get version if available
    detected_version = version_data.get("VERSION", "26.0.0") if version_data else "26.0.0"
    
    # First Panel: License Agreement Required
    license_info_text = Text()
    license_info_text.append("🔍 ", style="bold yellow")
    license_info_text.append("Detected Version: ", style="bold white")
    license_info_text.append(f"{detected_version}\n\n", style="bold green")
    
    license_info_text.append("📄 ", style="bold cyan")
    license_info_text.append("International Program License Agreement\n\n", style="bold white")
    
    license_info_text.append("Please review the license agreements before proceeding:\n\n", style="white")
    
    license_info_text.append("📄 ", style="bold cyan")
    license_info_text.append("IBM Content Cortex:\n", style="bold white")
    license_info_text.append("   https://ibm.biz/CPE_CCX_License_26_0_0\n\n", style="cyan")
    
    license_info_text.append("📄 ", style="bold cyan")
    license_info_text.append("Software Notices:\n", style="bold white")
    license_info_text.append("   http://ibm.biz/CCX_Notices_26_0_0\n\n", style="cyan")
    
    license_info_text.append("📄 ", style="bold cyan")
    license_info_text.append("IBM Enterprise Records:\n", style="bold white")
    license_info_text.append("   https://ibm.biz/ier_license_521\n\n", style="cyan")
    
    license_info_text.append("📄 ", style="bold cyan")
    license_info_text.append("IBM Content Collector for SAP:\n", style="bold white")
    license_info_text.append("   https://ibm.biz/iccsap_license_4002\n\n", style="cyan")
    
    license_info_text.append("📄 ", style="bold cyan")
    license_info_text.append("IBM Cloud Pak for Business Automation:\n", style="bold white")
    license_info_text.append("   https://ibm.biz/cp4ba_license_2600\n\n", style="cyan")
    
    license_info_text.append("⚠ ", style="bold yellow")
    license_info_text.append("You must accept the license to continue deployment.", style="bold yellow")
    
    license_panel = Panel(
        license_info_text,
        title="[bold white]License Agreement Required[/bold white]",
        border_style="white",
        padding=(1, 2)
    )
    
    console.print(license_panel)
    console.print()
    
    # Second Panel: License Agreement Required (Data Collection Notice)
    agreement_text = Text()
    agreement_text.append("⚠ ", style="bold yellow")
    agreement_text.append("You are about to accept the IBM Content Cortex License Agreement\n\n", style="bold white")
    
    agreement_text.append("📊 ", style="bold cyan")
    agreement_text.append("Data collection will be enabled by default\n", style="white")
    agreement_text.append("📄 ", style="bold cyan")
    agreement_text.append("Review full license terms in the License Information document\n\n", style="white")
    
    agreement_text.append("By accepting the license, you agree and understand that by default the program collects certain data and metrics regarding deployment and usage. ", style="white")
    agreement_text.append("For more information, please consult the License Information for IBM Content Cortex.", style="bold white")
    
    agreement_panel = Panel(
        agreement_text,
        title="[bold yellow]⚠ LICENSE AGREEMENT REQUIRED ⚠[/bold yellow]",
        border_style="yellow",
        padding=(1, 2)
    )
    
    console.print(agreement_panel)
    console.print()
    
    # Third Panel: License Terms
    terms_text = Text()
    terms_text.append("📋 ", style="bold cyan")
    terms_text.append("License Agreement Acceptance\n\n", style="bold white")
    
    terms_text.append("By accepting, you agree to:\n", style="white")
    terms_text.append("  • Comply with all license terms and conditions\n", style="white")
    terms_text.append("  • Use the software within entitled scope\n", style="white")
    terms_text.append("  • Maintain proper license documentation\n\n", style="white")
    
    terms_text.append("⚠ ", style="bold yellow")
    terms_text.append("Required: ", style="bold yellow")
    terms_text.append("You must accept to proceed with deployment.", style="white")
    
    terms_panel = Panel(
        terms_text,
        title="[bold white]License Terms[/bold white]",
        border_style="white",
        padding=(1, 2)
    )
    
    console.print(terms_panel)
    console.print()
    
    # Require explicit acceptance with questionary for better UX
    try:
        accepted = questionary.confirm(
            "Do you accept the IBM Content Cortex License Agreement?",
            default=False,  # Default to False for explicit acceptance
            auto_enter=False,
            style=Style([
                ('qmark', 'fg:yellow bold'),
                ('question', 'bold'),
                ('answer', 'fg:green bold'),
            ])
        ).ask()
    except Exception:
        # Fallback to rich Confirm if questionary fails
        accepted = Confirm.ask(
            "Do you accept the IBM Content Cortex License Agreement?",
            default=False
        )
    
    if accepted:
        console.print()
        console.print(Panel.fit(
            Text("✓ License Agreement Accepted", style="bold green"),
            border_style="green",
            padding=(0, 2)
        ))
        console.print()
        return True
    else:
        console.print()
        console.print(Panel.fit(
            Text("✗ License Agreement Declined - Deployment Cancelled", style="bold red"),
            border_style="red",
            padding=(0, 2)
        ))
        console.print()
        console.print("[yellow]Note:[/yellow] You must accept the license agreement to proceed with operator installation.")
        console.print()
        return False


# Create a method to print directory tree
def print_directory_tree(name: str, path: str) -> Tree:
    """Print a directory tree."""
    tree = Tree(f"📁 [bold blue]{name}[/bold blue]", guide_style="blue")
    walk_directory(pathlib.Path(path), tree)
    return tree


# Clear console based on system OS
def clear(console):
    if platform.system() == 'Windows':
        os.system('cls')
    else:
        console.clear()


def walk_directory(directory: pathlib.Path, tree: Tree) -> None:
    """Recursively build a Tree with directory contents."""
    # Sort dirs first then by filename
    paths = sorted(
        pathlib.Path(directory).iterdir(),
        key=lambda path: (path.is_file(), path.name.lower()),
    )
    for path in paths:
        # Remove hidden files
        if path.name.startswith("."):
            continue
        if path.parts[-1] == "venv":
            continue
        if path.is_dir():
            style = "dim" if path.name.startswith("__") else ""
            branch = tree.add(
                f"📁 [bold blue]{escape(path.name)}[/bold blue]",
                style=style,
                guide_style=style,
            )
            walk_directory(path, branch)
        else:
            text_filename = Text(path.name, "cyan")
            text_filename.highlight_regex(r"\..*$", "bold cyan")
            text_filename.stylize(f"link file://{path}")
            file_size = path.stat().st_size
            text_filename.append(f" ({decimal(file_size)})", "cyan")
            if path.suffix == ".py":
                icon = " "
            elif path.suffix == ".toml":
                icon = " "
            elif path.suffix == ".yaml":
                icon = "󱃾 "
            elif path.suffix == ".sql":
                icon = " "
            else:
                icon = " "
            tree.add(Text(icon) + text_filename)


# Create a selection summary table for the user to review
def db_summary_table(selection_summary: dict) -> Table:
    """Create a selection summary table for the user to review."""
    tableDB = Table(title="Database Selection")

    tableDB.add_column("Type", justify="right", style="cyan", no_wrap=True)
    tableDB.add_column("No. Object Stores", style="magenta")
    tableDB.add_column("SSL Enabled", justify="right", style="green")

    tableDB.add_row(selection_summary["db_type"], str(selection_summary["os_number"]), str(selection_summary["db_ssl"]))

    return tableDB


# Create a selection summary table for the user to review
def idp_summary_table(selection_summary: dict) -> Table:
    """Create a selection summary table for the user to review."""
    tableIdp = Table(title="Identity Provider Selection")

    tableIdp.add_column("Discovery Enabled", justify="right", style="cyan", no_wrap=True)
    tableIdp.add_column("ID", style="magenta")
    tableIdp.add_column("Validation Method", justify="right", style="green")

    for idp in selection_summary["idp_info"]:
        tableIdp.add_row(str(idp["discovery_enabled"]), idp["id"], str(idp["validation_method"]))

    return tableIdp


# Create a selection summary table for the user to review
def ldap_summary_table(selection_summary: dict) -> Table:
    """Create a selection summary table for the user to review."""
    tableldap = Table(title="LDAP Selection")

    tableldap.add_column("Type", justify="right", style="cyan", no_wrap=True)
    tableldap.add_column("ID", style="magenta")
    tableldap.add_column("SSL Enabled", justify="right", style="green")

    for ldap in selection_summary["ldap_info"]:
        tableldap.add_row(ldap["type"], ldap["id"], str(ldap["ssl"]))

    return tableldap


def selection_tree(selection_summary: dict) -> Tree:
    """Create a selection summary tree for the user to review."""
    tree = Tree("Selection Summary", guide_style="cyan")

    version_tree = Tree("IBM Content Cortex")
    version_tree.add(selection_summary["ccx_version"])

    tree.add(version_tree)

    license_tree = Tree("License Model")
    license_tree.add(selection_summary["license_model"])

    tree.add(license_tree)

    platform_tree = Tree("Platform")
    platform_tree.add(selection_summary["platform"])

    if selection_summary["ingress"]:
        ingress_tree = Tree("Ingress")
        ingress_tree.add(str(selection_summary["ingress"]))
        platform_tree.add(ingress_tree)

    tree.add(platform_tree)

    if selection_summary["optional_components"]:
        components_tree = Tree("Components")
        for component in selection_summary["optional_components"]:
            components_tree.add(component)
        tree.add(components_tree)

    init_tree = Tree("Content Initialization")
    init_tree.add(str(selection_summary["content_initialize"]))
    tree.add(init_tree)

    verify_tree = Tree("Content Verification")
    verify_tree.add(str(selection_summary["content_verification"]))
    tree.add(verify_tree)
    return tree


def mustgather_details(cr_details: dict, components: [], all_operator_details: dict, selected_operators: list) -> Panel:
    """
    Display MustGather collection details in a modern, structured format.
    
    Args:
        cr_details: Custom Resource details dictionary
        components: List of selected components
        all_operator_details: Dictionary of all operator details {operator_type: details}
        selected_operators: List of selected operator types ["content", "ai-services"]
        
    Returns:
        Panel with formatted MustGather collection details
    """
    # Build title based on operators actually found (not just selected)
    found_operators = list(all_operator_details.keys())
    if len(found_operators) == 2:
        operator_display = "Content & AI Services Operators"
    elif len(found_operators) == 1:
        if "ai-services" in found_operators:
            operator_display = "AI Services Operator"
        else:
            operator_display = "Content Operator"
    elif "ai-services" in selected_operators:
        # Fallback to selected if none found
        operator_display = "AI Services Operator"
    else:
        operator_display = "Content Operator"
    
    # Build the collection description
    collection_items = [
        "• Cluster Information and Resource Usage"
    ]
    
    # Add operator-specific items for each selected operator
    if all_operator_details:
        for op_type in selected_operators:
            if op_type in all_operator_details:
                operator_name = "Content Operator" if op_type == "content" else "AI Services Operator"
                
                # Content operator has Ansible logs, AI Services does not
                if op_type == "content":
                    collection_items.append(f"• {operator_name} Deployment & Ansible Logs")
                else:
                    collection_items.append(f"• {operator_name} Deployment & Logs")
                
                collection_items.append("• Role, RoleBinding & Service Account")
                
                install_type = all_operator_details[op_type].get("type", "YAML")
                if install_type == "OLM":
                    collection_items.append("• OLM: Subscription, CSV, and Catalog Source Details")
                elif install_type == "HELM":
                    collection_items.append("• Helm: Release and Chart Details")
                else:
                    collection_items.append("• YAML Deployment Artifacts")
    
    # Add CR-specific items
    if cr_details:
        collection_items.extend([
            "• The IBM Content Cortex Custom Resource (CR) file",
            "• Components Logs",
            "• Workloads: Deployment, Pods & PDB Details",
            "• Networking: Route, Ingress & Services",
            "• Storage: PVCs, PVs & StorageClasses",
            "• Configuration: If approved, Configmaps and Secrets"
        ])
    
    # Create tables section
    tables = []
    
    # Project Details Table
    if cr_details:
        details_table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
        details_table.add_column("Parameter", style="cyan", width=20)
        details_table.add_column("Value", style="white")
        
        # Show appVersion if available, otherwise fall back to version
        if "appVersion" in cr_details and cr_details["appVersion"]:
            details_table.add_row("App Version", cr_details.get("appVersion", "Unknown"))
            details_table.add_row("FNCM Version", cr_details.get("version", "Unknown"))
        else:
            details_table.add_row("Deployed Version", cr_details.get("version", "Unknown"))
        
        details_table.add_row("Namespace", cr_details.get("namespace", "Unknown"))
        
        if "platform" in cr_details:
            platform = cr_details["platform"]
            platform = "CNCF" if platform == "other" else platform.upper()
            details_table.add_row("Platform", platform)
        
        tables.append(Panel(details_table, title="[bold]📦 Project Details[/bold]", border_style="cyan"))
    else:
        tables.append(Panel(
            Text("No Custom Resource found in namespace", style="yellow"),
            title="[bold]⚠ Project Details[/bold]",
            border_style="yellow"
        ))
    
    # Operator Details Tables - one for each selected operator
    if all_operator_details:
        for op_type in selected_operators:
            if op_type in all_operator_details:
                op_details = all_operator_details[op_type]
                operator_table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
                operator_table.add_column("Parameter", style="cyan", width=20)
                operator_table.add_column("Value", style="white")
                
                op_display_name = "Content Operator" if op_type == "content" else "AI Services Operator"
                operator_table.add_row("Operator Name", op_details.get("deployment", "Unknown"))
                operator_table.add_row("Operator Type", op_type.upper())
                operator_table.add_row("Release", op_details.get("release", "Unknown"))
                operator_table.add_row("Install Type", op_details.get("type", "Unknown"))
                
                if op_details.get("type") == "OLM":
                    operator_table.add_row("Installed CSV", op_details.get("installedCSV", "N/A"))
                    operator_table.add_row("Channel", op_details.get("channel", "N/A"))
                    operator_table.add_row("Catalog Source", op_details.get("catalogSource", "N/A"))
                    operator_table.add_row("Catalog Install Type", op_details.get("catalogType", "N/A"))
                
                tables.append(Panel(operator_table, title=f"[bold]⚙️  {op_display_name}[/bold]", border_style="cyan"))
    else:
        tables.append(Panel(
            Text("No Operators found in namespace", style="yellow"),
            title="[bold]⚠ Operator Details[/bold]",
            border_style="yellow"
        ))
    
    # Components Table
    if components and len(components) > 0:
        components_sorted = sorted(components)
        component_table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
        component_table.add_column("Selected", style="green")
        
        for component in components_sorted:
            component_table.add_row(f"✓ {component}")
        
        tables.append(Panel(component_table, title="[bold]📋 Components[/bold]", border_style="cyan"))
    
    # Build the main content
    description_text = Text()
    description_text.append(
        f"The IBM Content Cortex MustGather collects files to help IBM support diagnose "
        f"and resolve issues with your {operator_display} deployment.\n\n",
        style="white"
    )
    description_text.append("Collection includes:\n", style="bold yellow")
    for item in collection_items:
        description_text.append(f"{item}\n", style="white")
    
    # Combine everything
    content = Group(
        description_text,
        Text(""),
        Columns(tables, equal=False, expand=True)
    )
    
    return Panel(
        content,
        title=f"[bold white]📊 MustGather Collection Details - {operator_display}[/bold white]",
        border_style="bright_blue",
        padding=(1, 2)
    )


def upgrade_details(deployment_details: dict, version_details: dict, current_operator: dict) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="upper"),
        Layout(name="lower"),
    )

    layout["upper"].size = 3

    layout["lower"].split_row(
        Layout(name="left"),
        Layout(name="right"),
    )

    msg = Text("Operator Upgrade Details", style="bold green", justify="center")
    msg_panel = Panel(msg)
    layout["upper"].update(msg_panel)

    summary_msg = ("\nThe IBM Content Cortex Operator Deployment will upgrade\n"
                   "the following artifacts to your cluster:\n\n")

    left_panels = []
    right_panels = []

    if current_operator:
        current_operator_table = Table(title="Current Operator Details")
        current_operator_table.add_column("Parameter", style="cyan")
        current_operator_table.add_column("Value", style="red")

        current_operator_table.add_row("Operator Name", current_operator["deployment"])
        current_operator_table.add_row("Release", current_operator["release"])
        current_operator_table.add_row("Install Type", current_operator["type"])
        current_operator_table.add_row("Registry", current_operator["registry"])

        if current_operator["type"] == "OLM":
            current_operator_table.add_row("Installed CSV", current_operator["installedCSV"])
            current_operator_table.add_row("Channel", current_operator["channel"])
            current_operator_table.add_row("Catalog Source", current_operator["catalogSource"])
            current_operator_table.add_row("Catalog Install Type", current_operator["catalogType"])

        right_panels.append(current_operator_table)

    if deployment_details:
        deployment_table = Table(title="Upgraded Operator Details")
        deployment_table.add_column("Parameter", style="cyan")
        deployment_table.add_column("Value", style="red")

        deployment_table.add_row("Operator Name", deployment_details["deployment"])
        deployment_table.add_row("Release", deployment_details["release"])
        deployment_table.add_row("Install Type", deployment_details["type"])
        deployment_table.add_row("Registry", deployment_details["registry"])

        summary_msg += ("- FNCM Operator Deployment\n"
                        "- Role, RoleBinding & Service Account\n"
                        "- FNCM Custom Resource Definition (CRD)\n")

        if deployment_details["type"] == "OLM":
            deployment_table.add_row("Installed CSV", deployment_details["installedCSV"])
            deployment_table.add_row("Channel", deployment_details["channel"])
            deployment_table.add_row("Catalog Source", deployment_details["catalogSource"])
            deployment_table.add_row("Catalog Install Type", deployment_details["catalogType"])

            summary_msg += ("- Cluster Role & Cluster Role Binding\n"
                            "- FNCM Operator Catalog Source\n"
                            "- Subscription and Operator Group\n")

        right_panels.append(deployment_table)

    if version_details:
        version_table = Table(title="Project Details")
        version_table.add_column("Parameter", style="cyan")
        version_table.add_column("Value", style="red")

        version_table.add_row("Namespace", version_details["namespace"])
        version_table.add_row("Platform", version_details["platform"])

        left_panels.append(version_table)


    if deployment_details and current_operator:
        if deployment_details["type"] == "OLM" and current_operator["type"] == "YAML":
            msg = Text("Operator Upgrade will change the Operator Install Type\n"
                       "from YAML to OLM (Operator Lifecycle Management)", style="bold cyan")
            msg_panel = Panel.fit(msg)
            left_panels.append(msg_panel)

    deploy_msg = Text(summary_msg)
    left_panels.append(deploy_msg)

    right_group = Columns(right_panels)
    left_group = Group(*left_panels)

    layout["right"].update(right_group)

    layout["left"].update(left_group)

    return layout


def deploy_details(deployment_details: dict, version_details: dict) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="upper"),
        Layout(name="lower"),
    )

    layout["upper"].size = 3

    layout["lower"].split_row(
        Layout(name="left"),
        Layout(name="right"),
    )

    msg = Text("Operator Deployment Details", style="bold green", justify="center")
    msg_panel = Panel(msg)
    layout["upper"].update(msg_panel)

    summary_msg = ("\nThe IBM Content Cortex Operator Deployment will apply\n"
                   "the following artifacts to your cluster:\n\n")

    right_panels = []
    left_panels = []

    if deployment_details:
        deployment_table = Table(title="Operator Details")
        deployment_table.add_column("Parameter", style="cyan")
        deployment_table.add_column("Value", style="red")

        deployment_table.add_row("Operator Name", deployment_details["deployment"])
        deployment_table.add_row("Release", deployment_details["release"])
        deployment_table.add_row("Install Type", deployment_details["type"])
        deployment_table.add_row("Registry", deployment_details["registry"])

        summary_msg += ("- FNCM Operator Deployment\n"
                        "- FNCM Custom Resource Definition (CRD)\n"
                        "- Role, RoleBinding & Service Account\n")

        if deployment_details["type"] == "OLM":
            deployment_table.add_row("Installed CSV", deployment_details["installedCSV"])
            deployment_table.add_row("Channel", deployment_details["channel"])
            deployment_table.add_row("Catalog Source", deployment_details["catalogSource"])
            deployment_table.add_row("Catalog Install Type", deployment_details["catalogType"])

            summary_msg += ("- FNCM Operator Catalog Source\n"
                            "- Subscription and Operator Group\n")

        left_panels.append(deployment_table)

    if version_details:
        version_table = Table(title="Project Details")
        version_table.add_column("Parameter", style="cyan")
        version_table.add_column("Value", style="red")

        version_table.add_row("Namespace", version_details["namespace"])
        version_table.add_row("Platform", version_details["platform"])

        right_panels.append(version_table)

    deploy_msg = Text(summary_msg)
    right_panels.append(deploy_msg)

    right_group = Group(*right_panels)
    left_group = Columns(left_panels)

    layout["right"].update(left_group)

    layout["left"].update(right_group)

    return layout

def deploy_details_multi_operator(deployment_details: dict, version_details: dict, selected_operators: list, version_data: dict = None, operator_status: dict = None, force_mode: bool = False) -> Table:
    """
    Display compact deployment details for multi-operator deployment.
    Shows configuration plus the execution plan: shared cluster setup first,
    then operator deployments running in parallel.
    
    Args:
        deployment_details: Dictionary containing deployment configuration
        version_details: Dictionary containing version and platform information
        selected_operators: List of OperatorType enums for selected operators
        version_data: Raw version data from version.toml (optional)
        operator_status: Dictionary containing operator installation status (optional)
        force_mode: When True, all selected operators are shown regardless of is_current
        
    Returns:
        Table with compact multi-operator deployment information
    """
    from .operator_config import get_operator_metadata
    from .utilities import get_operator_version
    import yaml
    import os
    
    main_table = Table(
        title="Deployment Configuration",
        show_header=True,
        header_style="bold cyan",
        border_style="green",
        title_style="bold green",
        show_lines=False,
        padding=(0, 1),
        box=None
    )
    
    main_table.add_column("Parameter", style="cyan", no_wrap=True)
    main_table.add_column("Value", style="white")
    
    if deployment_details:
        main_table.add_row("Deployment Type", deployment_details.get("type", "N/A"))
        main_table.add_row("Registry", deployment_details.get("registry", "N/A"))
        main_table.add_row("Release", deployment_details.get("release", "N/A"))
        
        if deployment_details.get("type") == "OLM":
            main_table.add_row("Catalog Type", deployment_details.get("catalogType", "N/A"))
    
    # Build the list of operators that will actually be deployed.
    # When force_mode is True every selected operator is redeployed regardless of
    # whether it is already at the target version, so the filter must be bypassed.
    status_key_map = {
        'content': 'content',
        'ai-services': 'ai-services',
        'usage-metering': 'usage-metering',
        'license-service': 'licensing',
        'model-gateway': 'model-gateway',
        'enhanced-extraction': 'enhanced-extraction',
        'cnpg': 'cnpg',
        'redis': 'redis',
    }

    operators_to_deploy = []
    if force_mode:
        # In force mode every selected operator is deployed — show all of them.
        operators_to_deploy = list(selected_operators)
    elif operator_status:
        for op_type in selected_operators:
            op_value = op_type.value
            status_key = status_key_map.get(op_value, op_value)

            # Only include if operator needs action (not already current)
            if status_key in operator_status:
                if not operator_status[status_key].get('is_current', False):
                    operators_to_deploy.append(op_type)
            else:
                # Operator not in status (new install)
                operators_to_deploy.append(op_type)
    else:
        # No status available — show all selected operators
        operators_to_deploy = list(selected_operators)
    
    if version_details:
        main_table.add_row("Namespace", version_details.get("namespace", "N/A"))
        main_table.add_row("Operators Count", str(len(operators_to_deploy)))
    
    main_table.add_row("", "")
    main_table.add_row("[bold cyan]Execution Plan[/bold cyan]", "")
    main_table.add_row(
        "Stage 1",
        "[bold green]Shared Cluster Setup[/bold green] — runs once before operator deployment"
    )
    main_table.add_row(
        "",
        "Create or verify namespace, create image pull secret, and apply shared cluster prerequisites"
    )
    main_table.add_row(
        "Stage 2",
        "[bold yellow]Parallel Operator Deployment[/bold yellow] — selected operators deploy concurrently after cluster setup completes"
    )
    
    main_table.add_row("", "")
    main_table.add_row("[bold cyan]Parallel Operators[/bold cyan]", "")
    
    for op_type in operators_to_deploy:
        metadata = get_operator_metadata(op_type)

        version = deployment_details.get("release", "26.0.0")
        if version_data:
            version = get_operator_version(
                version_data,
                metadata.operator_type.value,
                "VERSION"
            )

        # Determine per-operator action label
        op_value = op_type.value
        status_key = status_key_map.get(op_value, op_value)
        if force_mode and operator_status and operator_status.get(status_key, {}).get('is_current', False):
            action_label = "[bold yellow]force redeploy[/bold yellow]"
        elif operator_status and operator_status.get(status_key, {}).get('installed', False):
            action_label = "[bold cyan]upgrade[/bold cyan]"
        else:
            action_label = "[bold green]install[/bold green]"

        operator_info = f"[bold white]{metadata.display_name}[/bold white]"
        details = (
            f"[cyan]Queued after Stage 1[/cyan] • "
            f"[yellow]{version}[/yellow] • "
            f"{action_label}"
        )
        main_table.add_row(operator_info, details)
    
    return main_table



def generate_gather_results(property_folder: str, selection_summary: dict, movedb: bool, moveldap: bool) -> Layout:
    """Generate modern, compact summary screen for gather mode completion."""
    
    # Build main layout - single row split for maximum space efficiency
    layout = Layout()
    layout.split_row(
        Layout(name="left", ratio=2),
        Layout(name="right", ratio=3)
    )
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # LEFT PANEL: Configuration + Next Steps (stacked vertically)
    # ═══════════════════════════════════════════════════════════════════════════════
    left_layout = Layout()
    left_layout.split_column(
        Layout(name="config"),
        Layout(name="next_steps", size=7)
    )
    
    # Configuration tree (compact, no extra padding)
    config_tree = _create_compact_config_tree(selection_summary)
    config_panel = Panel(
        config_tree,
        title="[bold cyan]⚙ Configuration[/bold cyan]",
        border_style="cyan",
        padding=(0, 1)
    )
    
    # Next steps (compact)
    next_steps = _create_compact_next_steps(selection_summary)
    
    left_layout["config"].update(config_panel)
    left_layout["next_steps"].update(next_steps)
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # RIGHT PANEL: Files + Database/LDAP/IDP info (stacked vertically)
    # ═══════════════════════════════════════════════════════════════════════════════
    right_content = []
    
    # Property files tree (compact)
    files_tree = print_directory_tree("propertyFiles", property_folder)
    files_panel = Panel(
        files_tree,
        title="[bold cyan]📁 Generated Files[/bold cyan]",
        border_style="cyan",
        padding=(0, 1)
    )
    right_content.append(files_panel)
    
    # Database selection (compact, no extra padding)
    if selection_summary.get("db_type"):
        db_info = _create_compact_db_info(selection_summary, movedb)
        right_content.append(db_info)
    
    # LDAP selection (compact)
    if len(selection_summary.get("ldap_info", [])) > 0:
        ldap_info = _create_compact_ldap_info(selection_summary, moveldap)
        right_content.append(ldap_info)
    
    # IDP selection (compact)
    if len(selection_summary.get("idp_info", [])) > 0:
        idp_info = _create_compact_idp_info(selection_summary)
        right_content.append(idp_info)
    
    # AI Services model providers (compact)
    if selection_summary.get("model_providers") and len(selection_summary.get("model_providers", [])) > 0:
        ai_services_info = _create_compact_ai_services_info(selection_summary)
        right_content.append(ai_services_info)
    
    right_group = Group(*right_content)
    
    # Assemble layout
    layout["left"].update(left_layout)
    layout["right"].update(right_group)
    
    return layout


def _create_compact_config_tree(selection_summary: dict) -> Tree:
    """Create a compact configuration tree with icons."""
    tree = Tree("", guide_style="dim cyan")
    
    # Version
    version_node = tree.add(f"[cyan]📦 IBM Content Cortex[/cyan] [white]{selection_summary['ccx_version']}[/white]")
    
    # License
    tree.add(f"[cyan]📄 License[/cyan] [white]{selection_summary['license_model']}[/white]")
    
    # Platform
    platform_text = f"[cyan]☸  Platform[/cyan] [white]{selection_summary['platform']}[/white]"
    if selection_summary.get("ingress"):
        platform_text += f" [dim]• Ingress[/dim]"
    tree.add(platform_text)
    
    # Operators (determine which are selected based on optional_components)
    operators_node = tree.add("[cyan]⚙️  Operators[/cyan]")
    optional_components = selection_summary.get("optional_components", [])
    
    # Check for Content operator (if any content-related components exist)
    content_components = ["BAN", "CPE", "CSS", "CMIS", "GraphQL", "Task Manager", "External Share"]
    has_content = any(comp in optional_components for comp in content_components)
    
    # Check for AI Services operator (if model providers exist)
    has_ai_services = selection_summary.get("model_provider_count", 0) > 0
    
    if has_content:
        operators_node.add("[green]✓[/green] [white]Content[/white]")
    if has_ai_services:
        operators_node.add("[green]✓[/green] [white]AI Services[/white]")
    
    # Authentication
    auth_type = selection_summary.get("auth_type", "Not configured")
    if auth_type:
        auth_node = tree.add(f"[cyan]🔐 Authentication[/cyan] [white]{auth_type}[/white]")
        
        # Show LDAP count if applicable
        ldap_count = len(selection_summary.get("ldap_info", []))
        if ldap_count > 0:
            auth_node.add(f"[dim]• {ldap_count} LDAP server{'s' if ldap_count > 1 else ''}[/dim]")
        
        # Show IDP count if applicable
        idp_count = len(selection_summary.get("idp_info", []))
        if idp_count > 0:
            auth_node.add(f"[dim]• {idp_count} IDP provider{'s' if idp_count > 1 else ''}[/dim]")
    
    # AI Services (if configured)
    if has_ai_services:
        ai_node = tree.add("[cyan]🤖 AI Services[/cyan]")
        provider_count = selection_summary.get("model_provider_count", 0)
        ai_node.add(f"[white]{provider_count} model provider{'s' if provider_count > 1 else ''}[/white]")
        
        # List each provider type
        for provider in selection_summary.get("model_providers", []):
            provider_type = provider.get("provider_type", "Unknown")
            if provider_type == "WATSONX_SAAS":
                provider_display = "WatsonX.ai SaaS"
            elif provider_type == "WATSONX_LWE":
                provider_display = "WatsonX.ai WLE"
            elif provider_type == "MICROSOFT_FOUNDRY":
                provider_display = "Microsoft Foundry"
            else:
                provider_display = provider_type
            ai_node.add(f"[dim]• {provider_display}[/dim]")
    
    # Components (if any)
    if optional_components:
        components_node = tree.add("[cyan]🧩 Components[/cyan]")
        for component in optional_components:
            components_node.add(f"[white]• {component}[/white]")
    
    # Security & Network
    security_node = tree.add("[cyan]🔒 Security & Network[/cyan]")
    
    # FIPS
    fips_enabled = selection_summary.get("fips_support", False)
    fips_icon = "✓" if fips_enabled else "✗"
    security_node.add(f"[{'green' if fips_enabled else 'dim'}]{fips_icon} FIPS Mode[/{'green' if fips_enabled else 'dim'}]")
    
    # Network Policy
    np_enabled = selection_summary.get("np_support", False)
    np_icon = "✓" if np_enabled else "✗"
    security_node.add(f"[{'green' if np_enabled else 'dim'}]{np_icon} Network Policy[/{'green' if np_enabled else 'dim'}]")
    
    # Egress
    egress_enabled = selection_summary.get("egress_support", False)
    egress_icon = "✓" if egress_enabled else "✗"
    security_node.add(f"[{'green' if egress_enabled else 'dim'}]{egress_icon} Egress[/{'green' if egress_enabled else 'dim'}]")
    
    # Content settings (only if Content operator is selected)
    if has_content:
        settings_node = tree.add("[cyan]⚡ Content Settings[/cyan]")
        init_icon = "✓" if selection_summary.get("content_initialize") else "✗"
        verify_icon = "✓" if selection_summary.get("content_verification") else "✗"
        settings_node.add(f"[{'green' if selection_summary.get('content_initialize') else 'dim'}]{init_icon} Initialize[/{'green' if selection_summary.get('content_initialize') else 'dim'}]")
        settings_node.add(f"[{'green' if selection_summary.get('content_verification') else 'dim'}]{verify_icon} Verify[/{'green' if selection_summary.get('content_verification') else 'dim'}]")
    
    return tree


def _create_compact_db_info(selection_summary: dict, movedb: bool) -> Panel:
    """Create compact database info panel."""
    db_table = Table.grid(padding=(0, 1))
    db_table.add_column(style="cyan", justify="right", width=14)
    db_table.add_column(style="white")
    
    db_table.add_row("Type:", selection_summary["db_type"])
    db_table.add_row("Object Stores:", str(selection_summary["os_number"]))
    
    ssl_icon = "🔒" if selection_summary["db_ssl"] else "🔓"
    ssl_text = f"{ssl_icon} {'Enabled' if selection_summary['db_ssl'] else 'Disabled'}"
    db_table.add_row("SSL:", ssl_text)
    
    if movedb:
        db_table.add_row("", "[dim]✓ Migrated[/dim]")
    
    return Panel(
        db_table,
        title="[bold cyan]🗄 Database[/bold cyan]",
        border_style="cyan",
        padding=(0, 1)
    )


def _create_compact_ldap_info(selection_summary: dict, moveldap: bool) -> Panel:
    """Create compact LDAP info panel."""
    ldap_table = Table.grid(padding=(0, 1))
    ldap_table.add_column(style="cyan", justify="right", width=14)
    ldap_table.add_column(style="white")
    
    for idx, ldap in enumerate(selection_summary["ldap_info"], 1):
        if idx > 1:
            ldap_table.add_row("", "")  # Spacer
        
        ldap_table.add_row(f"LDAP {idx}:", ldap["id"])
        ldap_table.add_row("Type:", ldap["type"])
        
        ssl_icon = "🔒" if ldap["ssl"] else "🔓"
        ssl_text = f"{ssl_icon} {'Enabled' if ldap['ssl'] else 'Disabled'}"
        ldap_table.add_row("SSL:", ssl_text)
    
    if moveldap:
        ldap_table.add_row("", "")
        ldap_table.add_row("", "[dim]✓ Migrated[/dim]")
    
    return Panel(
        ldap_table,
        title="[bold cyan]👥 LDAP[/bold cyan]",
        border_style="cyan",
        padding=(0, 1)
    )


def _create_compact_idp_info(selection_summary: dict) -> Panel:
    """Create compact IDP info panel."""
    idp_table = Table.grid(padding=(0, 1))
    idp_table.add_column(style="cyan", justify="right", width=14)
    idp_table.add_column(style="white")
    
    for idx, idp in enumerate(selection_summary["idp_info"], 1):
        if idx > 1:
            idp_table.add_row("", "")  # Spacer
        
        idp_table.add_row(f"IDP {idx}:", idp["id"])
        
        discovery_icon = "✓" if idp["discovery_enabled"] else "✗"
        discovery_text = f"{discovery_icon} {'Enabled' if idp['discovery_enabled'] else 'Disabled'}"
        idp_table.add_row("Discovery:", discovery_text)
        idp_table.add_row("Validation:", idp["validation_method"])
    
    return Panel(
        idp_table,
        title="[bold cyan]🔐 Identity Provider[/bold cyan]",
        border_style="cyan",
        padding=(0, 1)
    )

def _create_compact_ai_services_info(selection_summary: dict) -> Panel:
    """Create compact AI Services model provider info panel."""
    ai_table = Table.grid(padding=(0, 1))
    ai_table.add_column(style="cyan", justify="right", width=14)
    ai_table.add_column(style="white")
    
    # Add provider count
    provider_count = selection_summary.get("model_provider_count", 0)
    ai_table.add_row("Providers:", str(provider_count))
    
    # Add each provider's details
    for idx, provider in enumerate(selection_summary.get("model_providers", []), 1):
        if idx > 1:
            ai_table.add_row("", "")  # Spacer
        
        provider_type = provider.get("provider_type", "Unknown")
        
        # Map provider type to display name
        if provider_type == "WATSONX_SAAS":
            provider_display = "🤖 WatsonX.ai SaaS"
        elif provider_type == "WATSONX_LWE":
            provider_display = "🤖 WatsonX.ai WLE"
        elif provider_type == "MICROSOFT_FOUNDRY":
            provider_display = "🤖 Microsoft Foundry"
        else:
            provider_display = f"🤖 {provider_type}"
        
        ai_table.add_row(f"Model {idx}:", provider_display)
    
    return Panel(
        ai_table,
        title="[bold cyan]🤖 AI Services[/bold cyan]",
        border_style="cyan",
        padding=(0, 1)
    )



def _create_compact_next_steps(selection_summary: dict) -> Panel:
    """Create ultra-compact next steps panel."""
    steps_table = Table.grid(padding=(0, 1))
    steps_table.add_column(style="bold yellow", width=2)
    steps_table.add_column(style="white")
    
    steps_table.add_row("1.", "Review TOML files in [cyan]./propertyFiles[/cyan]")
    steps_table.add_row("2.", "Fill in all [bold red]<Required>[/bold red] values")
    steps_table.add_row("3.", "Add SSL certs (if enabled) & ICC masterkey (if enabled)")
    steps_table.add_row("4.", "Run: [green]python3 prerequisites.py generate[/green]")
    
    return Panel(
        steps_table,
        title="[bold white]📋 Next Steps[/bold white]",
        border_style="green",
        padding=(0, 1)
    )


def upgrade_deployment_details(update_list: list, version_details: dict, download_folder_path: ""):
    """
    Display upgrade deployment details with modern Rich styling.
    
    Args:
        update_list: List of CR updates made during upgrade
        version_details: Dictionary containing version information
        download_folder_path: Path to CCxUpgrade/<namespace> folder
        
    Returns:
        Rich renderable showing upgrade details in modern format
    """
    right_panels = []
    
    # Modern header with emoji
    header_text = Text()
    header_text.append("📦 ", style="bold cyan")
    header_text.append("IBM Content Cortex Deployment Preparation", style="bold cyan")
    
    msg_panel = Panel.fit(
        header_text,
        border_style="cyan",
        padding=(0, 2)
    )
    right_panels.append(msg_panel)

    # Build summary message with structured sections
    summary_parts = []
    summary_parts.append(Text("✓ Custom Resource (CR) Upgrade Complete\n", style="bold green"))
    summary_parts.append(Text("\n📁 Generated Files:\n", style="bold yellow"))
    summary_parts.append(Text("  • Current and upgraded CR → ", style="dim"))
    summary_parts.append(Text("./CCxUpgrade/<namespace>/CustomResources/\n", style="cyan"))
    
    if version_details.get("version") in ("5.7.0"):
        summary_parts.append(Text("  • Network Policies → ", style="dim"))
        summary_parts.append(Text("./CCxUpgrade/<namespace>/NetworkPolicies/\n", style="cyan"))
    
    summary_parts.append(Text("\n📋 Next Steps:\n", style="bold yellow"))
    summary_parts.append(Text("  1. Review upgrade details in tables below\n", style="dim"))
    summary_parts.append(Text("  2. Verify CR changes match your requirements\n", style="dim"))
    summary_parts.append(Text("  3. Apply the upgraded CR to your cluster", style="dim"))

    summary_text = Text()
    for part in summary_parts:
        summary_text.append(part)
    
    summary_panel = Panel(
        summary_text,
        border_style="green",
        padding=(1, 2)
    )
    right_panels.append(summary_panel)

    left_panels = []

    # CR Updates table with modern styling
    if update_list:
        update_table = Table(
            title="📝 Custom Resource Upgrade Details",
            title_style="bold cyan",
            border_style="cyan",
            show_header=True,
            header_style="bold cyan"
        )
        update_table.add_column("Updates Applied", style="white", no_wrap=False)

        for update in update_list:
            update_table.add_row(f"• {update}")

        left_panels.append(update_table)

    # Version details table with modern styling
    if version_details:
        version_table = Table(
            title="🔧 Upgrade Configuration",
            title_style="bold yellow",
            border_style="yellow",
            show_header=True,
            header_style="bold yellow"
        )
        version_table.add_column("Parameter", style="cyan", width=20)
        version_table.add_column("Value", style="white")

        version_table.add_row("Content Version", version_details["version"])
        version_table.add_row("Namespace", version_details["namespace"])
        version_table.add_row("Platform", version_details["platform"])
        version_table.add_row("App Version", version_details["appVersion"])

        left_panels.append(version_table)

    # Directory tree with modern styling
    if download_folder_path:
        cr_tree = print_directory_tree("CCxUpgrade", download_folder_path)
        left_panels.append(cr_tree)

    right_group = Group(*right_panels)
    left_group = Columns(left_panels)

    cr_info = Columns([right_group, left_group], equal=True)

    return cr_info

def display_prereq_passed(prereqs=None):
    """
    Display passed prerequisites in a comprehensive validation table format.
    
    Args:
        prereqs: Dictionary of prerequisite check results
        
    Returns:
        Rich Panel containing a validation table with Category, Check, Status, and Details columns
    """
    if prereqs is None:
        prereqs = {}

    # Create main validation table
    validation_table = Table(
        show_header=True,
        header_style="bold cyan",
        border_style="cyan",
        title="🔍 Pre-Deployment Validation",
        title_style="bold cyan",
        expand=True,
        padding=(0, 1)
    )
    
    validation_table.add_column("Category", style="cyan", no_wrap=True, width=20)
    validation_table.add_column("Check", style="white", width=25)
    validation_table.add_column("Status", style="green", width=20)
    validation_table.add_column("Details", style="magenta", width=30)

    # Track if we've added the Prerequisites category header
    prereq_category_added = False
    
    # Add prerequisite checks dynamically
    # Podman check removed - authentication now done via HTTP API
    
    if 'connection' in prereqs and prereqs['connection']:
        validation_table.add_row(
            "Prerequisites" if not prereq_category_added else "",
            "K8s Connection",
            "✓ Connected",
            prereqs.get("k8s_version", "")
        )
        prereq_category_added = True
    
    if 'skopeo' in prereqs and prereqs['skopeo']:
        validation_table.add_row(
            "Prerequisites" if not prereq_category_added else "",
            "Skopeo CLI",
            "✓ Available",
            prereqs.get("skopeo_version", "")
        )
        prereq_category_added = True
    
    if 'oc' in prereqs and prereqs['oc']:
        validation_table.add_row(
            "Prerequisites" if not prereq_category_added else "",
            "OC CLI",
            "✓ Available",
            prereqs.get("oc_version", "")
        )
        prereq_category_added = True
    
    if 'ibm-pak' in prereqs and prereqs['ibm-pak']:
        validation_table.add_row(
            "Prerequisites" if not prereq_category_added else "",
            "IBM-Pak Plugin",
            "✓ Available",
            prereqs.get("ibm-pak_version", "")
        )
        prereq_category_added = True
    
    if 'mirror' in prereqs and prereqs['mirror']:
        validation_table.add_row(
            "Prerequisites" if not prereq_category_added else "",
            "Mirror Plugin",
            "✓ Available",
            prereqs.get("mirror_version", "")
        )
        prereq_category_added = True
    
    if 'java' in prereqs and prereqs['java']:
        validation_table.add_row(
            "Prerequisites" if not prereq_category_added else "",
            "Java",
            "✓ Available",
            prereqs.get("java_version", "")
        )
        prereq_category_added = True
    
    if "descriptor_files" in prereqs and prereqs["descriptor_files"]:
        validation_table.add_row(
            "Prerequisites" if not prereq_category_added else "",
            "Descriptor Files",
            "✓ Available",
            "All required files found"
        )
        prereq_category_added = True

    # Return the table directly without panel wrapper for consistency
    return validation_table

def display_manifest_results(manifests=None):
    header_panel = Panel.fit("Manifests Generated", style="bold green")

    manifest_msg = Text("\n"+manifests, style="bold cyan")

    return Group(header_panel, manifest_msg)

def display_airgap_vars(airgap_vars=None):
    if airgap_vars is None:
        airgap_vars = {}

    airgap_msg = Text(
                      "\n\nThe following variables will be used to configure and mirror the IBM Content Cortex Images."
                      "\nReview all Airgap Variables below:\n")


    if len(airgap_vars) > 0:

        var_table = Table(title="Airgap Variables")

        var_table.add_column("Name", style="cyan")
        var_table.add_column("Value", style="magenta")

        for var in airgap_vars:
            var_table.add_row(var, airgap_vars[var])

    var_group = Group( airgap_msg, var_table)

    return var_group

def display_prereq_validation_table(results: dict, health_metrics: dict = None) -> None:  # noqa: E302
    """
    Display the canonical Pre-Deployment Validation table.

    Shared by all scripts (prerequisites, must_gather, clean_deployment,
    upgrade_deployment, load_images, deploy_operator).  Each script passes the
    ``results`` dict returned by ``prereq_checks``; ``health_metrics`` is only
    populated by deploy_operator when OLM permission checks have been run.

    Args:
        results:        Dict returned by prereq_checks — keys such as
                        "connection", "k8s_version", "helm", "helm_version",
                        "java", "java_version", "keytool", "podman",
                        "skopeo", "skopeo_version", "oc", "oc_version",
                        "ibm-pak", "ibm-pak_version", "mirror", "mirror_version",
                        "descriptor_files".
        health_metrics: Optional dict with OLM permission data (deploy_operator only).
                        Keys: "permissions", "cluster_accessible", "current_user".
    """
    if health_metrics is None:
        health_metrics = {}

    validation_table = Table(
        title="🔍 Pre-Deployment Validation",
        show_header=True,
        header_style="bold cyan",
        border_style="cyan",
        title_style="bold cyan",
        expand=False,
    )
    validation_table.add_column("Category", style="cyan", no_wrap=True)
    validation_table.add_column("Check", style="white")
    validation_table.add_column("Status", style="green", no_wrap=True)
    validation_table.add_column("Details", style="magenta")

    first_row = True  # tracks whether to show "Prerequisites" category label

    def _add(check_label: str, status: str, details: str = "") -> None:
        nonlocal first_row
        category = "Prerequisites" if first_row else ""
        validation_table.add_row(category, check_label, status, details)
        first_row = False

    if results.get("connection"):
        _add("K8s Connection", "✓ Connected", results.get("k8s_version", ""))
    if results.get("helm"):
        _add("Helm CLI", "✓ Available", results.get("helm_version", ""))
    if results.get("java"):
        _add("Java", "✓ Available", results.get("java_version", ""))
    if results.get("keytool"):
        _add("Keytool", "✓ Available")
    if results.get("podman"):
        _add("Podman CLI", "✓ Available")
    if results.get("skopeo"):
        _add("Skopeo CLI", "✓ Available", results.get("skopeo_version", ""))
    if results.get("oc"):
        _add("OC CLI", "✓ Available", results.get("oc_version", ""))
    if results.get("ibm-pak"):
        _add("IBM-Pak Plugin", "✓ Available", results.get("ibm-pak_version", ""))
    if results.get("mirror"):
        _add("OC Mirror Plugin", "✓ Available", results.get("mirror_version", ""))
    if results.get("descriptor_files"):
        _add("Descriptor Files", "✓ All found")

    # OLM user-permissions section (deploy_operator only)
    permissions = health_metrics.get("permissions", {})
    if permissions:
        if health_metrics.get("cluster_accessible"):
            current_user = health_metrics.get("current_user", "Unknown")
            validation_table.add_row(
                "User Permissions", "Current User", "✓ Authenticated",
                current_user[:20] if len(current_user) > 20 else current_user,
            )
        allowed_count = sum(1 for p in permissions.values() if p.get("status") == "allowed")
        partial_count = sum(1 for p in permissions.values() if p.get("status") == "partial")
        denied_count  = sum(1 for p in permissions.values() if p.get("status") == "denied")
        categories = {
            "Core Resources": ["pods", "services", "configmaps", "secrets",
                               "serviceaccounts", "persistentvolumeclaims"],
            "Workloads":  ["deployments", "statefulsets", "daemonsets"],
            "RBAC":       ["roles", "rolebindings", "clusterroles", "clusterrolebindings"],
            "Cluster":    ["namespaces", "customresourcedefinitions", "apiservices"],
            "OLM":        ["catalogsources", "subscriptions", "operatorgroups", "clusterserviceversions"],
        }
        for cat_name, resource_list in categories.items():
            cat_perms = {k: v for k, v in permissions.items()
                         if any(r in k for r in resource_list)}
            if not cat_perms:
                continue
            cat_denied  = sum(1 for p in cat_perms.values() if p.get("status") == "denied")
            cat_partial = sum(1 for p in cat_perms.values() if p.get("status") == "partial")
            cat_allowed = sum(1 for p in cat_perms.values() if p.get("status") == "allowed")
            cat_total   = len(cat_perms)
            if cat_denied > 0:
                cat_status = f"✗ {cat_denied}/{cat_total} denied"
            elif cat_partial > 0:
                cat_status = f"⚠️ {cat_partial}/{cat_total} partial"
            else:
                cat_status = f"✓ {cat_allowed}/{cat_total} granted"
            validation_table.add_row("", f"{cat_name} Permissions", cat_status, "")
            if cat_denied > 0 or cat_partial > 0:
                for perm_key in sorted(cat_perms.keys()):
                    perm   = cat_perms[perm_key]
                    status = perm.get("status", "unknown")
                    if status in ("denied", "partial"):
                        validation_table.add_row(
                            "",
                            f"  └─ {perm.get('description', perm_key)}",
                            "⚠️ Partial" if status == "partial" else "✗ Denied",
                            perm.get("scope", "").title(),
                        )
        summary = (f"✗ {denied_count} denied" if denied_count > 0
                   else f"⚠️ {partial_count} partial" if partial_count > 0
                   else "✓ All granted")
        validation_table.add_row("", "Overall Summary", summary, f"{len(permissions)} checked")

    from rich.console import Console as _Console
    _Console().print()
    _Console().print(validation_table)
    _Console().print()


def display_issues(generate_folder=None, required_fields=None,
                   certs=None, incorrect_certs=None,
                   masterkey_present=True, invalid_trusted_certs=None,
                   keystore_password_valid=True, incorrect_naming_conv=None,
                   mode=None, tools=None, invalid_db_password_list=None, correct_ssl_mode=True,
                   deployment_prop=None, descriptors=None, error_code=None, docs_link=None) -> Layout:
    # Build Layout for display
    layout = Layout()
    layout.split_column(
        Layout(name="upper"),
        Layout(name="lower"),
    )

    layout["upper"].size = 3

    layout["lower"].split_row(
        Layout(name="left"),
        Layout(name="right"),
    )

    layout["left"].size = None
    layout["right"].ratio = 2

    left_panel_list = []

    # Build header message with error code and docs link if provided
    header_parts = ["Issues Found"]
    if error_code:
        header_parts.append(f"Error Code: {error_code}")
    if docs_link:
        header_parts.append(f"📚 Documentation: {docs_link}")
    
    message = Text("\n".join(header_parts), style="bold red", justify="center")
    result_panel = Panel(message, style="bold red")
    layout["upper"].update(result_panel)
    # Create the left side panel
    # Create next steps panel

    # Redemption steps are built based on what issues are found
    next_steps_panel = Panel.fit("Remediation Steps")
    instruction_list = []

    section_files = ['fncm_db_server.toml',
                     'fncm_ldap_server.toml',
                     'fncm_components_options.toml',
                     'fncm_identity_provider.toml',
                     'fncm_scim_server.toml']
    unsectioned_files = ['fncm_user_group.toml',
                         'fncm_deployment.toml',
                         'fncm_ingress.toml']

    error_tables = []

    # Build the tables based on issues with required fields missing in toml files
    if required_fields is not None:
        instruction_list.append("Use the tables to fix the missing values for the toml files")
    # adding keystore password to list of fields to be fixed if fips is enabled and keystore password is less than 16 characters
    if not keystore_password_valid:
        instruction_list.append("Keystore password length should be at least 16 characters long when FIPS is enabled.")
        if "fncm_user_group.toml" in required_fields:
            if (["KEYSTORE_PASSWORD"], "<Required>") not in required_fields["fncm_user_group.toml"]:
                required_fields["fncm_user_group.toml"].append((["KEYSTORE_PASSWORD"], "Incorrect Length"))
        else:
            required_fields["fncm_user_group.toml"] = []
            required_fields["fncm_user_group.toml"].append((["KEYSTORE_PASSWORD"], "Incorrect Length"))
    if required_fields is not None:
        for file in required_fields:
            filename = file.split('/')[1]
            if filename in section_files:
                parsed_parameters = parse_required_fields(required_fields[file])
                error_table = Table(title=filename)
                error_table.add_column("Section", style="cyan", no_wrap=True)
                error_table.add_column("Parameters", style="blue")
                for section in parsed_parameters:
                    parameters = ""
                    for i in parsed_parameters[section]:
                        parameters += "- " + i + "\n"
                    error_table.add_row(section, parameters.strip())

                error_tables.append(error_table)

            elif filename in unsectioned_files:
                error_table = Table(title=filename)
                error_table.add_column("Parameters", style="blue")
                for section in required_fields[file]:
                    parameters = ""
                    parameters += "- " + section[0][0]
                    error_table.add_row(parameters.strip())
                error_tables.append(error_table)

    if certs:
        instruction_list.append(
            "Missing SSL certificates need to be added to respective folder under ./propertyFile/ssl-certs")
        error_table = Table(title="SSL Certificates Missing")
        error_table.add_column("Connection", style="magenta")
        error_table.add_column("Missing", style="red")
        for connection in certs:
            files = ""
            for i in certs[connection]:
                files += "- " + i + "\n"
            error_table.add_row(connection, files.strip())

        error_tables.append(error_table)

    if descriptors:
        instruction_list.append(
            "Missing Descriptor files need to be added to respective folder under ../descriptors")
        error_table = Table(title="Files Missing")
        error_table.add_column("Missing", style="red")
        for file in descriptors:
            error_table.add_row(file)

        error_tables.append(error_table)

    if incorrect_certs:
        instruction_list.append("All SSL certificates need to be in PEM (Privacy Enhanced Mail) format")
        error_table = Table(title="Incorrect SSL Certificates")
        error_table.add_column("Connection", style="magenta")
        error_table.add_column("Incorrect", style="red")
        for connection in incorrect_certs:
            files = ""
            for i in incorrect_certs[connection]:
                files += "- " + i + "\n"
            error_table.add_row(connection, files.strip())

        error_tables.append(error_table)

    if not masterkey_present:
        instruction_list.append(
            "Make sure masterkey.txt file has been added under ./propertyFile/icc for ICC for Email setup")
        error_table = Table(title="ICC Setup")
        error_table.add_column("Missing", style="red")
        error_table.add_row("masterkey.txt")

        error_tables.append(error_table)

    if invalid_trusted_certs:
        instruction_list.append("All trusted certificates need to be in PEM (Privacy Enhanced Mail) format")
        error_table = Table(title="Incorrect Trusted Certificates")
        error_table.add_column("Missing", style="red")
        for cert in invalid_trusted_certs:
            error_table.add_row(cert)
        error_tables.append(error_table)

    if incorrect_naming_conv or (invalid_db_password_list is not None and len(invalid_db_password_list) > 0):
        incorrect_dbs = []
        error_table = Table(title="Database Requirements")
        error_table.add_column("Database(s)", style="red")
        instruction_list.append("Review the list of database requirements below:\n")
        if incorrect_naming_conv:
            instruction_list.append("- DB2 Database name needs to be less than 9 characters\n")
            for db in incorrect_naming_conv:
                incorrect_dbs.append(db)
        if len(invalid_db_password_list) > 0:
            instruction_list.append(
                "- Postgresql Database password length needs to be at least 16 characters long when FIPS is enabled")
            for db in invalid_db_password_list:
                incorrect_dbs.append(db)
        for db in incorrect_dbs:
            error_table.add_row(db)
        error_tables.append(error_table)

    if not correct_ssl_mode:
        instruction_list.append("SSL Mode for Postgresql can only be \"require\" when FIPS is enabled")

    if tools:
        if "connection" in tools:
            # Display detailed connection issue panel only (no redundant instruction)
            cluster_issue_text = Text()
            cluster_issue_text.append("󰣇 ", style="bold red")
            cluster_issue_text.append("Cluster connection unavailable\n\n", style="bold white")
            cluster_issue_text.append(
                "No active Kubernetes/OpenShift cluster connection was detected.\n",
                style="bright_white"
            )
            cluster_issue_text.append("ℹ ", style="bold cyan")
            cluster_issue_text.append(
                "Ensure you are logged in and your kube context is set correctly.",
                style="cyan"
            )

            error_tables.append(
                Panel(
                    cluster_issue_text,
                    title="[bold red]Connection Issue[/bold red]",
                    border_style="bright_red",
                    padding=(1, 2),
                    expand=True
                )
            )
            tools.remove("connection")
        if "Windows OS" in tools:
            instruction_list.append("Load Images Script is not supported for Windows OS")
            error_tables.append(Panel.fit("Windows OS is not supported for this script", style="bold cyan"))
            tools.remove("Windows OS")
        if "Mac OS" in tools:
            instruction_list.append("Load Images Script in Airgap mode is not supported for Mac OS")
            error_tables.append(Panel.fit("Mac OS is not supported for this script", style="bold cyan"))
            tools.remove("Mac OS")

        if "java_version" in tools:
            instruction_list.append(
                "Make sure you have the correct Java version installed, refer to the table on the right for the correct Java version to install.\n")
            error_table = Table(title="Correct Java Version to use")
            error_table.add_column("IBM Content Cortex Version", style="green")
            error_table.add_column("Java Version", style="green")
            if deployment_prop["ccx_version"] == "26.0.0":
                error_table.add_row("26.0.0", "Java 25")
            error_tables.append(error_table)
            tools.remove("java_version")

        if "oc" in tools:
            instruction_list.append("Make sure you have the oc CLI installed\n\n"
                                    "See the following link for installation instructions: https://mirror.openshift.com/pub/openshift-v4/clients/ocp/latest/")

        if "mirror plugin" in tools:
            instruction_list.append("Make sure you have the oc mirror plugin installed\n\n"
                                    "See the following link for installation instructions: https://mirror.openshift.com/pub/openshift-v4/clients/ocp/latest/")


        if "ibm-pak plugin" in tools:
            instruction_list.append("Make sure you have the oc ibm-pak plugin installed\n\n"
                                    "See the following link for installation instructions: https://github.com/IBM/ibm-pak/releases/latest")


        if tools:
            instruction_list.append("Install any missing tools")
            error_table = Table(title="Tools Missing")
            error_table.add_column("Tools", style="green")
            for tool in tools:
                if tool != "connection":
                    error_table.add_row("- " + tool)
            error_tables.append(error_table)

    error_table_output = Columns(error_tables)

    layout["lower"]["right"].update(error_table_output)

    # Only show remediation steps section if there are actual instructions
    if instruction_list:
        left_panel_list.append(next_steps_panel)
        
        instruction_msg = ""
        for instruction in instruction_list:
            instruction_msg += f":x: {instruction}\n\n"

        instructions = Panel.fit(instruction_msg.strip())
        left_panel_list.append(instructions)

    # Add note on rerunning generate if property files are fixed
    # Add generate command to rerun
    if mode == "validate":
        validate_instruction_list = []
        note = Panel.fit(
            "Important: Rerun the below command once all issues have been resolved to update the generated files.")
        validate_instruction_list.append(note)

        code = "python3 prerequisites.py generate"
        command = Panel.fit(
            Syntax(code, "bash", theme="ansi_dark")
        )
        validate_instruction_list.append(command)
        validate_group = Group(*validate_instruction_list)
        left_panel_list.append(validate_group)

    left_panel = Group(*left_panel_list)

    layout["lower"]["left"].update(left_panel)

    return layout

def generate_casepackage_results(ibmpak_folder: str, download_output: str, repo: bool ) -> Layout:
    # Build Layout for display
    layout = Layout()
    layout.split_column(
        Layout(name="upper"),
        Layout(name="lower"),
    )

    layout["upper"].size = 3

    layout["lower"].split_row(
        Layout(name="left"),
        Layout(name="right"),
    )

    layout["left"].size = None
    layout["right"].ratio = 2

    left_panel_list = []

    right_panel_list = []

    # Create the left side panel
    # Create next steps panel
    message = Text("Case Package Downloaded", style="bold cyan", justify="center")
    result_panel = Panel(message)

    layout["upper"].update(result_panel)

    if repo:
        repo_panel = Panel.fit(Text("IBM Cloud-Pak OCI registry Enabled"), style="bold green")
        left_panel_list.append(repo_panel)

    download = Panel.fit(Text(download_output))

    left_panel_list.append(download)

    left_panel = Group(*left_panel_list)

    right_panel_list.append(Panel.fit("IBM-Pak Files Structure"))
    right_panel_list.append(print_directory_tree(".ibm-pak", ibmpak_folder))

    right_panel = Group(*right_panel_list)

    layout["lower"]["right"].update(right_panel)
    layout["lower"]["left"].update(left_panel)

    return layout


def generate_generate_results(generate_folder: str):
    """Display modern generation summary with rich formatting."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    
    console = Console()
    
    # Success message
    console.print()
    summary = Text()
    summary.append("✓ ", style="bold green")
    summary.append("All artifacts generated successfully!\n\n", style="bold white")
    summary.append(f"Output Directory: ", style="white")
    summary.append(f"{generate_folder}\n", style="cyan")
    
    console.print(Panel(
        summary,
        title="[bold green]Files Generated Successfully[/bold green]",
        border_style="green",
        padding=(1, 2)
    ))
    
    # File tree
    console.print()
    console.print(Panel(
        print_directory_tree("generatedFiles", generate_folder),
        title="[bold cyan]Generated Files Structure[/bold cyan]",
        border_style="cyan",
        padding=(1, 2)
    ))
    
    # Next steps
    console.print()
    next_steps = Text()
    next_steps.append("1. ", style="bold white")
    next_steps.append("Review the Generated files:\n", style="white")
    next_steps.append("   - Database SQL files\n", style="dim white")
    next_steps.append("   - Deployment Secrets\n", style="dim white")
    next_steps.append("   - SSL Certs in yaml format\n", style="dim white")
    next_steps.append("   - Custom Resource (CR) file\n", style="dim white")
    next_steps.append("   - AI Services artifacts (if configured)\n\n", style="dim white")
    
    next_steps.append("2. ", style="bold white")
    next_steps.append("Use the SQL files to create the databases\n\n", style="white")
    
    next_steps.append("3. ", style="bold white")
    next_steps.append("Run the following command to validate:\n\n", style="white")
    next_steps.append("   python3 prerequisites.py validate\n", style="bold cyan")
    
    console.print(Panel(
        next_steps,
        title="[bold yellow]Next Steps[/bold yellow]",
        border_style="yellow",
        padding=(1, 2)
    ))
    console.print()


def generate_loadimage_results(summary: {}) -> Layout:
    # Build Layout for display
    layout = Layout()
    layout.split_column(
        Layout(name="upper"),
        Layout(name="lower"),
    )

    layout["upper"].size = 3

    layout["lower"].split_row(
        Layout(name="left"),
        Layout(name="right"),
    )

    left_panel_list = []

    right_panel_list = []

    # Create the left side panel
    # Create next steps panel
    total = summary["total"]
    if 0 < len(summary["failed"]) < total:
        message = Panel(Text("Image Push Completed with Errors", justify="center"), style="bold yellow")
    elif len(summary["failed"]) == total:
        message = Panel(Text("Image Push Failed",  justify="center"), style="bold red")
    else:
        message = Panel(Text("Image Push Completed Successfully", justify="center"), style="bold green")

    result_panel = message

    layout["upper"].update(result_panel)

    next_steps_panel = Panel.fit("Next Steps")
    instructions = Panel.fit(
        "1. If any failures review the generated image details TOML file\n"
        "2. To configure your IBM Content Cortex deployment to use the private registry set the following in your Custom Resource File"
    )
    private_registry = summary["private_registry"]
    code = f"spec:\n" \
           f"  shared_configuration:\n" \
           f"    sc_image_repository: {private_registry}"

    command = Panel.fit(
        Syntax(code, "yaml", theme="ansi_dark")
    )

    left_panel_list.append(next_steps_panel)
    left_panel_list.append(instructions)
    left_panel_list.append(command)

    left_panel = Group(*left_panel_list)

    if len(summary["failed"]) > 0:
        failed_table = Table(title="Failed Images")
        failed_table.add_column("Image", style="red")
        for image in summary["failed"]:
            element = f"- {image}"
            failed_table.add_row(element)
        right_panel_list.append(failed_table)

    if len(summary["completed"]) > 0:
        pushed_table = Table(title="Pushed Images")
        pushed_table.add_column("Image", style="green")
        for image in summary["completed"]:
            element = f"- {image}"
            pushed_table.add_row(element)
        right_panel_list.append(pushed_table)

    right_panel = Group(*right_panel_list)

    layout["lower"]["right"].update(right_panel)
    layout["lower"]["left"].update(left_panel)

    return layout

def mustgather_network_results(networkpolicy_folder: str, namespace='<namespace>') -> Layout:
    # Build Layout for display
    layout = Layout()
    layout.split_column(
        Layout(name="upper"),
        Layout(name="lower"),
    )

    layout["upper"].size = 3

    layout["lower"].split_row(
        Layout(name="left"),
        Layout(name="right"),
    )

    left_panel_list = []

    right_panel_list = []

    # Create the left side panel
    # Create next steps panel
    message = Text("Generated Network Policies Downloaded Successfully", style="bold cyan", justify="center")

    result_panel = Panel(message)

    layout["upper"].update(result_panel)

    next_steps_panel = Panel.fit("Next Steps")
    instructions = Panel.fit(
        "1. Egress and Ingress Network Policies have been generated and downloaded to your current directory\n"
        "2. Review the generated network policies files\n"
        "3. You can use the following command to apply the network policies to your cluster"
    )

    code = f"python mustgather.py networkpolicy --apply"

    command = Panel.fit(
        Syntax(code, "bash", theme="ansi_dark")
    )

    left_panel_list.append(next_steps_panel)
    left_panel_list.append(instructions)
    left_panel_list.append(command)

    left_panel = Group(*left_panel_list)

    right_panel_list.append(Panel.fit("Network Policy Files Structure"))
    right_panel_list.append(print_directory_tree("FNCMNetworkPolicies", networkpolicy_folder))

    right_panel = Group(*right_panel_list)

    layout["lower"]["right"].update(right_panel)
    layout["lower"]["left"].update(left_panel)

    return layout


def generate_loadimages_results(imageDetailFolder: str, airgap=False) -> Group:
    """
    Generate a clean, modern layout for load images results.
    
    Args:
        imageDetailFolder: Path to the image details folder
        airgap: Whether this is airgap mode
        
    Returns:
        Group: Rich group with simplified results display
    """
    result_panels = []
    
    # Success message
    success_text = Text()
    success_text.append("✅ ", style="bold green")
    if airgap:
        success_text.append("Airgap Environment Variables Generated Successfully", style="bold green")
    else:
        success_text.append("Image Details File Generated Successfully", style="bold green")
    
    success_panel = Panel.fit(
        success_text,
        border_style="green",
        padding=(0, 2)
    )
    result_panels.append(success_panel)
    result_panels.append(Text())  # Spacing
    
    # Next steps in a clean format
    if airgap:
        next_steps = Text()
        next_steps.append("🚀 Next Steps\n\n", style="bold cyan")
        next_steps.append("📋 Review the ImageDetails file contents:\n", style="white")
        next_steps.append("   • Image Repositories\n", style="dim white")
        next_steps.append("   • Image Tags/Digests\n", style="dim white")
        next_steps.append("   • All Component Images\n\n", style="dim white")
        next_steps.append("📝 Optional: Update repositories or tags if needed\n\n", style="white")
        next_steps.append("🚀 Run the following command to start image mirror:\n", style="white")
        
        command = "python3 loadimages.py --airgap push"
    else:
        next_steps = Text()
        next_steps.append("🚀 Next Steps\n\n", style="bold cyan")
        next_steps.append("📋 Review the ImageDetails file contents:\n", style="white")
        next_steps.append("   • Image Repositories\n", style="dim white")
        next_steps.append("   • Image Tags/Digests\n", style="dim white")
        next_steps.append("   • All Component Images\n\n", style="dim white")
        next_steps.append("📝 Optional: Update repositories or tags if needed\n\n", style="white")
        next_steps.append("🚀 Run the following command to push images:\n", style="white")
        
        command = "python3 loadimages.py push"
    
    next_steps_panel = Panel(
        next_steps,
        border_style="cyan",
        padding=(1, 2)
    )
    result_panels.append(next_steps_panel)
    result_panels.append(Text())  # Spacing
    
    # Command in a clean panel
    command_panel = Panel(
        Syntax(command, "bash", theme="monokai", padding=1),
        title="[bold white]💻 Command[/bold white]",
        border_style="green",
        padding=(1, 2)
    )
    result_panels.append(command_panel)
    result_panels.append(Text())  # Spacing
    
    # File structure in a compact format
    if airgap:
        structure_title = "Airgap Variables"
    else:
        structure_title = "ImageDetails Files"
    
    structure_panel = Panel(
        print_directory_tree(structure_title, imageDetailFolder),
        title=f"[bold cyan]📁 {structure_title} Structure[/bold cyan]",
        border_style="cyan",
        padding=(1, 2)
    )
    result_panels.append(structure_panel)
    
    return Group(*result_panels)


class ldap_entry_types(Enum):
    USER = 0
    GROUP = 1
    USER_GROUP = 2

class scim_entry_types(Enum):
    USER = 0
    GROUP = 1
    USER_GROUP = 2
    ADMIN = 3

def idp_token_claim_results(claims, missing_claims):
    """ Validates and displays final IDP token claims results """

    panel_group = []

    claim_table = Table(title="IDP Token Claims")
    claim_table.add_column("Parameter", style="cyan")
    claim_table.add_column("Claim", style="green")
    claim_table.add_column("Value", style="magenta")

    for key, value in claims.items():
        claim_table.add_row(key, value[0], value[1])

    panel_group.append(Panel.fit(claim_table))

    if missing_claims:

        missing_claims_table = Table(title="Missing Claims")
        missing_claims_table.add_column("Claim", style="yellow")

        for claim in missing_claims:
            missing_claims_table.add_row(claim)

        panel_group.append(Panel.fit(missing_claims_table))



    return Group(*panel_group)

def scim_admin_group_results(results, missing_claims):
    """ Validates and displays final SCIM Admin Group results """

    panel_group = []

    if len(results) != 0:

        claim_table = Table(title="User SCIM Mapping for Admin Groups")
        claim_table.add_column("Parameter", style="blue")
        claim_table.add_column("SCIM Key", style="cyan")
        claim_table.add_column("SCIM Data", style="cyan")

        for key, value in results.items():
            claim_table.add_row(key, value['scim_key'], value['scim_value'])

        if len(claim_table.rows) > 0:
            panel_group.append(Panel.fit(claim_table))

    if missing_claims:

        missing_claims_table = Table(title="Unmapped Data")
        missing_claims_table.add_column("Claim", style="yellow")

        for claim in missing_claims:
            missing_claims_table.add_row(claim)

        panel_group.append(Panel.fit(missing_claims_table))



    return Group(*panel_group)



def scim_admin_user_results(user_role, results, missing_claims, groups=None, unmatched_claims=None):
    """ Validates and displays final SCIM Admin results """

    panel_group = []

    if len(results) != 0:

        claim_table = Table(title="User SCIM / Token Mapping for User Role: " + user_role)
        claim_table.add_column("Parameter", style="blue")
        claim_table.add_column("SCIM Key", style="cyan")
        claim_table.add_column("SCIM Data", style="cyan")
        claim_table.add_column("Token Claim", style="magenta")
        claim_table.add_column("Token Value", style="magenta")

        for key, value in results.items():
            claim_table.add_row(key, value['scim_key'], value['scim_value'], value['token_key'], value['token_value'])

        if len(claim_table.rows) > 0:
            panel_group.append(Panel.fit(claim_table))

        if len(unmatched_claims) > 0:
            unmatched_table = Table(title="Unmatched Claims")
            unmatched_table.add_column("Claim", style="red")

            for claim in unmatched_claims:
                unmatched_table.add_row(claim['claim'])

            panel_group.append(Panel.fit(unmatched_table))

    if groups:
        group_panel = Table(title="User Group Membership")
        group_panel.add_column("Group Name", style="cyan")
        group_panel.add_column("Group ID", style="magenta")

        for group in groups:
            name = "Unknown Group"
            id = "Unknown ID"
            if 'displayName' in group:
                name = group.get('displayName', '')

            if 'id' in group:
                id = group.get('id', '')

            if 'value' in group:
                id = group.get('value', '')

            if 'display' in group:
                name = group.get('display', '')

            group_panel.add_row(name, id)

        panel_group.append(group_panel)
    else:
        group_panel = Panel.fit("User is not part of any groups, but Group Membership data is present in SCIM data", title="Group Membership", style="bold yellow")
        panel_group.append(group_panel)



    if missing_claims:

        missing_claims_table = Table(title="Unmapped Data")
        missing_claims_table.add_column("Claim", style="yellow")

        for claim in missing_claims:
            missing_claims_table.add_row(claim)

        panel_group.append(Panel.fit(missing_claims_table))



    return Group(*panel_group)


# Function to display ldap search results
def ldap_search_results(entries_result_dict):
    user_table_list = []
    group_table_list = []
    user_group_table_list = []

    # Build lists of users found, missing and duplicated
    users_found = []
    users_missing = []
    users_duplicated = []

    # Build lists of groups found, missing and duplicated
    groups_found = []
    groups_missing = []
    groups_duplicated = []

    user_or_group_missing = []

    missing = False
    duplicated = False

    for entry, value in entries_result_dict.items():
        if value["type"] == ldap_entry_types.USER:
            if value["count"] == 1:
                users_found.append(entry)
            elif value["count"] == 0:
                users_missing.append(entry)
            else:
                users_duplicated.append(entry)
        elif value["type"] == ldap_entry_types.GROUP:
            if value["count"] == 1:
                groups_found.append(entry)
            elif value["count"] == 0:
                groups_missing.append(entry)
            else:
                groups_duplicated.append(entry)
        else:
            user_or_group_missing.append(entry)

    # Build tables for users and groups
    if len(users_found) > 0:
        users_found_table = Table(title="Users Found")
        users_found_table.add_column("User", style="green")
        users_found_table.add_column("Found in", style="green")
        for user in users_found:
            users_found_table.add_row(user, entries_result_dict[user]["ldap_id"][0])

        user_table_list.append(users_found_table)

    if len(users_missing) > 0:
        user_missing_table = Table(title="Users Missing")
        user_missing_table.add_column("User", style="yellow")
        for user in users_missing:
            user_missing_table.add_row(user)

        user_table_list.append(user_missing_table)
        missing = True

    if len(users_duplicated) > 0:
        user_duplicate_table = Table(title="Users Duplicated")
        user_duplicate_table.add_column("User", style="red")
        user_duplicate_table.add_column("Found in", style="red")
        for user in users_duplicated:
            ldaps = ""
            for i in entries_result_dict[user]["ldap_id"]:
                ldaps += "- " + i + "\n"
            user_duplicate_table.add_row(user, ldaps)

        user_table_list.append(user_duplicate_table)
        duplicated = True

    if len(groups_found) > 0:
        groups_found_table = Table(title="Groups Found")
        groups_found_table.add_column("Group", style="green")
        groups_found_table.add_column("Found in", style="green")
        for group in groups_found:
            groups_found_table.add_row(group, entries_result_dict[group]["ldap_id"][0])

        group_table_list.append(groups_found_table)

    if len(groups_missing) > 0:
        group_missing_table = Table(title="Groups Missing")
        group_missing_table.add_column("Group", style="yellow")
        for group in groups_missing:
            group_missing_table.add_row(group)

        group_table_list.append(group_missing_table)
        missing = True

    if len(groups_duplicated) > 0:
        group_duplicate_table = Table(title="Groups Duplicated")
        group_duplicate_table.add_column("Group", style="red")
        group_duplicate_table.add_column("Found in", style="red")
        for group in groups_duplicated:
            ldaps = ""
            for i in entries_result_dict[group]["ldap_id"]:
                ldaps += "- " + i + "\n"
            group_duplicate_table.add_row(group, ldaps)

        group_table_list.append(group_duplicate_table)
        duplicated = True

    if len(user_or_group_missing) > 0:
        user_group_missing_table = Table(title="Users or Groups Missing")
        user_group_missing_table.add_column("Users or Groups", style="yellow")
        for entry in user_or_group_missing:
            user_group_missing_table.add_row(entry)

        user_group_table_list.append(user_group_missing_table)
        missing = True

    panel_list = []

    if len(user_table_list) != 0:
        user_table_output = Group(*user_table_list)
        user_panel = Panel.fit(user_table_output, title="Users Search Results")
        panel_list.append(user_panel)

    if len(group_table_list) != 0:
        group_table_output = Group(*group_table_list)
        group_panel = Panel.fit(group_table_output, title="Groups Search Results")
        panel_list.append(group_panel)

    if len(user_group_table_list) != 0:
        user_group_table_output = Group(*user_group_table_list)
        user_group_panel = Panel.fit(user_group_table_output, title="User or Groups Search Results")
        panel_list.append(user_group_panel)

    if duplicated:
        panel_list.append(Panel.fit(":x: Duplicated users and groups found!\n"
                                    "This can causes issue when logging in.", style="bold red"))

    if missing:
        panel_list.append(Panel.fit(":exclamation_mark: Some users and groups where not found!\n"
                                    "Please review Property Files.", style="bold yellow"))

    if not duplicated and not missing:
        panel_list.append(Panel.fit(":white_heavy_check_mark: All users and groups where found!", style="bold green"))

    result_group = Group(*panel_list)

    return result_group

def scim_search_results(result_dict):

    """ Validates and displays final SCIM search results """

    user_table_list = []
    group_table_list = []
    user_group_table_list = []

    # Build lists of users found, missing and duplicated
    users_found = []
    users_missing = []

    # Build lists of groups found, missing and duplicated
    groups_found = []
    groups_missing = []

    user_or_group_missing = []

    missing = False
    scim_results_validation = False

    for entry, value in result_dict.items():
        if value["type"] == scim_entry_types.USER:
            if value["count"] == 1:
                users_found.append(entry)
            elif value["count"] == 0:
                users_missing.append(entry)
        elif value["type"] == scim_entry_types.GROUP:
            if value["count"] == 1:
                groups_found.append(entry)
            elif value["count"] == 0:
                groups_missing.append(entry)
        else:
            user_or_group_missing.append(entry)

    # Build tables for users and groups
    if len(users_found) > 0:
        users_found_table = Table(title="Users Found")
        users_found_table.add_column("User", style="green")
        for user in users_found:
            users_found_table.add_row(user)

        user_table_list.append(users_found_table)

    if len(users_missing) > 0:
        user_missing_table = Table(title="Users Missing")
        user_missing_table.add_column("User", style="yellow")
        for user in users_missing:
            user_missing_table.add_row(user)

        user_table_list.append(user_missing_table)
        missing = True

    if len(groups_found) > 0:
        groups_found_table = Table(title="Groups Found")
        groups_found_table.add_column("Group", style="green")
        for group in groups_found:
            groups_found_table.add_row(group)

        group_table_list.append(groups_found_table)

    if len(groups_missing) > 0:
        group_missing_table = Table(title="Groups Missing")
        group_missing_table.add_column("Group", style="yellow")
        for group in groups_missing:
            group_missing_table.add_row(group)

        group_table_list.append(group_missing_table)
        missing = True

    if len(user_or_group_missing) > 0:
        user_group_missing_table = Table(title="Users or Groups Missing")
        user_group_missing_table.add_column("Users or Groups", style="yellow")
        for entry in user_or_group_missing:
            user_group_missing_table.add_row(entry)

        user_group_table_list.append(user_group_missing_table)
        missing = True

    panel_list = []

    if len(user_table_list) != 0:
        user_table_output = Group(*user_table_list)
        user_panel = Panel.fit(user_table_output, title="Users Search Results")
        panel_list.append(user_panel)

    if len(group_table_list) != 0:
        group_table_output = Group(*group_table_list)
        group_panel = Panel.fit(group_table_output, title="Groups Search Results")
        panel_list.append(group_panel)

    if len(user_group_table_list) != 0:
        user_group_table_output = Group(*user_group_table_list)
        user_group_panel = Panel.fit(user_group_table_output, title="User or Groups Search Results")
        panel_list.append(user_group_panel)

    if missing:
        panel_list.append(Panel.fit(":exclamation_mark: Some users and groups where not found!\n"
                                    "Please review Property Files.", style="bold yellow"))


    if not missing:
        panel_list.append(Panel.fit(":white_heavy_check_mark: All users and groups where found!", style="bold green"))
        scim_results_validation = True

    result_group = Group(*panel_list)

    return result_group, scim_results_validation

    

def display_deployment_resources(logger, deployment_resources=None, deployment_details=None, operator_details=None, version_details=None):
    # Build Layout for display
    if version_details is None:
        version_details = {}

    if deployment_resources is None:
        deployment_resources = {}

    if deployment_details is None:
        deployment_details = {}

    if operator_details is None:
        operator_details = {}

    layout = Layout()
    layout.split_column(
        Layout(name="upper"),
        Layout(name="lower"),
    )

    layout["upper"].size = 3

    layout["lower"].split_row(
        Layout(name="left"),
        Layout(name="right"),
    )

    layout["left"].minimum_size = 50
    layout["right"].ratio = 9

    message = Text("IBM Content Cortex Deployment Resources to be Deleted", style="bold blue", justify="center")
    result_panel = Panel(message)
    layout["upper"].update(result_panel)

    layout["upper"].update(result_panel)

    left_panel_list = []

    if version_details:
        version_table = Table(title="Project Details")
        version_table.add_column("Parameter", style="cyan")
        version_table.add_column("Value", style="red")

        version_table.add_row("Namespace", version_details["namespace"])
        version_table.add_row("Platform", version_details["platform"])

        left_panel_list.append(version_table)

    instructions_msg = "The following aspects of your deployment will be cleaned up:"

    left_behind_msg = "\n\nThe following resources will not be deleted:\n\n"

    right_panel_list = []

    if deployment_details:
        resource_tables = []

        for key, value in deployment_resources.items():
            if key != "persistent_volume_claim":
                if value:
                    tableResource = Table(title=key)
                    tableResource.add_column("Name", style="cyan")
                    for item in value:
                        resource = ""
                        resource += "- " + item
                        tableResource.add_row(resource)
                    resource_tables.append(tableResource)

        right_panel_list.extend(resource_tables)

        # Deployment Details Panel
        details_header_panel = Panel.fit("Deployment Details", style="bold cyan", border_style="cyan")

        left_panel_list.append(details_header_panel)

        deployment_details_list = ""

        for key, value in deployment_details.items():
            deployment_details_list += f"- {key}: {value}\n\n"

        details_panel = Panel.fit(deployment_details_list.strip())
        left_panel_list.append(details_panel)

        instructions_msg += ("\n\nIBM Content Cortex Deployment: \n"
                             "  - Deployments\n"
                             "  - Services\n"
                             "  - Operator Generated ConfigMap\n"
                             "  - Operator Generated Secrets\n"
                             "  - Network Policies\n"
                             "  - Ingress or Routes")

        left_behind_msg += ("  - Persistent Volume Claims\n"
                            "  - Persistent Volumes\n"
                            "  - User Created ConfigMaps\n"
                            "  - User Created Secrets\n")
    else:
        deployment_missing = Panel.fit("No FNCM Deployment Found", style="bold red")
        left_panel_list.append(deployment_missing)

    # Operator Details Panel
    if operator_details:
        instructions_msg += ("\n\nIBM Content Cortex Operator: \n"
                             "  - Operator Deployment\n"
                             "  - Role, RoleBinding & Service Account\n")

        if operator_details["type"] == "OLM":
            instructions_msg += ("  - Subscription and Operator Group\n"
                                 "  - Operator Catalog Source\n")
            left_behind_msg += ("  - Cluster Role & Cluster Role Binding\n"
                                "  - Custom Resource Definition (CRD)\n")
        else:
            left_behind_msg += "  - Custom Resource Definition (CRD)\n"


        operator_table = Table(title="Operator Details")
        operator_table.add_column("Parameter", style="cyan")
        operator_table.add_column("Value", style="red")

        operator_table.add_row("Operator Name", operator_details["deployment"])
        operator_table.add_row("Release", operator_details["release"])
        operator_table.add_row("Install Type", operator_details["type"])

        if operator_details["type"] == "OLM" and "Installed CSV" in operator_details.keys():
            operator_table.add_row("Installed CSV", operator_details["installedCSV"])
            operator_table.add_row("Channel", operator_details["channel"])
            operator_table.add_row("Catalog Source", operator_details["catalogSource"])
            operator_table.add_row("Catalog Install Type", operator_details["catalogType"])

        right_panel_list.append(operator_table)
    else:
        operator_missing = Panel.fit("No Operator Deployment Found", style="bold red")
        right_panel_list.append(operator_missing)

    left_panel_list.append(Text(instructions_msg.strip()))
    left_panel_list.append(Text(left_behind_msg.rstrip()))

    left_panel = Group(*left_panel_list)
    to_be_deleted_tables = Columns(right_panel_list)

    layout["lower"]["right"].update(to_be_deleted_tables)
    layout["lower"]["left"].update(left_panel)

    return layout



def display_toml_syntax_error(exc: Exception, config_file: str) -> Panel:
    """
    Render a toml.TomlDecodeError as the same styled Panel used for Pydantic
    validation errors, with a human-readable location and the offending line.

    Args:
        exc:         The TomlDecodeError (or any exception from toml.load).
        config_file: Path shown in the panel title.

    Returns:
        A Panel ready to print().
    """
    lineno  = getattr(exc, 'lineno',  None)
    colno   = getattr(exc, 'colno',   None)
    raw_msg = getattr(exc, 'msg',     None) or str(exc)
    doc     = getattr(exc, 'doc',     None) or ""

    # Extract the offending source line when available
    offending = ""
    if lineno and doc:
        lines = doc.splitlines()
        if 1 <= lineno <= len(lines):
            offending = lines[lineno - 1].strip()

    # Build location string
    if lineno and colno:
        location = f"line {lineno}, column {colno}"
    elif lineno:
        location = f"line {lineno}"
    else:
        location = "unknown location"

    content = Text()
    content.append("Syntax error in ", style="white")
    content.append(f"{config_file}\n\n", style="cyan")
    content.append("  1. ", style="bold red")
    content.append(f"{raw_msg}\n", style="white")
    if offending:
        content.append(f"     at {location}: ", style="dim white")
        content.append(f"{offending}\n", style="yellow")
    else:
        content.append(f"     at {location}\n", style="dim white")

    content.append("\nHow to fix:\n", style="bold yellow")
    content.append(f"  1. Open ", style="dim white")
    content.append(f"{config_file}", style="cyan")
    content.append(f" and go to {location}\n", style="dim white")
    content.append("  2. Correct the value so it matches the expected type\n", style="dim white")
    content.append("     (e.g. use ", style="dim white")
    content.append("true", style="yellow")
    content.append(" / ", style="dim white")
    content.append("false", style="yellow")
    content.append(" for booleans, a number for integers)\n", style="dim white")
    content.append("  3. Re-run the script once the file is corrected", style="dim white")

    return Panel(
        content,
        title="[bold red]❌ Configuration Syntax Error[/bold red]",
        border_style="red",
        padding=(1, 2),
    )


def display_config_validation_errors(errors: List[str], config_file: str) -> Panel:
    """
    Display Pydantic validation errors for configuration files.

    Args:
        errors: List of validation error messages
        config_file: Path to the configuration file that failed validation

    Returns:
        A single Panel containing all error and remediation content.
    """
    content = Text()

    # Error list
    content.append(f"Found {len(errors)} error(s) in ", style="white")
    content.append(f"{config_file}\n\n", style="cyan")

    for idx, error in enumerate(errors, 1):
        # Strip the leading "❌ " prefix added by the validator — the icon is on the number
        clean = error.lstrip("❌ ").strip()
        content.append(f"  {idx}. ", style="bold red")
        content.append(f"{clean}\n", style="white")

    # How to fix
    content.append("\nHow to fix:\n", style="bold yellow")
    content.append(f"  1. Open ", style="dim white")
    content.append(f"{config_file}", style="cyan")
    content.append(" and correct the error(s) above\n", style="dim white")
    content.append("  2. Replace any placeholder values (e.g. ", style="dim white")
    content.append("<Namespace>", style="yellow")
    content.append(")\n", style="dim white")
    content.append("  3. Verify field values match the documented valid options\n", style="dim white")
    content.append("  4. Re-run the script once the file is corrected", style="dim white")

    return Panel(
        content,
        title="[bold red]❌ Configuration Validation Failed[/bold red]",
        border_style="red",
        padding=(1, 2),
    )



def display_operator_selection(operators: List[dict], selected: List[str] = None) -> Layout:
    """
    Display available operators for selection with metadata.
    
    Args:
        operators: List of operator metadata dictionaries
        selected: List of currently selected operator types
        
    Returns:
        Layout with operator information
    """
    layout = Layout()
    layout.split_column(
        Layout(name="upper"),
        Layout(name="lower"),
    )
    
    layout["upper"].size = 3
    
    # Header
    message = Text("IBM Content Cortex Operator Selection", style="bold cyan", justify="center")
    header_panel = Panel(message, style="bold cyan")
    layout["upper"].update(header_panel)
    
    # Operator table
    operator_table = Table(title="Available Operators", show_header=True, header_style="bold cyan")
    operator_table.add_column("Operator", style="cyan", width=25)
    operator_table.add_column("Description", style="white", width=50)
    operator_table.add_column("Required", style="yellow", width=10)
    operator_table.add_column("CPU", style="green", width=10)
    operator_table.add_column("Memory", style="green", width=10)
    
    selected = selected or []
    
    for op in operators:
        required_mark = "✓ Yes" if op.get("required", False) else "No"
        selected_mark = "✓ " if op["type"] in selected else ""
        
        resources = op.get("resource_requirements", {})
        cpu = resources.get("cpu", "N/A")
        memory = resources.get("memory", "N/A")
        
        operator_table.add_row(
            f"{selected_mark}{op['display_name']}",
            op["description"],
            required_mark,
            cpu,
            memory
        )
    
    # Info panel
    info_text = (
        "[bold yellow]Selection Guidelines:[/bold yellow]\n\n"
        "• [cyan]License Service[/cyan] and [cyan]Usage Metering[/cyan] are required and will always be deployed\n"
        "• [cyan]Content (Core FNCM)[/cyan] is optional based on deployment needs\n"
        "• [cyan]AI Services[/cyan] requires Content operator\n"
        "• Dependencies will be automatically validated\n\n"
        "[bold green]Tip:[/bold green] Select Content for core FNCM features, add AI Services as needed"
    )
    
    info_panel = Panel(info_text, title="Information", border_style="blue")
    
    content_group = Group(operator_table, Text("\n"), info_panel)
    layout["lower"].update(content_group)
    
    return layout


def display_operator_summary(selected_operators: List[dict], total_resources: dict) -> Panel:
    """
    Display summary of selected operators and total resource requirements.
    
    Args:
        selected_operators: List of selected operator metadata
        total_resources: Dictionary with total resource requirements
        
    Returns:
        Panel with operator deployment summary
    """
    summary_table = Table(show_header=True, header_style="bold green", box=None)
    summary_table.add_column("Operator", style="cyan")
    summary_table.add_column("Status", style="green")
    
    for op in selected_operators:
        summary_table.add_row(
            op["display_name"],
            "✓ Selected"
        )
    
    resources_text = (
        f"\n[bold yellow]Total Resource Requirements:[/bold yellow]\n"
        f"  CPU: {total_resources.get('cpu', 'N/A')}\n"
        f"  Memory: {total_resources.get('memory', 'N/A')}\n"
        f"  Storage: {total_resources.get('storage', 'N/A')}\n"
    )
    
    content = Group(
        Text("Selected Operators for Deployment", style="bold cyan"),
        Text(""),
        summary_table,
        Text(resources_text)
    )
    
    return Panel(content, title="Deployment Summary", border_style="green")



# ============================================================================
# Smart Deployment Order Functions
# ============================================================================

def display_deployment_order(
    operators: List,
    deployment_order: List
) -> None:
    """
    Display the calculated deployment order with dependency explanation.
    
    Args:
        operators: List of OperatorType objects selected for deployment
        deployment_order: List of OperatorType objects in deployment order
    """
    from rich import print
    from .operator_config import get_operator_metadata
    
    tree = Tree("📋 [bold cyan]Deployment Order[/bold cyan]")
    
    for idx, op in enumerate(deployment_order, 1):
        metadata = get_operator_metadata(op)
        node = tree.add(f"[green]{idx}.[/green] {metadata.display_name}")
        
        if metadata.dependencies:
            deps_node = node.add("[yellow]Dependencies:[/yellow]")
            for dep in metadata.dependencies:
                dep_meta = get_operator_metadata(dep)
                deps_node.add(f"→ {dep_meta.display_name}")
        else:
            node.add("[dim]No dependencies[/dim]")
    
    print(tree)
    print()


def display_deployment_waves(waves: List[List]) -> None:
    """
    Display deployment waves for parallel deployment.
    
    Args:
        waves: List of waves, where each wave is a list of OperatorType objects
    """
    from rich import print
    from .operator_config import get_operator_metadata
    
    table = Table(title="🌊 Deployment Waves (Parallel Groups)")
    table.add_column("Wave", style="cyan", justify="center", width=8)
    table.add_column("Operators", style="green")
    table.add_column("Can Deploy in Parallel", justify="center", width=20)
    
    for idx, wave in enumerate(waves, 1):
        operators = ", ".join([get_operator_metadata(op).display_name for op in wave])
        parallel = "[green]✓[/green]" if len(wave) > 1 else "—"
        table.add_row(str(idx), operators, parallel)
    
    print(table)
    print()


def display_deployment_graph_summary(summary: dict) -> None:
    """
    Display a summary of the deployment graph analysis.
    
    Args:
        summary: Dictionary containing deployment graph statistics
    """
    from rich import print
    
    if "error" in summary:
        print(f"[red]✗ Error analyzing deployment graph:[/red] {summary['error']}")
        return
    
    lines = [
        f"[bold cyan]Deployment Graph Analysis[/bold cyan]",
        "",
        f"[bold]Total Operators:[/bold] {summary['total_operators']}",
        f"[bold]Deployment Waves:[/bold] {summary['total_waves']}",
        f"[bold]Max Parallel:[/bold] {summary['max_parallel']} operators",
        f"[bold]Has Dependencies:[/bold] {'Yes' if summary['has_dependencies'] else 'No'}",
    ]
    
    print(Panel("\n".join(lines), border_style="cyan", title="📊 Deployment Plan"))
    print()


def display_dependency_errors(errors: List[str]) -> None:
    """
    Display dependency validation errors.
    
    Args:
        errors: List of error messages
    """
    from rich import print
    
    if not errors:
        print("[green]✓[/green] All dependencies validated successfully")
        print()
        return
    
    print(Panel.fit(
        "[bold red]Dependency Validation Errors[/bold red]",
        border_style="red"
    ))
    print()
    
    for idx, error in enumerate(errors, 1):
        print(f"  [red]{idx}.[/red] {error}")
    
    print()
    print("[yellow]⚠[/yellow]  Please select all required dependencies or remove dependent operators.")
    print()



# ═══════════════════════════════════════════════════════════════════════════════
# Modern Deployment Progress Display Functions
# ═══════════════════════════════════════════════════════════════════════════════

def create_deployment_header(
    operator_name: str,
    namespace: str,
    deployment_type: str,
    selected_operators: List | None = None,
    parallel: bool = False,
    version_data: dict | None = None
) -> Panel:
    """
    Create a modern, visually appealing deployment header.
    
    Args:
        operator_name: Name of the operator being deployed (legacy single-operator)
        namespace: Target namespace
        deployment_type: Type of deployment (olm or yaml)
        selected_operators: List of OperatorType enums for multi-operator deployment
        parallel: Whether parallel deployment is enabled
        version_data: Version data from version.toml (optional)
    
    Returns:
        Rich Panel with deployment header
    """
    from .operator_config import get_operator_metadata
    from .utilities import get_operator_version
    
    header_text = Text()
    header_text.append("🚀 ", style="bold cyan")
    
    if selected_operators and len(selected_operators) > 1:
        header_text.append("IBM Content Cortex Multi-Operator Deployment\n\n", style="bold white")
        
        header_text.append("📦 Operators: ", style="bold yellow")
        header_text.append(f"{len(selected_operators)} operators", style="white")
        if parallel:
            header_text.append(" (parallel deployment)", style="bold green")
        header_text.append("\n", style="white")
        
        header_text.append("🧭 Flow: ", style="bold yellow")
        header_text.append("Shared cluster setup first", style="white")
        if parallel:
            header_text.append(", then parallel operator deployment", style="bold green")
        else:
            header_text.append(", then operator deployment", style="white")
        header_text.append("\n", style="white")
        
        for op in selected_operators:
            metadata = get_operator_metadata(op)
            header_text.append("   • ", style="cyan")
            header_text.append(f"{metadata.display_name}", style="white")
            
            # Add version information if available
            if version_data:
                version = get_operator_version(version_data, metadata.operator_type.value, "VERSION")
                header_text.append(f" (v{version})", style="dim white")
            
            header_text.append("\n", style="white")
    else:
        header_text.append("IBM Content Cortex Operator Deployment\n\n", style="bold white")
        
        header_text.append("📦 Operator: ", style="bold yellow")
        header_text.append(f"{operator_name}\n", style="white")
    
    header_text.append("\n🎯 Namespace: ", style="bold yellow")
    header_text.append(f"{namespace}\n", style="white")
    
    header_text.append("⚙️  Method: ", style="bold yellow")
    method_display = "OLM (Operator Lifecycle Manager)" if deployment_type == "olm" else "YAML (Direct Apply)"
    header_text.append(f"{method_display}\n", style="white")
    
    header_text.append("🕐 Started: ", style="bold yellow")
    header_text.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), style="white")
    
    title = "[bold cyan]Multi-Operator Deployment Initiated[/bold cyan]" if (selected_operators and len(selected_operators) > 1) else "[bold cyan]Deployment Initiated[/bold cyan]"
    
    return Panel(
        header_text,
        title=title,
        border_style="cyan",
        padding=(1, 2)
    )


def create_phase_header(phase_name: str, phase_number: int, total_phases: int, style: str = "cyan") -> Panel:
    """
    Create a modern phase header with progress indicator.
    
    Args:
        phase_name: Name of the deployment phase
        phase_number: Current phase number (1-based)
        total_phases: Total number of phases
        style: Color style for the panel
    
    Returns:
        Rich Panel with phase header
    """
    # Create progress indicator
    progress_text = Text()
    progress_text.append(f"Phase {phase_number}/{total_phases}", style=f"bold {style}")
    
    # Create phase name with icon
    phase_icons = {
        "Cluster Setup": "🔧",
        "OLM Setup": "📋",
        "CRD & Permission Setup": "🔐",
        "Deploying Operator": "🚀"
    }
    
    icon = phase_icons.get(phase_name, "▶️")
    phase_text = Text()
    phase_text.append(f"{icon} {phase_name}", style=f"bold {style}")
    
    # Combine into panel
    content = Text()
    content.append(progress_text)
    content.append("\n")
    content.append(phase_text)
    
    return Panel(
        content,
        border_style=style,
        padding=(0, 2)
    )


def format_deployment_step(message: str, status: str = "info", indent: int = 0) -> Text:
    """
    Format a deployment step message with appropriate icon and color.
    
    Args:
        message: The step message
        status: Status type (info, success, warning, error, skip)
        indent: Indentation level
    
    Returns:
        Formatted Rich Text object
    """
    # Status icons and colors
    status_config = {
        "info": ("ℹ️", "cyan"),
        "success": ("✅", "green"),
        "warning": ("⚠️", "yellow"),
        "error": ("❌", "red"),
        "skip": ("⏭️", "dim"),
        "exists": ("📌", "yellow")
    }
    
    icon, color = status_config.get(status, ("•", "white"))
    
    # Create formatted text
    text = Text()
    text.append("  " * indent)  # Add indentation
    text.append(f"{icon}  ", style=f"bold {color}")
    text.append(message, style=color if status in ["success", "error"] else "white")
    
    return text


def create_phase_summary(phase_name: str, duration: float, success: bool = True) -> Panel:
    """
    Create a summary panel for a completed phase.
    
    Args:
        phase_name: Name of the completed phase
        duration: Duration in seconds
        success: Whether the phase completed successfully
    
    Returns:
        Rich Panel with phase summary
    """
    if success:
        icon = "✅"
        status_text = "Completed"
        style = "green"
    else:
        icon = "❌"
        status_text = "Failed"
        style = "red"
    
    content = Text()
    content.append(f"{icon} {phase_name} ", style=f"bold {style}")
    content.append(status_text, style=f"bold {style}")
    content.append(f"\n⏱️  Duration: {duration:.1f}s", style="dim")
    
    return Panel(
        content,
        border_style=style,
        padding=(0, 2)
    )


def create_deployment_footer(success: bool, total_duration: float, namespace: str) -> Panel:
    """
    Create a modern deployment completion footer.
    
    Args:
        success: Whether deployment was successful
        total_duration: Total deployment duration in seconds
        namespace: Target namespace
    
    Returns:
        Rich Panel with deployment footer
    """
    if success:
        icon = "🎉"
        title = "Deployment Successful"
        style = "bold green"
        border_style = "green"
        message = f"IBM Content Cortex Operator has been successfully deployed to namespace '{namespace}'"
    else:
        icon = "⚠️"
        title = "Deployment Failed"
        style = "bold red"
        border_style = "red"
        message = f"Deployment to namespace '{namespace}' encountered errors"
    
    content = Text()
    content.append(f"{icon} ", style=style)
    content.append(f"{message}\n\n", style="white")
    
    # Add duration
    minutes = int(total_duration // 60)
    seconds = int(total_duration % 60)
    content.append("⏱️  Total Duration: ", style="bold yellow")
    if minutes > 0:
        content.append(f"{minutes}m {seconds}s", style="white")
    else:
        content.append(f"{seconds}s", style="white")
    
    content.append("\n🕐 Completed: ", style="bold yellow")
    content.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), style="white")
    
    return Panel(
        content,
        title=f"[{style}]{title}[/{style}]",
        border_style=border_style,
        padding=(1, 2)
    )
