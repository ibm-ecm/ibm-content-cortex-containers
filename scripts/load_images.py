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

# Script to copy images to the private registry
'''
This script loads images to a private registry and
generates a set of tags and repositories to be copied
there is an extract mode to create the list of images and a load option to load that list of images
the default mode creates a list and uploads those images to private registry
'''
import logging
import os
import toml

import questionary
from questionary import Style
import typer
from click import style
from rich import print
from rich.console import Console
from rich.live import Live
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, MofNCompleteColumn, \
    TimeElapsedColumn
from rich.table import Table
from rich.text import Text
from typing_extensions import Annotated

from helper_scripts.gather import gather as g
from helper_scripts.gather import silent_gather as sg
from helper_scripts.loadimages import load_extract as le
from helper_scripts.utilities.config_models import validate_loadimages_config
from helper_scripts.utilities.interface import clear, display_issues, display_prereq_passed, \
    generate_loadimages_results, generate_loadimage_results, display_config_validation_errors, \
    display_prereq_validation_table, display_toml_syntax_error
from helper_scripts.utilities.utilities import validate_image_details_file, prereq_checks, read_version_toml

__version__ = "26.1.0"

app = typer.Typer()

state = {
    "verbose": False,
    "silent": False,
    "logger": logging,
    "dev": False,
    "setup": None,
    "image_details": "",
    "dryrun": False,
    "version_data": {},
    "tls_verify": True,
    "prod_entitlement_key": "",
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
    file_handler = logging.FileHandler("loadimages.log")
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
        print(f"IBM Content Cortex Load Images CLI: {__version__}")
        raise typer.Exit()


def push_cncf_images():
    load = le.LoadExtract(console, state["logger"], silent=state["silent"], dev=state["dev"],
                          folder_path=state["image_details"], tls_verify=state["tls_verify"])

    image_detail_file = os.path.join(state["image_details"], "imageDetails.toml")

    image_prop_dict = validate_image_details_file(logger=state["logger"], image_tag_file=image_detail_file)

    load.parse_toml_file(image_details_dict=image_prop_dict)

    if not state["silent"]:
        state["setup"].collect_verify_entitlement_key()
        state["setup"].collect_verify_private_registry()

        # Sync TLS verification setting from interactive selection (silent mode
        # keeps the value set at construction time from the --tls-verify flag)
        state["tls_verify"] = state["setup"]._tls_verify
        load._tls_verify = state["tls_verify"]
        state["logger"].info(f"TLS verification after user selection: {state['tls_verify']}")

    private_registry = state["setup"].private_registry_server
    if not private_registry:
        state["logger"].error(
            "Private registry is not set. "
            "Ensure PRIVATE_REGISTRY_URL is configured in the silent install file."
        )
        raise SystemExit(1)

    load.private_registry_server = private_registry

    # Forward credentials so Skopeo can authenticate at copy time.
    # Source: IBM ICR always uses username "cp" + entitlement key as password.
    # Destination: the private registry username/password.
    load.src_creds = f"cp:{state['setup']._entitlement_key}"
    load.dest_creds = f"{state['setup']._private_registry_username}:{state['setup']._private_registry_password}"

    # In dev mode a second production entitlement key is needed for cp.icr.io
    # images (Redis/Model Gateway operands) that have no preprod equivalent.
    # Sourced from --prod-entitlement-key flag (both interactive and silent modes).
    if state["dev"] and state["prod_entitlement_key"]:
        load.prod_src_creds = f"cp:{state['prod_entitlement_key']}"

    # Forward the private registry CA cert directory if configured.
    # Skopeo --dest-cert-dir expects a directory of PEM files, so we use the
    # directory that contains the cert file the user specified.
    _ssl_cert = getattr(state["setup"], "_private_registry_ssl_cert", None) or ""
    if _ssl_cert:
        load.dest_cert_dir = os.path.dirname(os.path.abspath(_ssl_cert))
        state["logger"].info(f"Private registry cert dir for Skopeo: {load.dest_cert_dir}")

    number_of_images = load.number_of_images

    if not state["silent"]:
        print()
        try:
            start_copy = questionary.confirm(
                "Do you want to proceed with pushing the images to the private registry?",
                default=True,
                style=Style([
                    ('question', 'fg:cyan bold'),
                    ('answer', 'fg:green bold')
                ])
            ).ask()
            
            if start_copy is None or not start_copy:
                exit(1)
        except Exception:
            # Fallback to simple confirmation if questionary fails
            print("[yellow]⚠ Using fallback confirmation[/yellow]")
            if input("Proceed with pushing images to private registry? (Y/n): ").lower() in ['n', 'no']:
                exit(1)
    if state["dryrun"]:
        exit()

    clear(console)

    print(Panel.fit("Starting IBM Content Cortex Image Push", style="cyan"))
    state["logger"].info(f"Starting IBM Content Cortex Image Push")
    
    # Use new Live-based progress tracker with multi-threading
    _interrupted = False
    try:
        load.copy_images_with_live_tracker()
    except KeyboardInterrupt:
        _interrupted = True
        print("\n")
        print(Panel.fit("⚠ Image copy interrupted by user", style="yellow"))
    except Exception as e:
        state["logger"].error(f"Error during image copy: {e}")
        print(f"\n[red]Error during image copy: {e}[/red]")
        raise SystemExit(1)

    summary = load.image_push_summary
    print(generate_loadimage_results(summary))

    failed = summary.get("failed", [])
    if failed:
        for name, error in failed:
            state["logger"].error(f"Image push failure: {name}" + (f" — {error}" if error else ""))
        state["logger"].error(f"Image push completed with {len(failed)} failure(s).")
        raise SystemExit(1)

    if _interrupted:
        raise SystemExit(1)


def generate_cncf_images():
    extract = le.LoadExtract(console, state["logger"], silent=state["silent"], dev=state["dev"],
                             folder_path=state["image_details"], version_data=state["version_data"], tls_verify=state["tls_verify"])

    # In dev mode the operand images use release tags (e.g. "26.0.1") that do
    # not exist on the staging registry.  Require a sprint tag override before
    # proceeding so the manifest is always usable.
    if state["dev"]:
        dev_image_tag = os.environ.get("DEV_IMAGE_TAG", "")
        if not dev_image_tag:
            if state["silent"]:
                state["logger"].error(
                    "DEV_IMAGE_TAG is not set. "
                    "Export the sprint tag before running in dev mode, "
                    "e.g.: export DEV_IMAGE_TAG=2601.SP17"
                )
                raise SystemExit(1)
            else:
                dev_image_tag = questionary.text(
                    "DEV_IMAGE_TAG is not set. Enter the sprint tag for operand images:",
                    style=Style([
                        ('question', 'fg:cyan bold'),
                        ('answer',   'fg:green bold'),
                    ]),
                ).ask()
                if not dev_image_tag:
                    state["logger"].error("No sprint tag provided — aborting dev mode generate.")
                    raise SystemExit(1)
        extract.dev_image_tag = dev_image_tag
        state["logger"].info(f"Dev mode: overriding operand tags with DEV_IMAGE_TAG={dev_image_tag}")

    # ── Operand images from CR descriptors ──────────────────────────────────
    # Content operands (CPE, Navigator, CSS, etc.)
    extract.parse_content_template()

    # AI Services operands
    extract.parse_ai_services_template()

    # WDU operands (wdu-runtime, wdu-models under cp.icr.io/cp/cp4a/iadp/)
    if os.path.exists(extract._wdu_pattern_path):
        extract.parse_wdu_cr_template()

    # ── Operator images from descriptor operator.yaml files ─────────────────
    # Content operator
    if os.path.exists(extract._content_operator_path):
        extract.parse_operator_template(extract._content_operator_path, "ibm-content-operator")

    # AI Services operator
    if os.path.exists(extract._ai_services_operator_path):
        extract.parse_operator_template(extract._ai_services_operator_path, "ibm-ccx-ai-services-operator")

    # Model Gateway operator + operand images
    if os.path.exists(extract._model_gateway_operator_path):
        extract.parse_operator_template(extract._model_gateway_operator_path, "ibm-model-gateway-operator")
    if os.path.exists(extract._model_gateway_images_txt_path):
        extract.parse_images_txt(extract._model_gateway_images_txt_path)

    # WDU operator
    if os.path.exists(extract._wdu_operator_path):
        extract.parse_operator_template(extract._wdu_operator_path, "ibm-ccx-wdu-services-operator")

    # Redis operator + operand images
    if os.path.exists(extract._redis_operator_path):
        extract.parse_operator_template(extract._redis_operator_path, "ibm-redis-cp-operator")
    if os.path.exists(extract._redis_images_txt_path):
        extract.parse_images_txt(extract._redis_images_txt_path)

    # CNPG operator + operand images (pg-16, pg-17, pg-18, pg-pooler, bundle, catalog)
    if os.path.exists(extract._cnpg_operator_path):
        extract.parse_operator_template(extract._cnpg_operator_path, "ibm-pg-operator")
    if os.path.exists(extract._cnpg_images_txt_path):
        extract.parse_images_txt(extract._cnpg_images_txt_path)

    # Usage Metering and License Service — images live on production icr.io/cpopen only
    # (no preprod equivalent). Included in all modes; _PRODUCTION_ONLY_PREFIXES ensures
    # they are never rewritten to preprod.icr.io in dev mode.
    if os.path.exists(extract._usage_metering_operator_path):
        extract.parse_operator_template(extract._usage_metering_operator_path, "ibm-usage-metering-operator")

    if os.path.exists(extract._license_service_operator_path):
        extract.parse_operator_template(extract._license_service_operator_path, "ibm-licensing-operator")

    # Legacy Content operator (backward compatibility — root-level descriptor)
    if os.path.exists(extract._operator_path):
        extract.parse_operator_template(extract._operator_path, "ibm-fncm-operator")

    extract.create_image_details_file()

    layout = generate_loadimages_results(state["image_details"])
    print(layout)


def display_mode_version(mode: str, description: str):
    """
    Display the mode and version of the script in a modern, visually appealing format.
    
    Args:
        mode: The operation mode
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
    if state["dryrun"]:
        active_flags.append("🔍 Dry Run")
    
    if state["dev"]:
        active_flags.append("🔧 Development Mode")
    
    if state["silent"]:
        active_flags.append("🤫 Silent Mode")
    
    if state["verbose"]:
        active_flags.append("📢 Verbose Logging")
    
    if not state["tls_verify"]:
        active_flags.append("🔓 TLS Verification Disabled")
    
    # Add active flags if any
    if active_flags:
        header_table.add_row("", "")  # Empty row for spacing
        for flag in active_flags:
            header_table.add_row("", f"[bold magenta]{flag}[/bold magenta]")
    
    # Create the main panel with modern styling
    print(Panel(
        header_table,
        title="[bold white]📦 IBM Content Cortex Load Images CLI[/bold white]",
        border_style="bright_blue",
        padding=(1, 2),
        expand=False
    ))
    print()


@app.command()
def generate():
    """
        Generate the image details file.
    """
    generate_cncf_images()


@app.command()
def push(
    prod_entitlement_key: Annotated[str, typer.Option(
        "--prod-entitlement-key",
        help=(
            "Production IBM Entitlement Registry key for cp.icr.io. "
            "Required in --dev mode to pull operand images (Redis, Model Gateway) "
            "that are only available on the production entitled registry."
        ),
        rich_help_panel="Customization and Utils")] = ""):
    """
        Push images to a registry based on existing image details file.
    """
    if prod_entitlement_key:
        state["prod_entitlement_key"] = prod_entitlement_key
    elif state["dev"]:
        print(Panel.fit(
            "⚠ --dev is active but --prod-entitlement-key was not provided.\n"
            "Images from cp.icr.io (Redis haproxy/operand, Model Gateway go-proxy)\n"
            "will fail to pull. Pass --prod-entitlement-key <key> to fix this.",
            style="bold yellow"
        ))
        print()

    push_cncf_images()


# main function
@app.callback(invoke_without_command=True)
def main(ctx: typer.Context,
         version: Annotated[bool, typer.Option(
             "--version", help="Show version and exit.",
             callback=version_callback, is_eager=True)] = False,
         silent: Annotated[bool, typer.Option(
             help="Enable Silent Install (no prompts).",
             rich_help_panel="Customization and Utils")] = False,
         verbose: Annotated[bool, typer.Option(
             help="Enable verbose logging.",
             rich_help_panel="Customization and Utils")] = False,
         tls_verify: Annotated[bool, typer.Option(
             help="Enable TLS verification for Skopeo operations.",
             rich_help_panel="Customization and Utils")] = True,
         dryrun: Annotated[bool, typer.Option(
             help="Perform a dry run",
             rich_help_panel="Customization and Utils")] = False,
         dev: Annotated[bool, typer.Option(hidden=True)] = False,
         prod_entitlement_key: Annotated[str, typer.Option(
             "--prod-entitlement-key",
             help=(
                 "Production IBM Entitlement Registry key for cp.icr.io. "
                 "Required in --dev mode when using the default (generate + push) mode. "
                 "For push subcommand only, pass the flag after 'push' instead."
             ),
             hidden=True)] = ""):
    """
        IBM Content Cortex Load Images CLI.
    """

    if verbose:
        state["verbose"] = True
        FILE_LOG_LEVEL = logging.DEBUG
    else:
        FILE_LOG_LEVEL = logging.WARNING

    state["logger"] = setup_logger(FILE_LOG_LEVEL)

    if prod_entitlement_key:
        state["prod_entitlement_key"] = prod_entitlement_key

    if silent:
        state["silent"] = True
    if dev:
        state["dev"] = True
    if dryrun:
        state["dryrun"] = True
    
    # Set TLS verification state (explicitly set both True and False cases)
    state["tls_verify"] = tls_verify
    state["logger"].info(f"TLS verification is set to: {state['tls_verify']}")

    # Anchor to the directory containing this script (container-samples/scripts/)
    # so the path is correct regardless of what directory the user runs from.
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    state["image_details"] = os.path.join(_script_dir, "imageDetails")

    if not os.path.exists(state["image_details"]):
        os.mkdir(state["image_details"])

    checks = []
    files = []
    wdu_files = []

    if ctx.invoked_subcommand is None:
        display_mode_version("Extract and Push Images",
                             "Generate ImageDetails and Push images to Private Registry")
        
        # Display what will be done
        info_text = Text()
        info_text.append("This mode will:\n\n", style="bold white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Extract image details from descriptors\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Generate image manifest file\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Push images to private registry\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Verify image availability\n", style="white")
        
        print(Panel(
            info_text,
            title="[bold white]📦 Image Operations[/bold white]",
            border_style="cyan",
            padding=(1, 2)
        ))
        print()

        if dev and not state["prod_entitlement_key"]:
            print(Panel.fit(
                "⚠ --dev is active but --prod-entitlement-key was not provided.\n"
                "Images from cp.icr.io (Redis haproxy/operand, Model Gateway go-proxy)\n"
                "will fail to pull. Pass --prod-entitlement-key <key> to fix this.",
                style="bold yellow"
            ))
            print()
        
        checks = ["skopeo"]
        files = [
            "content-cortex/content/ibm_content_full_cr.yaml",
            "content-cortex/ai-services/ibm_ai_services_full_cr.yaml",
            "content-cortex/content/operator.yaml",
            "content-cortex/ai-services/operator.yaml",
            "model-gateway/operator.yaml",
            "wdu/operator.yaml",
            "redis/operator.yaml",
            "cnpg/operator.yaml",
            "usage-metering/operator.yaml",
            "license-service/operator.yaml",
        ]
        wdu_files = [
            "descriptors/wdu/ibm_wdu_services_full_cr.yaml",
        ]
    elif ctx.invoked_subcommand == "push":
        display_mode_version("Push Images", "Push Images to Private Registry Only")
        
        # Display what will be done
        info_text = Text()
        info_text.append("This mode will:\n\n", style="bold white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Read existing image manifest\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Push images to private registry\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Verify image availability\n", style="white")
        
        print(Panel(
            info_text,
            title="[bold white]📦 Image Operations[/bold white]",
            border_style="cyan",
            padding=(1, 2)
        ))
        print()
        
        checks = ["skopeo"]
        files = []

    elif ctx.invoked_subcommand == "generate":
        display_mode_version("Generate Image Detail File", "Generate Image Details File Only")
        
        # Display what will be done
        info_text = Text()
        info_text.append("This mode will:\n\n", style="bold white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Extract image details from descriptors\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Generate image manifest file\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Save for later push operation\n", style="white")
        
        print(Panel(
            info_text,
            title="[bold white]📦 Image Operations[/bold white]",
            border_style="cyan",
            padding=(1, 2)
        ))
        print()
        
        checks = []
        files = [
            "content-cortex/content/ibm_content_full_cr.yaml",
            "content-cortex/ai-services/ibm_ai_services_full_cr.yaml",
            "content-cortex/content/operator.yaml",
            "content-cortex/ai-services/operator.yaml",
            "model-gateway/operator.yaml",
            "wdu/operator.yaml",
            "redis/operator.yaml",
            "cnpg/operator.yaml",
            "usage-metering/operator.yaml",
            "license-service/operator.yaml",
        ]
        wdu_files = [
            "descriptors/wdu/ibm_wdu_services_full_cr.yaml",
        ]
    # container-samples/ is one level above the scripts/ submodule directory.
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _cs_root = os.path.dirname(_script_dir)
    descriptor_path = os.path.join(_cs_root, "descriptors")

    required_files = []
    for file in files:
        required_files.append(os.path.join(descriptor_path, file))
    for file in wdu_files:
        required_files.append(os.path.join(_cs_root, file))

    missing_tools, results, files = prereq_checks(logger=state["logger"], prereqs=checks, files=required_files)

    # Print table of prerequisites that are missing
    if len(missing_tools) > 0 or len(files) > 0:
        layout = display_issues(tools=missing_tools, descriptors=files)
        print(layout)
        exit(1)
    else:
        display_prereq_validation_table(results)

    # Read Version File
    version_path = os.path.join(_cs_root, "version.toml")

    if os.path.exists(version_path):
        state["version_data"] = read_version_toml(version_path, state["logger"])
        state["version_data"]["VERSION"] = state["version_data"]["VERSION"].split('-')[0]
    else:
        state["version_data"] = {}

    if not state["silent"]:
        # this is the user details object which does pre-checks and collects some necessary details
        state["setup"] = g.GatherOptions(state["logger"], console, script_type="load_extract", dev=state["dev"], tls_verify=state["tls_verify"])
    else:
        # this is the user details object which does pre-checks and collects some necessary details
        silent_path = os.path.join(_script_dir, "silent_config", "silent_install_loadimages.toml")

        # Validate configuration with Pydantic before proceeding
        state["logger"].info(f"Validating silent load-images configuration: {silent_path}")
        try:
            import toml as _toml
            with open(silent_path, 'r') as _f:
                _config_dict = _toml.load(_f)
            _success, _, _validation_errors = validate_loadimages_config(_config_dict)
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

        state["setup"] = sg.SilentGatherOptions(state["logger"], silent_path, script_type="load_extract", dev=state["dev"], tls_verify=state["tls_verify"])
        # For 'generate', no registry access is needed — skip network verification.
        state["setup"].silent_parse_load_images_file(
            verify=(ctx.invoked_subcommand != "generate")
        )

        # If the registry does not use SSL (SSL_ENABLED=false), skopeo must also
        # skip TLS verification for the destination — regardless of the --tls-verify
        # CLI flag (which only controls the Python requests session used for the
        # pre-flight reachability / auth check).
        if not state["setup"]._private_registry_ssl_enabled:
            state["tls_verify"] = False
            state["logger"].info(
                "PRIVATE_REGISTRY_SSL_ENABLED=false — setting tls_verify=False "
                "so skopeo uses --dest-tls-verify=false"
            )

    if ctx.invoked_subcommand is None:
        generate()
        push()


if __name__ == "__main__":
    app()
