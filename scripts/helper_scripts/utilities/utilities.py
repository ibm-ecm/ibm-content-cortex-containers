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
import base64
import logging
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
from typing import Literal, Optional, Dict
import yaml

import requests
import toml
from requests import ConnectTimeout
from rich import print
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from toml.decoder import TomlDecodeError

from .prerequisites_utilites import command_available, check_java_version, \
    get_skopeo_version, filepath_validate, get_ibm_pak_version, get_oc_version, get_mirror_version
from ..property.read_prop import ReadPropImageTag
from ..utilities import kubernetes_utilites as k

# Set up logger for this module
logger = logging.getLogger(__name__)

# Type alias for resource types
ResourceType = Literal[
    "cluster role binding",
    "catalog source",
    "operator group",
    "subscription"
]


def extract_catalog_name_from_descriptors(setup):
    """
    Extract catalog source name from catalogsource.yaml descriptor file.
    
    Args:
        setup: Setup object that may contain descriptor paths or files
        
    Returns:
        str: Catalog source name from descriptor, or default fallback
    """
    try:
        # Try multiple approaches to find the catalog file
        catalog_file = None
        
        # Approach 1: Check if descriptor_path attribute exists
        if hasattr(setup, 'descriptor_path') and setup.descriptor_path:
            catalog_file = os.path.join(setup.descriptor_path, "op-olm", "catalogsource.yaml")
        
        # Approach 2: Look in common descriptor locations relative to scripts directory
        if not catalog_file or not os.path.exists(catalog_file):
            # Get the scripts directory (where this file is located)
            scripts_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            # Go up one level to container-samples, then into descriptors/content
            base_path = os.path.join(scripts_dir, "..", "descriptors", "content")
            test_file = os.path.join(base_path, "op-olm", "catalogsource.yaml")
            if os.path.exists(test_file):
                catalog_file = test_file
        
        # Approach 3: Try from current working directory
        if not catalog_file or not os.path.exists(catalog_file):
            test_file = os.path.join(os.getcwd(), "descriptors", "content", "op-olm", "catalogsource.yaml")
            if os.path.exists(test_file):
                catalog_file = test_file
        
        if catalog_file and os.path.exists(catalog_file):
            with open(catalog_file, 'r') as f:
                catalog_yaml = yaml.safe_load(f)
                name = catalog_yaml.get('metadata', {}).get('name', 'ibm-content-operator-catalog')
                return name
    except Exception:
        pass
    return "ibm-content-operator-catalog"  # Fallback default (updated from ibm-fncm-operator-catalog)


def extract_operator_name_from_descriptors(setup):
    """
    Extract operator deployment name from operator.yaml descriptor file.
    
    Args:
        setup: Setup object that may contain descriptor paths or files
        
    Returns:
        str: Operator deployment name from descriptor, or default fallback
    """
    try:
        # Try multiple approaches to find the operator file
        operator_file = None
        
        # Approach 1: Check if descriptor_path attribute exists
        if hasattr(setup, 'descriptor_path') and setup.descriptor_path:
            operator_file = os.path.join(setup.descriptor_path, "operator.yaml")
        
        # Approach 2: Look in common descriptor locations relative to scripts directory
        if not operator_file or not os.path.exists(operator_file):
            # Get the scripts directory (where this file is located)
            scripts_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            # Go up one level to container-samples, then into descriptors/content
            base_path = os.path.join(scripts_dir, "..", "descriptors", "content")
            test_file = os.path.join(base_path, "operator.yaml")
            if os.path.exists(test_file):
                operator_file = test_file
        
        # Approach 3: Try from current working directory
        if not operator_file or not os.path.exists(operator_file):
            test_file = os.path.join(os.getcwd(), "descriptors", "content", "operator.yaml")
            if os.path.exists(test_file):
                operator_file = test_file
        
        if operator_file and os.path.exists(operator_file):
            with open(operator_file, 'r') as f:
                operator_yaml = yaml.safe_load(f)
                name = operator_yaml.get('metadata', {}).get('name', 'ibm-content-operator')
                return name
    except Exception:
        pass
    return "ibm-content-operator"  # Fallback default (updated from ibm-fncm-operator)

# Function to log in to a registry using podman
def login_to_registry_podman(registry_host, username, password, logger, ssl_enabled=False, ssl_cert_path='', registry_port='', registry_path='', tls_verify=True):
    try:
        # Build the registry URL
        registry = ""

        if registry_host:
            registry += registry_host
        if registry_port:
            registry += f":{registry_port}"
        if registry_path:
            registry += f"/{registry_path}"

        if ssl_enabled and tls_verify:
            # Allow self-signed certificates
            command = ["podman", "login", registry, "-u", username, "--password-stdin", "--cert-dir", ssl_cert_path, f"--tls-verify={tls_verify}"]
        else:
            command = ["podman", "login", registry, "-u", username, "--password-stdin", f"--tls-verify={tls_verify}"]

        # Using subprocess to run the Podman login command
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, error = process.communicate(input=password.encode())

        if process.returncode == 0:
            logger.info("Login succeeded!")
            return True
        else:
            logger.info(f"Login failed. {error.decode()}")
            print()
            print(Text(f"{error.decode()}", style="bold red"))
            return False
    except Exception as e:
        logger.info(f"Error: {e}")
        return False


# Function to log in to a registry using skopeo
def login_to_registry_skopeo(registry_host, username, password, logger, ssl_enabled=False, ssl_cert_path='', registry_port='', registry_path='', tls_verify=True):
    """
    Log in to a container registry using skopeo.
    
    Args:
        registry_host: Registry hostname
        username: Registry username
        password: Registry password
        logger: Logger instance
        ssl_enabled: Whether SSL is enabled
        ssl_cert_path: Path to SSL certificate directory
        registry_port: Registry port
        registry_path: Registry path
        tls_verify: Whether to verify TLS certificates
        
    Returns:
        bool: True if login succeeded, False otherwise
    """
    try:
        # Build the registry URL for authentication
        # NOTE: Skopeo login authenticates against the base registry (hostname:port)
        # The path (e.g., /cp in cp.stg.icr.io/cp) is NOT included in authentication
        registry = ""

        if registry_host:
            registry += registry_host
        if registry_port:
            registry += f":{registry_port}"
        # Path is intentionally NOT added for authentication

        # Build skopeo login command
        # Note: TLS flags must come before the registry address
        command = ["skopeo", "login"]
        
        # Add TLS verification flag before registry address
        if not tls_verify:
            command.append("--tls-verify=false")
        
        # Add certificate directory if SSL is enabled
        if ssl_enabled and ssl_cert_path:
            command.extend(["--cert-dir", ssl_cert_path])
        
        # Add registry address and credentials
        command.extend([registry, "-u", username, "--password-stdin"])

        # Using subprocess to run the skopeo login command
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, error = process.communicate(input=password.encode())

        if process.returncode == 0:
            logger.info("Skopeo login succeeded!")
            return True
        else:
            logger.info(f"Skopeo login failed. {error.decode()}")
            print()
            print(Text(f"Skopeo: {error.decode()}", style="bold red"))
            return False
    except Exception as e:
        logger.info(f"Skopeo login error: {e}")
        return False


