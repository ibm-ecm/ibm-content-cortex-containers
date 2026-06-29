###############################################################################
#
# Licensed Materials - Property of IBM
#
# (C) Copyright IBM Corp. 2023. All Rights Reserved.
#
# US Government Users Restricted Rights - Use, duplication or
# disclosure restricted by GSA ADP Schedule Contract with IBM Corp.
#
###############################################################################


# Write a main function that parses command line arguments
#  - the main should take a mode as an argument
#  - the modes can are gather, generate, validate
#  - the gather mode accepts a migration option
#  - the migration option accept a folder location
#  - the main should call the appropriate function based on the mode
#  - the main should pass the parsed arguments to the function
#  - the main should print the output of the function

import fnmatch
import logging
import os
import platform
import shutil
import sys
from datetime import datetime
from typing_extensions import Annotated
import re

import typer
import questionary
from questionary import Style
from rich import print
from rich.columns import Columns
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.live import Live
from rich.progress import (
    Progress,
    SpinnerColumn,
    TimeElapsedColumn,
    MofNCompleteColumn, BarColumn, TaskProgressColumn, TextColumn,
)
from rich.layout import Layout
from rich.table import Table as RichTable
from rich.prompt import Confirm
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from toml.decoder import TomlDecodeError

from helper_scripts.gather import gather_prerequisites as g
from helper_scripts.gather import silent_gather_prerequisites as sg
from helper_scripts.generate.generate_cr import GenerateCR
from helper_scripts.generate.generate_ai_services import GenerateAIServices
from helper_scripts.generate.generate_metrics import GenerateMetrics
from helper_scripts.generate.generate_secrets import GenerateSecrets
from helper_scripts.generate.generate_sql import GenerateSql
from helper_scripts.property import property as p
from helper_scripts.property.read_prop import *
from helper_scripts.property.read_prop import ReadPropAIServices
from helper_scripts.property.unified_validation import UnifiedValidationDisplay
from helper_scripts.property.generate_property_readme import GeneratePropertyReadme
from helper_scripts.utilities.interface import clear, generate_gather_results, generate_generate_results, \
    display_issues, display_prereq_passed, display_config_validation_errors, display_prereq_validation_table, \
    display_toml_syntax_error
from helper_scripts.utilities.config_models import validate_prerequisites_config
from helper_scripts.utilities.prerequisites_utilites import zip_folder, \
    create_generate_folder, check_ssl_folders, check_icc_masterkey, check_trusted_certs, check_dbname, \
    check_keystore_password_length, collect_visible_files, check_db_password_length, check_db_ssl_mode, \
    add_idp_to_trusted_certs
from helper_scripts.utilities.utilities import read_version_toml, prereq_checks
from helper_scripts.validate import validate as v
from helper_scripts.validate.validation_display import ValidationDisplay

__version__ = "26.0.0"

app = typer.Typer()
state = {
    "verbose": False,
    "silent": False,
    "logger": logging
}

console = Console(record=True)


def version_callback(value: bool):
    if value:
        print(f"IBM Content Cortex Deployment Prerequisites CLI: {__version__}")
        raise typer.Exit()



@app.callback()
def main(ctx: typer.Context,
         version: Annotated[bool, typer.Option(
    "--version", help="Show version and exit.",
    callback=version_callback, is_eager=True)] = None,
         silent: Annotated[bool, typer.Option(
             help="Enable Silent Install (no prompts).",
             rich_help_panel="Customization and Utils")] = False,
         verbose: Annotated[bool, typer.Option(
             help="Enable verbose logging.",
             rich_help_panel="Customization and Utils")] = False):

    """
    IBM Content Cortex Deployment Prerequisites CLI.
    """
    if verbose:
        state["verbose"] = True
        FILE_LOG_LEVEL = logging.DEBUG
    else:
        FILE_LOG_LEVEL = logging.WARNING

    state["logger"] = setup_logger(FILE_LOG_LEVEL)

    if silent:
        state["silent"] = True

    # Read Version File
    version_path = os.path.join(os.path.dirname(os.getcwd()), "version.toml")
    if not os.path.exists(version_path):
        version_path = os.path.join(os.path.dirname(os.path.dirname(os.getcwd())), "version.toml")

    if os.path.exists(version_path):
        state["version_data"] = read_version_toml(version_path, state["logger"])
    else:
        state["version_data"] = {}

    # Only run prerequisite checks if a subcommand is invoked AND --help is not in arguments
    # This prevents checks from running when --help or --version is used
    if ctx.invoked_subcommand is not None and "--help" not in sys.argv:
        if ctx.invoked_subcommand == "gather":
            if not state["silent"]:
                clear(console)
            display_mode_version("Gather",
                                 "Gather information required for IBM Content Cortex Deployment")
            checks = ["connection",]
            files = []


        elif ctx.invoked_subcommand == "generate":
            display_mode_version("Generate",
                                 "Generate all deployment artifacts for IBM Content Cortex Deployment")
            checks = ["connection",]
            files = []

        elif ctx.invoked_subcommand == "validate":
            display_mode_version("Validate",
                                 "Validate all prerequisites for IBM Content Cortex Deployment")
            checks = ["connection","keytool", "java"]
            if platform.system() == 'Windows':
                checks.append("powershell")
            files = []


        missing_tools, results, files = prereq_checks(logger=state["logger"], prereqs=checks, files=files)

        # Print table of prerequisites that are missing
        if len(missing_tools) > 0 or len(files) > 0:
            state["logger"].info("Prerequisites failed. Displaying missing tools and files.")

            if missing_tools == ["connection"] and not files:
                unified_display = UnifiedValidationDisplay(console)
                unified_display.add_connection_issue(cluster_connected=False)
                unified_display.display()
            else:
                layout = display_issues(tools=missing_tools, descriptors=files)
                print(layout)

            exit(1)
        else:
            state["logger"].info("Prerequisites passed.")
            display_prereq_validation_table(results)


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
    file_handler = logging.FileHandler("prerequisites.log")
    file_handler.setLevel(logging.DEBUG)
    formatter_file = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)-100s - %(filename)s:%(lineno)d", "%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(formatter_file)

    # Add handlers to the logger
    logger.addHandler(shell_handler)
    logger.addHandler(file_handler)

    return logger


def display_mode_version(mode: str, description: str):
    """
    Display the mode and version of the script with active flags in a modern, visually appealing format.
    
    Args:
        mode: The operation mode (e.g., "Gather Prerequisites", "Generate Secrets")
        description: Description of what the script does
    """
    if not state["silent"]:
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
        state["logger"].info("Silent Mode is enabled")
    
    if state["verbose"]:
        active_flags.append("📢 Verbose Logging")
        state["logger"].info("Verbose Logging is enabled")
    
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
        title="[bold white]📋 IBM Content Cortex Deployment Prerequisites CLI[/bold white]",
        border_style="bright_blue",
        padding=(1, 2),
        expand=False
    ))
    print()




