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
from typing import List
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
from helper_scripts.generate.generate_wdu import GenerateWDU
from helper_scripts.generate.generate_model_gateway import GenerateModelGateway
from helper_scripts.generate.generate_cnpg_redis import (
    GenerateCNPGRedis,
    CNPG_SUPERUSER,
    DEFAULT_PG_PORT,
    DEFAULT_PG_DBNAME,
    DEFAULT_WDU_PG_DBNAME,
    DEFAULT_PG_SSLMODE,
    CNPG_PG_SSLMODE,
)
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

__version__ = "26.1.0"

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
            # Generate mode does NOT require a cluster connection upfront.
            # A connection is only needed when IBM-managed CNPG or Redis is selected;
            # that check is performed lazily inside the generate() function after the
            # property files have been read and the infra mode is known.
            checks = []
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
            if checks:
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
        info_text.append("Operator choices (Content, AI Services, WDU, Model Gateway)\n", style="white")
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
            
            gather.collect_operators(state["version_data"])
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
        gather.silent_operators()

        # Resolve AI provider types from [PROVIDER_N] sections.
        # Must run after silent_operators() so has_ai_services_operator() is accurate.
        # Model Gateway case is handled later inside silent_model_gateway_infra().
        if gather.has_ai_services_operator():
            gather.silent_model_providers()

        # Only collect LDAP if Content operator is selected
        # AI Services alone only needs IDP, not LDAP
        if gather.has_content_operator() and gather.auth_type in ("LDAP", "LDAP_IDP"):
            gather.silent_ldap()

        if gather.auth_type in ("LDAP_IDP", "SCIM_IDP"):
            gather.silent_idp()

        gather.silent_ingress()
        gather.silent_fips_support()
        gather.silent_network_policies_support()
        gather.silent_secret_management()
        gather.silent_sendmail_support()
        gather.silent_icc_support()
        gather.silent_tm_support()
        gather.silent_db()
        gather.silent_license_model()
        gather.silent_initverify()
        gather.silent_model_gateway_infra()
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

    wdu_properties = None
    if gather.has_wdu_operator():
        # In interactive mode, ask IBM-managed vs external for CNPG.
        # In silent mode, silent_model_gateway_infra() already set the flag.
        if not hasattr(gather, "_wdu_use_ibm_cnpg"):
            gather.collect_wdu_infra()
        wdu_properties = property_obj.populate_wdu_propertyfile()
        # Stamp the infrastructure choice into the property dict so it is written
        # to ccx-wdu.toml and picked up during generate mode.
        if wdu_properties is not None:
            # Stamp the infrastructure choice into the nested [postgres] section.
            # property.py create_wdu_propertyfile() will duplicate this into both
            # [postgres_session] and [postgres_transaction] TOML sections.
            if "postgres" not in wdu_properties:
                wdu_properties["postgres"] = {}
            wdu_properties["postgres"]["USE_IBM_CNPG"] = {
                "value": gather.wdu_use_ibm_cnpg,
                "comment": [
                    "Set to true to deploy an IBM-managed CNPG (PostgreSQL) cluster in-cluster.",
                    "Set to false to connect WDU to your own external PostgreSQL.",
                ]
            }
            wdu_properties["postgres"]["SSL_ENABLED"] = {
                "value": gather.wdu_pg_ssl,
                "comment": [
                    "Enable SSL for the WDU PostgreSQL connection.",
                    "Only used when USE_IBM_CNPG=false.",
                    "When USE_IBM_CNPG=true SSL is always enabled (sslmode=verify-ca).",
                ]
            }
            # Stamp the KVP/WatsonX AI opt-in flag.  When False (the default) the
            # [wxai] section is omitted from ccx-wdu.toml and no secret is generated.
            wdu_properties["WDU_ENABLE_WXAI"] = {
                "value": gather.wdu_enable_wxai,
                "comment": [
                    "Set to true to enable KVP with WatsonX AI for Enhanced Extraction (WDU).",
                    "When true: fill in the [wxai] section below with your watsonx.ai credentials.",
                    "Default: false",
                ]
            }

    model_gateway_properties = None
    if gather.has_model_gateway_operator():
        # In interactive mode, ask IBM-managed vs external for CNPG and Redis separately.
        # In silent mode, silent_model_gateway_infra() already set both flags.
        if not hasattr(gather, "_mg_use_ibm_cnpg"):
            gather.collect_model_gateway_infra()
        model_gateway_properties = property_obj.populate_model_gateway_propertyfile()
        # Stamp the independent infrastructure choices into the property dict so they
        # are written to ccx-model-gateway.toml for use during generate mode.
        if model_gateway_properties is not None:
            # Stamp the infrastructure choices into the nested [postgres] / [redis]
            # sections so they are written to ccx-model-gateway.toml correctly.
            if "postgres" not in model_gateway_properties:
                model_gateway_properties["postgres"] = {}
            if "redis" not in model_gateway_properties:
                model_gateway_properties["redis"] = {}
            model_gateway_properties["postgres"]["USE_IBM_CNPG"] = {
                "value": gather.mg_use_ibm_cnpg,
                "comment": [
                    "Set to true to deploy an IBM-managed CNPG (PostgreSQL) cluster in-cluster.",
                    "Set to false to connect Model Gateway to your own external PostgreSQL.",
                ]
            }
            model_gateway_properties["postgres"]["SSL_ENABLED"] = {
                "value": gather.mg_pg_ssl,
                "comment": [
                    "Enable SSL for the Model Gateway PostgreSQL connection.",
                    "Only used when USE_IBM_CNPG=false.",
                    "When USE_IBM_CNPG=true SSL is always enabled (sslmode=verify-ca).",
                ]
            }
            model_gateway_properties["redis"]["USE_IBM_REDIS"] = {
                "value": gather.mg_use_ibm_redis,
                "comment": [
                    "Set to true to deploy an IBM-managed Redis instance in-cluster.",
                    "Set to false to use your own external Redis (or disable Redis).",
                ]
            }

        deployment_properties = None

    property_obj.create_property_structure()

    # Download the GraphQL root-CA certificate from the migrated FNCMCluster CR secret.
    # The gather object already has an active Kubernetes connection (used to read the CR),
    # so download_certificate_from_secret() is available right now.
    if gather.fncm_migration_settings:
        migration_settings = gather.fncm_migration_settings
        if migration_settings.get('graphql_root_ca_secret'):
            root_ca_secret = migration_settings['graphql_root_ca_secret']
            namespace = gather.namespace
            ssl_folder = os.path.join(os.getcwd(), "propertyFile", namespace, "ssl-certs", "graphql")
            cert_dest = os.path.join(ssl_folder, "root-ca.pem")

            state["logger"].info(
                f"Attempting to download GraphQL root-CA certificate from secret '{root_ca_secret}'"
            )
            cert_content = gather._k.download_certificate_from_secret(
                secret_name=root_ca_secret,
                namespace=namespace,
                cert_key="root-ca.crt",
            )

            if cert_content:
                os.makedirs(ssl_folder, exist_ok=True)
                with open(cert_dest, "w") as f:
                    f.write(cert_content)
                state["logger"].info(
                    f"GraphQL root-CA certificate written to {cert_dest}"
                )
                cert_info = Text()
                cert_info.append("✅ GraphQL Root-CA Certificate Downloaded\n\n", style="bold green")
                cert_info.append("  Secret:   ", style="white")
                cert_info.append(f"{root_ca_secret}\n", style="cyan")
                cert_info.append("  Location: ", style="white")
                cert_info.append(
                    f"propertyFile/{namespace}/ssl-certs/graphql/root-ca.pem\n",
                    style="cyan",
                )
                print(Panel(cert_info, border_style="green", padding=(0, 2)))
            else:
                state["logger"].warning(
                    f"Could not download certificate from secret '{root_ca_secret}' — manual step required"
                )
                cert_warn = Text()
                cert_warn.append("⚠️  GraphQL Root-CA Certificate Not Downloaded\n\n", style="bold yellow")
                cert_warn.append("The certificate secret could not be read automatically.\n", style="white")
                cert_warn.append("Please add the certificate manually before running generate mode:\n\n",
                                  style="white")
                cert_warn.append("  Secret:          ", style="white")
                cert_warn.append(f"{root_ca_secret}\n", style="cyan")
                cert_warn.append("  Target location: ", style="white")
                cert_warn.append(
                    f"propertyFile/{namespace}/ssl-certs/graphql/root-ca.pem\n\n",
                    style="cyan",
                )
                cert_warn.append("To extract manually:\n", style="bold white")
                cert_warn.append(
                    f"  kubectl get secret {root_ca_secret} -n {namespace}"
                    f" -o jsonpath='{{.data.root-ca\\.crt}}' | base64 -d"
                    f" > propertyFile/{namespace}/ssl-certs/graphql/root-ca.pem\n",
                    style="dim white",
                )
                print(Panel(cert_warn, border_style="yellow", padding=(0, 2)))

        # Download IDP SSL certificate(s) from secrets in trusted_certificate_list whose
        # name contains 'idp'.  Each cert is written to ssl-certs/idp/<secret-name>.pem.
        idp_ssl_secrets = migration_settings.get('idp_ssl_secrets', [])
        if idp_ssl_secrets:
            namespace = gather.namespace
            idp_ssl_folder = os.path.join(os.getcwd(), "propertyFile", namespace, "ssl-certs", "idp")
            os.makedirs(idp_ssl_folder, exist_ok=True)

            downloaded: list[str] = []
            failed: list[str] = []

            for secret_name in idp_ssl_secrets:
                state["logger"].info(
                    f"Attempting to download IDP SSL certificate from secret '{secret_name}'"
                )
                cert_content = gather._k.download_certificate_from_secret(
                    secret_name=secret_name,
                    namespace=namespace,
                )
                if cert_content:
                    cert_dest = os.path.join(idp_ssl_folder, f"{secret_name}.pem")
                    with open(cert_dest, "w") as f:
                        f.write(cert_content)
                    state["logger"].info(
                        f"IDP SSL certificate '{secret_name}' written to {cert_dest}"
                    )
                    downloaded.append(secret_name)
                else:
                    state["logger"].warning(
                        f"Could not download IDP SSL certificate from secret '{secret_name}'"
                    )
                    failed.append(secret_name)

            if downloaded and not failed:
                idp_info = Text()
                idp_info.append("✅ IDP SSL Certificate(s) Downloaded\n\n", style="bold green")
                for name in downloaded:
                    idp_info.append("  Secret:   ", style="white")
                    idp_info.append(f"{name}\n", style="cyan")
                    idp_info.append("  Location: ", style="white")
                    idp_info.append(
                        f"propertyFile/{namespace}/ssl-certs/idp/{name}.pem\n",
                        style="cyan",
                    )
                print(Panel(idp_info, border_style="green", padding=(0, 2)))
            else:
                idp_warn = Text()
                if downloaded:
                    idp_warn.append(
                        "⚠️  Some IDP SSL Certificates Could Not Be Downloaded\n\n",
                        style="bold yellow",
                    )
                    idp_warn.append("Downloaded successfully:\n", style="white")
                    for name in downloaded:
                        idp_warn.append(f"  ✓ {name}\n", style="green")
                    idp_warn.append("\n")
                else:
                    idp_warn.append(
                        "⚠️  IDP SSL Certificate(s) Not Downloaded\n\n",
                        style="bold yellow",
                    )
                idp_warn.append(
                    "The following certificate secret(s) could not be read automatically.\n"
                    "Please add them manually before running generate mode:\n\n",
                    style="white",
                )
                for name in failed:
                    idp_warn.append(f"  Secret: ", style="white")
                    idp_warn.append(f"{name}\n", style="cyan")
                    idp_warn.append(f"  Target:  ", style="white")
                    idp_warn.append(
                        f"propertyFile/{namespace}/ssl-certs/idp/{name}.pem\n\n",
                        style="cyan",
                    )
                    idp_warn.append("  To extract manually:\n", style="bold white")
                    idp_warn.append(
                        f"    kubectl get secret {name} -n {namespace}"
                        f" -o jsonpath='{{.data.tls\\.crt}}' | base64 -d"
                        f" > propertyFile/{namespace}/ssl-certs/idp/{name}.pem\n\n",
                        style="dim white",
                    )
                print(Panel(idp_warn, border_style="yellow", padding=(0, 2)))

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

    # Create WDU property file if WDU operator is selected
    if gather.has_wdu_operator() and wdu_properties is not None:
        property_obj.create_wdu_propertyfile(wdu_properties)

    # Create Model Gateway property file if Model Gateway operator is selected
    if gather.has_model_gateway_operator() and model_gateway_properties is not None:
        property_obj.create_model_gateway_propertyfile(model_gateway_properties)

    # ── Gather-mode infrastructure CR generation ──────────────────────────────
    # When IBM-managed CNPG or Redis is selected, generate the CRs and secrets
    # into generatedFiles/<namespace>/infrastructure/ now (at end of gather mode)
    # so the customer can deploy them before running generate mode.
    if gather.has_model_gateway_operator():
        _gather_use_ibm_cnpg = gather.mg_use_ibm_cnpg
        _gather_use_ibm_redis = gather.mg_use_ibm_redis
        if _gather_use_ibm_cnpg or _gather_use_ibm_redis:
            try:
                _infra_folder = os.path.join(os.getcwd(), "generatedFiles", namespace, "infrastructure")
                os.makedirs(_infra_folder, exist_ok=True)
                _infra_secrets_folder = os.path.join(_infra_folder, "secrets")
                os.makedirs(_infra_secrets_folder, exist_ok=True)

                _block_sc = getattr(gather, "_mg_block_storage_class", "")
                state["logger"].info(
                    f"Generating infrastructure CRs into {_infra_folder} "
                    f"(CNPG={_gather_use_ibm_cnpg}, Redis={_gather_use_ibm_redis}, sc={_block_sc})"
                )

                infra_gen = GenerateCNPGRedis(
                    mg_properties=model_gateway_properties or {},
                    wdu_properties={},
                    deployment_properties={},
                    namespace=namespace,
                    logger=state["logger"],
                    output_folder=_infra_folder,
                    block_storage_class=_block_sc,
                )

                _infra_ok = True
                if _gather_use_ibm_cnpg:
                    if not infra_gen.generate_cnpg_mg_cr():
                        state["logger"].warning("CNPG MG CR generation failed")
                        _infra_ok = False
                if _gather_use_ibm_redis:
                    import secrets as _secrets
                    import string as _string
                    _redis_pwd = "".join(
                        _secrets.choice(_string.ascii_letters + _string.digits)
                        for _ in range(24)
                    )
                    if not infra_gen.generate_redis_cr(_redis_pwd):
                        state["logger"].warning("Redis CR generation failed")
                        _infra_ok = False
                    if not infra_gen.generate_redis_pwd_secret(_redis_pwd):
                        state["logger"].warning("Redis pwd secret generation failed")
                        _infra_ok = False

                if _infra_ok:
                    _t = Text()
                    _t.append("✅  Infrastructure CRs generated\n\n", style="bold green")
                    _t.append("Files written to:\n", style="white")
                    _t.append(f"  generatedFiles/{namespace}/infrastructure/\n", style="cyan")
                    if _gather_use_ibm_cnpg:
                        _t.append("  ├─ ibm_pg_cluster_mg_cr.yaml\n", style="dim white")
                    if _gather_use_ibm_redis:
                        _t.append("  ├─ ibm_redis_cr.yaml\n", style="dim white")
                        _t.append("  └─ secrets/ibm-redis-mg-secret.yaml\n", style="dim white")
                    _t.append("\nFollow infrastructure/README.md to deploy these before running generate.\n",
                              style="bold yellow")
                    print(Panel(_t,
                                title="[bold white]Infrastructure CRs Ready[/bold white]",
                                border_style="green", padding=(1, 2)))
                    state["logger"].info("Infrastructure CRs generated successfully")
                else:
                    print(
                        "\n[yellow]⚠ Some infrastructure CR files could not be generated. "
                        "Check the log for details.[/yellow]\n"
                    )

            except Exception as _e:
                state["logger"].error(f"Error generating infrastructure CRs: {str(_e)}")
                state["logger"].exception("Detailed error:")
                print(f"\n[yellow]⚠ Error generating infrastructure CRs: {str(_e)}[/yellow]\n")

    # ── Gather-mode WDU infrastructure CR generation ──────────────────────────
    if gather.has_wdu_operator() and gather.wdu_use_ibm_cnpg:
        try:
            _infra_folder = os.path.join(os.getcwd(), "generatedFiles", namespace, "infrastructure")
            os.makedirs(_infra_folder, exist_ok=True)
            _infra_secrets_folder = os.path.join(_infra_folder, "secrets")
            os.makedirs(_infra_secrets_folder, exist_ok=True)

            _wdu_block_sc = getattr(gather, "_wdu_block_storage_class", "")
            state["logger"].info(
                f"Generating WDU infrastructure CRs into {_infra_folder} "
                f"(CNPG=True, sc={_wdu_block_sc})"
            )

            wdu_infra_gen = GenerateCNPGRedis(
                mg_properties={},
                wdu_properties=wdu_properties or {},
                deployment_properties={},
                namespace=namespace,
                logger=state["logger"],
                output_folder=_infra_folder,
                block_storage_class=_wdu_block_sc,
            )

            _wdu_infra_ok = True
            if not wdu_infra_gen.generate_cnpg_wdu_cr():
                state["logger"].warning("CNPG WDU CR generation failed")
                _wdu_infra_ok = False
            if not wdu_infra_gen.generate_cnpg_wdu_pooler_cr():
                state["logger"].warning("CNPG WDU Pooler CR generation failed")
                _wdu_infra_ok = False

            if _wdu_infra_ok:
                _t = Text()
                _t.append("✅  WDU Infrastructure CRs generated\n\n", style="bold green")
                _t.append("Files written to:\n", style="white")
                _t.append(f"  generatedFiles/{namespace}/infrastructure/\n", style="cyan")
                _t.append("  ├─ ibm_pg_cluster_wdu_cr.yaml\n", style="dim white")
                _t.append("  └─ ibm_pg_pooler_wdu_cr.yaml", style="dim white")
                _t.append("  (PgBouncer — apply after cluster is healthy)\n", style="dim cyan")
                _t.append("\nFollow infrastructure/README.md to deploy these before running generate.\n",
                          style="bold yellow")
                print(Panel(_t,
                            title="[bold white]WDU Infrastructure CRs Ready[/bold white]",
                            border_style="green", padding=(1, 2)))
                state["logger"].info("WDU infrastructure CRs generated successfully")
            else:
                print(
                    "\n[yellow]⚠ Some WDU infrastructure CR files could not be generated. "
                    "Check the log for details.[/yellow]\n"
                )

        except Exception as _e:
            state["logger"].error(f"Error generating WDU infrastructure CRs: {str(_e)}")
            state["logger"].exception("Detailed error:")
            print(f"\n[yellow]⚠ Error generating WDU infrastructure CRs: {str(_e)}[/yellow]\n")

    # ── Unified infrastructure README (covers MG + WDU in a single file) ──────
    _readme_mg_cnpg  = gather.has_model_gateway_operator() and getattr(gather, "mg_use_ibm_cnpg", False)
    _readme_mg_redis = gather.has_model_gateway_operator() and getattr(gather, "mg_use_ibm_redis", False)
    _readme_wdu_pool = gather.has_wdu_operator() and getattr(gather, "wdu_use_ibm_cnpg", False)
    if _readme_mg_cnpg or _readme_mg_redis or _readme_wdu_pool:
        try:
            _infra_folder = os.path.join(os.getcwd(), "generatedFiles", namespace, "infrastructure")
            from helper_scripts.generate.generate_readme import GenerateReadme as _GR
            _GR.generate_infrastructure_readme(
                namespace=namespace,
                use_mg_cnpg=_readme_mg_cnpg,
                use_mg_redis=_readme_mg_redis,
                output_folder=_infra_folder,
                logger=state["logger"],
                use_wdu_cnpg_pooler=_readme_wdu_pool,
            )
        except Exception as _e:
            state["logger"].error(f"Error generating infrastructure README: {str(_e)}")

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