# Function to log in to both podman and skopeo registries
def login_to_registry_both(registry_host, username, password, logger, ssl_enabled=False, ssl_cert_path='', registry_port='', registry_path='', tls_verify=True):
    """
    Log in to a container registry using both podman and skopeo.
    This ensures both tools can access the registry for image operations.
    
    Args:
        registry_host: Registry hostname
        username: Registry username
        password: Registry password
        logger: Logger instance
        ssl_enabled: Whether SSL is enabled
        ssl_cert_path: Path to SSL certificate directory
        registry_port: Registry port
        registry_path: Registry path
        tls_verify: Whether to verify TLS certificates
        
    Returns:
        bool: True if both logins succeeded, False otherwise
    """
    try:
        logger.info("Logging in to registry with podman and skopeo...")
        
        # Login with podman
        podman_success = login_to_registry_podman(
            registry_host=registry_host,
            username=username,
            password=password,
            logger=logger,
            ssl_enabled=ssl_enabled,
            ssl_cert_path=ssl_cert_path,
            registry_port=registry_port,
            registry_path=registry_path,
            tls_verify=tls_verify
        )
        
        if not podman_success:
            logger.error("Podman login failed")
            return False
        
        # Check if skopeo is available
        if command_available("skopeo"):
            # Login with skopeo
            skopeo_success = login_to_registry_skopeo(
                registry_host=registry_host,
                username=username,
                password=password,
                logger=logger,
                ssl_enabled=ssl_enabled,
                ssl_cert_path=ssl_cert_path,
                registry_port=registry_port,
                registry_path=registry_path,
                tls_verify=tls_verify
            )
            
            if not skopeo_success:
                logger.warning("Skopeo login failed, but podman login succeeded")
                print()
                print(Text("⚠ Warning: Skopeo login failed. Image copy operations may be affected.", style="bold yellow"))
                # Return True since podman succeeded - skopeo is optional
                return True
            
            logger.info("Successfully logged in with both podman and skopeo")
        else:
            logger.info("Skopeo not available, only podman login performed")
        
        return True
        
    except Exception as e:
        logger.error(f"Error during registry login: {e}")
        return False


def generate_license_usage_secrets(airgap_config: Dict, namespace: str, logger, descriptor_path: Path) -> bool:
    """
    Generate or update license-advisor and usage-metering secrets based on airgap configuration.
    Creates copies of template files rather than modifying the originals.
    
    Args:
        airgap_config: Dictionary containing airgap configuration
        namespace: Kubernetes namespace for the secrets
        logger: Logger instance
        descriptor_path: Path to descriptor files
        
    Returns:
        bool: True if secrets were generated/updated successfully
    """
    try:
        logger.info("Generating license-advisor and usage-metering secrets")
        
        enable_software_central = airgap_config.get('enable_software_central', False)
        entitlement_key = airgap_config.get('entitlement_key', '')
        
        # Paths to template secret files (originals - do not modify)
        ls_secret_template_path = descriptor_path / "license-service" / "licensing_upload_secret.yaml"
        ums_secret_template_path = descriptor_path / "usage-metering" / "ibmusagemetering_upload_secret.yaml"
        
        # Paths to generated secret files (copies with actual values) in scripts/.tmp directory
        scripts_dir = Path(__file__).parent.parent  # Go up to scripts directory
        tmp_dir = scripts_dir / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        ls_secret_path = tmp_dir / "licensing_upload_secret.yaml"
        ums_secret_path = tmp_dir / "ibmusagemetering_upload_secret.yaml"
        
        # Paths to CR files
        ls_cr_path = descriptor_path / "license-service" / "licensing_cr.yaml"
        ums_cr_path = descriptor_path / "usage-metering" / "ibmusagemetering_cr.yaml"
        
        if enable_software_central and entitlement_key:
            # Connected deployment - create secrets with entitlement key
            logger.info("Creating secrets for connected deployment with Software Central upload enabled")
            
            # Encode entitlement key to base64
            encoded_key = base64.b64encode(entitlement_key.encode()).decode()
            
            # Read template files and create copies with actual values
            # License-advisor secret
            if ls_secret_template_path.exists():
                with open(ls_secret_template_path, 'r') as f:
                    ls_secret_content = f.read()
                # Replace placeholder with actual encoded key and namespace
                ls_secret_content = ls_secret_content.replace('<base64-encoded-key>', encoded_key)
                ls_secret_content = ls_secret_content.replace('namespace: ibm-licensing', f'namespace: {namespace}')
            else:
                # Fallback: generate from scratch if template doesn't exist
                ls_secret_content = f"""################################################################################
#
# Licensed Materials - Property of IBM
#
# (C) Copyright IBM Corp. 2026. All Rights Reserved.
#
# US Government Users Restricted Rights - Use, duplication or
# disclosure restricted by GSA ADP Schedule Contract with IBM Corp.
#
###############################################################################
apiVersion: v1
kind: Secret
metadata:
  name: ibm-ccx-ls-secret
  namespace: {namespace}
type: Opaque
data:
  entitlementKey: {encoded_key}
"""
            
            # Usage-metering secret
            if ums_secret_template_path.exists():
                with open(ums_secret_template_path, 'r') as f:
                    ums_secret_content = f.read()
                # Replace placeholder with actual encoded key
                ums_secret_content = ums_secret_content.replace('<base64-encoded-key>', encoded_key)
                # Add namespace if not present in template
                if 'namespace:' not in ums_secret_content:
                    ums_secret_content = ums_secret_content.replace(
                        'metadata:\n   name: ibm-ccx-ums-secret',
                        f'metadata:\n   name: ibm-ccx-ums-secret\n   namespace: {namespace}'
                    )
            else:
                # Fallback: generate from scratch if template doesn't exist
                ums_secret_content = f"""################################################################################
#
# Licensed Materials - Property of IBM
#
# (C) Copyright IBM Corp. 2026. All Rights Reserved.
#
# US Government Users Restricted Rights - Use, duplication or
# disclosure restricted by GSA ADP Schedule Contract with IBM Corp.
#
###############################################################################
kind: Secret
apiVersion: v1
metadata:
  name: ibm-ccx-ums-secret
  namespace: {namespace}
data:
  token: {encoded_key}
type: Opaque
"""
            
            # Write generated secrets to files (not overwriting templates)
            with open(ls_secret_path, 'w') as f:
                f.write(ls_secret_content)
            logger.info(f"Created license-advisor secret at {ls_secret_path}")
            
            with open(ums_secret_path, 'w') as f:
                f.write(ums_secret_content)
            logger.info(f"Created usage-metering secret at {ums_secret_path}")
            
            # Update CRs to enable softwareCentral
            update_cr_software_central(ls_cr_path, True, logger)
            update_cr_software_central(ums_cr_path, True, logger)
            
            print()
            print(Panel.fit(
                "✓ License-advisor and usage-metering secrets created\n"
                "✓ Software Central upload [bold green]enabled[/bold green]",
                style="green",
                title="[bold]Secrets Generated[/bold]"
            ))
            
        else:
            # Airgapped deployment - disable Software Central upload
            logger.info("Airgapped deployment detected - disabling Software Central upload")
            
            # Update CRs to disable softwareCentral
            update_cr_software_central(ls_cr_path, False, logger)
            update_cr_software_central(ums_cr_path, False, logger)
            
            # Remove generated secret files if they exist (not templates)
            if ls_secret_path.exists():
                ls_secret_path.unlink()
                logger.info(f"Removed generated license-advisor secret file")
            
            if ums_secret_path.exists():
                ums_secret_path.unlink()
                logger.info(f"Removed generated usage-metering secret file")
            
            print()
            print(Panel.fit(
                "✓ Software Central upload [bold red]disabled[/bold red]\n"
                "  (Airgapped deployment configuration)\n\n"
                "[yellow]Note:[/yellow] License and usage data must be uploaded manually to Software Central.",
                style="yellow",
                title="[bold]Configuration Updated[/bold]"
            ))
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to generate license/usage secrets: {str(e)}")
        print()
        print(Panel.fit(
            f"❌ Failed to generate secrets:\n{str(e)}",
            style="bold red"
        ))
        return False