@app.command()
def gather(
        move: Annotated[str, typer.Option(help="Folder location of the migration files",
                                          rich_help_panel="Mode Options",
                                          dir_okay=True)] = "",
        ccx_version: Annotated[str, typer.Option(help="IBM Content Cortex version override",
                                             rich_help_panel="Mode Options")] = ""
):
    """
    Gather the prerequisites for IBM Content Cortex Deployment.
    """

    if move != '':
        dir_exists = os.path.isdir(move)

        if not dir_exists:
            # Enhanced error message with helpful context
            state["logger"].error(f"Migration directory not found: {move}")
            
            # Display rich error panel with guidance
            error_text = Text()
            error_text.append("✗ ", style="bold red")
            error_text.append("Migration Directory Not Found\n\n", style="bold red")
            error_text.append("The specified directory does not exist:\n", style="white")
            error_text.append(f"  {os.path.abspath(move)}\n\n", style="yellow")
            error_text.append("Expected Contents:\n", style="bold white")
            error_text.append("  • ", style="green")
            error_text.append("GCD XML file (e.g., *gcd*.xml)\n", style="white")
            error_text.append("  • ", style="green")
            error_text.append("Object Store XML files (e.g., *os*.xml)\n", style="white")
            error_text.append("  • ", style="green")
            error_text.append("LDAP XML files (e.g., *ldap*.xml)\n", style="white")
            error_text.append("  • ", style="green")
            error_text.append("Navigator XML file (e.g., *ecm*.xml)\n\n", style="white")
            error_text.append("Please verify:\n", style="bold white")
            error_text.append("  1. The directory path is correct\n", style="dim white")
            error_text.append("  2. You have read permissions\n", style="dim white")
            error_text.append("  3. The directory contains XML migration files\n", style="dim white")
            
            print()
            print(Panel(
                error_text,
                title="[bold red]Migration Error[/bold red]",
                border_style="red",
                padding=(1, 2)
            ))
            print()
            
            raise typer.Exit(code=1)

    move_db = False
    move_ldap = False

    if ccx_version != '':
        state["version_data"]["VERSION"] = ccx_version

    if not state["silent"]:
        # Display mode header with enhanced styling
        print()
        header_text = Text()
        header_text.append("📝 ", style="bold yellow")
        header_text.append("Gather Mode", style="bold cyan")
        header_text.append(" - Collect Deployment Configuration", style="white")
        
        print(Panel(
            header_text,
            title="[bold white]IBM Content Cortex Prerequisites[/bold white]",
            border_style="cyan",
            padding=(1, 2)
        ))
        print()
        
        # Display what will be gathered
        info_text = Text()
        info_text.append("This mode will collect:\n\n", style="bold white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("License model and platform selection\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Operator choices (Content, AI Services)\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Authentication configuration (LDAP, IDP, SCIM)\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Database and storage requirements\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("AI model provider settings (if applicable)\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Optional components and features\n", style="white")
        
        print(Panel(
            info_text,
            title="[bold white]Configuration Collection[/bold white]",
            border_style="green",
            padding=(1, 2)
        ))
        print()
        
        # this is the user details object
        gather = g.GatherPrereqOptions(logger=state["logger"], console=console)

        if move == '':
            gather.collect_license_model(state["version_data"])
            print()  # Add spacing
            
            gather.collect_operators()
            print()  # Add spacing
            
            gather.collect_namespace()
            print()  # Add spacing
            
            # Check for existing FNCMCluster deployment and offer migration
            # This is specifically for AI Services setup when Content is already deployed
            if gather.has_ai_services_operator() and not gather.has_content_operator():
                migrated = gather.check_and_migrate_from_fncm_deployment()
                if migrated:
                    print()  # Add spacing after migration summary
            
            gather.collect_ingress()
            print()  # Add spacing
            
            gather.collect_auth_type()
            print()  # Add spacing
            
            gather.collect_fips_info()
            print()  # Add spacing
            
            gather.collect_secret_management()
            print()  # Add spacing
            
            gather.collect_networkpolicy_info()
            print()  # Add spacing
            
            gather.collect_optional_components()
            print()  # Add spacing
            
            # Collect model provider information if AI Services operator is selected
            if gather.has_ai_services_operator():
                gather.collect_model_providers()
                print()  # Add spacing
                
                # Add GraphQL SSL folder for AI Services
                if "graphql" not in gather.ssl_directory_list:
                    gather.ssl_directory_list.append("graphql")
            
            # Only collect database info if Content operator is selected
            if gather.has_content_operator():
                gather.collect_db_info()
                print()  # Add spacing

            # Only collect LDAP if Content operator is selected
            # AI Services alone only needs IDP, not LDAP
            if gather.has_content_operator() and gather.auth_type in ("LDAP", "LDAP_IDP"):
                gather.collect_ldap_number()
                gather.collect_ldap_type()
                print()  # Add spacing

            if gather.auth_type in ("LDAP_IDP", "SCIM_IDP"):
                gather.collect_idp_number()
                gather.collect_idp_discovery()
                print()  # Add spacing

            gather.collect_init_verify_content()
        else:
            # Migration path - collect configuration with XML files
            gather.collect_license_model(state["version_data"])
            print()  # Add spacing
            
            gather.collect_operators()
            print()  # Add spacing
            
            gather.collect_namespace()
            print()  # Add spacing

            gather.collect_ingress()
            print()  # Add spacing

            gather.collect_auth_type()
            print()  # Add spacing
            
            gather.collect_fips_info()
            print()  # Add spacing
            
            gather.collect_secret_management()
            print()  # Add spacing
            
            gather.collect_networkpolicy_info()
            print()  # Add spacing

            gather.collect_optional_components()
            print()  # Add spacing
            
            # Collect model provider information if AI Services operator is selected
            if gather.has_ai_services_operator():
                gather.collect_model_providers()
                print()  # Add spacing
                
                # Add GraphQL SSL folder for AI Services
                if "graphql" not in gather.ssl_directory_list:
                    gather.ssl_directory_list.append("graphql")

            # Get all files in the directory as list by type
            files = collect_visible_files(move)
            gcd_file = fnmatch.filter(files, "*gcd*.xml")
            os_files = fnmatch.filter(files, "*os*.xml")
            ldap_files = fnmatch.filter(files, "*ldap*.xml")
            icn_files = fnmatch.filter(files, "*ecm*.xml")

            move_dict = {}

            if len(icn_files) > 1:
                state["logger"].error(
                    "More than one Navigator file found. Please remove the extra files and try again.")
                raise typer.Exit()
            elif len(icn_files) == 0:
                move_dict["ICN"] = []
            else:
                move_dict["ICN"] = icn_files

            if len(gcd_file) > 1:
                state["logger"].error("More than one GCD file found. Please remove the extra files and try again.")
                raise typer.Exit()
            elif len(gcd_file) == 0:
                move_dict["GCD"] = []
            else:
                move_dict["GCD"] = gcd_file

            # Only collect LDAP if Content operator is selected
            # AI Services alone only needs IDP, not LDAP
            if gather.has_content_operator() and gather.auth_type in ("LDAP", "LDAP_IDP"):
                if len(ldap_files) > 0:
                    ldap_number = len(ldap_files)
                    gather.ldap_number = ldap_number
                    gather.parse_ldap_files(os.path.abspath(move), ldap_files)
                    move_dict["LDAP"] = ldap_files
                    move_ldap = True
                else:
                    gather.collect_ldap_number()
                    gather.collect_ldap_type()
                    move_dict["LDAP"] = []

            if gather.auth_type in ("LDAP_IDP", "SCIM_IDP"):
                gather.collect_idp_number()
                gather.collect_idp_discovery()
                print()  # Add spacing

            # Determine DB type
            all_db_files = []
            all_db_files.extend(gcd_file)
            all_db_files.extend(os_files)
            all_db_files.extend(icn_files)
            if len(all_db_files) > 0:
                gather.parse_db_files(os.path.abspath(move), all_db_files)
                move_db = True
            else:
                gather.collect_db_type()

            # Determine number of OS's
            if len(os_files) > 0:
                os_number = len(os_files)
                gather.os_number = os_number
                move_dict["OS"] = os_files
            else:
                gather.collect_os_number()
                move_dict["OS"] = []

            # Determine SSL Enabled
            gather.collect_db_ssl_info()
            print()  # Add spacing
            
            # Collect init verify content at the end of migration path
            gather.collect_init_verify_content()

    else:
        # add logic to populate user_details using silent mode

        silent_path = os.path.join("silent_config", "silent_install_prerequisites.toml")

        # Validate configuration with Pydantic before proceeding
        state["logger"].info(f"Validating silent prerequisites configuration: {silent_path}")
        try:
            import toml as _toml
            with open(silent_path, 'r') as _f:
                _config_dict = _toml.load(_f)

            _success, _validated_config, _validation_errors = validate_prerequisites_config(_config_dict)

            if not _success:
                print(display_config_validation_errors(_validation_errors, silent_path))
                raise typer.Exit(code=1)

            state["logger"].info("✓ Configuration validated successfully")

        except FileNotFoundError:
            print(Panel.fit(f"❌ Configuration file not found: {silent_path}", style="bold red"))
            raise typer.Exit(code=1)
        except typer.Exit:
            raise
        except TomlDecodeError as _e:
            print(display_toml_syntax_error(_e, silent_path))
            raise typer.Exit(code=1)
        except Exception as _e:
            state["logger"].error(f"Unexpected error loading configuration: {str(_e)}")
            print(Panel.fit(f"❌ Unexpected error: {str(_e)}", style="bold red"))
            raise typer.Exit(code=1)

        gather = sg.SilentGatherPrereqOptions(state["logger"], silent_path)

        # Individual components instead:
        gather.silent_version(state["version_data"])
        gather.silent_namespace()
        gather.silent_auth_type()
        gather.silent_optional_components()
        
        # Only collect LDAP if Content operator is selected
        # AI Services alone only needs IDP, not LDAP
        if gather.has_content_operator() and gather.auth_type in ("LDAP", "LDAP_IDP"):
            gather.silent_ldap()

        if gather.auth_type in ("LDAP_IDP", "SCIM_IDP"):
            gather.silent_idp()

        gather.silent_ingress()
        gather.silent_fips_support()
        gather.silent_network_policies_support()
        gather.silent_optional_components()
        gather.silent_sendmail_support()
        gather.silent_icc_support()
        gather.silent_tm_support()
        gather.silent_db()
        gather.silent_license_model()
        gather.silent_initverify()
        gather.error_check()

    namespace = gather.namespace
    state["logger"].info(f"Namespace: {namespace}")

    # Zip up previous propertyFile if it exists
    # Remove the propertyFile folder
    if os.path.exists(os.path.join(os.getcwd(), "propertyFile", namespace)):
        if not os.path.exists(os.path.join(os.getcwd(), "backups")):
            os.mkdir(os.path.join(os.getcwd(), "backups"))
        now = datetime.now()
        dt_string = now.strftime("%Y-%m-%d_%H-%M")
        zip_folder(os.path.join(os.getcwd(), "backups", f"propertyFile_{namespace}_{dt_string}"),
                   os.path.join(os.getcwd(), "propertyFile", namespace))
        shutil.rmtree(os.path.join(os.getcwd(), "propertyFile", namespace))

    # function call to create property files
    property_obj = p.Property(gather, os.getcwd(), state["logger"], console)
    
    # Pre-populate AI Services properties to add LWE SSL folders to ssl_directory_list
    # This must happen BEFORE create_property_structure() so SSL folders are created
    aiservices_properties = None
    aiservices_integration_properties = None
    if gather.has_ai_services_operator():
        aiservices_properties = property_obj.populate_aiservices_propertyfile()
        aiservices_integration_properties = property_obj.populate_aiservices_integration_propertyfile()
    
    property_obj.create_property_structure()
    
    # Note: GraphQL certificate download from migrated FNCMCluster CR is skipped in gather mode
    # Certificate download requires Kubernetes connectivity, which is only available in validate mode
    # Users should manually add certificates to propertyFile/{namespace}/ssl-certs/graphql/ if needed
    if gather.fncm_migration_settings:
        migration_settings = gather.fncm_migration_settings
        if migration_settings.get('graphql_root_ca_secret'):
            root_ca_secret = migration_settings['graphql_root_ca_secret']
            namespace = gather.namespace
            ssl_folder = os.path.join(os.getcwd(), "propertyFile", namespace, "ssl-certs", "graphql")
            
            state["logger"].info(f"GraphQL certificate from secret '{root_ca_secret}' detected in migration settings")
            print(f"\n[yellow]ℹ GraphQL SSL Certificate Required[/yellow]")
            print(f"[white]  Secret Name: {root_ca_secret}[/white]")
            print(f"[white]  Target Location: propertyFile/{namespace}/ssl-certs/graphql/[/white]")
            print(f"[dim]  Note: Certificate download requires Kubernetes connectivity (available in validate mode)[/dim]")
            print(f"[dim]  Please manually add the certificate to the target location before running generate mode[/dim]")

    # Only create database property file if Content operator is selected
    if gather.has_content_operator():
        db_properties = property_obj.populate_db_propertyfile()
        if move_db:
            db_properties = property_obj.move_database(os.path.abspath(move), move_dict, db_properties)
        property_obj.create_db_propertyfile(db_properties)

    # Only create LDAP property file if Content operator is selected
    # AI Services alone only needs IDP, not LDAP
    if gather.has_content_operator() and gather.auth_type in ("LDAP", "LDAP_IDP"):
        ldap_properties = property_obj.populate_ldap_propertyfile()
        if move_ldap:
            ldap_properties = property_obj.move_ldap(os.path.abspath(move), move_dict, ldap_properties)
        property_obj.create_ldap_propertyfile(ldap_properties)

    if gather.auth_type in ("LDAP_IDP", "SCIM_IDP"):
        idp_properties = property_obj.populate_idp_propertyfile()
        property_obj.create_idp_propertyfile(idp_properties)

    if gather.auth_type in ("SCIM_IDP"):
        scim_properties = property_obj.populate_scim_propertyfile()
        property_obj.create_scim_propertyfile(scim_properties)

    # Create ingress property file if:
    # 1. User selected ingress during gather, OR
    # 2. Ingress settings were migrated from Content CR (AI Services only scenario)
    # Note: Only create ingress TOML for CNCF/other platforms, not OCP (which uses Routes)
    should_create_ingress = False
    
    if gather.ingress:
        # User explicitly selected ingress during gather
        should_create_ingress = True
    elif gather.fncm_migration_settings and gather.fncm_migration_settings.get('ingress_enabled') is not None:
        # Ingress settings were migrated from Content CR
        # Only create ingress TOML if platform is CNCF or "other", not OCP
        migrated_platform = gather.fncm_migration_settings.get('platform', '').upper()
        if migrated_platform in ('CNCF', 'OTHER'):
            should_create_ingress = True
            state["logger"].info(f"Creating ingress TOML for migrated settings on {migrated_platform} platform")
        else:
            state["logger"].info(f"Skipping ingress TOML creation for {migrated_platform} platform (uses Routes)")
    
    if should_create_ingress:
        # If we have migrated settings, update the ingress properties before creating the file
        if gather.fncm_migration_settings and gather.fncm_migration_settings.get('ingress_enabled') is not None:
            migration_settings = gather.fncm_migration_settings
            ingress_enabled = migration_settings.get('ingress_enabled', False)
            
            # Update the ingress properties with migrated values
            property_obj._ingress_properties['INGRESS_ENABLED']['value'] = ingress_enabled
            
            # Migrate hostname if available
            ingress_hostname = migration_settings.get('ingress_hostname')
            if ingress_hostname:
                property_obj._ingress_properties['INGRESS_HOSTNAME']['value'] = ingress_hostname
                state["logger"].info(f"Migrated ingress hostname: {ingress_hostname}")
            
            # Migrate TLS secret if available
            ingress_tls_secret = migration_settings.get('ingress_tls_secret')
            if ingress_tls_secret:
                property_obj._ingress_properties['INGRESS_TLS_SECRET_NAME']['value'] = ingress_tls_secret
                property_obj._ingress_properties['INGRESS_TLS_ENABLED']['value'] = True
                state["logger"].info(f"Migrated ingress TLS secret: {ingress_tls_secret}")
            
            # Migrate annotations if available
            # Annotations from CR are in "key: value" format and will be written as triple-quoted strings by TOML library
            ingress_annotations = migration_settings.get('ingress_annotations')
            if ingress_annotations and isinstance(ingress_annotations, list):
                # Pass annotations directly - TOML library will handle triple-quote formatting
                property_obj._ingress_properties['INGRESS_ANNOTATIONS']['value'] = ingress_annotations
                state["logger"].info(f"Migrated {len(ingress_annotations)} ingress annotations")
            
            # Migrate service type if available
            service_type = migration_settings.get('service_type')
            if service_type:
                property_obj._ingress_properties['SERVICE_TYPE']['value'] = service_type
                state["logger"].info(f"Migrated service type: {service_type}")
            
            state["logger"].info(f"Using migrated ingress settings from Content CR: INGRESS_ENABLED={ingress_enabled}")
            print(f"\n[green]✓ Using ingress configuration from Content deployment[/green]")
            print(f"[dim]  Ingress Enabled: {ingress_enabled}[/dim]")
            print(f"[dim]  Source: {migration_settings.get('ingress_source', 'Content CR')}[/dim]")
            if ingress_hostname:
                print(f"[dim]  Hostname: {ingress_hostname}[/dim]")
            if ingress_tls_secret:
                print(f"[dim]  TLS Secret: {ingress_tls_secret}[/dim]")
            if ingress_annotations:
                print(f"[dim]  Annotations: {len(ingress_annotations)} annotation(s)[/dim]")
            if service_type:
                print(f"[dim]  Service Type: {service_type}[/dim]")
        
        property_obj.create_ingress_propertyfile()
    property_obj.create_deployment_propertyfile()

    # Only create user/group property file if Content operator is selected
    if gather.has_content_operator():
        property_obj.create_user_group_propertyfile()

    # this is a property file generated for custom properties such as sendmail, icc , task manager groups etc
    if gather.sendmail_support or gather.icc_support or gather.tm_custom_groups:
        property_obj.create_custom_component_propertyfile()
    
    # Create AI Services property files if AI Services operator is selected
    # Properties were already populated earlier to ensure SSL folders are created
    if gather.has_ai_services_operator() and aiservices_properties is not None:
        property_obj.create_aiservices_propertyfile(aiservices_properties)
        property_obj.create_aiservices_integration_propertyfile(aiservices_integration_properties)

    # Generate README documentation for property files
    try:
        state["logger"].info("Generating property file documentation")
        property_readme_generator = GeneratePropertyReadme(
            namespace=namespace,
            property_folder=property_obj.property_folder,
            gather_obj=gather,
            logger=state["logger"]
        )
        
        if property_readme_generator.generate_readme():
            state["logger"].info("✓ Property file README generated successfully")
            print(f"\n[green]✓ Property file documentation generated: propertyFile/{namespace}/README.md[/green]")
        else:
            state["logger"].warning("⚠ Property file README generation failed")
            print(f"\n[yellow]⚠ Property file README generation failed[/yellow]")
    except Exception as e:
        state["logger"].error(f"Error generating property file README: {str(e)}")
        state["logger"].exception("Detailed error:")
        print(f"\n[yellow]⚠ Error generating property file README: {str(e)}[/yellow]")

    # Commented out the line below as it was removing error messages
    clear(console)
    layout = generate_gather_results(property_obj.property_folder,
                                     gather.to_dict(),
                                     move_db,
                                     move_ldap)

    print(layout)


@app.command()
def generate():
    """
    Generate the prerequisites for IBM Content Cortex Deployment.
    """

    if not state["silent"]:
        # Display mode header with enhanced styling
        print()
        header_text = Text()
        header_text.append("🔧 ", style="bold yellow")
        header_text.append("Generate Mode", style="bold cyan")
        header_text.append(" - Create Kubernetes Artifacts", style="white")
        
        print(Panel(
            header_text,
            title="[bold white]IBM Content Cortex Prerequisites[/bold white]",
            border_style="cyan",
            padding=(1, 2)
        ))
        print()
        
        # Display what will be generated
        info_text = Text()
        info_text.append("This mode will generate:\n\n", style="bold white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Kubernetes Secrets (database, LDAP, IDP, SCIM)\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("SQL Scripts (GCD, Object Stores, Navigator)\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Custom Resource (CR) YAML files\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("AI Services artifacts (if configured)\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Usage metering metrics (CPE, GraphQL, CMIS)\n", style="white")
        
        print(Panel(
            info_text,
            title="[bold white]Generated Artifacts[/bold white]",
            border_style="green",
            padding=(1, 2)
        ))
        print()
        
        # this is the user details object
        deploy1 = g.GatherPrereqOptions(logger=state["logger"], console=console)
        # Set script_type to 'generate' to skip namespace existence check
        deploy1._script_type = 'generate'
        deploy1.collect_namespace()
    else:
        deploy1 = sg.SilentGatherPrereqOptions(logger=state["logger"],
                                               envfile_path=os.path.join("silent_config", "silent_install_prerequisites.toml"))
        # Individual components loaded:
        deploy1.silent_version(state["version_data"])
        deploy1.silent_namespace()

    namespace = deploy1.namespace
    state["logger"].info(f"Namespace: {namespace}")


    # Loading property folder locations
    prop_folder = os.path.join(os.getcwd(), "propertyFile", namespace)

    if not os.path.exists(prop_folder):
        state["logger"].info("Property files are missing. Please run the gather command first.")
        print()
        print(Panel.fit(Text(f"Property files are missing for namespace: {namespace}.\n\n"
                             "Please run the python3 prerequisites.py gather command first."), style="bold red"))
        raise typer.Exit()

    ssl_cert_folder = os.path.join(os.getcwd(), "propertyFile", namespace, "ssl-certs")
    trusted_certs_folder = os.path.join(os.getcwd(), "propertyFile", namespace, "ssl-certs", "trusted-certs")
    icc_folder = os.path.join(os.getcwd(), "propertyFile", namespace, "icc")

    # Loading generated folder location
    generated_folder = os.path.join(os.getcwd(), "generatedFiles", namespace)

    # Loading property files locations
    db_prop_file = os.path.join(prop_folder, "content_db_server.toml")
    ldap_prop_file = os.path.join(prop_folder, "content_ldap_server.toml")
    idp_prop_file = os.path.join(prop_folder, "ccx-identity_provider.toml")
    usergroup_prop_file = os.path.join(prop_folder, "content_user_group.toml")
    deployment_prop_file = os.path.join(prop_folder, "ccx-deployment.toml")
    ingress_prop_file = os.path.join(prop_folder, "ccx-ingress.toml")
    customcomponent_prop_file = os.path.join(prop_folder, "content_components_options.toml")
    scim_prop_file = os.path.join(prop_folder, "content_scim_server.toml")
    aiservices_prop_file = os.path.join(prop_folder, "aiservices_providers.toml")

    # Set defaults for property files
    db_prop = None
    aiservices_prop = None
    aiservices_integration_prop = None
    ldap_prop = None
    idp_prop = None
    usergroup_prop = None
    deployment_prop = None
    ingress_prop = None
    customcomponent_prop = None
    scim_prop = None

    try:
        # Load property files if they exist
        if os.path.exists(db_prop_file):
            db_prop = ReadPropDb(os.path.join(prop_folder, "content_db_server.toml"), state["logger"])

        if os.path.exists(ldap_prop_file):
            ldap_prop = ReadPropLdap(os.path.join(prop_folder, "content_ldap_server.toml"), state["logger"])

        if os.path.exists(idp_prop_file):
            idp_prop = ReadPropIdp(os.path.join(prop_folder, "ccx-identity_provider.toml"), state["logger"])

        if os.path.exists(usergroup_prop_file):
            usergroup_prop = ReadPropUsergroup(os.path.join(prop_folder, "content_user_group.toml"), state["logger"])

        if os.path.exists(deployment_prop_file):
            deployment_prop = ReadPropDeployment(os.path.join(prop_folder, "ccx-deployment.toml"), state["logger"])

        if os.path.exists(ingress_prop_file):
            ingress_prop = ReadPropIngress(os.path.join(prop_folder, "ccx-ingress.toml"), state["logger"])

        if os.path.exists(customcomponent_prop_file):
            customcomponent_prop = ReadPropCustomComponent(os.path.join(prop_folder, "content_components_options.toml"),
                                                           state["logger"])
        if os.path.exists(scim_prop_file):
            scim_prop = ReadPropSCIM(os.path.join(prop_folder, "content_scim_server.toml"), state["logger"])
        
        if os.path.exists(aiservices_prop_file):
            aiservices_prop = ReadPropAIServices(os.path.join(prop_folder, "aiservices_providers.toml"), state["logger"])
        
        # Read AI Services Integration property file if it exists
        aiservices_integration_prop_file = os.path.join(prop_folder, "aiservices_integration.toml")
        if os.path.exists(aiservices_integration_prop_file):
            from helper_scripts.property.read_prop import ReadPropAIServicesIntegration
            aiservices_integration_prop = ReadPropAIServicesIntegration(aiservices_integration_prop_file, state["logger"])

        # Create dictionaries for property files if not None
        if db_prop:
            db_prop_dict = db_prop.to_dict()
        else:
            db_prop_dict = {}

        if scim_prop:
            scim_prop_dict = scim_prop.to_dict()
        else:
            scim_prop_dict = {}

        if ldap_prop:
            ldap_prop_dict = ldap_prop.to_dict()
        else:
            ldap_prop_dict = {}

        if idp_prop:
            idp_prop_dict = idp_prop.to_dict()
        else:
            idp_prop_dict = {}

        if usergroup_prop:
            usergroup_prop_dict = usergroup_prop.to_dict()
        else:
            usergroup_prop_dict = {}

        if deployment_prop:
            deployment_prop_dict = deployment_prop.to_dict()
        else:
            deployment_prop_dict = {}

        if ingress_prop:
            ingress_prop_dict = ingress_prop.to_dict()
        else:
            ingress_prop_dict = {}

        if customcomponent_prop:
            customcomponent_prop_dict = customcomponent_prop.to_dict()
        else:
            customcomponent_prop_dict = {}
        
        if aiservices_prop:
            aiservices_prop_dict = aiservices_prop.to_dict()
        else:
            aiservices_prop_dict = {}
        
        if aiservices_integration_prop:
            aiservices_integration_prop_dict = aiservices_integration_prop.to_dict()
        else:
            aiservices_integration_prop_dict = {}

    except TomlDecodeError:
        state["logger"].exception(
            f"Exception when reading Property Files\n"
            f"Please Review your Property files for missing quotes and formatting.\n\n")
        exit(1)
    except Exception as e:
        state["logger"].exception(
        f"Exception when reading Property Files\n"
        f"Please Review your Property files for missing quotes and formatting.\n\n")
        exit(1)

    # Only run database-related validations if database properties exist (Content operator deployed)
    incorrect_naming_convention = []
    invalid_db_password_list = []
    correct_ssl_mode = True
    
    if db_prop_dict:
        incorrect_naming_convention = check_dbname(db_prop_dict)
        invalid_db_password_list = check_db_password_length(db_prop_dict, deployment_prop_dict)
        correct_ssl_mode = check_db_ssl_mode(db_prop_dict, deployment_prop_dict)
    
    # Check if SSL certificates are present and correct format
    # Only pass db_prop and ldap_prop if they exist (Content operator deployed)
    missing_certs, incorrect_certs = check_ssl_folders(db_prop=db_prop_dict if db_prop_dict else None,
                                                       ldap_prop=ldap_prop_dict if ldap_prop_dict else None,
                                                       ssl_cert_folder=ssl_cert_folder,
                                                       deploy_prop=deployment_prop_dict,
                                                       idp_prop=idp_prop_dict,
                                                       scim_prop=scim_prop_dict,
                                                       graphql_prop=aiservices_integration_prop_dict if aiservices_integration_prop_dict else None,
                                                       aiservices_prop=aiservices_prop_dict if aiservices_prop_dict else None)
    masterkey_present = check_icc_masterkey(customcomponent_prop_dict, icc_folder)
    trusted_certs_present, invalid_trusted_certs = check_trusted_certs(trusted_certs_folder)

    ban_present = bool(deployment_prop_dict.get("BAN", False))
    cpe_present = bool(deployment_prop_dict.get("CPE", False))
    content_generation_enabled = bool(db_prop_dict and (ban_present or cpe_present))
    keystore_password_valid = True
    if content_generation_enabled and usergroup_prop_dict:
        keystore_password_valid = check_keystore_password_length(usergroup_prop_dict, deployment_prop_dict)

    cert_failed = len(missing_certs) > 0 or len(incorrect_certs) > 0 or (
            trusted_certs_present and len(invalid_trusted_certs) > 0)

    incorrect_entries = len(incorrect_naming_convention) > 0

    # Use unified validation display for ALL issues
    unified_display = UnifiedValidationDisplay(console)
    
    # Add property validation errors - only for properties that exist
    # Content-specific properties (only validate if db_prop exists, indicating Content deployment)
    if db_prop:
        unified_display.add_property_validation_errors(db_prop, "Database")
    if ldap_prop:
        unified_display.add_property_validation_errors(ldap_prop, "LDAP")
    if usergroup_prop:
        unified_display.add_property_validation_errors(usergroup_prop, "User Groups")
    if customcomponent_prop:
        unified_display.add_property_validation_errors(customcomponent_prop, "Custom Components")
    
    # Common properties (validate for both AI Services and Content)
    if idp_prop:
        unified_display.add_property_validation_errors(idp_prop, "Identity Provider")
    if scim_prop:
        unified_display.add_property_validation_errors(scim_prop, "SCIM")
    if deployment_prop:
        unified_display.add_property_validation_errors(deployment_prop, "Deployment")
    if ingress_prop:
        unified_display.add_property_validation_errors(ingress_prop, "Ingress")
    
    # AI Services properties (validate when AI Services is deployed)
    if aiservices_prop:
        # Validate single default model across all enabled providers
        is_valid, message = aiservices_prop.validate_single_default_model()
        if not is_valid:
            # Add the validation error directly to unified display
            unified_display.has_errors = True
            unified_display.issues.append({
                'category': 'Property Validation',
                'type': 'AI Services',
                'severity': 'high',
                'field': 'DEFAULT_MODEL',
                'message': message,
                'location': 'AI Services → Default Model Configuration',
                'file': 'aiservices_providers.toml',
                'remediation': {
                    'error': 'Invalid default model configuration',
                    'fix': 'Ensure exactly ONE model across all enabled providers has DEFAULT=true',
                    'example': '# In aiservices_providers.toml:\n'
                              '[PROVIDER_1.models]\n'
                              '[[PROVIDER_1.models]]\n'
                              'MODEL = "ibm/granite-13b-chat-v2"\n'
                              'DEFAULT = "true"  # Only ONE model should have this\n'
                              'ENABLED = "true"'
                }
            })
        
        # Validate SSL certificates for enabled LWE providers
        ssl_valid, ssl_errors = aiservices_prop.validate_lwe_ssl_certificates(ssl_cert_folder)
        if not ssl_valid:
            unified_display.has_errors = True
            for error_msg in ssl_errors:
                # Parse the error message to extract provider and details
                lines = error_msg.split('\n')
                provider_line = lines[0] if lines else error_msg
                provider_match = provider_line.split(']')[0].replace('[', '') if ']' in provider_line else 'UNKNOWN'
                
                unified_display.issues.append({
                    'category': 'SSL Certificates',
                    'type': 'AI Services LWE Provider',
                    'severity': 'high',
                    'field': provider_match,
                    'message': error_msg,
                    'location': f'AI Services → {provider_match} → SSL Certificate',
                    'file': 'ssl-certs/',
                    'remediation': {
                        'error': 'Missing SSL certificate for LWE provider',
                        'fix': 'Add SSL certificate files to the provider\'s SSL folder',
                        'example': '# Obtain the SSL certificate from your WatsonX LWE deployment\n'
                                  '# Copy certificate files (.pem, .crt, .cer) to the provider\'s SSL folder\n'
                                  '# Example: ./propertyFile/<namespace>/ssl-certs/ai-provider-<provider_id>/'
                    }
                })
        
        unified_display.add_property_validation_errors(aiservices_prop, "AI Services")
    if aiservices_integration_prop:
        unified_display.add_property_validation_errors(aiservices_integration_prop, "AI Services Integration")
    
    # Add certificate issues
    unified_display.add_certificate_issues(missing_certs, incorrect_certs)
    
    # Add other validation issues - only for Content deployments
    if db_prop:
        unified_display.add_masterkey_issue(masterkey_present)
        fips_support = deployment_prop.to_dict().get("FIPS_SUPPORT", False) if deployment_prop else False
        unified_display.add_keystore_password_issue(keystore_password_valid, fips_support)
        unified_display.add_database_password_issues(invalid_db_password_list)
        unified_display.add_ssl_mode_issue(correct_ssl_mode)
        unified_display.add_naming_convention_issues(incorrect_naming_convention)
    
    # Display all issues in unified UI
    if unified_display.display():
        exit(1)
    else:
        # creating folder structure for generate folder
        if os.path.exists(generated_folder):
            if not os.path.exists(os.path.join(os.getcwd(), "backups")):
                os.mkdir(os.path.join(os.getcwd(), "backups"))
            now = datetime.now()
            dt_string = now.strftime("%Y-%m-%d_%H-%M")
            zip_folder(os.path.join(os.getcwd(), "backups", f"generatedFiles_{namespace}_{dt_string}"),
                       os.path.join(os.getcwd(), "generatedFiles", namespace))
            shutil.rmtree(generated_folder)
        # Extract vault_enabled from deployment properties
        vault_enabled = deployment_prop.to_dict().get('VAULT_ENABLED', False) if deployment_prop else False
        state["logger"].info(f"Vault enabled: {vault_enabled}")
        state["logger"].info(f"Creating folder structure with vault_enabled={vault_enabled}")
        create_generate_folder(trusted_certs_present, namespace=namespace, create_metrics=content_generation_enabled, vault_enabled=vault_enabled)


        if content_generation_enabled:
            console.print("\n[bold cyan]Generating Content Kubernetes Artifacts...[/bold cyan]\n")
            generate_secrets = GenerateSecrets(db_properties=db_prop_dict,
                                               ldap_properties=ldap_prop_dict,
                                               idp_properties=idp_prop_dict,
                                               usergroup_properties=usergroup_prop_dict,
                                               customcomponent_properties=customcomponent_prop_dict,
                                               scim_properties=scim_prop_dict,
                                               deployment_properties=deployment_prop_dict,
                                               logger=state["logger"], namespace=namespace)

            # Checking for IER / ICCSAP.
            if "IER" in deployment_prop_dict.keys():
                if deployment_prop_dict["IER"]:
                    generate_secrets.create_ier_secret()

            if "ICCSAP" in deployment_prop_dict.keys():
                if deployment_prop_dict["ICCSAP"]:
                    generate_secrets.create_iccsap_secret()

            if ban_present:
                generate_secrets.create_ban_secret()
            if ldap_prop:
                generate_secrets.create_ldap_secret()
                generate_secrets.create_ldap_ssl_secrets()
            if idp_prop:
                generate_secrets.create_idp_secret()
                generate_secrets.create_idp_ssl_secrets()
                generate_secrets.create_idp_public_key_secret()

            if scim_prop:
                generate_secrets.create_scim_secret()
                generate_secrets.create_scim_ssl_secrets()

            # if icc for email set up is supported, then we create icc related secrets
            if customcomponent_prop_dict:
                if "ICC" in customcomponent_prop_dict.keys():
                    generate_secrets.create_icc_secrets()
            if cpe_present:
                generate_secrets.create_fncm_secret()

            if db_prop and db_prop_dict["DATABASE_SSL_ENABLE"]:
                generate_secrets.create_ssl_db_secrets()

            if trusted_certs_present:
                generate_secrets.create_trusted_secrets()

            generate_sql = GenerateSql(db_prop_dict, state["logger"], namespace=namespace)
            if cpe_present:
                generate_sql.create_gcd()
                generate_sql.create_os()
            if ban_present:
                generate_sql.create_icn()

            # generate CR
            cr = GenerateCR(db_properties=db_prop_dict,
                            ldap_properties=ldap_prop_dict,
                            usergroup_properties=usergroup_prop_dict,
                            deployment_properties=deployment_prop_dict,
                            ingress_properties=ingress_prop_dict,
                            customcomponent_properties=customcomponent_prop_dict,
                            idp_properties=idp_prop_dict,
                            scim_properties=scim_prop_dict,
                            logger=state["logger"], namespace=namespace)

            cr.generate_cr()

        # Generate AI Services artifacts if AI Services properties are present
        if aiservices_prop and aiservices_prop_dict:
            state["logger"].info("Generating AI Services artifacts (CR, Secrets, ConfigMap)")
            try:
                ai_services_generator = GenerateAIServices(
                    aiservices_properties=aiservices_prop_dict,
                    deployment_properties=deployment_prop_dict,
                    idp_properties=idp_prop_dict,
                    db_properties=db_prop_dict,
                    aiservices_integration_properties=aiservices_integration_prop_dict,
                    ingress_properties=ingress_prop_dict,
                    egress_properties={},  # Egress is derived from deployment_properties
                    namespace=namespace,
                    logger=state["logger"],
                    console=console
                )
                
                # Generate all AI Services artifacts
                if ai_services_generator.generate_all():
                    state["logger"].info("AI Services artifacts generated successfully")
                else:
                    state["logger"].warning("Some AI Services artifacts failed to generate")
            except Exception as e:
                state["logger"].error(f"Error generating AI Services artifacts: {str(e)}")
                state["logger"].exception("Detailed error:")

        # Generate usage metering metrics for deployed Content Operator components only
        # Check if any Content Operator components (CPE, GRAPHQL, CMIS) are deployed
        if deployment_prop and deployment_prop_dict:
            content_components_deployed = any([
                deployment_prop_dict.get("CPE", False),
                deployment_prop_dict.get("GRAPHQL", False),
                deployment_prop_dict.get("CMIS", False)
            ])
            
            if content_components_deployed:
                state["logger"].info("Generating usage metering metrics for deployed components")
                try:
                    metrics_generator = GenerateMetrics(
                        deployment_properties=deployment_prop_dict,
                        namespace=namespace,
                        logger=state["logger"]
                    )
                    
                    # Generate metrics for all applicable components
                    if metrics_generator.generate_all_metrics():
                        state["logger"].info("Usage metering metrics generated successfully")
                    else:
                        state["logger"].warning("Some metrics failed to generate")
                except Exception as e:
                    state["logger"].error(f"Error generating metrics: {str(e)}")
                    state["logger"].exception("Detailed error:")
            else:
                state["logger"].info("No Content Operator components deployed, skipping metrics generation")

        # Generate README files for all generated artifacts
        state["logger"].info("Generating README files for generated artifacts")
        try:
            from helper_scripts.generate.generate_readme import GenerateReadme
            
            readme_generator = GenerateReadme(
                namespace=namespace,
                deployment_properties=deployment_prop_dict,
                db_properties=db_prop_dict,
                logger=state["logger"]
            )
            
            # Generate all README files
            if readme_generator.generate_all_readmes():
                state["logger"].info("✓ README files generated successfully")
            else:
                state["logger"].warning("⚠ Some README files failed to generate")
        except Exception as e:
            state["logger"].error(f"Error generating README files: {str(e)}")
            state["logger"].exception("Detailed error:")

    # Display overall generation summary (includes all files: Content Operator + AI Services + Metrics)
    generate_generate_results(generated_folder)


@app.command()
def validate(
        apply: bool = typer.Option(False, help="Apply all generated artifacts to the cluster"),
        skip_storage_class: bool = typer.Option(False, "--skip-storageclass", "-sc", help="Skip storage class validation"),
        skip_database: bool = typer.Option(False, "--skip-database", "-db", help="Skip database validation"),
        skip_ldap: bool = typer.Option(False, "--skip-ldap", "-l", help="Skip LDAP validation"),
        skip_idp: bool = typer.Option(False, "--skip-idp", "-idp", help="Skip IDP validation"),
        skip_scim: bool = typer.Option(False, "--skip-scim", "-scim", help="Skip SCIM validation"),
        skip_ai_services: bool = typer.Option(False, "--skip-ai-services", "-ai", help="Skip AI Services validation"),
        pvc_size: str = typer.Option('10Mi', "--pvc-size", "-pvc", help="Set size for sample persitant volume validation"),
):
    """
    Validate the prerequisites for IBM Content Cortex Deployment.
    """

    # By default, all validations are executed
    validate_storage_class = not skip_storage_class
    validate_database = not skip_database
    validate_ldap = not skip_ldap
    validate_idp = not skip_idp
    validate_scim = not skip_scim
    validate_ai_services = not skip_ai_services

    if not state["silent"]:
        # Display mode header with enhanced styling
        print()
        header_text = Text()
        header_text.append("✓ ", style="bold green")
        header_text.append("Validate Mode", style="bold cyan")
        header_text.append(" - Test Prerequisites", style="white")
        
        print(Panel(
            header_text,
            title="[bold white]IBM Content Cortex Prerequisites[/bold white]",
            border_style="cyan",
            padding=(1, 2)
        ))
        print()
        
        # Display what will be validated
        info_text = Text()
        info_text.append("This mode will validate:\n\n", style="bold white")
        
        if validate_storage_class:
            info_text.append("  ✓ ", style="bold green")
            info_text.append("Storage Classes\n", style="white")
        else:
            info_text.append("  ⊘ ", style="bold yellow")
            info_text.append("Storage Classes (skipped)\n", style="dim")
            
        if validate_database:
            info_text.append("  ✓ ", style="bold green")
            info_text.append("Database Connectivity\n", style="white")
        else:
            info_text.append("  ⊘ ", style="bold yellow")
            info_text.append("Database Connectivity (skipped)\n", style="dim")
            
        if validate_ldap:
            info_text.append("  ✓ ", style="bold green")
            info_text.append("LDAP Connectivity & Users/Groups\n", style="white")
        else:
            info_text.append("  ⊘ ", style="bold yellow")
            info_text.append("LDAP Connectivity (skipped)\n", style="dim")
            
        if validate_idp:
            info_text.append("  ✓ ", style="bold green")
            info_text.append("Identity Provider (IDP)\n", style="white")
        else:
            info_text.append("  ⊘ ", style="bold yellow")
            info_text.append("Identity Provider (skipped)\n", style="dim")
            
        if validate_scim:
            info_text.append("  ✓ ", style="bold green")
            info_text.append("SCIM Configuration\n", style="white")
        else:
            info_text.append("  ⊘ ", style="bold yellow")
            info_text.append("SCIM Configuration (skipped)\n", style="dim")
            
        if validate_ai_services:
            info_text.append("  ✓ ", style="bold green")
            info_text.append("AI Services Configuration\n", style="white")
        else:
            info_text.append("  ⊘ ", style="bold yellow")
            info_text.append("AI Services Configuration (skipped)\n", style="dim")
        
        print(Panel(
            info_text,
            title="[bold white]Validation Scope[/bold white]",
            border_style="green",
            padding=(1, 2)
        ))
        print()

    # Create hint text with rich styling
    hint_text = Text()
    hint_text.append("- Run the validation from the IBM Content Cortex Operator\n", style="white")
    hint_text.append("- All tools and libraries are installed\n", style="white")
    hint_text.append("- Validation from within the your cluster can test private connections\n", style="white")
    hint_text.append("- See the below command to copy the folder and run the validation.", style="white")
    
    hint_panel = Panel(
        hint_text,
        title="[bold white]Hint[/bold white]",
        border_style="white",
        padding=(1, 2)
    )

    # Create command panel with syntax highlighting
    command_panel = Panel(
        Syntax(
            "cd ..\n"
            "export OPERATOR=$(kubectl get pods -l 'name=ibm-fncm-operator' | awk 'NR>1 {print $1}')\n"
            "kubectl cp scripts  $OPERATOR:/opt/ansible\n"
            "kubectl exec -it $OPERATOR -- bash\n"
            "cd /opt/ansible/scripts\n"
            "python3 prerequisites.py validate",
            "bash",
            theme="monokai",
            line_numbers=False,
            word_wrap=True
        ),
        title="[bold white]Command[/bold white]",
        border_style="white",
        padding=(1, 2)
    )

    # Display operator panel with columns
    operator_panel = Panel(
        Columns([hint_panel, command_panel], align="left", equal=True),
        title="[bold white]IBM Content Cortex Operator[/bold white]",
        border_style="cyan",
        padding=(0, 1)
    )
    print(operator_panel)
    print()

    if not state["silent"]:
        # this is the user details object
        # Validate mode requires Kubernetes connection
        gather = g.GatherPrereqOptions(state["logger"], console, require_k8s_connection=True)
        gather.collect_namespace()
    else:
        gather = sg.SilentGatherPrereqOptions(state["logger"],
                                              os.path.join("silent_config", "silent_install_prerequisites.toml"))
        # Individual components loaded:
        gather.silent_version(state["version_data"])
        gather.silent_namespace()

    namespace = gather.namespace
    state["logger"].info(f"Namespace: {namespace}")

    # Loading property folder locations
    prop_folder = os.path.join(os.getcwd(), "propertyFile", namespace)

    if not os.path.exists(prop_folder):
        state["logger"].info("Property files are missing. Please run the gather command first.")
        print()
        print(Panel.fit(Text(f"Property files are missing for namespace: {namespace}.\n\n"
                             "Please run the python3 prerequisites.py gather command first."), style="bold red"))
        raise typer.Exit()
    
    # Validate passed pvc_size 
    # Write a regex match for pvc_size 
    pvc_pattern = re.compile(r'^[0-9]+(mi|gi)$')
    if not re.match(pvc_pattern, pvc_size.lower()):
        print(Panel.fit(Text("Invalid pvc_size.\n"
                             "Size needs to be either ending in Mi or Gi"), style="bold red"))
        state["logger"].info("The passed pvc_size is not valid. Size needs to be either ending in Mi or Gi")
        raise typer.Exit()

    ssl_cert_folder = os.path.join(os.getcwd(), "propertyFile", namespace, "ssl-certs")
    trusted_certs_folder = os.path.join(os.getcwd(), "propertyFile", namespace, "ssl-certs", "trusted-certs")
    icc_folder = os.path.join(os.getcwd(), "propertyFile", "icc")

    # Loading generated folder location
    generated_folder = os.path.join(os.getcwd(), "generatedFiles", namespace)

    # Loading property files locations
    db_prop_file = os.path.join(prop_folder, "content_db_server.toml")
    ldap_prop_file = os.path.join(prop_folder, "content_ldap_server.toml")
    idp_prop_file = os.path.join(prop_folder, "ccx-identity_provider.toml")
    scim_prop_file = os.path.join(prop_folder, "content_scim_server.toml")
    usergroup_prop_file = os.path.join(prop_folder, "content_user_group.toml")
    deployment_prop_file = os.path.join(prop_folder, "ccx-deployment.toml")
    ingress_prop_file = os.path.join(prop_folder, "ccx-ingress.toml")
    customcomponent_prop_file = os.path.join(prop_folder, "content_components_options.toml")
    aiservices_prop_file = os.path.join(prop_folder, "aiservices_providers.toml")
    aiservices_integration_prop_file = os.path.join(prop_folder, "aiservices_integration.toml")

    # Set defaults for property files
    db_prop = None
    ldap_prop = None
    idp_prop = None
    scim_prop = None
    usergroup_prop = None
    deployment_prop = None
    ingress_prop = None
    customcomponent_prop = None
    aiservices_prop = None
    aiservices_integration_prop = None
    try:
        # Load property files if they exist
        if os.path.exists(db_prop_file):
            db_prop = ReadPropDb(os.path.join(prop_folder, "content_db_server.toml"), state["logger"])

        if os.path.exists(ldap_prop_file):
            ldap_prop = ReadPropLdap(os.path.join(prop_folder, "content_ldap_server.toml"), state["logger"])

        if os.path.exists(idp_prop_file):
            idp_prop = ReadPropIdp(os.path.join(prop_folder, "ccx-identity_provider.toml"), state["logger"])

        if os.path.exists(scim_prop_file):
            scim_prop = ReadPropSCIM(os.path.join(prop_folder, "content_scim_server.toml"), state["logger"])

        if os.path.exists(usergroup_prop_file):
            usergroup_prop = ReadPropUsergroup(os.path.join(prop_folder, "content_user_group.toml"), state["logger"])

        if os.path.exists(deployment_prop_file):
            deployment_prop = ReadPropDeployment(os.path.join(prop_folder, "ccx-deployment.toml"), state["logger"])

        if os.path.exists(ingress_prop_file):
            ingress_prop = ReadPropIngress(os.path.join(prop_folder, "ccx-ingress.toml"), state["logger"])

        if os.path.exists(customcomponent_prop_file):
            customcomponent_prop = ReadPropCustomComponent(os.path.join(prop_folder, "content_components_options.toml"),
                                                           state["logger"])
        
        if os.path.exists(aiservices_prop_file):
            aiservices_prop = ReadPropAIServices(
                os.path.join(prop_folder, "aiservices_providers.toml"),
                state["logger"],
                console=console,
                auto_display_errors=True
            )
        
        if os.path.exists(aiservices_integration_prop_file):
            from helper_scripts.property.read_prop import ReadPropAIServicesIntegration
            aiservices_integration_prop = ReadPropAIServicesIntegration(aiservices_integration_prop_file, state["logger"])

        # Create dictionaries for property files if not None
        if db_prop:
            db_prop_dict = db_prop.to_dict()
        else:
            db_prop_dict = {}

        if ldap_prop:
            ldap_prop_dict = ldap_prop.to_dict()
        else:
            ldap_prop_dict = {}

        if idp_prop:
            idp_prop_dict = idp_prop.to_dict()
        else:
            idp_prop_dict = {}

        if scim_prop:
            scim_prop_dict = scim_prop.to_dict()
        else:
            scim_prop_dict = {}

        if usergroup_prop:
            usergroup_prop_dict = usergroup_prop.to_dict()
        else:
            usergroup_prop_dict = {}

        if deployment_prop:
            deployment_prop_dict = deployment_prop.to_dict()
        else:
            deployment_prop_dict = {}

        if ingress_prop:
            ingress_prop_dict = ingress_prop.to_dict()
        else:
            ingress_prop_dict = {}

        if customcomponent_prop:
            customcomponent_prop_dict = customcomponent_prop.to_dict()
        else:
            customcomponent_prop_dict = {}
        
        if aiservices_integration_prop:
            aiservices_integration_prop_dict = aiservices_integration_prop.to_dict()
        else:
            aiservices_integration_prop_dict = {}
        
        if aiservices_prop:
            aiservices_prop_dict = aiservices_prop.to_dict()
        else:
            aiservices_prop_dict = {}
    except TomlDecodeError:
        state["logger"].exception(
            f"Exception when reading Property Files\n"
            f"Please Review your Property files for missing quotes and formatting.\n\n")
        exit(1)
    except Exception as e:
        state["logger"].exception(
        f"Exception when reading Property Files\n"
        f"Please Review your Property files for missing quotes and formatting.\n\n")
        exit(1)



    vobject = v.Validate(state["logger"],
                         db_prop=db_prop_dict,
                         ldap_prop=ldap_prop_dict,
                         deploy_prop=deployment_prop_dict,
                         idp_prop=idp_prop_dict,
                         scim_prop=scim_prop_dict,
                         component_prop=customcomponent_prop_dict,
                         user_group_prop=usergroup_prop_dict, 
                         pvc_size=pvc_size,
                         namespace=namespace)

    db_number = 0

    if "CPE" in deployment_prop_dict.keys():
        if deployment_prop_dict["CPE"]:
            db_number += 1
            db_number += len(db_prop_dict["_os_ids"])

    if "BAN" in deployment_prop_dict.keys():
        if deployment_prop_dict["BAN"]:
            db_number += 1

    storageclass_number = len(vobject.get_unique_storageclass())

    # Check SSL certificates - only pass properties that exist (same as generate mode)
    missing_certs, incorrect_certs = check_ssl_folders(db_prop=db_prop_dict if db_prop_dict else None,
                                                       ldap_prop=ldap_prop_dict if ldap_prop_dict else None,
                                                       ssl_cert_folder=ssl_cert_folder,
                                                       deploy_prop=deployment_prop_dict,
                                                       idp_prop=idp_prop_dict,
                                                       scim_prop=scim_prop_dict,
                                                       graphql_prop=aiservices_integration_prop_dict if aiservices_integration_prop_dict else None,
                                                       aiservices_prop=aiservices_prop_dict if aiservices_prop_dict else None)
    # Check for validation errors - the new system displays errors automatically
    # Use unified validation display for ALL issues
    unified_display = UnifiedValidationDisplay(console)
    
    # Add property validation errors - only for properties that exist (same as generate mode)
    if db_prop:
        unified_display.add_property_validation_errors(db_prop, "Database")
    if ldap_prop:
        unified_display.add_property_validation_errors(ldap_prop, "LDAP")
    if idp_prop:
        unified_display.add_property_validation_errors(idp_prop, "Identity Provider")
    if scim_prop:
        unified_display.add_property_validation_errors(scim_prop, "SCIM")
    if aiservices_prop:
        unified_display.add_property_validation_errors(aiservices_prop, "AI Services")
    if aiservices_integration_prop:
        unified_display.add_property_validation_errors(aiservices_integration_prop, "AI Services Integration")
    if usergroup_prop:
        unified_display.add_property_validation_errors(usergroup_prop, "User Groups")
    if deployment_prop:
        unified_display.add_property_validation_errors(deployment_prop, "Deployment")
    if ingress_prop:
        unified_display.add_property_validation_errors(ingress_prop, "Ingress")
    if customcomponent_prop:
        unified_display.add_property_validation_errors(customcomponent_prop, "Custom Components")
    
    # Add certificate issues
    unified_display.add_certificate_issues(missing_certs, incorrect_certs)
    
    # Display all issues in unified UI
    if unified_display.display():
        exit(1)
    else:
        # Starting validation with enhanced UI
        print()
        validation_header = Text()
        validation_header.append("🔍 ", style="bold cyan")
        validation_header.append("Running Validation Tests", style="bold white")
        
        print(Panel(
            validation_header,
            border_style="cyan",
            padding=(1, 2)
        ))
        print()

        # Display FIPS warning if enabled
        if deployment_prop_dict.get("FIPS_SUPPORT", False):
            fips_warning = Text()
            fips_warning.append("🔒 ", style="bold purple")
            fips_warning.append("FIPS Mode Enabled", style="bold purple")
            fips_warning.append("\n\nValidating all connections with FIPS protocol.", style="white")
            fips_warning.append("\nThese tests will only pass on FIPS-enabled platforms.", style="dim")
            
            print(Panel(
                fips_warning,
                border_style="purple",
                padding=(1, 2)
            ))
            print()

        # Initialize ValidationDisplay with rich Live display
        display = ValidationDisplay(console)
        
        # Add all validation tests based on what's enabled
        if validate_storage_class:
            display.add_test(
                "storage",
                "Storage Classes",
                "Infrastructure",
                storageclass_number
            )
        
        if validate_database and db_number > 0:
            display.add_test(
                "database",
                "Database Connections",
                "Infrastructure",
                db_number
            )
        
        if validate_ldap and ldap_prop:
            ldap_count = len(ldap_prop_dict.get("_ldap_ids", []))
            display.add_test(
                "ldap",
                "LDAP Connectivity",
                "Directory Services",
                ldap_count
            )
            display.add_test(
                "ldap_users",
                "LDAP Users & Groups",
                "Directory Services",
                ldap_count
            )
        
        if validate_idp and idp_prop:
            display.add_test(
                "idp",
                "Identity Provider",
                "Authentication",
                1
            )
        
        if validate_scim and scim_prop:
            display.add_test(
                "scim",
                "SCIM Configuration",
                "User Management",
                1
            )
        
        if validate_ai_services and aiservices_prop:
            display.add_test(
                "ai_services",
                "AI Services Configuration",
                "AI Integration",
                1
            )
        
        # Start the live display
        with display:
            # Create truststore if needed
            if validate_database or validate_ldap:
                display.add_detail("Creating PKCS12 truststore for secure connections...")
                # Create a minimal progress adapter for truststore creation
                class TruststoreProgress:
                    def add_task(self, description, total=None):
                        return 0
                    def update(self, task_id, advance=None):
                        pass
                    def log(self, message=None):
                        # Handle Panel objects and extract text
                        if message is None:
                            return
                        if isinstance(message, Panel):
                            renderable = message.renderable
                            if isinstance(renderable, Text):
                                display.add_detail(renderable.plain)
                            elif isinstance(renderable, str):
                                display.add_detail(renderable)
                        elif isinstance(message, Text):
                            display.add_detail(message.plain)
                        elif isinstance(message, str):
                            display.add_detail(message)
                
                vobject.create_truststore(TruststoreProgress())
                display.add_detail("Truststore created successfully")
            
            # Run validations with live display updates
            try:
                # Validating storage classes
                if validate_storage_class:
                    display.start_test("storage")
                    display.add_detail("Checking storage class availability...")
                    success = vobject.validate_all_storage_classes_with_display(display)
                    display.complete_test("storage", success,
                        "All storage classes validated" if success else "Storage class validation failed")
                
                # Validating databases
                if validate_database and db_number > 0:
                    display.start_test("database")
                    display.add_detail("Testing database connectivity...")
                    success = vobject.validate_all_db_with_display(display)
                    display.complete_test("database", success,
                        "All database connections validated" if success else "Database validation failed")
                
                # Validating LDAP
                if validate_ldap and ldap_prop:
                    display.start_test("ldap")
                    display.add_detail("Testing LDAP server connectivity...")
                    ldaps_validated = vobject.validate_all_ldap_with_display(display)
                    display.complete_test("ldap", ldaps_validated,
                        "LDAP connectivity validated" if ldaps_validated else "LDAP validation failed")
                    
                    if ldaps_validated:
                        display.start_test("ldap_users")
                        display.add_detail("Validating LDAP users and groups...")
                        success = vobject.validate_ldap_users_groups_with_display(display)
                        display.complete_test("ldap_users", success,
                            "LDAP users and groups validated" if success else "User/group validation failed")
                    else:
                        display.skip_test("ldap_users", "Skipped due to LDAP connectivity failure")
                
                # Validating IDP
                if validate_idp and idp_prop:
                    display.start_test("idp")
                    display.add_detail("Testing identity provider configuration...")
                    success = vobject.validate_all_idps_with_display(display)
                    display.complete_test("idp", success,
                        "Identity provider validated" if success else "IDP validation failed")
                
                # Validating SCIM
                if validate_scim and scim_prop:
                    display.start_test("scim")
                    display.add_detail("Testing SCIM configuration...")
                    success = vobject.validate_scim_with_display(display)
                    display.complete_test("scim", success,
                        "SCIM configuration validated" if success else "SCIM validation failed")
                
                # Validating AI Services
                if validate_ai_services and aiservices_prop:
                    display.start_test("ai_services")
                    aiservices_prop_dict = aiservices_prop.to_dict()
                    
                    display.add_detail("Checking AI Services configuration...")
                    
                    # Validate single default model across all enabled providers
                    is_valid, message = aiservices_prop.validate_single_default_model()
                    if not is_valid:
                        display.complete_test("ai_services", False,
                            "Default model validation failed",
                            failure_reason=message,
                            remediation="1. Edit propertyFile/<namespace>/aiservices_providers.toml\n"
                                       "2. Ensure exactly ONE model across all enabled providers has DEFAULT=true\n"
                                       "3. Check that at least one provider has ENABLED=true\n"
                                       "4. Re-run validation: python3 prerequisites.py validate")
                    else:
                        # Only continue with further validation if default model check passed
                        display.add_detail(f"✓ {message}")
                        
                        # Get all enabled AI providers
                        enabled_providers = []
                        for key in aiservices_prop_dict.keys():
                            if key.startswith("AI_PROVIDER") or key.startswith("PROVIDER_"):
                                provider = aiservices_prop_dict[key]
                                # Only validate enabled providers
                                if provider.get("ENABLED", "false").lower() == "true":
                                    enabled_providers.append((key, provider))
                        
                        if not enabled_providers:
                            display.complete_test("ai_services", False,
                                "No enabled AI providers found",
                                failure_reason="No providers have ENABLED=true in aiservices_providers.toml",
                                remediation="1. Edit propertyFile/<namespace>/aiservices_providers.toml\n"
                                           "2. Set ENABLED=true for at least one provider\n"
                                           "3. Ensure the provider has all required fields configured\n"
                                           "4. Re-run validation: python3 prerequisites.py validate")
                        else:
                            # Validate all enabled providers
                            all_valid = True
                            for provider_key, provider_config in enabled_providers:
                                display.add_detail(f"\nValidating provider: {provider_key}")
                                
                                # Check provider URL
                                if "PROVIDER_URL" in provider_config:
                                    endpoint = provider_config["PROVIDER_URL"]
                                    display.add_detail(f"  Provider URL: {endpoint}")
                                
                                # Check provider type
                                provider_type = provider_config.get("PROVIDER_TYPE", "unknown")
                                display.add_detail(f"  Provider type: {provider_type}")
                                
                                # Validate credentials based on provider type
                                provider_valid = True
                                
                                # Check API_KEY (required for all provider types)
                                api_key_present = "API_KEY" in provider_config and provider_config["API_KEY"] and provider_config["API_KEY"] not in ["<Required>", ""]
                                if api_key_present:
                                    display.add_detail("  API key: ✓ Present")
                                else:
                                    display.add_detail("  API key: ✗ Missing or set to <Required>")
                                    provider_valid = False
                                
                                # Check provider-specific required fields
                                if provider_type == "watsonx_saas":
                                    space_id_present = "SPACE_ID" in provider_config and provider_config["SPACE_ID"] and provider_config["SPACE_ID"] not in ["<Required>", ""]
                                    if space_id_present:
                                        display.add_detail("  Space ID: ✓ Present")
                                    else:
                                        display.add_detail("  Space ID: ✗ Missing or set to <Required>")
                                        provider_valid = False
                                
                                if not provider_valid:
                                    all_valid = False
                            
                            if all_valid:
                                display.complete_test("ai_services", True,
                                    f"AI Services configuration validated ({len(enabled_providers)} enabled provider(s))")
                            else:
                                remediation_steps = [
                                    "1. Edit propertyFile/<namespace>/aiservices_providers.toml",
                                    "2. For each enabled provider, replace <Required> placeholders:",
                                    "   - API_KEY: Your provider's API key",
                                    "   - SPACE_ID: Your WatsonX.ai Space ID (for watsonx_saas only)",
                                    "3. Ensure credentials have proper permissions",
                                    "4. Re-run validation: python3 prerequisites.py validate"
                                ]
                                
                                display.complete_test("ai_services", False,
                                    "One or more enabled providers have missing credentials",
                                    failure_reason="Required credential fields are missing or still set to <Required>",
                                    remediation="\n".join(remediation_steps))
                
            except Exception as e:
                state["logger"].exception(f"Validation error: {e}")
                display.add_detail(f"[red]Error during validation: {str(e)}[/red]")
        
        # Display detailed failure information after Live display ends
        display.display_failures()
        
        print()

        if all(vobject.is_validated.values()):
            print()
            success_text = Text()
            success_text.append("✓ ", style="bold green")
            success_text.append("All Prerequisites Validated Successfully!", style="bold green")
            
            print(Panel(
                success_text,
                border_style="green",
                padding=(1, 2)
            ))
            print()
            
            # Check if Vault is enabled
            vault_enabled = deployment_prop_dict.get('VAULT_ENABLED', False)
            
            if apply:
                state["logger"].info("Auto-applying artifacts (--apply flag set)")
                if vault_enabled:
                    state["logger"].info("Vault is enabled - applying SecretProviderClass resources")
                vobject.auto_apply_secrets_ssl()
                vobject.auto_apply_configmaps()
                vobject.auto_apply_metrics()
                vobject.auto_apply_cr()
            else:
                # Use questionary for interactive prompts
                print()
                apply_info = Text()
                apply_info.append("📦 ", style="bold cyan")
                apply_info.append("Ready to Apply Artifacts", style="bold white")
                apply_info.append("\n\nYou can now apply the generated artifacts to your cluster.", style="white")
                
                # Add Vault-specific information if enabled
                if vault_enabled:
                    apply_info.append("\n\n", style="white")
                    apply_info.append("🔒 Vault Integration Enabled", style="bold purple")
                    apply_info.append("\nSecretProviderClass resources will be applied instead of regular Kubernetes Secrets.", style="dim")
                
                print(Panel(
                    apply_info,
                    border_style="cyan",
                    padding=(1, 2)
                ))
                print()
                
                # Customize prompt based on Vault status
                if vault_enabled:
                    secrets_prompt = "Apply SSL certificates and SecretProviderClass resources to the cluster?"
                else:
                    secrets_prompt = "Apply SSL certificates and Secrets to the cluster?"
                
                apply_ssls_secrets = questionary.confirm(
                    secrets_prompt,
                    default=True,
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                    ])
                ).ask()
                
                if apply_ssls_secrets is None:  # User cancelled
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                    
                if apply_ssls_secrets:
                    vobject.auto_apply_secrets_ssl()
                
                print()
                apply_configmaps = questionary.confirm(
                    "Apply ConfigMaps to the cluster?",
                    default=True,
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                    ])
                ).ask()
                
                if apply_configmaps is None:  # User cancelled
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                    
                if apply_configmaps:
                    vobject.auto_apply_configmaps()
                
                print()
                apply_metrics = questionary.confirm(
                    "Apply Metrics (IBMServiceMeterDefinition) to the cluster?",
                    default=True,
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                    ])
                ).ask()
                
                if apply_metrics is None:  # User cancelled
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                    
                if apply_metrics:
                    vobject.auto_apply_metrics()
                    
                print()
                apply_cr = questionary.confirm(
                    "Apply Custom Resources (CRs) to the cluster?",
                    default=True,
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                    ])
                ).ask()
                
                if apply_cr is None:  # User cancelled
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                    
                if apply_cr:
                    vobject.auto_apply_cr()
        else:
            print()
            warning_text = Text()
            warning_text.append("⚠ ", style="bold yellow")
            warning_text.append("Some Validation Checks Failed", style="bold yellow")
            warning_text.append("\n\nReview the validation results above and fix any issues before applying.", style="white")
            
            print(Panel(
                warning_text,
                border_style="yellow",
                padding=(1, 2)
            ))
            print()
            
            # Check if Vault is enabled
            vault_enabled = deployment_prop_dict.get('VAULT_ENABLED', False)
            
            if apply:
                state["logger"].warning("Auto-applying artifacts despite validation failures (--apply flag set)")
                if vault_enabled:
                    state["logger"].info("Vault is enabled - applying SecretProviderClass resources")
                vobject.auto_apply_secrets_ssl()
                vobject.auto_apply_configmaps()
                vobject.auto_apply_metrics()
                vobject.auto_apply_cr()
            else:
                # Use questionary for interactive prompts with warnings
                print()
                warning_info = Text()
                warning_info.append("⚠ ", style="bold yellow")
                warning_info.append("Proceed with Caution", style="bold yellow")
                warning_info.append("\n\nSome validations failed. Applying artifacts may cause deployment issues.", style="white")
                
                # Add Vault-specific information if enabled
                if vault_enabled:
                    warning_info.append("\n\n", style="white")
                    warning_info.append("🔒 Vault Integration Enabled", style="bold purple")
                    warning_info.append("\nSecretProviderClass resources will be applied instead of regular Kubernetes Secrets.", style="dim")
                
                print(Panel(
                    warning_info,
                    border_style="yellow",
                    padding=(1, 2)
                ))
                print()
                
                # Customize prompt based on Vault status
                if vault_enabled:
                    secrets_prompt = "Apply SSL certificates and SecretProviderClass resources despite validation failures?"
                else:
                    secrets_prompt = "Apply SSL certificates and Secrets despite validation failures?"
                
                apply_ssls_secrets = questionary.confirm(
                    secrets_prompt,
                    default=False,
                    style=Style([
                        ('qmark', 'fg:yellow bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:yellow bold'),
                    ])
                ).ask()
                
                if apply_ssls_secrets is None:  # User cancelled
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                    
                if apply_ssls_secrets:
                    vobject.auto_apply_secrets_ssl()
                
                print()
                apply_configmaps = questionary.confirm(
                    "Apply ConfigMaps despite validation failures?",
                    default=False,
                    style=Style([
                        ('qmark', 'fg:yellow bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:yellow bold'),
                    ])
                ).ask()
                
                if apply_configmaps is None:  # User cancelled
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                    
                if apply_configmaps:
                    vobject.auto_apply_configmaps()
                
                print()
                apply_metrics = questionary.confirm(
                    "Apply Metrics (IBMServiceMeterDefinition) despite validation failures?",
                    default=False,
                    style=Style([
                        ('qmark', 'fg:yellow bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:yellow bold'),
                    ])
                ).ask()
                
                if apply_metrics is None:  # User cancelled
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                    
                if apply_metrics:
                    vobject.auto_apply_metrics()
                    
                print()
                apply_cr = questionary.confirm(
                    "Apply Custom Resources (CRs) despite validation failures?",
                    default=False,
                    style=Style([
                        ('qmark', 'fg:yellow bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:yellow bold'),
                    ])
                ).ask()
                
                if apply_cr is None:  # User cancelled
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                    
                if apply_cr:
                    vobject.auto_apply_cr()


if __name__ == "__main__":
    app()