# ---------------------------------------------------------------------------
# Live-cluster detection display helpers (used by generate mode)
# ---------------------------------------------------------------------------

def _display_cnpg_detection(
    component: str,
    namespace: str,
    host_fqdn: str,
    ca_secret_name: str,
    app_secret_name: str,
    ca_cert_b64: str,
    password_b64: str,
    client_cert_b64: str = "",
    client_key_b64: str = "",
    pooler_fqdn: str = "",
) -> None:
    """Render a rich panel showing what was detected from a live CNPG cluster.

    Args:
        component:        Human label — "Model Gateway" or "Enhanced Extraction (WDU)".
        namespace:        Kubernetes namespace that was queried.
        host_fqdn:        Resolved read-write FQDN for the CNPG cluster.
        ca_secret_name:   Name of the Kubernetes secret holding the CA certificate.
        app_secret_name:  Name of the Kubernetes secret holding the app password.
        ca_cert_b64:      Base64-encoded CA certificate (used for length check only).
        password_b64:     Base64-encoded password (used for length check only).
        client_cert_b64:  Base64-encoded client certificate for mTLS (empty = no mTLS).
        client_key_b64:   Base64-encoded client private key for mTLS (empty = no mTLS).
        pooler_fqdn:      PgBouncer pooler FQDN (WDU only; empty = no pooler).
    """
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    _mtls = bool(client_cert_b64 and client_key_b64)

    body = Text()
    body.append("🔍  Live cluster query complete — artifacts detected\n\n", style="bold green")

    # ── Cluster context ──────────────────────────────────────────────────────
    body.append("Cluster Context\n", style="bold yellow")
    body.append("  Namespace:  ", style="white")
    body.append(f"{namespace}\n", style="cyan")
    body.append("  Component:  ", style="white")
    body.append(f"{component}\n\n", style="cyan")

    # ── Connection endpoint ──────────────────────────────────────────────────
    body.append("PostgreSQL Endpoint\n", style="bold yellow")
    body.append("  Host FQDN:  ", style="white")
    body.append(f"{host_fqdn}\n", style="green")
    if pooler_fqdn:
        body.append("  Pooler:     ", style="white")
        body.append(f"{pooler_fqdn}\n", style="green")
    body.append("  Port:       ", style="white")
    body.append("5432  (default)\n\n", style="cyan")

    # ── Secrets read ─────────────────────────────────────────────────────────
    body.append("Secrets Retrieved from Cluster\n", style="bold yellow")

    _ok = "[bold green]✓ Retrieved[/bold green]"
    _ca_status = _ok if ca_cert_b64 else "[bold red]✗ Empty[/bold red]"
    _pw_status  = _ok if password_b64 else "[bold red]✗ Empty[/bold red]"

    body.append("  CA Certificate\n", style="white")
    body.append("    Secret:  ", style="dim white")
    body.append(f"{ca_secret_name}  ", style="cyan")
    body.append(f"→  key: ca.crt  ")
    body.append_text(Text.from_markup(_ca_status))
    body.append("\n")

    body.append("  App Password\n", style="white")
    body.append("    Secret:  ", style="dim white")
    body.append(f"{app_secret_name}  ", style="cyan")
    body.append(f"→  key: password  ")
    body.append_text(Text.from_markup(_pw_status))
    body.append("\n")

    if _mtls:
        _cert_status = _ok if client_cert_b64 else "[bold red]✗ Empty[/bold red]"
        _key_status  = _ok if client_key_b64  else "[bold red]✗ Empty[/bold red]"
        body.append("  mTLS Client Certificate\n", style="white")
        body.append("    Secret:  ", style="dim white")
        body.append(f"serverTLSSecret  ", style="cyan")
        body.append(f"→  key: tls.crt  ")
        body.append_text(Text.from_markup(_cert_status))
        body.append("\n")
        body.append("  mTLS Client Key\n", style="white")
        body.append("    Secret:  ", style="dim white")
        body.append(f"serverTLSSecret  ", style="cyan")
        body.append(f"→  key: tls.key  ")
        body.append_text(Text.from_markup(_key_status))
        body.append("\n")
    body.append("\n")

    # ── What was generated ───────────────────────────────────────────────────
    body.append("Generated Artifacts\n", style="bold yellow")
    body.append("  ✓ ", style="bold green")
    body.append("External connection secret stamped with live credentials\n", style="white")
    body.append("  ✓ ", style="bold green")
    if _mtls:
        body.append(
            "CA cert + client cert/key embedded (sslmode=verify-ca with mTLS)\n",
            style="white",
        )
    else:
        body.append(
            "CA certificate embedded for TLS verification (sslmode=verify-ca)\n",
            style="white",
        )

    console.print()
    console.print(Panel(
        body,
        title=f"[bold white]🗄️  PostgreSQL Detected — {component}[/bold white]",
        border_style="green",
        padding=(1, 2),
    ))