def update_cr_software_central(cr_path: Path, enable: bool, logger) -> bool:
    """
    Update Custom Resource YAML to enable/disable softwareCentral upload.
    
    Args:
        cr_path: Path to CR YAML file
        enable: True to enable softwareCentral, False to disable
        logger: Logger instance
        
    Returns:
        bool: True if updated successfully
    """
    try:
        if not cr_path.exists():
            logger.warning(f"CR file not found: {cr_path}")
            return False
        
        with open(cr_path, 'r') as f:
            cr_data = yaml.safe_load(f)
        
        # Update based on CR type
        if 'IBMLicensing' in str(cr_data.get('kind', '')):
            # License Service CR
            if 'spec' not in cr_data:
                cr_data['spec'] = {}
            if 'softwareCentral' not in cr_data['spec']:
                cr_data['spec']['softwareCentral'] = {}
            
            cr_data['spec']['softwareCentral']['enable'] = enable
            if enable:
                cr_data['spec']['softwareCentral']['entitlementKeySecret'] = 'ibm-ccx-ls-secret'
            else:
                # Remove entitlementKeySecret if disabling
                cr_data['spec']['softwareCentral'].pop('entitlementKeySecret', None)
                
        elif 'IBMUsageMetering' in str(cr_data.get('kind', '')):
            # Usage Metering CR
            if 'spec' not in cr_data:
                cr_data['spec'] = {}
            if 'sender' not in cr_data['spec']:
                cr_data['spec']['sender'] = {}
            if 'softwareCentral' not in cr_data['spec']['sender']:
                cr_data['spec']['sender']['softwareCentral'] = {}
            
            cr_data['spec']['sender']['softwareCentral']['enable'] = enable
            if enable:
                cr_data['spec']['sender']['softwareCentral']['entitlementKeySecret'] = 'ibm-ccx-ums-secret'
            else:
                # Remove entitlementKeySecret if disabling
                cr_data['spec']['sender']['softwareCentral'].pop('entitlementKeySecret', None)
        
        # Write updated CR back to file
        with open(cr_path, 'w') as f:
            yaml.dump(cr_data, f, default_flow_style=False, sort_keys=False)
        
        logger.info(f"Updated {cr_path.name} - softwareCentral.enable = {enable}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to update CR {cr_path}: {str(e)}")
        return False


# Function to check oc plugins
def check_oc_plugins(logger, plugin):
    try:
        logger.info("OpenShift CLI available")
        env_vars = {
            'PATH': os.environ["PATH"],
            'HOME': os.environ["HOME"]
        }

        command = f"oc {plugin} --help"
        oc_plugins = subprocess.run(command, env=env_vars, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # Get Error code from the command
        if oc_plugins.returncode == 0:
            logger.info(f"{plugin} plugin available")
            return True

        logger.info(f"{plugin} plugin not available")
        return False
    except Exception as e:
        logger.info(f"Error: {e}")
        return


# Function to do the prerequisite checks before the script starts
def prereq_checks(logger, prereqs=None, files=None, ccx_version='26.0.0', helm_chart_source='packaged'):
    logger.info(f"Checking prerequisites ...")
    if prereqs is None:
        prereqs = []

    if files is None:
        files = []
    try:
        missing_tools = []
        missing_files = []

        prereq_summary = {
            "podman": False,
            "java": False,
            "java_version": "",
            "k8s_version": "",
            "connection": False,
            "helm_charts": True,
            "helm_charts_missing": [],
            "skopeo": False,
            "skopeo_version": "",
            "oc": False,
            "oc_version": "",
            "mirror": False,
            "mirror_version": "",
            "ibm-pak": False,
            "ibm-pak_version": "",
            "helm": False,
            "helm_version": ""
        }

        platform_type = platform.system()

        if len(files) > 0:
            descriptor_present = []
            prereq_summary["descriptor_files"] = True
            for descriptor in files:
                present = filepath_validate(filepath=descriptor)
                if not present:
                    # Get only the file name
                    descriptor = os.path.basename(descriptor)
                    missing_files.append(descriptor)
                descriptor_present.append(present)
            if not all(descriptor_present):
                logger.info(f"Prerequisites failed -> Descriptor files not present - {missing_files}")
                prereq_summary["descriptor_files"] = False

        # Podman check removed - authentication now done via HTTP API
        # Podman only needed in load_images.py for airgap mode
        if any(x in prereqs for x in ["podman"]):
            logger.info(f"Checking if the 'podman' is available.")
            podman = command_available("podman")

            if podman:
                logger.info("Podman available for airgap image operations")
                prereq_summary["podman"] = True
            else:
                logger.info("Podman not present")
                logger.info("Note: Podman only required for airgap image operations")
                missing_tools.append("Podman CLI (for airgap operations)")

        if "oc" in prereqs:
            logger.info(f"Checking if the 'oc' command is available.")
            oc = command_available("oc")
            if not oc:
                logger.info("Prerequisites failed -> OpenShift CLI not installed")
                missing_tools.append("OpenShift CLI")
            else:
                logger.info("OpenShift CLI available")
                prereq_summary["oc"] = True
                prereq_summary["oc_version"] = get_oc_version(logger)

                if "mirror" in prereqs:
                    if platform_type.lower() == "windows":
                        missing_tools.append("Windows OS")
                        logger.info("Prerequisites failed -> Windows Machine not supported")

                    elif platform_type.lower() == "darwin":
                        missing_tools.append("Mac OS")
                        logger.info("Prerequisites failed -> Mac OS not supported")

                    else:
                        mirror = check_oc_plugins(logger, "mirror")
                        if not mirror:
                            logger.info("Prerequisites failed -> oc mirror plugin not installed")
                            missing_tools.append("mirror plugin")
                        else:
                            logger.info("oc mirror plugin available")
                            prereq_summary["mirror"] = True
                            prereq_summary["mirror_version"] = get_mirror_version(logger)
                            logger.info(f"Mirror Version: {prereq_summary['mirror_version']}")

                if "ibm-pak" in prereqs:
                    logger.info(f"Checking if the 'ibm-pak' plugin is available.")
                    ibm_pak = check_oc_plugins(logger, "ibm-pak")
                    if not ibm_pak:
                        logger.info("Prerequisites failed -> oc ibm-pak plugin not installed")
                        missing_tools.append("ibm-pak plugin")
                    else:
                        logger.info("oc ibm-pak plugin available")
                        prereq_summary["ibm-pak"] = True
                        prereq_summary["ibm-pak_version"] = get_ibm_pak_version(logger)
                        logger.info(f"IBM PAK Version: {prereq_summary['ibm-pak_version']}")

        if "powershell" in prereqs:
            logger.info(f"Checking if 'PowerShell' is available.")
            powershell_present = command_available("powershell.exe")

            if not powershell_present:
                logger.info("Prerequisites failed -> PowerShell not installed")
                missing_tools.append("PowerShell")
            else:
                logger.info("PowerShell available")
                prereq_summary["powershell"] = True

        if "keytool" in prereqs:
            logger.info(f"Checking if 'keytool' is available.")
            keytool_present = command_available("keytool")

            if not keytool_present:
                logger.info("Prerequisites failed -> keytool not installed")
                missing_tools.append("keytool")
            else:
                logger.info("keytool available")
                prereq_summary["keytool"] = True

        # Java Check
        if "java" in prereqs:

            logger.info(f"Checking if 'Java' is available.")
            java_present = command_available("java")

            if not java_present:
                logger.info("Prerequisites failed -> Java not installed")
                missing_tools.append("Java")
            else:
                logger.info("Java available")
                prereq_summary["java"] = True
                logger.info("Checking Java version")
                java_version = check_java_version(ccx_version)

                # Collect the Java version even if it is incorrect

                if not java_version:
                    logger.info("Prerequisites failed -> Java version not found")
                    missing_tools.append("Java")
                else:
                    logger.info(f"Java version found: {java_version}")
                    prereq_summary["java_version"] = java_version
                    
                prereq_summary["expected_java_version"] = "25"

                logger.info("Expected Java version: " + prereq_summary["expected_java_version"])

        # check if cluster is logged in
        if "connection" in prereqs:
            try:
                kube = k.KubernetesUtilities(logger)
                logger.info("Checking if user is logged into the OCP console")
                server_version, ocp_logged_in = kube.get_kubernetes_version()

                if not ocp_logged_in:
                    logger.info("Prerequisites failed -> User is not logged into the OCP console")
                    missing_tools.append("connection")
                else:
                    logger.info("User is logged into the OCP console")
                    prereq_summary["connection"] = True
                    prereq_summary["k8s_version"] = server_version

            except (ConnectTimeout, ConnectionError) as e:
                logger.info(f"Could not connect to kubernetes cluster: {e}")
                missing_tools.append("connection")
            except Exception as e:
                logger.info("Prerequisites failed -> User is not logged into the OCP console")
                missing_tools.append("connection")

        if "helm" in prereqs:
            logger.info("Checking if Helm CLI is available")
            helm_available = command_available("helm")
            if not helm_available:
                logger.info("Prerequisites failed -> Helm CLI not installed")
                missing_tools.append("Helm CLI")
            else:
                logger.info("Helm CLI available")
                prereq_summary["helm"] = True
                # Get Helm version
                try:
                    result = subprocess.run(
                        ["helm", "version", "--short"],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        # Extract version from output like "v3.12.0+g..."
                        version_output = result.stdout.strip()
                        if version_output.startswith('v'):
                            helm_version = version_output.split('+')[0]  # Remove commit hash
                            prereq_summary["helm_version"] = helm_version
                            logger.info(f"Helm version: {helm_version}")
                            
                            # Validate Helm version is 4.x or above
                            try:
                                version_num = helm_version.lstrip('v')
                                major_version = int(version_num.split('.')[0])
                                if major_version < 4:
                                    # Store version info for modern validation display
                                    logger.error(f"Helm version {helm_version} is not supported. Required: 4.x or above")
                                    missing_tools.append(f"Helm 4.x+ (found {helm_version})")
                                    prereq_summary["helm"] = False
                                    prereq_summary["helm_version_invalid"] = True
                                    prereq_summary["helm_version_found"] = helm_version
                                else:
                                    logger.info(f"Helm version {helm_version} meets minimum requirement (4.x+)")
                                    prereq_summary["helm_version_invalid"] = False
                            except (ValueError, IndexError) as ve:
                                logger.warning(f"Could not parse Helm version '{helm_version}': {ve}")
                                prereq_summary["helm_version"] = helm_version
                        else:
                            prereq_summary["helm_version"] = version_output
                    else:
                        prereq_summary["helm_version"] = "unknown"
                except Exception as e:
                    logger.warning(f"Could not get Helm version: {e}")
                    prereq_summary["helm_version"] = "unknown"
        
        # Only check for packaged charts if explicitly using packaged source
        # For github/public/url sources, charts are downloaded automatically
        if "helm_charts" in prereqs and helm_chart_source == "packaged":
            from pathlib import Path
            from helper_scripts.helm.helm_deployer import HelmDeployer
            
            try:
                # Check for all possible operator charts
                all_operators = ["content", "ai-services", "license-service", "usage-metering"]
                helm_deployer = HelmDeployer(logger=logger)
                missing_charts = helm_deployer._check_packaged_charts(all_operators)
                
                if missing_charts:
                    # Store results silently - error will be displayed by _handle_prerequisite_validation
                    prereq_summary["helm_charts"] = False
                    prereq_summary["helm_charts_missing"] = missing_charts
                    # Add to missing_tools to block deployment
                    missing_tools.append("Helm Charts")
                else:
                    prereq_summary["helm_charts"] = True
                    prereq_summary["helm_charts_missing"] = []
            except Exception as e:
                # Silent failure - error will be displayed by _handle_prerequisite_validation
                prereq_summary["helm_charts"] = False
                missing_tools.append("Helm Charts")

        if "skopeo" in prereqs:
            logger.info("Checking if skopeo is available")
            if platform_type == "windows":
                missing_tools.append("Windows OS")
                logger.info("Prerequisites failed -> Windows Machine not supported")
            else:
                skopeo_available = command_available("skopeo")
                if not skopeo_available:
                    logger.info("Prerequisites failed -> Skopeo not installed")
                    missing_tools.append("Skopeo CLI")
                else:
                    logger.info("Skopeo CLI available")
                    prereq_summary["skopeo"] = True
                    prereq_summary["skopeo_version"] = get_skopeo_version(logger)

        return missing_tools, prereq_summary, missing_files

    except Exception as e:
        logger.info(
            f"Exception from prerequisites check function -  {str(e)}")


# Function to read a version toml file
def read_version_toml(file_path, logger):
    """
    Read version data from TOML file with support for operator-specific sections.
    
    The TOML file structure includes:
    - Top-level bundle information (VERSION, APP_VERSION, CASE_VERSION, etc.)
    - Operator-specific sections matching descriptor folder names:
      [content], [usage-metering], [license-service], [ai-services]
    
    Each operator section contains: VERSION, APP_VERSION, CHANNEL, CSV, CASE_VERSION, CASE_NAME
    
    Args:
        file_path: Path to version.toml file
        logger: Logger instance
        
    Returns:
        dict: Version data with top-level keys and nested operator sections
    """
    try:
        logger.info(f"Reading version data from file: {file_path}")
        version_data = toml.loads(open(file_path, encoding="utf-8").read())
        logger.info(f"Version data read: {version_data}")

        # Process top-level VERSION for backward compatibility
        display = version_data.get("VERSION", "26.0.0")
        version = display.split("-")[0]
        version_data["VERSION"] = version
        version_data["DISPLAY"] = display
        
        # Log operator versions if present (using descriptor folder names)
        operator_sections = ["content", "usage-metering", "license-service", "ai-services"]
        for op_section in operator_sections:
            if op_section in version_data:
                op_version = version_data[op_section].get("VERSION", "N/A")
                logger.info(f"{op_section} version: {op_version}")
        
        return version_data
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
        return None
    except TomlDecodeError as e:
        logger.error(f"Error reading the toml file: {e}")
        return None
    except Exception as e:
        logger.error(f"Error reading version file: {e}")
        return None


def get_operator_version(version_data: dict, operator_type: str, key: str = "VERSION") -> str:
    """
    Get version information for a specific operator from version data.
    
    Args:
        version_data: Dictionary containing version data from version.toml
        operator_type: Type of operator - matches descriptor folder names:
                      'content', 'usage-metering', 'license-service', 'ai-services'
        key: Specific key to retrieve (VERSION, APP_VERSION, CHANNEL, CSV,
             CASE_VERSION, CASE_NAME). Defaults to "VERSION"
    
    Returns:
        str: The requested version value, or bundle-level value as fallback
        
    Examples:
        >>> get_operator_version(version_data, 'content', 'VERSION')
        '26.0.0'
        >>> get_operator_version(version_data, 'usage-metering', 'CHANNEL')
        'v26.0'
    """
    if not version_data:
        return "26.0.0"  # Default fallback
    
    # Operator type matches TOML section name (descriptor folder name)
    section_name = operator_type.lower()
    
    if section_name in version_data:
        # Get value from operator-specific section
        operator_data = version_data[section_name]
        if key in operator_data:
            return operator_data[key]
    
    # Fallback to bundle-level value
    return version_data.get(key, "26.0.0")


def get_all_operator_versions(version_data: dict) -> dict:
    """
    Get version information for all operators from version data.
    
    Args:
        version_data: Dictionary containing version data from version.toml
    
    Returns:
        dict: Dictionary with operator types (descriptor folder names) as keys
              and their version info as values
        
    Example:
        >>> versions = get_all_operator_versions(version_data)
        >>> versions['content']['VERSION']
        '26.0.0'
        >>> versions['usage-metering']['CHANNEL']
        'v26.0'
    """
    if not version_data:
        return {}
    
    # Operator types match descriptor folder names and TOML section names
    operators = ['content', 'usage-metering', 'license-service', 'ai-services']
    
    result = {}
    for op_type in operators:
        if op_type in version_data:
            result[op_type] = version_data[op_type].copy()
        else:
            # Fallback to bundle-level values
            result[op_type] = {
                'VERSION': version_data.get('VERSION', '26.0.0'),
                'APP_VERSION': version_data.get('APP_VERSION', '26.0.0'),
                'CHANNEL': version_data.get('CHANNEL', 'v26.0'),
                'CSV': version_data.get('CSV', 'v26.0.0'),
                'CASE_VERSION': version_data.get('CASE_VERSION', '26.0.0'),
                'CASE_NAME': version_data.get('CASE_NAME', 'ibm-cp-ccx-case')
            }
    
    return result


def replace_namespace_in_file(
    project_name: str,
    input_file: str | Path,
    output_file: str | Path,
    resource_type: str = "",
    private: bool = False
) -> bool:
    """
    Replace namespace placeholders in Kubernetes YAML descriptor files.
    
    Handles REPLACE_NAMESPACE and <NAMESPACE> placeholders across different
    Kubernetes resource types for Content Cortex and License Service deployments.
    
    Args:
        project_name: Target namespace to replace placeholders with
        input_file: Path to source YAML file
        output_file: Path for modified YAML output
        resource_type: Kubernetes resource type:
            - "cluster role binding": Replaces '<NAMESPACE>' placeholder
            - "catalog source": Replaces 'REPLACE_NAMESPACE' in namespace field
            - "operator group": Replaces 'REPLACE_NAMESPACE' in namespace and targetNamespaces
            - "subscription": Replaces 'REPLACE_NAMESPACE' in namespace and sourceNamespace
        private: If True with subscription, ensures sourceNamespace is updated (already handled by REPLACE_NAMESPACE)
    
    Returns:
        bool: True if successful, False otherwise
        
    Raises:
        ValueError: If project_name is empty
        FileNotFoundError: If input_file doesn't exist
        
    Example:
        >>> replace_namespace_in_file(
        ...     "my-namespace",
        ...     "descriptors/content/op-olm/catalogsource.yaml",
        ...     "output/catalogsource.yaml",
        ...     "catalog source"
        ... )
        True
    """
    # Input validation
    if not project_name or not project_name.strip():
        logger.error("project_name cannot be empty")
        raise ValueError("project_name must be a non-empty string")
    
    # Convert to Path objects for better path handling
    input_path = Path(input_file)
    output_path = Path(output_file)
    
    # Validate input file exists
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        raise FileNotFoundError(f"Input file does not exist: {input_path}")
    
    if not input_path.is_file():
        logger.error(f"Input path is not a file: {input_path}")
        raise ValueError(f"Input path must be a file: {input_path}")
    
    try:
        # Read the content of the input file
        logger.debug(f"Reading input file: {input_path}")
        content = input_path.read_text(encoding='utf-8')
        
        if not content:
            logger.warning(f"Input file is empty: {input_path}")
        
        # Perform replacements based on resource type
        replaced_content = _apply_namespace_replacements(
            content=content,
            project_name=project_name,
            resource_type=resource_type.lower().strip(),
            private=private
        )
        
        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write the modified content to the output file
        logger.debug(f"Writing output file: {output_path}")
        output_path.write_text(replaced_content, encoding='utf-8')
        
        logger.info(
            f"✓ Successfully replaced namespace in {input_path.name} "
            f"(type: {resource_type or 'generic'}) -> {output_path.name}"
        )
        return True
        
    except PermissionError as e:
        logger.error(f"Permission denied: {e}")
        raise
    except UnicodeDecodeError as e:
        logger.error(f"File encoding error in {input_path}: {e}")
        raise ValueError(f"Unable to decode file {input_path}. Expected UTF-8 encoding.")
    except Exception as e:
        logger.error(f"Unexpected error processing {input_path}: {e}", exc_info=True)
        return False


def _apply_namespace_replacements(
    content: str,
    project_name: str,
    resource_type: str,
    private: bool
) -> str:
    """
    Apply resource-type-specific namespace text replacements.
    
    This helper function encapsulates the replacement logic for different
    Kubernetes resource types, making the main function cleaner and easier to test.
    
    Args:
        content: Original file content
        project_name: Namespace to replace placeholders with
        resource_type: Normalized (lowercase) resource type
        private: Whether this is a private deployment (affects sourceNamespace)
        
    Returns:
        str: Content with namespace replacements applied
    """
    if resource_type == "cluster role binding":
        # Replace '<NAMESPACE>' placeholder (used in cluster role bindings)
        return content.replace('<NAMESPACE>', project_name)
    
    elif resource_type == "catalog source":
        # Replace REPLACE_NAMESPACE in catalogsource.yaml
        # Appears in: metadata.namespace (line 15 in template)
        return content.replace('REPLACE_NAMESPACE', project_name)
    
    elif resource_type == "operator group":
        # Replace all REPLACE_NAMESPACE occurrences in operator_group.yaml
        # Appears in: metadata.namespace and spec.targetNamespaces
        return content.replace('REPLACE_NAMESPACE', project_name)
    
    elif resource_type == "subscription":
        # Replace REPLACE_NAMESPACE in subscription.yaml
        # Appears in: metadata.namespace and spec.sourceNamespace
        # The simple replace handles both fields correctly
        replaced = content.replace('REPLACE_NAMESPACE', project_name)
        
        # Note: private parameter is kept for backward compatibility
        # but sourceNamespace is already handled by REPLACE_NAMESPACE replacement
        if private:
            logger.debug("Private deployment: sourceNamespace already replaced via REPLACE_NAMESPACE")
        
        return replaced
    
    else:
        # Unknown resource type - return content unchanged with warning
        # This allows the function to be repurposed for other text replacements
        logger.warning(
            f"Unknown resource_type '{resource_type}'. "
            "No replacements applied. Content returned unchanged."
        )
        return content


# Function to recursively search for key value pairs in a yaml
def extract_values(data, key):
    """
    Recursively extract values for a given key from a nested dictionary.
    """
    if isinstance(data, dict):
        for k, v in data.items():
            if k == key:
                yield v
            elif isinstance(v, dict):
                yield from extract_values(v, key)
            elif isinstance(v, list):
                for item in v:
                    yield from extract_values(item, key)


# Function to check if key is present in a yaml file
def is_key_present(dictionary, key):
    # Check if the key is in the current level of the dictionary
    if key in dictionary:
        return True

    # Iterate through the values of the dictionary
    for value in dictionary.values():
        # If the value is another dictionary, recursively check if the key is present in it
        if isinstance(value, dict):
            if is_key_present(value, key):
                return True

    # If the key is not found at any level of indentation
    return False


# Function to check if a key is present and return the path
def find_keys_and_structures(dictionary, key, path=[], results=[]):
    # Check if the key is in the current level of the dictionary
    if key in dictionary:
        results.append((dictionary, path, key))

    # Iterate through the items of the dictionary
    for k, v in dictionary.items():
        # If the value is another dictionary, recursively check if the key is present in it
        if isinstance(v, dict):
            find_keys_and_structures(v, key, path + [k], results)

    return results


# Function to create current deployment info
def create_current_operator_info(operator_details):
    # Get Registry
    registry = operator_details["image"].split("/")[0]

    # Get CSV numbers
    if operator_details["type"] == "OLM":
        name, installed_csv = operator_details["installedCSV"].split(".", 1)

        current_details = {
            "deployment": operator_details["deployment"],
            "release": operator_details["release"],
            "type": operator_details["type"],
            "installedCSV": installed_csv,
            "channel": operator_details["channel"],
            "catalogSource": operator_details["catalogSource"],
            "catalogType": operator_details["catalogType"],
            "registry": registry
        }
    else:
        current_details = {
            "deployment": operator_details["deployment"],
            "release": operator_details["release"],
            "type": operator_details["type"],
            "registry": registry
        }
    return current_details


def create_deployment_info(setup, version_data, use_helm=False):
    """
    Create deployment information dictionary.
    
    Args:
        setup: Setup object containing deployment configuration
        version_data: Version data from version.toml (can be top-level or operator-specific)
        use_helm: Whether Helm deployment is being used (default: False for OLM)
    
    Returns:
        dict: Deployment details including version, CSV, channel, etc.
    """
    if version_data:
        # Check if this is operator-specific data (has CSV/CHANNEL keys)
        # or top-level data (needs to extract operator section)
        if "CSV" in version_data and "CHANNEL" in version_data:
            # Already operator-specific data
            version = version_data["VERSION"]
            csv = version_data["CSV"]
            channel = version_data["CHANNEL"]
        else:
            # Top-level data - need to extract operator-specific section
            # Determine which operator section to use
            operator_section = None
            
            # Check if setup has selected_operators (multi-operator deployment)
            if hasattr(setup, 'selected_operators') and setup.selected_operators:
                # For multi-operator deployments, use bundle-level version for "release"
                # Individual operator versions are shown separately in the operator list
                version = version_data.get("VERSION", "26.0.0")
                csv = version_data.get("CSV", "v26.0.0")
                channel = version_data.get("CHANNEL", "v26.0")
            # Check legacy operator_type attribute (single operator deployment)
            elif hasattr(setup, 'operator_type'):
                operator_section = setup.operator_type
                # Extract operator-specific version data for single operator
                if operator_section in version_data:
                    op_data = version_data[operator_section]
                    version = op_data.get("VERSION", version_data.get("VERSION", "26.0.0"))
                    csv = op_data.get("CSV", "v26.0.0")
                    channel = op_data.get("CHANNEL", "v26.0")
                else:
                    # Fallback to top-level VERSION if operator section not found
                    logger.warning(f"Operator section '{operator_section}' not found in version data, using defaults")
                    version = version_data.get("VERSION", "26.0.0")
                    csv = "v26.0.0"
                    channel = "v26.0"
            # Default to bundle-level version
            else:
                version = version_data.get("VERSION", "26.0.0")
                csv = "v26.0.0"
                channel = "v26.0"
    else:
        # No version data provided - use legacy defaults
        version = "5.7.0"
        csv = "57.0.0"
        channel = "25.0.0"

    # Determine deployment type based on use_helm flag
    # Helm is the default for both OCP and CNCF (other) platforms
    # OLM is only used when explicitly requested via --use-olm flag
    if use_helm:
        type = "Helm"
        # For Helm deployments, catalog info is not applicable
        catalog_type = "N/A"
        catalog_source = "N/A"
    else:
        # OLM deployment (only when --use-olm flag is used)
        type = "OLM"
        if setup.private_catalog:
            catalog_type = "Private"
        else:
            catalog_type = "Global"
        # Extract catalog source name from descriptor files for OLM
        catalog_source = extract_catalog_name_from_descriptors(setup)

    # Set registry
    if setup.private_registry:
        registry = f'{setup.private_registry_server}'
    else:
        registry = "icr.io"
    
    # Extract operator name from descriptor files
    operator_name = extract_operator_name_from_descriptors(setup)

    deployment_details = {
        "deployment": operator_name,
        "release": version,
        "type": type,
        "installedCSV": csv if not use_helm else "N/A",  # CSV not applicable for Helm
        "channel": channel if not use_helm else "N/A",   # Channel not applicable for Helm
        "catalogSource": catalog_source,
        "catalogType": catalog_type,
        "registry": registry
    }
    
    # Add Helm-specific fields if using Helm deployment
    if use_helm:
        deployment_details["helm_chart_source"] = getattr(setup, 'helm_chart_source', 'packaged')
    
    return deployment_details


#Function to compare the requests and limits section of CR and return a flag to denote if a update is required or not
def resource_limits_comparison(current_value,upgrade_value,limits=False):
    try:
        # Assumption is that all values that do not have any letters in it are by default in Gigabytes
        # Considering all values having Mi , M , m to be Megabytes and converting them to Gigabytes for comparison
        if "Mi" in current_value or "M" in current_value or "m" in current_value:
            current_gb_value = int(re.sub(r'[a-zA-Z]', '', current_value))/1024
        else:
            current_gb_value = int(re.sub(r'[a-zA-Z]', '', current_value))

        if "Mi" in upgrade_value or "M" in upgrade_value or "m" in upgrade_value:
            upgrade_gb_value = int(re.sub(r'[a-zA-Z]', '', upgrade_value))/1024
        else:
            upgrade_gb_value = int(re.sub(r'[a-zA-Z]', '', upgrade_value))

        #comparison is different for requests and limits.
        if limits:
            if current_gb_value > upgrade_gb_value:
                return True
            else:
                return False
        else:
            if current_gb_value < upgrade_gb_value:
                return True
            else:
                return False
    except Exception as e:
        return True


# Function to update a key value pair using the values present in a another dictionary
# used to update tags and resources if they are present in the cr to be updated
# We use dictionary2 to update values in dictionary1
def update_value_by_path(dictionary1, path, dictionary2, requests=False, limits=False, logger=None):
    # Get the first key in the path
    key = path[0]

    # If there's only one key in the path, update the value
    if len(path) == 1:
        if requests:
            try:
                if resource_limits_comparison(dictionary1[key]["requests"]["cpu"],dictionary2[key]["requests"]["cpu"]):
                    dictionary1[key]["requests"]["cpu"] = dictionary2[key]["requests"]["cpu"]
                if resource_limits_comparison(dictionary1[key]["requests"]["memory"],dictionary2[key]["requests"]["memory"]):
                    dictionary1[key]["requests"]["memory"] = dictionary2[key]["requests"]["memory"]
                if resource_limits_comparison(dictionary1[key]["requests"]["ephemeral_storage"],dictionary2[key]["requests"]["ephemeral_storage"]):
                    dictionary1[key]["requests"]["ephemeral_storage"] = dictionary2[key]["requests"][
                        "ephemeral_storage"]
            except Exception as e:
                logger.info(e)

        elif limits:

            try:
                if resource_limits_comparison(dictionary1[key]["limits"]["cpu"],dictionary2[key]["limits"]["cpu"],limits=True):
                    dictionary1[key]["limits"]["cpu"] = dictionary2[key]["limits"]["cpu"]
                if resource_limits_comparison(dictionary1[key]["limits"]["memory"],dictionary2[key]["limits"]["memory"],limits=True):
                    dictionary1[key]["limits"]["memory"] = dictionary2[key]["limits"]["memory"]
                if resource_limits_comparison(dictionary1[key]["limits"]["ephemeral_storage"],dictionary2[key]["limits"]["ephemeral_storage"],limits=True):
                    dictionary1[key]["limits"]["ephemeral_storage"] = dictionary2[key]["limits"]["ephemeral_storage"]
            except Exception as e:
                logger.info(e)

        else:
            # For image tags and repos we just pop the tag and repo out
            try:

                dictionary1[key] = {}
            except Exception as e:
                logger.info(e)
    else:
        # Recursively update the nested dictionary
        if key in dictionary1 and key in dictionary2:
            update_value_by_path(dictionary1[key], path[1:], dictionary2[key], requests, limits, logger=logger)
        else:
            raise KeyError(f"Key '{key}' not found in dictionary")

def delete_key_by_path(dictionary, path_list, target_key, logger=None):
    """
    Deletes a key from a nested dictionary given a list of keys representing its path.

    Args:
        dictionary (dict): The dictionary to modify.
        path_list (list): A list of keys representing the path to the key to be deleted.
        target_key (str): The key to be deleted.
        logger: Logger object for logging information.
    """
    if not path_list:
        return

    current_dict = dictionary
    # Traverse to the parent dictionary of the key to be deleted
    for key in path_list:
        if not isinstance(current_dict, dict) or key not in current_dict:
            # Handle cases where the path is invalid
            logger.info(f"Path error: Key '{key}' not found or not a dictionary in the path.")
            return
        current_dict = current_dict[key]

    # Delete the target key from its parent dictionary
    if isinstance(current_dict, dict) and target_key in current_dict:
        del current_dict[target_key]
    else:
        logger.info(f"Deletion error: Key '{target_key}' not found at the specified path.")


def parse_yaml_for_keys(yaml_data, keys):
    """
    Parse YAML data for specified keys and extract values.
    """
    parsed_values = {key: list(extract_values(yaml_data, key)) for key in keys}
    return parsed_values


def create_version_info(setup, version_data, cr_details=None):
    namespace = setup.namespace

    if version_data:
        # VERSION: product/helm version displayed in the UI (e.g. 26.0.1)
        version = version_data.get("VERSION", "26.0.0")
        # APP_VERSION: base release version used for CR template selection (e.g. 26.0.0)
        appVersion = version_data.get("APP_VERSION", version)
    else:
        appVersion = "26.0.0"
        version = "26.0.0"

    # Get platform from CR details if available, otherwise default to OCP
    platform = "OCP"  # Default platform
    if cr_details and isinstance(cr_details, dict):
        platform = cr_details.get("platform", "OCP")

    version_details = {
        "version": version,
        "namespace": namespace,
        "appVersion": appVersion,
        "platform": platform
    }

    return version_details


# Create tmp folder
def create_tmp_folder():
    tmp_folder = os.path.join(os.getcwd(), ".tmp")
    if os.path.exists(tmp_folder):
        try:
            # Remove the directory and its contents
            shutil.rmtree(tmp_folder)
        except OSError as e:
            print(f"Failed to delete directory '{tmp_folder}': {e}")
    # Create the directory
    try:
        os.makedirs(tmp_folder)
        return tmp_folder
    except OSError as e:
        print(f"Failed to create directory '{tmp_folder}': {e}")


# image copying mechanism for loadimages.py
def copy_image(source_image, dest_image, progress=None, tls_verify=True):
    try:
        # Construct Skopeo command to copy image with the same digest
        # The tls_verify flag controls TLS verification for the DESTINATION (private registry)
        # Source registry (IBM's public registry) should always use TLS verification
        # Note: TLS flags must come before the image references
        # Use --all to copy all architectures and --preserve-digests to maintain image digests
        if tls_verify:
            # Verify TLS for both source and destination
            command = f"skopeo copy --src-tls-verify=true --dest-tls-verify=true docker://{source_image} docker://{dest_image} --all --preserve-digests --remove-signatures"
        else:
            # Skip TLS verification for destination only (source always verified)
            command = f"skopeo copy --src-tls-verify=true --dest-tls-verify=false docker://{source_image} docker://{dest_image} --all --preserve-digests --remove-signatures"

        # Execute Skopeo command
        process = subprocess.Popen(command, stdout=subprocess.PIPE, shell=True, stderr=subprocess.PIPE)

        while True:
            line = process.stdout.readline().decode('utf-8')
            if not line:
                break
            progress.log(line)

        error = process.stderr.read().decode('utf-8')
        error_split = error.split("msg=")
        error_msg = error_split[-1]

        if error != '':
            progress.log(Text(error_msg, style="bold red"))
            progress.log(Text(f"Error copying image to {dest_image}", style="bold red"))
            progress.log()
            return False

        progress.log(Text(f"Image copied to {dest_image} successfully", style="bold green"))
        progress.log()
        return True

    except Exception as e:
        (f"Error: {e}")
        return False


# Function to read all env variables from the airgap variables file
def read_airgap_vars(airgap_details_file):
    airgap_vars = {}
    # Need to ignore comments and "remove" the export keyword
    with open(airgap_details_file, 'r') as file:
        for line in file:
            trimmed = line.strip()
            if trimmed and not trimmed.startswith('#'):
                key, value = trimmed.split("=")
                key = key.replace("export ", "")
                airgap_vars[key] = value

    return airgap_vars


# Parse the airgap details file

# Validate the image tag and repo file details
def validate_airgap_details_file(logger, airgap_details_file: str):
    try:
        # Check if the airgap details file exists
        if not os.path.exists(airgap_details_file):
            print(Panel.fit(f"Issues Found", style="bold red"))
            print(
                f"\n[prompt.invalid]Airgap details file {airgap_details_file} is missing.\n\n"
                f"Please run the script in generate mode to generate the file.\n")

            print(Panel.fit(
                Syntax("python3 loadimages.py --airgap generate", "bash", theme="ansi_dark")
            ))
            exit(1)

        airgap_vars = read_airgap_vars(airgap_details_file)

        if not airgap_vars:
            print(Panel.fit(f"Issues Found", style="bold red"))
            print(
                f"\n[prompt.invalid]Airgap details file {airgap_details_file} is empty.\n\n"
                f"Please run the script in generate mode to generate the file.\n")

            print(Panel.fit(
                Syntax("python3 loadimages.py --airgap generate", "bash", theme="ansi_dark")
            ))
            exit(1)

        # Check all the required variables are present
        required_vars = ["CASE_NAME", "CASE_VERSION", "IBMPAK_HOME", "TARGET_REGISTRY",
                         "REGISTRY_AUTH_FILE", "CASE_INVENTORY_SETUP"]

        missing_vars = [var for var in required_vars if var not in airgap_vars]

        if missing_vars:
            print(Panel.fit(f"Issues Found", style="bold red"))
            print(f"\n[prompt.invalid]Required variables are missing in the airgap details file.\n\n"
                  f"Please add the following variables to the file: {missing_vars}")
            exit(1)

        # Check if the IBM PAK home directory is valid
        ibm_pak_home = os.path.join(airgap_vars["IBMPAK_HOME"], '.ibm-pak')
        if not os.path.exists(ibm_pak_home):
            print(Panel.fit(f"Issues Found", style="bold red"))
            print(f"\n[prompt.invalid]IBM PAK home directory {ibm_pak_home} does not exist.\n\n"
                  f"The IBM PAK directory is populated when the CASE Package is downloaded.\n"
                  f"Please run the script in generate mode to complete the CASE package setup.\n")
            print(Panel.fit(
                Syntax("python3 loadimages.py --airgap generate", "bash", theme="ansi_dark")
            ))
            exit(1)

        return airgap_vars

    except Exception as e:
        logger.exception(
            f"Exception when reading ImageDetails Files\n"
            f"Please Review your Airgap Details file: {e}\n\n")
        exit(1)


# Validate the image tag and repo file details
def validate_image_details_file(logger, image_tag_file):
    try:
        # Load property files if they exist
        if os.path.exists(image_tag_file):
            try:
                image_prop = ReadPropImageTag(image_tag_file, logger)
            except TomlDecodeError:
                print(Panel.fit(f"Issues Found", style="bold red"))
                print(
                    f"\n[prompt.invalid]Exception when reading ImageDetails File\n\n"
                    f"Please Review your Property files for missing quotes and formatting.\n\n")
                exit(1)
            incorrect_keys = image_prop.check_toml()
            if incorrect_keys:
                print(Panel.fit(f"Issues Found", style="bold red"))
                print(f"\n[prompt.invalid]There are certain components which have incorrect format.\n\n"
                      f"Please review the file and correct the following keys: {incorrect_keys}")
                exit(1)

        else:
            print(Panel.fit(f"Issues Found", style="bold red"))
            print(
                f"\n[prompt.invalid]Image details file {image_tag_file} is missing.\n\n"
                f"Please run the script in generate mode to generate the file.\n")

            print(Panel.fit(
                Syntax("python3 loadimages.py generate", "bash", theme="ansi_dark")
            ))

            exit(1)
        # Create dictionaries for property files if not None
        if image_prop:
            image_prop_dict = image_prop.to_dict()
        else:
            image_prop_dict = {}

        return image_prop_dict
    except Exception as e:
        logger.exception(
            f"Exception when reading ImageDetails Files\n"
            f"Please Review your Property files for missing quotes and formatting.{e}\n\n")
        exit(1)


def update_operator_template(input_file, output_file):
    # Define the patterns and replacements
    patterns_replacements = [
        (r'dba_license', r'value:.*', r'value: accept'),
        (r'baw_license', r'value:.*', r'value: accept'),
        (r'fncm_license', r'value:.*', r'value: accept'),
        (r'ier_license', r'value:.*', r'value: accept')
    ]

    # Read input file, apply replacements, and write to output file
    with open(input_file, 'r') as fin, open(output_file, 'w') as fout:
        for line in fin:
            for pattern, search_pattern, replacement in patterns_replacements:
                if re.search(pattern, line):
                    next(fin)  # Skip to the next line
                    line = re.sub(search_pattern, replacement, line)
                    break  # Once a pattern is matched, break out of the loop
            fout.write(line)