def _display_redis_detection(
    namespace: str,
    host: str,
    pwd_secret_name: str,
    password_b64: str,
    cr_name: str = "",
) -> None:
    """Render a rich panel showing what was detected from a live IBM Redis instance.

    Args:
        namespace:       Kubernetes namespace that was queried.
        host:            Short service hostname for IBM Redis master.
        pwd_secret_name: Name of the Kubernetes secret holding the Redis password.
        password_b64:    Base64-encoded password (used for length check only).
        cr_name:         Name of the Redis CR that was detected (for display).
    """
    from rich.panel import Panel
    from rich.text import Text

    body = Text()
    body.append("🔍  Live cluster query complete — artifacts detected\n\n", style="bold green")

    # ── Cluster context ──────────────────────────────────────────────────────
    body.append("Cluster Context\n", style="bold yellow")
    body.append("  Namespace:  ", style="white")
    body.append(f"{namespace}\n\n", style="cyan")

    # ── Connection endpoint ──────────────────────────────────────────────────
    body.append("Redis Endpoint\n", style="bold yellow")
    body.append("  Host:       ", style="white")
    body.append(f"{host}\n", style="green")
    body.append("  TLS Port:   ", style="white")
    body.append("6380  (IBM Redis default, TLS enabled)\n\n", style="cyan")

    # ── Secrets read ─────────────────────────────────────────────────────────
    body.append("Secrets Retrieved from Cluster\n", style="bold yellow")

    _pw_status = (
        "[bold green]✓ Retrieved[/bold green]"
        if password_b64
        else "[bold red]✗ Empty[/bold red]"
    )

    body.append("  Redis Password\n", style="white")
    body.append("    Secret:  ", style="dim white")
    body.append(f"{pwd_secret_name}  ", style="cyan")
    body.append(f"→  key: password  ")
    body.append_text(Text.from_markup(_pw_status))
    body.append("\n\n")

    # ── What was generated ───────────────────────────────────────────────────
    body.append("Generated Artifacts\n", style="bold yellow")
    body.append("  ✓ ", style="bold green")
    body.append("External connection secret stamped with live Redis credentials\n", style="white")
    body.append("  ✓ ", style="bold green")
    body.append("TLS enabled — IBM Redis uses port 6380 with in-cluster certificate\n", style="white")

    console.print()
    _redis_title = (
        f"[bold white]⚡  Redis Detected — {cr_name}[/bold white]"
        if cr_name
        else "[bold white]⚡  Redis Detected — Model Gateway[/bold white]"
    )
    console.print(Panel(
        body,
        title=_redis_title,
        border_style="green",
        padding=(1, 2),
    ))


def _display_cnpg_discovery_info(
    component: str,
    namespace: str,
    candidates: List[str],
    show_pooler: bool = False,
) -> None:
    """Show a pre-flight info panel before asking the customer to confirm/select a
    CNPG cluster.  Mirrors the FNCMCluster migration info panel style from gather mode.

    Args:
        component:    Human label — "Model Gateway" or "Enhanced Extraction (WDU)".
        namespace:    Kubernetes namespace that was searched.
        candidates:   List of matching CNPG Cluster CR names discovered.
        show_pooler:  When True, adds a bullet describing Pooler CR discovery
                      (used for WDU which routes transactions through PgBouncer).
    """
    info = Text()
    info.append("🔍 IBM CNPG PostgreSQL Cluster Detected\n\n", style="bold cyan")
    info.append(
        f"Found {len(candidates)} CNPG cluster(s) in namespace ",
        style="white",
    )
    info.append(f"{namespace}\n\n", style="bold cyan")

    if len(candidates) == 1:
        info.append("Cluster:  ", style="bold yellow")
        info.append(f"{candidates[0]}\n\n", style="cyan")
    else:
        info.append("Clusters:\n", style="bold yellow")
        for _c in candidates:
            info.append(f"  • {_c}\n", style="cyan")
        info.append("\n", style="white")

    info.append("💡 What will be extracted from the live cluster\n\n", style="bold yellow")
    info.append(
        f"Credentials for {component} will be read directly from the IBM CNPG operator secrets:\n\n",
        style="white",
    )
    info.append("  ✓ ", style="green")
    info.append("CA certificate  ", style="white")
    info.append("(<cluster>-ca → ca.crt)\n", style="dim white")
    info.append("  ✓ ", style="green")
    info.append("App password    ", style="white")
    info.append("(<cluster>-app → password)\n", style="dim white")
    info.append("  ✓ ", style="green")
    info.append("PostgreSQL host ", style="white")
    info.append("(status.writeService or <cluster>-rw.<namespace>.svc.cluster.local)\n", style="dim white")
    if show_pooler:
        info.append("  ✓ ", style="green")
        info.append("PgBouncer pooler", style="white")
        info.append("  (Pooler CR linked to cluster via spec.cluster.name → <pooler>.<namespace>.svc.cluster.local)\n", style="dim white")
    info.append("  ✓ ", style="green")
    info.append("mTLS client cert/key  ", style="white")
    info.append("(status.certificates.serverTLSSecret, if configured)\n\n", style="dim white")

    info.append("⚠️  Note: ", style="bold red")
    info.append(
        "The IBM CNPG operator must be Ready before secrets can be read.",
        style="yellow",
    )

    console.print()
    console.print(Panel(
        info,
        title=f"[bold white]🗄️  IBM CNPG Cluster — {component}[/bold white]",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()


def _display_redis_discovery_info(
    namespace: str,
    candidates: List[str],
) -> None:
    """Show a pre-flight info panel before asking the customer to confirm/select a
    Redis CR.  Mirrors the FNCMCluster migration info panel style from gather mode.

    Args:
        namespace:   Kubernetes namespace that was searched.
        candidates:  List of matching IBM Redis CR names discovered.
    """
    info = Text()
    info.append("🔍 IBM Redis Instance Detected\n\n", style="bold cyan")
    info.append(
        f"Found {len(candidates)} IBM Redis instance(s) in namespace ",
        style="white",
    )
    info.append(f"{namespace}\n\n", style="bold cyan")

    if len(candidates) == 1:
        info.append("Instance:  ", style="bold yellow")
        info.append(f"{candidates[0]}\n\n", style="cyan")
    else:
        info.append("Instances:\n", style="bold yellow")
        for _c in candidates:
            info.append(f"  • {_c}\n", style="cyan")
        info.append("\n", style="white")

    info.append("💡 What will be extracted from the live cluster\n\n", style="bold yellow")
    info.append(
        "Credentials for Model Gateway Redis will be read directly from the IBM Redis operator secrets:\n\n",
        style="white",
    )
    info.append("  ✓ ", style="green")
    info.append("Redis password  ", style="white")
    info.append("(spec.connectionSecret.secretName → password)\n", style="dim white")
    info.append("  ✓ ", style="green")
    info.append("Master service  ", style="white")
    info.append("(status.masterService or <cr>-master-svc)\n", style="dim white")
    info.append("  ✓ ", style="green")
    info.append("TLS mode        ", style="white")
    info.append("(spec.tls.enabled — IBM Redis default: enabled, port 6380)\n\n", style="dim white")

    info.append("⚠️  Note: ", style="bold red")
    info.append(
        "The IBM Redis operator must be Ready before secrets can be read.",
        style="yellow",
    )

    console.print()
    console.print(Panel(
        info,
        title="[bold white]⚡  IBM Redis Instance — Model Gateway[/bold white]",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()


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
        info_text.append("WDU artifacts (if configured)\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Model Gateway artifacts (if configured)\n", style="white")
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
    wdu_prop_file = os.path.join(prop_folder, "ccx-wdu.toml")
    model_gateway_prop_file = os.path.join(prop_folder, "ccx-model-gateway.toml")

    # Set defaults for property files
    db_prop = None
    aiservices_prop = None
    aiservices_integration_prop = None
    wdu_prop = None
    model_gateway_prop = None
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

        # Read WDU property file if it exists
        if os.path.exists(wdu_prop_file):
            from helper_scripts.property.read_prop import ReadPropWDU
            wdu_prop = ReadPropWDU(wdu_prop_file, state["logger"])

        # Read Model Gateway property file if it exists
        if os.path.exists(model_gateway_prop_file):
            from helper_scripts.property.read_prop import ReadPropModelGateway
            model_gateway_prop = ReadPropModelGateway(model_gateway_prop_file, state["logger"])

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

        if wdu_prop:
            wdu_prop_dict = wdu_prop.to_dict()
        else:
            wdu_prop_dict = {}

        if model_gateway_prop:
            model_gateway_prop_dict = model_gateway_prop.to_dict()
        else:
            model_gateway_prop_dict = {}

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
    _mg_use_ibm_cnpg = str(model_gateway_prop_dict.get("postgres", {}).get("USE_IBM_CNPG", False)).lower() in ("true", "1", "yes")
    # Mirror the key-fallback used inside validate_wdu_db():
    # prefer "postgres_session" (new PgBouncer TOML layout), fall back to bare "postgres".
    _wdu_pg_block = wdu_prop_dict.get("postgres_session") or wdu_prop_dict.get("postgres", {})
    _wdu_use_ibm_cnpg = str(_wdu_pg_block.get("USE_IBM_CNPG", False)).lower() in ("true", "1", "yes")
    missing_certs, incorrect_certs, mg_cnpg_cert_reminder = check_ssl_folders(
                                                       db_prop=db_prop_dict if db_prop_dict else None,
                                                       ldap_prop=ldap_prop_dict if ldap_prop_dict else None,
                                                       ssl_cert_folder=ssl_cert_folder,
                                                       deploy_prop=deployment_prop_dict,
                                                       idp_prop=idp_prop_dict,
                                                       scim_prop=scim_prop_dict,
                                                       graphql_prop=aiservices_integration_prop_dict if aiservices_integration_prop_dict else None,
                                                       aiservices_prop=aiservices_prop_dict if aiservices_prop_dict else None,
                                                       mg_use_ibm_cnpg=_mg_use_ibm_cnpg,
                                                       wdu_prop=wdu_prop_dict if wdu_prop_dict else None,
                                                       wdu_use_ibm_cnpg=_wdu_use_ibm_cnpg)
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
    if wdu_prop:
        unified_display.add_property_validation_errors(wdu_prop, "WDU")
    if model_gateway_prop:
        unified_display.add_property_validation_errors(model_gateway_prop, "Model Gateway")

    # Add certificate issues
    unified_display.add_certificate_issues(missing_certs, incorrect_certs)
    # Note: mg_cnpg_cert_reminder removed — the CA cert is now fetched live from
    # ibm-pg-cluster-mg-ca during generate mode; no manual cert copy step is needed.

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
            # Selective delete: preserve infrastructure/ so gather-mode CRs survive
            # across generate runs.  All other entries are removed for a clean slate.
            for _entry in os.scandir(generated_folder):
                if _entry.name == "infrastructure":
                    continue  # keep infrastructure/ — CRs were deployed by customer
                if _entry.is_dir(follow_symlinks=False):
                    shutil.rmtree(_entry.path)
                else:
                    os.remove(_entry.path)
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

            # Generate Model Gateway DB init SQL when MG is selected and using external PG.
            # CNPG (USE_IBM_CNPG=true) manages its own DB bootstrap — no SQL script needed.
            if model_gateway_prop and model_gateway_prop_dict:
                _mg_use_cnpg = str(
                    model_gateway_prop_dict.get("postgres", {}).get("USE_IBM_CNPG", False)
                ).lower() in ("true", "1", "yes")
                if not _mg_use_cnpg:
                    generate_sql.create_model_gateway(model_gateway_prop_dict)

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

        # Generate WDU artifacts if WDU property file is present
        if wdu_prop and wdu_prop_dict:
            state["logger"].info("Generating WDU (Enhanced Extraction) artifacts")
            try:
                wdu_generator = GenerateWDU(
                    wdu_properties=wdu_prop_dict,
                    deployment_properties=deployment_prop_dict,
                    namespace=namespace,
                    logger=state["logger"],
                )
                if wdu_generator.generate_all():
                    state["logger"].info("WDU artifacts generated successfully")
                else:
                    state["logger"].warning("Some WDU artifacts failed to generate")
            except Exception as e:
                state["logger"].error(f"Error generating WDU artifacts: {str(e)}")
                state["logger"].exception("Detailed error:")

            # Generate WDU DB init SQL when using external PG, independent of Content operator.
            # CNPG (USE_IBM_CNPG=true) manages its own DB bootstrap — no SQL script needed.
            # The TOML section is named postgres_session; USE_IBM_CNPG is the same in both.
            _wdu_pg_session = wdu_prop_dict.get("postgres_session", wdu_prop_dict.get("postgres", {}))
            _wdu_use_cnpg_sql = str(_wdu_pg_session.get("USE_IBM_CNPG", False)).lower() in ("true", "1", "yes")
            if not _wdu_use_cnpg_sql:
                _wdu_sql_gen = GenerateSql(
                    # GenerateSql needs DATABASE_TYPE to load templates; pass a minimal dict.
                    {"DATABASE_TYPE": "postgresql"},
                    state["logger"],
                    namespace=namespace,
                )
                _wdu_sql_gen.create_wdu(wdu_prop_dict)
                state["logger"].info("WDU DB init SQL generated (external PostgreSQL)")

        # ── Generate-mode infrastructure: external-connection secrets ─────────────
        # CNPG/Redis CRs were already generated during gather mode into infrastructure/.
        # Here we only generate the external-connection secrets (and WDU artifacts).
        # For IBM-managed infra the secrets are populated from live cluster queries;
        # for external/BYO the secrets are stamped from the property file.
        _use_ibm_cnpg_wdu = False
        if wdu_prop and wdu_prop_dict:
            # postgres_session is the primary TOML section; USE_IBM_CNPG is mirrored in both.
            _wdu_pg = wdu_prop_dict.get("postgres_session", wdu_prop_dict.get("postgres", {}))
            _use_ibm_cnpg_wdu = str(_wdu_pg.get("USE_IBM_CNPG", False)).lower() in ("true", "1", "yes")

        _use_ibm_cnpg_mg = False
        _use_ibm_redis = False
        if model_gateway_prop and model_gateway_prop_dict:
            _mg_pg = model_gateway_prop_dict.get("postgres", {})
            _mg_redis = model_gateway_prop_dict.get("redis", {})
            _use_ibm_cnpg_mg = str(_mg_pg.get("USE_IBM_CNPG", False)).lower() in ("true", "1", "yes")
            _use_ibm_redis = str(_mg_redis.get("USE_IBM_REDIS", False)).lower() in ("true", "1", "yes")

        if (model_gateway_prop and model_gateway_prop_dict) or _use_ibm_cnpg_wdu or bool(wdu_prop_dict):
            from helper_scripts.generate.cluster_info import (
                ClusterResourceNotFoundError,
                MultipleResourcesFoundError,
                discover_cnpg_clusters,
                discover_cnpg_poolers,
                discover_redis_crs,
                fetch_cnpg_mg_connection,
                fetch_cnpg_wdu_connection,
                fetch_redis_connection,
            )

            # ── IBM CNPG MG placeholder secret ───────────────────────────────
            # Generate a placeholder postgres external secret from known static
            # values (hostname, port, username, sslmode) before the cluster
            # connection check.  This ensures the file always exists after a
            # generate run even when the cluster is not yet reachable.  When the
            # cluster IS reachable the live-credentials path below overwrites it
            # with the real CA cert and password.
            if _use_ibm_cnpg_mg:
                try:
                    _placeholder_gen = GenerateCNPGRedis(
                        mg_properties=model_gateway_prop_dict or {},
                        wdu_properties={},
                        deployment_properties=deployment_prop_dict,
                        namespace=namespace,
                        logger=state["logger"],
                    )
                    _placeholder_gen.generate_mg_postgres_external_secret(
                        host=_placeholder_gen.cnpg_mg_hostname(),
                        port=DEFAULT_PG_PORT,
                        username=CNPG_SUPERUSER,
                        password="",
                        dbname=DEFAULT_PG_DBNAME,
                        parameters=CNPG_PG_SSLMODE,
                    )
                    state["logger"].info(
                        "Generated MG postgres external secret placeholder "
                        "(will be overwritten with live credentials when cluster is ready)"
                    )
                except Exception as _placeholder_exc:
                    state["logger"].warning(
                        f"Could not generate MG postgres external secret placeholder: {_placeholder_exc}"
                    )

            # ── Deferred connection check ─────────────────────────────────────
            # IBM-managed CNPG/Redis requires a live, authenticated cluster to
            # read the operator secrets.  External/BYO infra reads from property
            # files and needs no connection.  We gate here — after the property
            # files tell us which mode is active — rather than blocking all
            # generate runs upfront.
            #
            # The check performs a real API probe (GET /version) so that an
            # expired or unauthorized token is caught here and produces the clean
            # error panel, rather than failing mid-generation with a raw 401.
            _needs_live_cluster = _use_ibm_cnpg_mg or _use_ibm_redis or _use_ibm_cnpg_wdu
            if _needs_live_cluster:
                from helper_scripts.utilities.kubernetes_utilites import KubernetesUtilities
                from kubernetes.client.exceptions import ApiException as _ApiException

                _cluster_ok = False
                _cluster_error_detail = ""
                try:
                    _k8s_check = KubernetesUtilities(logger=state["logger"], require_connection=True)
                    if not _k8s_check.connected:
                        raise RuntimeError("kubeconfig loaded but client reports no connection")
                    # Probe the API server with a real authenticated request so
                    # that an expired/invalid token surfaces here rather than
                    # mid-generation as a raw 401 error.
                    _k8s_check.version_v1.get_code(_request_timeout=10)
                    _cluster_ok = True
                except _ApiException as _api_exc:
                    _cluster_error_detail = (
                        f"API server returned HTTP {_api_exc.status} "
                        f"({_api_exc.reason}). "
                        f"Your kubeconfig token may be expired — run "
                        f"[dim]oc login[/dim] or [dim]kubectl config use-context[/dim] "
                        f"to refresh credentials."
                    )
                except Exception as _conn_exc:
                    _cluster_error_detail = str(_conn_exc)

                if not _cluster_ok:
                    _ibm_components = ", ".join(filter(None, [
                        "IBM CNPG (MG)" if _use_ibm_cnpg_mg else "",
                        "IBM Redis" if _use_ibm_redis else "",
                        "IBM CNPG (WDU)" if _use_ibm_cnpg_wdu else "",
                    ]))
                    console.print(Panel(
                        f"[bold red]No authenticated Kubernetes cluster connection detected.[/bold red]\n\n"
                        f"The following IBM-managed infrastructure components require a live cluster\n"
                        f"connection so that generate mode can read their operator-created secrets:\n\n"
                        f"  [cyan]{_ibm_components}[/cyan]\n\n"
                        + (f"[yellow]Error:[/yellow] {_cluster_error_detail}\n\n" if _cluster_error_detail else "")
                        + f"[yellow]To fix:[/yellow]\n"
                        f"  1. Log in to the cluster:  "
                        f"[dim]oc login <api-url> -u <user>[/dim]  or  "
                        f"[dim]kubectl config use-context <context>[/dim]\n"
                        f"  2. Verify the IBM operators are deployed and Ready in namespace "
                        f"[cyan]{namespace}[/cyan]\n"
                        f"  3. Re-run:  [dim]python3 prerequisites.py generate[/dim]\n\n"
                        f"[dim]If you are using external (BYO) PostgreSQL and Redis, re-run gather\n"
                        f"and select the external option to remove the cluster dependency.[/dim]",
                        title="[bold red]Cluster Connection Required[/bold red]",
                        border_style="red",
                        padding=(1, 2),
                    ))
                    raise typer.Exit(code=1)

            state["logger"].info(
                f"Generating infra secrets "
                f"(MG CNPG={_use_ibm_cnpg_mg}, MG Redis={_use_ibm_redis}, WDU CNPG={_use_ibm_cnpg_wdu})"
            )

            # ── Phase header: Infrastructure detection ────────────────────────
            if not state["silent"]:
                _infra_items = []
                if _use_ibm_cnpg_mg:
                    _infra_items.append("IBM CNPG PostgreSQL (Model Gateway)")
                if _use_ibm_redis:
                    _infra_items.append("IBM Redis (Model Gateway)")
                if _use_ibm_cnpg_wdu:
                    _infra_items.append("IBM CNPG PostgreSQL (Enhanced Extraction)")
                _phase_text = Text()
                _phase_text.append("🔌  Connecting to live cluster to read IBM-managed secrets\n\n", style="bold cyan")
                _phase_text.append("Components queried:\n", style="bold yellow")
                for _item in _infra_items:
                    _phase_text.append(f"  • {_item}\n", style="white")
                _phase_text.append(
                    "\nSecrets are read directly from the cluster after IBM operators reach Ready status.",
                    style="dim white",
                )
                console.print()
                console.print(Panel(
                    _phase_text,
                    title="[bold cyan]🔍  Live Cluster Detection — IBM Infrastructure[/bold cyan]",
                    border_style="cyan",
                    padding=(1, 2),
                ))

            try:
                cnpg_redis_generator = GenerateCNPGRedis(
                    mg_properties=model_gateway_prop_dict or {},
                    wdu_properties=wdu_prop_dict or {},
                    deployment_properties=deployment_prop_dict,
                    namespace=namespace,
                    logger=state["logger"],
                )

                # ── MG Postgres external secret ───────────────────────────────
                if _use_ibm_cnpg_mg:
                    # IBM path: discover the deployed CNPG cluster, present a
                    # pre-flight info panel (matching FNCMCluster migration style),
                    # confirm with the customer, then fetch live credentials.

                    # ── Discovery ────────────────────────────────────────────
                    _confirmed_mg_cluster = None
                    try:
                        _mg_candidates = discover_cnpg_clusters(
                            namespace, name_hint="mg", logger=state["logger"]
                        )
                        if not _mg_candidates:
                            raise ClusterResourceNotFoundError(
                                resource_kind="Cluster",
                                resource_name="(name contains 'mg')",
                                namespace=namespace,
                            )

                        if not state["silent"]:
                            # Pre-flight info panel — show what was found and what
                            # will be extracted, before asking for confirmation.
                            _display_cnpg_discovery_info(
                                component="Model Gateway",
                                namespace=namespace,
                                candidates=_mg_candidates,
                            )

                        if not state["silent"]:
                            # Single candidate: confirm. If user says No, fall
                            # through to the select so they can choose a different
                            # cluster.  Only exit on Ctrl-C (None).
                            _mg_use = (
                                questionary.confirm(
                                    f"Use CNPG cluster '{_mg_candidates[0]}' for Model Gateway?",
                                    default=True,
                                    style=Style([
                                        ("qmark", "fg:cyan bold"),
                                        ("question", "bold"),
                                        ("answer", "fg:cyan bold"),
                                    ]),
                                ).ask()
                                if len(_mg_candidates) == 1
                                else False  # skip confirm when multiple — go straight to select
                            )
                            if _mg_use is None:
                                console.print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                                sys.exit(0)
                            if _mg_use:
                                _confirmed_mg_cluster = _mg_candidates[0]
                            else:
                                # User said No (or multiple candidates) — let them pick
                                _all_mg = discover_cnpg_clusters(
                                    namespace, name_hint="", logger=state["logger"]
                                ) or _mg_candidates
                                _confirmed_mg_cluster = questionary.select(
                                    "Select the correct Model Gateway (MG) CNPG cluster:",
                                    choices=[
                                        questionary.Choice(c, value=c) for c in _all_mg
                                    ],
                                    style=Style([
                                        ("qmark", "fg:cyan bold"),
                                        ("question", "bold"),
                                        ("answer", "fg:cyan bold"),
                                        ("pointer", "fg:cyan bold"),
                                        ("highlighted", "fg:cyan"),
                                        ("selected", "fg:green bold"),
                                    ]),
                                ).ask()
                                if _confirmed_mg_cluster is None:
                                    console.print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                                    sys.exit(0)
                        else:
                            # Silent mode: use the first candidate and log a warning
                            _confirmed_mg_cluster = _mg_candidates[0]
                            if len(_mg_candidates) > 1:
                                state["logger"].warning(
                                    f"Multiple MG CNPG clusters found {_mg_candidates}; "
                                    f"silently selecting '{_confirmed_mg_cluster}'"
                                )
                    except ClusterResourceNotFoundError as _e:
                        console.print(Panel(
                            f"[bold red]No CNPG cluster found in namespace '{namespace}'.[/bold red]\n\n"
                            f"[yellow]Deploy the infrastructure first:[/yellow]\n"
                            f"  kubectl apply -f generatedFiles/{namespace}/infrastructure/secrets/ -n {namespace}\n"
                            f"  kubectl apply -f generatedFiles/{namespace}/infrastructure/ibm_pg_cluster_mg_cr.yaml -n {namespace}\n"
                            f"  kubectl get clusters.pg.ibm.com ibm-pg-cluster-mg -n {namespace} -w\n\n"
                            f"[bold red]No Redis cluster found in namespace '{namespace}'.[/bold red]\n\n"
                            f"[yellow]Deploy the infrastructure first:[/yellow]\n"
                            f"  kubectl apply -f generatedFiles/{namespace}/infrastructure/ibm_redis_cr.yaml -n {namespace}\n"
                            f"  kubectl get rediscp ibm-redis-mg -n {namespace} -w\n\n"
                            f"Then re-run:  python3 prerequisites.py generate\n\n"
                            f"[dim]See generatedFiles/{namespace}/infrastructure/README.md for full instructions.[/dim]",
                            title="[bold red]Infrastructure Not Ready[/bold red]",
                            border_style="red",
                            padding=(1, 2),
                        ))
                        raise typer.Exit(code=1)

                    # ── Fetch credentials from confirmed cluster ──────────────
                    try:
                        (
                            _live_host,
                            _live_ca_b64,
                            _live_pwd_b64,
                            _mg_cluster_name,
                        ) = fetch_cnpg_mg_connection(
                            namespace,
                            state["logger"],
                            confirmed_cluster_name=_confirmed_mg_cluster,
                        )
                        import base64 as _b64mod
                        _live_pwd = _b64mod.b64decode(_live_pwd_b64).decode()
                        cnpg_redis_generator.generate_mg_postgres_external_secret(
                            host=_live_host,
                            port=DEFAULT_PG_PORT,
                            username=CNPG_SUPERUSER,
                            password=_live_pwd,
                            dbname=DEFAULT_PG_DBNAME,
                            parameters=CNPG_PG_SSLMODE,
                            live_ca_cert_b64=_live_ca_b64,
                        )
                        state["logger"].info(
                            f"MG postgres external secret populated from live CNPG cluster "
                            f"'{_mg_cluster_name}'"
                        )
                        if not state["silent"]:
                            _display_cnpg_detection(
                                component="Model Gateway",
                                namespace=namespace,
                                host_fqdn=_live_host,
                                ca_secret_name=f"{_mg_cluster_name}-ca",
                                app_secret_name=f"{_mg_cluster_name}-app",
                                ca_cert_b64=_live_ca_b64,
                                password_b64=_live_pwd_b64,
                            )
                    except ClusterResourceNotFoundError as _e:
                        console.print(Panel(
                            f"[bold red]IBM CNPG cluster secrets not found in namespace '{namespace}'.[/bold red]\n\n"
                            f"Required secret: [cyan]{_e.resource_name}[/cyan]\n\n"
                            f"The IBM CNPG cluster must be running before generate mode can read its credentials.\n\n"
                            f"[yellow]Deploy the infrastructure first:[/yellow]\n"
                            f"  kubectl apply -f generatedFiles/{namespace}/infrastructure/secrets/ -n {namespace}\n"
                            f"  kubectl apply -f generatedFiles/{namespace}/infrastructure/ibm_pg_cluster_mg_cr.yaml -n {namespace}\n"
                            f"  kubectl get clusters.pg.ibm.com {_confirmed_mg_cluster} -n {namespace} -w\n\n"
                            f"[bold red]No Redis cluster found in namespace '{namespace}'.[/bold red]\n\n"
                            f"[yellow]Deploy the infrastructure first:[/yellow]\n"
                            f"  kubectl apply -f generatedFiles/{namespace}/infrastructure/ibm_redis_cr.yaml -n {namespace}\n"
                            f"  kubectl get rediscp ibm-redis-mg -n {namespace} -w\n\n"
                            f"Then re-run:  python3 prerequisites.py generate\n\n"
                            f"[dim]See generatedFiles/{namespace}/infrastructure/README.md for full instructions.[/dim]",
                            title="[bold red]Infrastructure Not Ready[/bold red]",
                            border_style="red",
                            padding=(1, 2),
                        ))
                        raise typer.Exit(code=1)
                else:
                    # External path: use property file values from [postgres] section.
                    # Build parameters string from SSL_ENABLED + SSL_MODE, matching
                    # the same SSL-mode logic used for Content DB secrets.
                    _ext_pg = model_gateway_prop_dict.get("postgres", {})
                    _ssl_enabled = str(_ext_pg.get("SSL_ENABLED", False)).lower() in ("true", "1", "yes")
                    _ssl_mode = str(_ext_pg.get("SSL_MODE", "require"))
                    if _ssl_enabled and _ssl_mode in ("verify-ca", "verify-full"):
                        # sslrootcert path matches the volume mount in the MG operator pod
                        _ext_params = f"sslmode={_ssl_mode}&sslrootcert=/postgres-secrets/ca.crt"
                    elif _ssl_enabled:
                        # require or other modes — no cert path needed
                        _ext_params = f"sslmode={_ssl_mode}"
                    else:
                        # SSL disabled — explicitly pass disable so the operator does not
                        # attempt a TLS handshake (DEFAULT_PG_SSLMODE = "sslmode=require"
                        # would be wrong here).
                        _ext_params = "sslmode=disable"
                    cnpg_redis_generator.generate_mg_postgres_external_secret(
                        host=str(_ext_pg.get("HOSTNAME",      "<Required>")),
                        port=str(_ext_pg.get("PORT",          DEFAULT_PG_PORT)),
                        username=str(_ext_pg.get("USERNAME",  "<Required>")),
                        password=str(_ext_pg.get("PASSWORD",  "<Required>")),
                        dbname=str(_ext_pg.get("DATABASE_NAME", DEFAULT_PG_DBNAME)),
                        parameters=_ext_params,
                    )

                # ── MG Redis external secret ──────────────────────────────────
                if _use_ibm_redis:
                    # IBM path: discover the deployed Redis CR, present a
                    # pre-flight info panel (matching FNCMCluster migration style),
                    # confirm with the customer, then fetch live credentials.

                    # ── Discovery ────────────────────────────────────────────
                    _confirmed_redis_cr = None
                    try:
                        _redis_candidates = discover_redis_crs(
                            namespace, name_hint="mg", logger=state["logger"]
                        )
                        if not _redis_candidates:
                            raise ClusterResourceNotFoundError(
                                resource_kind="RedisCP",
                                resource_name="(name contains 'mg')",
                                namespace=namespace,
                            )

                        if not state["silent"]:
                            # Pre-flight info panel
                            _display_redis_discovery_info(
                                namespace=namespace,
                                candidates=_redis_candidates,
                            )

                        if not state["silent"]:
                            _redis_use = (
                                questionary.confirm(
                                    f"Use Redis instance '{_redis_candidates[0]}' for Model Gateway?",
                                    default=True,
                                    style=Style([
                                        ("qmark", "fg:cyan bold"),
                                        ("question", "bold"),
                                        ("answer", "fg:cyan bold"),
                                    ]),
                                ).ask()
                                if len(_redis_candidates) == 1
                                else False
                            )
                            if _redis_use is None:
                                console.print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                                sys.exit(0)
                            if _redis_use:
                                _confirmed_redis_cr = _redis_candidates[0]
                            else:
                                _all_redis = discover_redis_crs(
                                    namespace, name_hint="", logger=state["logger"]
                                ) or _redis_candidates
                                _confirmed_redis_cr = questionary.select(
                                    "Select the correct Model Gateway Redis instance:",
                                    choices=[
                                        questionary.Choice(c, value=c) for c in _all_redis
                                    ],
                                    style=Style([
                                        ("qmark", "fg:cyan bold"),
                                        ("question", "bold"),
                                        ("answer", "fg:cyan bold"),
                                        ("pointer", "fg:cyan bold"),
                                        ("highlighted", "fg:cyan"),
                                        ("selected", "fg:green bold"),
                                    ]),
                                ).ask()
                                if _confirmed_redis_cr is None:
                                    console.print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                                    sys.exit(0)
                        else:
                            _confirmed_redis_cr = _redis_candidates[0]
                            if len(_redis_candidates) > 1:
                                state["logger"].warning(
                                    f"Multiple Redis CRs found {_redis_candidates}; "
                                    f"silently selecting '{_confirmed_redis_cr}'"
                                )
                    except ClusterResourceNotFoundError as _e:
                        console.print(Panel(
                            f"[bold red]No CNPG cluster found in namespace '{namespace}'.[/bold red]\n\n"
                            f"[yellow]Deploy the infrastructure first:[/yellow]\n"
                            f"  kubectl apply -f generatedFiles/{namespace}/infrastructure/secrets/ -n {namespace}\n"
                            f"  kubectl apply -f generatedFiles/{namespace}/infrastructure/ibm_pg_cluster_mg_cr.yaml -n {namespace}\n"
                            f"  kubectl get clusters.pg.ibm.com ibm-pg-cluster-mg -n {namespace} -w\n\n"
                            f"[bold red]No Redis cluster found in namespace '{namespace}'.[/bold red]\n\n"
                            f"[yellow]Deploy the infrastructure first:[/yellow]\n"
                            f"  kubectl apply -f generatedFiles/{namespace}/infrastructure/ibm_redis_cr.yaml -n {namespace}\n"
                            f"  kubectl get rediscp ibm-redis-mg -n {namespace} -w\n\n"
                            f"Then re-run:  python3 prerequisites.py generate\n\n"
                            f"[dim]See generatedFiles/{namespace}/infrastructure/README.md for full instructions.[/dim]",
                            title="[bold red]Infrastructure Not Ready[/bold red]",
                            border_style="red",
                            padding=(1, 2),
                        ))
                        raise typer.Exit(code=1)

                    # ── Fetch credentials from confirmed Redis CR ─────────────
                    try:
                        _live_redis_host, _live_redis_pwd_b64, _redis_cr_name = (
                            fetch_redis_connection(
                                namespace,
                                state["logger"],
                                confirmed_cr_name=_confirmed_redis_cr,
                            )
                        )
                        import base64 as _b64mod2
                        _live_redis_pwd = _b64mod2.b64decode(_live_redis_pwd_b64).decode()
                        cnpg_redis_generator.generate_mg_redis_external_secret(
                            host=_live_redis_host,
                            password=_live_redis_pwd,
                            use_tls=True,
                        )
                        state["logger"].info(
                            f"MG redis external secret populated from live Redis CR '{_redis_cr_name}'"
                        )
                        if not state["silent"]:
                            _display_redis_detection(
                                namespace=namespace,
                                host=_live_redis_host,
                                pwd_secret_name=f"{_redis_cr_name}-secret",
                                password_b64=_live_redis_pwd_b64,
                                cr_name=_redis_cr_name,
                            )
                    except ClusterResourceNotFoundError as _e:
                        console.print(Panel(
                            f"[bold red]IBM CNPG cluster secrets not found in namespace '{namespace}'.[/bold red]\n\n"
                            f"[yellow]Deploy the infrastructure first:[/yellow]\n"
                            f"  kubectl apply -f generatedFiles/{namespace}/infrastructure/secrets/ -n {namespace}\n"
                            f"  kubectl apply -f generatedFiles/{namespace}/infrastructure/ibm_pg_cluster_mg_cr.yaml -n {namespace}\n"
                            f"  kubectl get clusters.pg.ibm.com ibm-pg-cluster-mg -n {namespace} -w\n\n"
                            f"[bold red]IBM Redis secret not found in namespace '{namespace}'.[/bold red]\n\n"
                            f"Required secret: [cyan]{_e.resource_name}[/cyan]\n\n"
                            f"The IBM Redis instance must be running before generate mode can read its credentials.\n\n"
                            f"[yellow]Deploy the infrastructure first:[/yellow]\n"
                            f"  kubectl apply -f generatedFiles/{namespace}/infrastructure/ibm_redis_cr.yaml -n {namespace}\n"
                            f"  kubectl get rediscp {_confirmed_redis_cr} -n {namespace} -w\n\n"
                            f"Then re-run:  python3 prerequisites.py generate\n\n"
                            f"[dim]See generatedFiles/{namespace}/infrastructure/README.md for full instructions.[/dim]",
                            title="[bold red]Infrastructure Not Ready[/bold red]",
                            border_style="red",
                            padding=(1, 2),
                        ))
                        raise typer.Exit(code=1)
                else:
                    # External / disabled path: use [redis] section
                    _ext_redis = model_gateway_prop_dict.get("redis", {}) if model_gateway_prop_dict else {}
                    if str(_ext_redis.get("ENABLED", False)).lower() in ("true", "1", "yes"):
                        cnpg_redis_generator.generate_mg_redis_external_secret(
                            host=str(_ext_redis.get("HOSTNAME", "<Required>")),
                            password=str(_ext_redis.get("PASSWORD", "<Required>")),
                            use_tls=str(_ext_redis.get("USE_TLS", False)).lower() in ("true", "1", "yes"),
                        )

                # ── WDU CNPG providers secret + CA secrets ────────────────────
                if _use_ibm_cnpg_wdu and wdu_prop_dict:
                    # IBM CNPG path: the CNPG cluster CR was already generated during
                    # gather mode into infrastructure/.  Here we only fetch live
                    # credentials from the running cluster to populate the providers
                    # secret and CA secrets (requires CNPG Ready).
                    # Pre-flight info panel + confirmation mirrors FNCMCluster
                    # migration style from gather mode.

                    # ── Discovery ────────────────────────────────────────────
                    _confirmed_wdu_cluster = None
                    try:
                        _wdu_candidates = discover_cnpg_clusters(
                            namespace, name_hint="wdu", logger=state["logger"]
                        )
                        if not _wdu_candidates:
                            raise ClusterResourceNotFoundError(
                                resource_kind="Cluster",
                                resource_name="(name contains 'wdu')",
                                namespace=namespace,
                            )

                        if not state["silent"]:
                            # Pre-flight info panel
                            _display_cnpg_discovery_info(
                                component="Enhanced Extraction (WDU)",
                                namespace=namespace,
                                candidates=_wdu_candidates,
                                show_pooler=True,
                            )

                        if not state["silent"]:
                            _wdu_use = (
                                questionary.confirm(
                                    f"Use CNPG cluster '{_wdu_candidates[0]}' for Enhanced Extraction (WDU)?",
                                    default=True,
                                    style=Style([
                                        ("qmark", "fg:cyan bold"),
                                        ("question", "bold"),
                                        ("answer", "fg:cyan bold"),
                                    ]),
                                ).ask()
                                if len(_wdu_candidates) == 1
                                else False
                            )
                            if _wdu_use is None:
                                console.print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                                sys.exit(0)
                            if _wdu_use:
                                _confirmed_wdu_cluster = _wdu_candidates[0]
                            else:
                                _all_wdu = discover_cnpg_clusters(
                                    namespace, name_hint="", logger=state["logger"]
                                ) or _wdu_candidates
                                _confirmed_wdu_cluster = questionary.select(
                                    "Select the correct Enhanced Extraction (WDU) CNPG cluster:",
                                    choices=[
                                        questionary.Choice(c, value=c) for c in _all_wdu
                                    ],
                                    style=Style([
                                        ("qmark", "fg:cyan bold"),
                                        ("question", "bold"),
                                        ("answer", "fg:cyan bold"),
                                        ("pointer", "fg:cyan bold"),
                                        ("highlighted", "fg:cyan"),
                                        ("selected", "fg:green bold"),
                                    ]),
                                ).ask()
                                if _confirmed_wdu_cluster is None:
                                    console.print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                                    sys.exit(0)
                        else:
                            _confirmed_wdu_cluster = _wdu_candidates[0]
                            if len(_wdu_candidates) > 1:
                                state["logger"].warning(
                                    f"Multiple WDU CNPG clusters found {_wdu_candidates}; "
                                    f"silently selecting '{_confirmed_wdu_cluster}'"
                                )
                    except ClusterResourceNotFoundError as _e:
                        console.print(Panel(
                            f"[bold red]No CNPG cluster found in namespace '{namespace}'.[/bold red]\n\n"
                            f"[yellow]Deploy the infrastructure first:[/yellow]\n"
                            f"  kubectl apply -f generatedFiles/{namespace}/infrastructure/secrets/ -n {namespace}\n"
                            f"  kubectl apply -f generatedFiles/{namespace}/infrastructure/ibm_pg_cluster_wdu_cr.yaml -n {namespace}\n"
                            f"  kubectl get clusters.pg.ibm.com ccx-wdu-pg -n {namespace} -w\n\n"
                            f"Then re-run:  python3 prerequisites.py generate\n\n"
                            f"[dim]See generatedFiles/{namespace}/infrastructure/README.md for full instructions.[/dim]",
                            title="[bold red]Infrastructure Not Ready[/bold red]",
                            border_style="red",
                            padding=(1, 2),
                        ))
                        raise typer.Exit(code=1)

                    # ── Fetch credentials from confirmed WDU cluster ──────────
                    import base64 as _b64wdu
                    try:
                        _wdu_session_fqdn, _wdu_pooler_fqdn, _wdu_ca_b64, _wdu_pwd_b64, _wdu_cluster_name = (
                            fetch_cnpg_wdu_connection(
                                namespace,
                                state["logger"],
                                confirmed_cluster_name=_confirmed_wdu_cluster,
                            )
                        )
                        _wdu_pwd = _b64wdu.b64decode(_wdu_pwd_b64).decode()
                        cnpg_redis_generator.generate_providers_secret(
                            host=_wdu_session_fqdn,
                            port=DEFAULT_PG_PORT,
                            username=CNPG_SUPERUSER,
                            password=_wdu_pwd,
                            dbname=DEFAULT_WDU_PG_DBNAME,
                            txn_host=_wdu_pooler_fqdn,
                            use_cnpg=True,
                        )
                        state["logger"].info(
                            f"WDU providers secret populated from live CNPG cluster "
                            f"'{_wdu_cluster_name}'"
                        )
                        if not state["silent"]:
                            _display_cnpg_detection(
                                component="Enhanced Extraction (WDU)",
                                namespace=namespace,
                                host_fqdn=_wdu_session_fqdn,
                                ca_secret_name=f"{_wdu_cluster_name}-ca",
                                app_secret_name=f"{_wdu_cluster_name}-app",
                                ca_cert_b64=_wdu_ca_b64,
                                password_b64=_wdu_pwd_b64,
                                pooler_fqdn=_wdu_pooler_fqdn,
                            )
                    except ClusterResourceNotFoundError as _e:
                        console.print(Panel(
                            f"[bold red]IBM CNPG cluster secrets not found in namespace '{namespace}'.[/bold red]\n\n"
                            f"Required secret: [cyan]{_e.resource_name}[/cyan]\n\n"
                            f"The IBM CNPG cluster for Enhanced Extraction must be running before\n"
                            f"generate mode can read its credentials.\n\n"
                            f"[yellow]Deploy the infrastructure first:[/yellow]\n"
                            f"  kubectl apply -f generatedFiles/{namespace}/infrastructure/secrets/ -n {namespace}\n"
                            f"  kubectl apply -f generatedFiles/{namespace}/infrastructure/ibm_pg_cluster_wdu_cr.yaml -n {namespace}\n"
                            f"  kubectl get clusters.pg.ibm.com {_confirmed_wdu_cluster} -n {namespace} -w\n\n"
                            f"Then re-run:  python3 prerequisites.py generate\n\n"
                            f"[dim]See generatedFiles/{namespace}/infrastructure/README.md for full instructions.[/dim]",
                            title="[bold red]Infrastructure Not Ready[/bold red]",
                            border_style="red",
                            padding=(1, 2),
                        ))
                        raise typer.Exit(code=1)

                elif wdu_prop_dict:
                    # ── External/BYO WDU postgres ─────────────────────────────
                    # Generate providers secret from property file values.
                    # ccx-wdu.toml is written with [postgres_session] and
                    # [postgres_transaction] sections; fall back to legacy [postgres]
                    # for property files created before the split was introduced.
                    if not state["silent"]:
                        console.print(
                            "  [cyan]→[/cyan] Generating providers secret for "
                            "Enhanced Extraction (WDU) …"
                        )
                    _wdu_pg_legacy   = wdu_prop_dict.get("postgres", {})
                    _wdu_pg_session  = wdu_prop_dict.get("postgres_session",  _wdu_pg_legacy)
                    _wdu_pg_txn      = wdu_prop_dict.get("postgres_transaction", _wdu_pg_legacy)
                    # Port and dbname are shared (same database, same port on both poolers).
                    _wdu_port  = str(_wdu_pg_session.get("PORT",          _wdu_pg_txn.get("PORT",          DEFAULT_PG_PORT)))
                    _wdu_db    = str(_wdu_pg_session.get("DATABASE_NAME", _wdu_pg_txn.get("DATABASE_NAME", DEFAULT_WDU_PG_DBNAME)))
                    _wdu_prov_ok = cnpg_redis_generator.generate_providers_secret(
                        # session connection (direct host)
                        host=str(_wdu_pg_session.get("HOSTNAME", "<Required>")),
                        port=_wdu_port,
                        username=str(_wdu_pg_session.get("USERNAME", "<Required>")),
                        password=str(_wdu_pg_session.get("PASSWORD", "<Required>")),
                        dbname=_wdu_db,
                        # transaction connection (separate pooler host/credentials when set)
                        txn_host=str(_wdu_pg_txn.get("HOSTNAME",  _wdu_pg_session.get("HOSTNAME", "<Required>"))),
                        txn_username=str(_wdu_pg_txn.get("USERNAME", _wdu_pg_session.get("USERNAME", "<Required>"))),
                        txn_password=str(_wdu_pg_txn.get("PASSWORD", _wdu_pg_session.get("PASSWORD", "<Required>"))),
                    )
                    if not _wdu_prov_ok:
                        state["logger"].warning("WDU providers secret generation failed")
                    else:
                        state["logger"].info("WDU providers secret generated successfully")

                state["logger"].info("Infra secrets generated successfully")

            except typer.Exit:
                raise
            except Exception as e:
                state["logger"].error(f"Error generating infra secrets: {str(e)}")
                state["logger"].exception("Detailed error:")

        # Generate Model Gateway artifacts if Model Gateway property file is present
        if model_gateway_prop and model_gateway_prop_dict:
            state["logger"].info("Generating Model Gateway artifacts")
            try:
                mg_generator = GenerateModelGateway(
                    model_gateway_properties=model_gateway_prop_dict,
                    deployment_properties=deployment_prop_dict,
                    namespace=namespace,
                    ingress_properties=ingress_prop_dict,
                    logger=state["logger"],
                )
                if mg_generator.generate_all():
                    state["logger"].info("Model Gateway artifacts generated successfully")
                else:
                    state["logger"].warning("Some Model Gateway artifacts failed to generate")
            except Exception as e:
                state["logger"].error(f"Error generating Model Gateway artifacts: {str(e)}")
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
                model_gateway_properties=model_gateway_prop_dict,
                wdu_properties=wdu_prop_dict,
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
    generate_generate_results(
        generate_folder=generated_folder,
        use_ibm_cnpg_mg=_use_ibm_cnpg_mg,
        use_ibm_cnpg_wdu=_use_ibm_cnpg_wdu,
        namespace=namespace,
    )

    _has_mg = bool(model_gateway_prop and model_gateway_prop_dict)

    # ── Post-generate MG infra callout ────────────────────────────────────────
    # When IBM-managed CNPG or Redis is selected, the MG CR MUST NOT be applied
    # until those operators report ready.  Print a prominent ordered checklist so
    # users who skip validate --apply know exactly what to do and why.
    _use_ibm_cnpg_mg_local = _use_ibm_cnpg_mg   # already resolved above
    _use_ibm_redis_local   = _use_ibm_redis      # already resolved above

    if _has_mg and (_use_ibm_cnpg_mg_local or _use_ibm_redis_local):
        _infra_lines = []
        _infra_lines.append(
            "[bold yellow]⚠  Model Gateway — apply secrets then CR[/bold yellow]\n"
        )
        _infra_lines.append(
            "[white]Apply the generated secrets first, then the Model Gateway CR.[/white]\n"
        )

        _step = 1

        # Step: apply all generated secrets
        _infra_lines.append(
            f"[cyan]{_step}.[/cyan] [bold]Apply all secrets[/bold]\n"
            f"   [dim]kubectl apply -f generatedFiles/{namespace}/secrets/ -n {namespace}[/dim]"
        )
        _step += 1

        # Step: apply MG CR
        _infra_lines.append(
            f"\n[cyan]{_step}.[/cyan] [bold]Apply Model Gateway CR[/bold]\n"
            f"   [dim]kubectl apply -f generatedFiles/{namespace}/ibm_model_gateway_cr_production.yaml -n {namespace}[/dim]"
        )
        _step += 1

        # Step: provision a provider via model-gateway.py
        _infra_lines.append(
            f"\n[cyan]{_step}.[/cyan] [bold]Provision a provider and models[/bold]\n"
            f"   [dim]# Once the Model Gateway CR is Ready, configure a provider:\n"
            f"   python3 model-gateway.py config url https://<gateway-host>\n"
            f"   python3 model-gateway.py login -u admin\n"
            f"   python3 model-gateway.py provision  [italic]# interactive end-to-end setup[/italic][/dim]"
        )

        _infra_lines.append(
            "\n[dim]💡 Tip: run [bold]python3 prerequisites.py validate --apply[/bold] to have the script "
            "handle steps 1–2 automatically, including readiness polling, cert and password injection.[/dim]"
        )

        print()
        print(Panel(
            "\n".join(_infra_lines),
            title="[bold yellow]📋 Next Steps — Model Gateway Infrastructure[/bold yellow]",
            border_style="yellow",
            padding=(1, 2),
            expand=False
        ))
        print()


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
        silent_path = os.path.join("silent_config", "silent_install_prerequisites.toml")
        gather = sg.SilentGatherPrereqOptions(state["logger"], silent_path)
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
    wdu_prop_file = os.path.join(prop_folder, "ccx-wdu.toml")
    model_gateway_prop_file = os.path.join(prop_folder, "ccx-model-gateway.toml")

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
    wdu_prop = None
    model_gateway_prop = None
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

        # Read WDU property file if it exists
        if os.path.exists(wdu_prop_file):
            from helper_scripts.property.read_prop import ReadPropWDU
            wdu_prop = ReadPropWDU(wdu_prop_file, state["logger"])

        # Read Model Gateway property file if it exists
        if os.path.exists(model_gateway_prop_file):
            from helper_scripts.property.read_prop import ReadPropModelGateway
            model_gateway_prop = ReadPropModelGateway(model_gateway_prop_file, state["logger"])

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

        if wdu_prop:
            wdu_prop_dict = wdu_prop.to_dict()
        else:
            wdu_prop_dict = {}

        if model_gateway_prop:
            model_gateway_prop_dict = model_gateway_prop.to_dict()
        else:
            model_gateway_prop_dict = {}

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
                         mg_prop=model_gateway_prop_dict if model_gateway_prop_dict else {},
                         wdu_prop=wdu_prop_dict if wdu_prop_dict else {},
                         pvc_size=pvc_size,
                         namespace=namespace)

    # _fncm_db_number: FNCM-only databases (CPE + BAN) that require DATABASE_TYPE
    # from content_db_server.toml.  Used to gate validate_all_db, which crashes with
    # KeyError if called when that file is absent (e.g. WDU standalone).
    _fncm_db_number = 0

    if "CPE" in deployment_prop_dict.keys():
        if deployment_prop_dict["CPE"]:
            _fncm_db_number += 1
            _fncm_db_number += len(db_prop_dict["_os_ids"])

    if "BAN" in deployment_prop_dict.keys():
        if deployment_prop_dict["BAN"]:
            _fncm_db_number += 1

    # db_number: total DB connections shown in the display panel (FNCM + MG + WDU).
    db_number = _fncm_db_number

    # Count MG external PG as a DB to validate (CNPG is self-managed, skip)
    _validate_mg_db = (
        bool(model_gateway_prop_dict) and
        str(model_gateway_prop_dict.get("postgres", {}).get("USE_IBM_CNPG", False)).lower()
        not in ("true", "1", "yes")
    )
    # Mirror the key-fallback used inside validate_wdu_db():
    # prefer "postgres_session" (new PgBouncer TOML layout), fall back to bare "postgres".
    _wdu_pg_block = wdu_prop_dict.get("postgres_session") or wdu_prop_dict.get("postgres", {})
    _validate_wdu_db = (
        bool(wdu_prop_dict) and
        str(_wdu_pg_block.get("USE_IBM_CNPG", False)).lower()
        not in ("true", "1", "yes")
    )
    if _validate_mg_db:
        db_number += 1
    if _validate_wdu_db:
        db_number += 1

    storageclass_number = len(vobject.get_unique_storageclass())

    # Check SSL certificates - only pass properties that exist (same as generate mode)
    _mg_use_ibm_cnpg = str(model_gateway_prop_dict.get("postgres", {}).get("USE_IBM_CNPG", False)).lower() in ("true", "1", "yes")
    _wdu_use_ibm_cnpg = str(_wdu_pg_block.get("USE_IBM_CNPG", False)).lower() in ("true", "1", "yes")
    missing_certs, incorrect_certs, mg_cnpg_cert_reminder = check_ssl_folders(
                                                       db_prop=db_prop_dict if db_prop_dict else None,
                                                       ldap_prop=ldap_prop_dict if ldap_prop_dict else None,
                                                       ssl_cert_folder=ssl_cert_folder,
                                                       deploy_prop=deployment_prop_dict,
                                                       idp_prop=idp_prop_dict,
                                                       scim_prop=scim_prop_dict,
                                                       graphql_prop=aiservices_integration_prop_dict if aiservices_integration_prop_dict else None,
                                                       aiservices_prop=aiservices_prop_dict if aiservices_prop_dict else None,
                                                       mg_use_ibm_cnpg=_mg_use_ibm_cnpg,
                                                       wdu_prop=wdu_prop_dict if wdu_prop_dict else None,
                                                       wdu_use_ibm_cnpg=_wdu_use_ibm_cnpg)
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
    if wdu_prop:
        unified_display.add_property_validation_errors(wdu_prop, "WDU")
    if model_gateway_prop:
        unified_display.add_property_validation_errors(model_gateway_prop, "Model Gateway")
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
    if mg_cnpg_cert_reminder:
        console.print(
            "\n[bold yellow]⚠  Model Gateway (IBM CNPG):[/bold yellow] Copy [cyan]ca.crt[/cyan] from the "
            "[cyan]ibm-pg-cluster-mg-ca[/cyan] secret into "
            "[cyan]ssl-certs/model-gateway/serverca/[/cyan] before running generate.\n"
            "   kubectl get secret ibm-pg-cluster-mg-ca -n <namespace> "
            "-o jsonpath='{.data.ca\\.crt}' | base64 -d > ssl-certs/model-gateway/serverca/ca.crt"
        )

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
        
        if validate_database and _fncm_db_number > 0:
            display.add_test(
                "database",
                "Database Connections",
                "Infrastructure",
                _fncm_db_number
            )
        if validate_database and _validate_mg_db:
            display.add_test(
                "mg_database",
                "Model Gateway PostgreSQL",
                "Infrastructure",
                1
            )
        if validate_database and _validate_wdu_db:
            display.add_test(
                "wdu_database",
                "WDU PostgreSQL",
                "Infrastructure",
                1
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
        
        if validate_ai_services and aiservices_prop and not model_gateway_prop:
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
                
                # Validating FNCM databases (CPE/BAN only — requires DATABASE_TYPE
                # from content_db_server.toml; WDU/MG PG are validated separately below)
                if validate_database and _fncm_db_number > 0:
                    display.start_test("database")
                    display.add_detail("Testing database connectivity...")
                    success = vobject.validate_all_db_with_display(display)
                    display.complete_test("database", success,
                        "All database connections validated" if success else "Database validation failed")
                
                # Validating Model Gateway external PostgreSQL
                if validate_database and _validate_mg_db:
                    display.start_test("mg_database")
                    display.add_detail("Testing Model Gateway PostgreSQL connectivity...")
                    success = vobject.validate_mg_db_with_display(display)
                    display.complete_test("mg_database", success,
                        "Model Gateway PostgreSQL validated" if success else "Model Gateway DB validation failed")

                # Validating WDU external PostgreSQL
                if validate_database and _validate_wdu_db:
                    display.start_test("wdu_database")
                    display.add_detail("Testing WDU PostgreSQL connectivity...")
                    success = vobject.validate_wdu_db_with_display(display)
                    display.complete_test("wdu_database", success,
                        "WDU PostgreSQL validated" if success else "WDU DB validation failed")

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
                
                # Validating AI Services (skip for model gateway deployments)
                if validate_ai_services and aiservices_prop and not model_gateway_prop:
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
                            if model_gateway_prop:
                                # Model Gateway manages its own provider configuration
                                # via model-gateway.py post-deploy; no providers are
                                # required in aiservices_providers.toml.
                                display.complete_test("ai_services", True,
                                    "AI Services valid (providers managed by Model Gateway)")
                            else:
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

        # In silent mode, --apply is the only way to enable automatic apply.
        # Without it, validation completes without applying or prompting.
        effective_apply = apply

        # Check if Vault is enabled (needed by both branches)
        vault_enabled = deployment_prop_dict.get('VAULT_ENABLED', False)

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

            if effective_apply:
                state["logger"].info("Auto-applying artifacts (--apply flag set)")
                if vault_enabled:
                    state["logger"].info("Vault is enabled - applying SecretProviderClass resources")
                vobject.auto_apply_secrets_ssl()
                vobject.auto_apply_configmaps()
                vobject.auto_apply_metrics()
                vobject.auto_apply_cr()
            elif state["silent"]:
                state["logger"].info("Silent mode: validation passed. No artifacts were applied (--apply not set).")
            else:
                # Interactive mode without --apply: prompt for each artifact type
                print()
                apply_info = Text()
                apply_info.append("📦 ", style="bold cyan")
                apply_info.append("Ready to Apply Artifacts", style="bold white")
                apply_info.append("\n\nYou can now apply the generated artifacts to your cluster.", style="white")
                
                if vault_enabled:
                    apply_info.append("\n\n", style="white")
                    apply_info.append("🔒 Vault Integration Enabled", style="bold purple")
                    apply_info.append("\nSecretProviderClass resources will be applied instead of regular Kubernetes Secrets.", style="dim")
                
                print(Panel(apply_info, border_style="cyan", padding=(1, 2)))
                print()
                
                secrets_prompt = (
                    "Apply SSL certificates and SecretProviderClass resources to the cluster?"
                    if vault_enabled else
                    "Apply SSL certificates and Secrets to the cluster?"
                )
                apply_ssls_secrets = questionary.confirm(secrets_prompt, default=True, style=Style([
                    ('qmark', 'fg:cyan bold'), ('question', 'bold'), ('answer', 'fg:cyan bold'),
                ])).ask()
                if apply_ssls_secrets is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                if apply_ssls_secrets:
                    vobject.auto_apply_secrets_ssl()
                
                print()
                apply_configmaps = questionary.confirm("Apply ConfigMaps to the cluster?", default=True, style=Style([
                    ('qmark', 'fg:cyan bold'), ('question', 'bold'), ('answer', 'fg:cyan bold'),
                ])).ask()
                if apply_configmaps is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                if apply_configmaps:
                    vobject.auto_apply_configmaps()
                
                print()
                apply_metrics = questionary.confirm("Apply Metrics (IBMServiceMeterDefinition) to the cluster?", default=True, style=Style([
                    ('qmark', 'fg:cyan bold'), ('question', 'bold'), ('answer', 'fg:cyan bold'),
                ])).ask()
                if apply_metrics is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                if apply_metrics:
                    vobject.auto_apply_metrics()

                print()
                apply_cr = questionary.confirm("Apply Custom Resources (CRs) to the cluster?", default=True, style=Style([
                    ('qmark', 'fg:cyan bold'), ('question', 'bold'), ('answer', 'fg:cyan bold'),
                ])).ask()
                if apply_cr is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                if apply_cr:
                    vobject.auto_apply_cr()
        else:
            # ── Validation failed ─────────────────────────────────────────────
            print()
            warning_text = Text()
            warning_text.append("⚠ ", style="bold yellow")
            warning_text.append("Some Validation Checks Failed", style="bold yellow")
            warning_text.append("\n\nReview the validation results above and fix any issues before applying.", style="white")
            
            print(Panel(warning_text, border_style="yellow", padding=(1, 2)))
            print()

            if state["silent"]:
                # Silent mode must never prompt. A failed validation is always
                # a non-zero result, and --apply additionally makes the abort
                # explicit because artifacts were requested.
                state["logger"].error(
                    "Silent mode: validation checks failed — artifacts were NOT applied. "
                    "Fix the issues reported above and re-run."
                )
                print(Panel(
                    "[bold red]✗ Silent mode: validation failed — apply aborted.[/bold red]\n\n"
                    "One or more prerequisite checks did not pass.\n"
                    "No artifacts were applied. Fix the reported issues and re-run validation.\n"
                    "Use [bold]--apply[/bold] only when you want a successful validation to apply artifacts.",
                    title="[bold red]Silent Install — Apply Aborted[/bold red]",
                    border_style="red",
                    padding=(1, 2)
                ))
                sys.exit(1)
            elif effective_apply:
                # Interactive --apply flag: honour the flag but make the failure
                # a hard stop — do not force-apply over broken prerequisites.
                state["logger"].error(
                    "Validation checks failed — artifacts were NOT applied. "
                    "Fix the issues above and re-run with --apply."
                )
                print(Panel(
                    "[bold red]✗ Validation failed — apply aborted.[/bold red]\n\n"
                    "One or more prerequisite checks did not pass.\n"
                    "Applying artifacts over a broken environment may cause an unrecoverable\n"
                    "deployment state.  Fix the issues above and re-run:\n\n"
                    "  [bold]python3 prerequisites.py validate --apply[/bold]",
                    title="[bold red]Apply Aborted[/bold red]",
                    border_style="red",
                    padding=(1, 2)
                ))
                sys.exit(1)
            else:
                # Interactive mode without --apply: ask with default=False to
                # make the cautious choice the path of least resistance.
                warning_info = Text()
                warning_info.append("⚠ ", style="bold yellow")
                warning_info.append("Proceed with Caution", style="bold yellow")
                warning_info.append("\n\nSome validations failed. Applying artifacts may cause deployment issues.", style="white")
                
                if vault_enabled:
                    warning_info.append("\n\n", style="white")
                    warning_info.append("🔒 Vault Integration Enabled", style="bold purple")
                    warning_info.append("\nSecretProviderClass resources will be applied instead of regular Kubernetes Secrets.", style="dim")
                
                print(Panel(warning_info, border_style="yellow", padding=(1, 2)))
                print()
                
                secrets_prompt = (
                    "Apply SSL certificates and SecretProviderClass resources despite validation failures?"
                    if vault_enabled else
                    "Apply SSL certificates and Secrets despite validation failures?"
                )
                apply_ssls_secrets = questionary.confirm(secrets_prompt, default=False, style=Style([
                    ('qmark', 'fg:yellow bold'), ('question', 'bold'), ('answer', 'fg:yellow bold'),
                ])).ask()
                if apply_ssls_secrets is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                if apply_ssls_secrets:
                    vobject.auto_apply_secrets_ssl()
                
                print()
                apply_configmaps = questionary.confirm("Apply ConfigMaps despite validation failures?", default=False, style=Style([
                    ('qmark', 'fg:yellow bold'), ('question', 'bold'), ('answer', 'fg:yellow bold'),
                ])).ask()
                if apply_configmaps is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                if apply_configmaps:
                    vobject.auto_apply_configmaps()
                
                print()
                apply_metrics = questionary.confirm("Apply Metrics (IBMServiceMeterDefinition) despite validation failures?", default=False, style=Style([
                    ('qmark', 'fg:yellow bold'), ('question', 'bold'), ('answer', 'fg:yellow bold'),
                ])).ask()
                if apply_metrics is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                if apply_metrics:
                    vobject.auto_apply_metrics()

                print()
                apply_cr = questionary.confirm("Apply Custom Resources (CRs) despite validation failures?", default=False, style=Style([
                    ('qmark', 'fg:yellow bold'), ('question', 'bold'), ('answer', 'fg:yellow bold'),
                ])).ask()
                if apply_cr is None:
                    print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
                    sys.exit(0)
                if apply_cr:
                    vobject.auto_apply_cr()


if __name__ == "__main__":
    app()
