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
import logging
import os.path
import re
import shutil
import subprocess
import time
from datetime import datetime
from enum import Enum

import jinja2
import requests
import toml
import yaml
from packaging import version
from rich import print
from rich.panel import Panel
from rich.text import Text
import questionary
from questionary import Style
from tomlkit import comment
from tomlkit import document
from tomlkit import nl
from tomlkit import table
from tomlkit.toml_file import TOMLFile

from ..utilities import kubernetes_utilites as k
from ..utilities.interface import generate_casepackage_results, clear
from ..utilities.prerequisites_utilites import zip_folder
from ..utilities.utilities import parse_yaml_for_keys


# CLass that contains functions to delete the CR as well delete the Operator
class LoadExtract:

    class AirgapChannel:
        Channel = Enum(
            value='Channel',
            names=[("v22.1", "5.5.9"), ("v22.2", "5.5.10"), ("v23.1", "5.5.11"), ("v23.2", "5.5.12"), ("v24.0", "5.6.0"), ("v25.0", "5.7.0")]
        )

        def __init__(self, channel: Channel):
            self._channel = channel

    def __init__(self, console, logger=None, silent=False, dev=False, airgap=False, folder_path="", version_data=None, tls_verify=True, cs_root=None):
        if version_data is None:
            version_data = {}
        self._logger = logger
        self._kube = k.KubernetesUtilities(logger)
        self._console = console
        self._dev = dev
        self._silent_mode = silent
        self._airgap = airgap
        self._tls_verify = tls_verify

        if 'VERSION' in version_data:
            self._ccx_version = version_data['VERSION']
        else:
            self._ccx_version = '26.0.0'

        if 'ALL_CHANNELS' in version_data:
            self._all_channel = version_data['ALL_CHANNELS']
        else:
            self._all_channel = False

        # CNCF image variables file Details
        self._image_details_folder = folder_path
        self._image_details_file = os.path.join(self._image_details_folder, "imageDetails.toml")

        self._apps_v1_api = self._kube.apps_v1
        self._core_v1_api = self._kube.core_v1
        self._custom_api = self._kube.custom_api

        # Repo information
        self._private_registry_full_server = ""

        # Derive the container-samples root from __file__ so the path is correct
        # regardless of what directory the user invokes the script from.
        # __file__ == .../container-samples/scripts/helper_scripts/loadimages/load_extract.py
        #   3 up -> .../container-samples/scripts/   (submodule / fncm-prerequisites root)
        #   4 up -> .../container-samples/            ← what we want
        # Callers (e.g. tests) may pass cs_root explicitly to override.
        if cs_root is not None:
            _cs_root = cs_root
        else:
            _cs_root = os.path.dirname(
                os.path.dirname(
                    os.path.dirname(
                        os.path.dirname(os.path.abspath(__file__))
                    )
                )
            )

        # file paths from container samples - CR operand descriptors
        self._content_pattern_path = os.path.join(_cs_root, "descriptors",
                                                   "content-cortex", "content", "ibm_content_full_cr.yaml")
        self._ai_services_pattern_path = os.path.join(_cs_root, "descriptors",
                                                       "content-cortex", "ai-services", "ibm_ai_services_full_cr.yaml")
        self._wdu_pattern_path = os.path.join(_cs_root, "descriptors",
                                              "wdu", "ibm_wdu_services_full_cr.yaml")

        # Descriptor-based operator paths — all operators ship operator.yaml in descriptors/
        self._content_operator_path = os.path.join(_cs_root, "descriptors",
                                                    "content-cortex", "content", "operator.yaml")
        self._ai_services_operator_path = os.path.join(_cs_root, "descriptors",
                                                        "content-cortex", "ai-services", "operator.yaml")
        self._model_gateway_operator_path = os.path.join(_cs_root, "descriptors",
                                                          "model-gateway", "operator.yaml")
        self._wdu_operator_path = os.path.join(_cs_root, "descriptors",
                                               "wdu", "operator.yaml")
        self._redis_operator_path = os.path.join(_cs_root, "descriptors",
                                                   "redis", "operator.yaml")
        self._cnpg_operator_path = os.path.join(_cs_root, "descriptors",
                                                 "cnpg", "operator.yaml")
        self._usage_metering_operator_path = os.path.join(_cs_root, "descriptors",
                                                           "usage-metering", "operator.yaml")
        self._license_service_operator_path = os.path.join(_cs_root, "descriptors",
                                                            "license-service", "operator.yaml")

        # Legacy operator path for backward compatibility
        self._operator_path = os.path.join(_cs_root, "descriptors", "operator.yaml")

        # Operand images.txt paths — list additional images shipped alongside each operator
        self._cnpg_images_txt_path = os.path.join(_cs_root, "descriptors", "cnpg", "images.txt")
        self._redis_images_txt_path = os.path.join(_cs_root, "descriptors", "redis", "images.txt")
        self._model_gateway_images_txt_path = os.path.join(_cs_root, "descriptors", "model-gateway", "images.txt")

        # Registry credentials forwarded from gather — used by Skopeo at copy time
        self._src_creds = ""           # "cp:<preprod_key>" for preprod.icr.io (dev) or production icr.io (prod)
        self._prod_src_creds = ""      # "cp:<prod_key>" for cp.icr.io — only needed in dev mode
        self._dest_creds = ""          # "<username>:<password>" for private registry
        self._dest_cert_dir = ""       # directory containing the private registry CA cert
        self._dev_image_tag = ""       # sprint tag to substitute for operand tags in dev mode

        # Variables to store the image details
        self._repo_tag_list = []
        self._repo_tag_dict_from_file = {}

        self._image_push_summary = {}
        self._number_of_images = 0

        # Airgap variables file Details
        self._airgap_template = os.path.join(os.getcwd(), "helper_scripts", "loadimages", "templates",
                                             "case_variables_template.j2")
        self._airgap_details_folder = folder_path
        self._airgap_details_file = os.path.join(self._airgap_details_folder, "airgap_variables.sh")
        self._ibmpak_home = os.path.join(os.getcwd())

        # Variables to store casePackage details
        if self._dev:
            self._casepackage_url = "https://raw.githubusercontent.com/IBM/cloud-pak/refs/heads/master/repo/case/ibm-cp-fncm-case/index.yaml"
        else:
            self._casepackage_url = "https://raw.githubusercontent.com/IBM/cloud-pak/master/repo/case/ibm-cp-fncm-case/index.yaml"

        self._case_versions = {}
        self._case_versions_list = []

        self._casepackage_version = "5.7.0"
        self._casename = "ibm-cp-fncm-case"

        self._airgap_vars = {}

    @property
    def casepackage_version(self):
        return self._casepackage_version

    @casepackage_version.setter
    def casepackage_version(self, value):
        self._casepackage_version = value

    @property
    def ibmpak_home(self):
        return self._ibmpak_home

    @ibmpak_home.setter
    def ibmpak_home(self, value):
        self._ibmpak_home = value

    @property
    def airgap_vars(self):
        return self._airgap_vars

    @airgap_vars.setter
    def airgap_vars(self, value):
        self._airgap_vars = value

    @property
    def case_versions(self):
        return self._case_versions_list

    @property
    def number_of_images(self):
        return self._number_of_images

    @property
    def image_push_summary(self):
        return self._image_push_summary

    @property
    def ccx_version(self):
        return self._ccx_version

    @ccx_version.setter
    def ccx_version(self, value):
        self._ccx_version = value

    # Getter for private registry server
    @property
    def private_registry_server(self):
        return self._private_registry_full_server

    # Setter for private registry server
    @private_registry_server.setter
    def private_registry_server(self, value):
        self._private_registry_full_server = value

    @property
    def src_creds(self):
        return self._src_creds

    @src_creds.setter
    def src_creds(self, value):
        self._src_creds = value

    @property
    def prod_src_creds(self):
        return self._prod_src_creds

    @prod_src_creds.setter
    def prod_src_creds(self, value):
        self._prod_src_creds = value

    @property
    def dest_creds(self):
        return self._dest_creds

    @dest_creds.setter
    def dest_creds(self, value):
        self._dest_creds = value

    @property
    def dest_cert_dir(self):
        return self._dest_cert_dir

    @dest_cert_dir.setter
    def dest_cert_dir(self, value):
        self._dest_cert_dir = value

    @property
    def dev_image_tag(self):
        return self._dev_image_tag

    @dev_image_tag.setter
    def dev_image_tag(self, value):
        self._dev_image_tag = value

    @staticmethod
    def __write_property_table(section, key, value, note, ):
        section.add(nl())
        for i in note:
            section.add(comment(f'{i}'))
        section.add(key, value)

    # Function to add airgap variables to the dictionary
    def add_airgap_vars(self, key, value):
        self._airgap_vars[key] = value

    # Helper function to check if an image already exists in the repo_tag_list
    def _is_duplicate_image(self, component_dict):
        """
        Check if an image with the same repository and tag/digest already exists.
        
        Args:
            component_dict: Dictionary containing 'repository' and either 'tag' or 'digest'
            
        Returns:
            bool: True if duplicate exists, False otherwise
        """
        repository = component_dict.get('repository', '').lower()
        tag = component_dict.get('tag', '')
        digest = component_dict.get('digest', '')
        
        for existing_image in self._repo_tag_list:
            existing_repo = existing_image.get('repository', '').lower()
            existing_tag = existing_image.get('tag', '')
            existing_digest = existing_image.get('digest', '')
            
            # Check if repository matches
            if repository == existing_repo:
                # Check if tag/digest matches
                if digest and digest == existing_digest:
                    return True
                elif tag and tag == existing_tag:
                    return True
        
        return False

    # Helper to identify images that must always be pulled from the production registry.
    # These are third-party or Common Services operators that have no staging (preprod)
    # equivalent and must never be rewritten in dev mode.
    _PRODUCTION_ONLY_PREFIXES = (
        "icr.io/cpopen/cpfs/",              # IBM Common Services operands
        "icr.io/cpopen/ibm-pg",             # IBM Operator for PostgreSQL (CNPG) operator + operands
        "icr.io/cpopen/ibm-redis",          # IBM Redis operator
        "icr.io/cpopen/ibm-cpd-model-gateway-operator",  # IBM Model Gateway operator
        "cp.icr.io/cp/ibm-redis-cp-",       # IBM Redis CP operand images (haproxy, operand)
        "cp.icr.io/cp/cpd/go-proxy",        # IBM Model Gateway go-proxy operand
        "icr.io/cpopen/ibm-usage-metering-operator",  # Common Services — no preprod equivalent
        "icr.io/cpopen/ibm-licensing-operator",       # Common Services — no preprod equivalent
    )

    @staticmethod
    def _is_production_only_image(repository: str) -> bool:
        """Return True if this image must always be pulled from the production registry."""
        repo = repository.lower()
        return any(repo.startswith(prefix) for prefix in LoadExtract._PRODUCTION_ONLY_PREFIXES)

    # Create the airgap variables file
    def create_airgap_details_file(self):
        self._logger.info(f"Creating the airgap details file: {self._airgap_details_file}")
        # Create the Airgap Details folder
        self.__create_airgap_details_folder()

        # Load the template
        template_loader = jinja2.FileSystemLoader(os.path.dirname(self._airgap_template))
        template_env = jinja2.Environment(loader=template_loader)
        template = template_env.get_template('case_variables_template.j2')

        # Convert dictionary to a list of dictionaries
        airgap_vars = list()
        for key, value in self._airgap_vars.items():
            airgap_vars.append({'key': key, 'value': value})

        # Render the template with data
        rendered_template = template.render(airgap_vars=airgap_vars)

        # Write the rendered template to a temporary file
        with open(self._airgap_details_file, 'w') as f:
            f.write(rendered_template)

    # Function to collect Case Versions
    def collect_case_versions(self):
        try:
            self._logger.info(f"Collecting the case versions")
            # Create tmp folder
            if not os.path.exists(os.path.join(os.getcwd(), ".tmp")):
                os.mkdir(os.path.join(os.getcwd(), ".tmp"))

            filename = os.path.join(os.getcwd(), ".tmp", "index.yaml")

            # Download the case package index.yaml file
            # Send a GET request to the URL
            response = requests.get(self._casepackage_url, stream=True, timeout=5)

            # Check if the request was successful
            if response.status_code == 200:
                # Open the file in write-binary mode
                with open(filename, 'wb') as file:
                    for chunk in response.iter_content(chunk_size=8192):
                        # Write each chunk to the file
                        file.write(chunk)
                self._logger.info(f"Downloaded case package index.yaml file to {filename}")
            else:
                print(Panel.fit(Text(f"Failed to download CASE Package index.yaml file"), style="bold yellow"))
                print()
                self._logger.info(f"Failed to download case package index.yaml file from {self._casepackage_url}")

            # Read the index.yaml file
            with open(filename, 'r') as file:
                case_versions = yaml.safe_load(file)

            # Return the case versions
            self._case_versions = case_versions
            case_versions_parsed = case_versions['versions'].keys()
            self._case_versions_list = case_versions_parsed
        except Exception as e:
            self._logger.info(f"Exception while trying to collect case versions - {e}")
            self._case_versions_list = []


    # Function to parse caseVersions
    def __parse_case_versions(self):
        self._logger.info(f"Parsing the case versions")
        case_versions = self._case_versions
        case_versions_dict = {}

        lowest_version = version.parse("5.5.9")

        # Loop through the caseVersions
        for key, data in case_versions['versions'].items():
            # Get the appVersion
            app_version = data["appVersion"].split("-")[0]

            # Check if the appVersion is greater or equal 5.5.9
            if version.parse(app_version) >= lowest_version:
                # Add the appVersion to the caseVersionsDict
                if app_version not in case_versions_dict:
                    case_versions_dict[app_version] = key
                else:
                    # Check if the casePackageVersion is greater than the current version
                    if version.parse(key) > version.parse(case_versions_dict[app_version]):
                        case_versions_dict[app_version] = key

        self._case_versions_list = case_versions_dict
        return case_versions_dict

    # Function to select the casePackageVersion
    def validate_case_package_version(self, case_version=None):
        print(Panel.fit("CASE Package Version Selection"))
        self._logger.info(f"Selecting the case package versions")

        case_versions_list = self._case_versions_list

        if case_version:
            print()
            print(Panel.fit(Text(f"Selected CASE Package Version: {case_version}", style="bold cyan")))
            print()

        # If case_version is not in the case_versions_list, output warning
        if case_version and case_version not in case_versions_list:
            print()
            print(Panel.fit(Text(f"Warning: The selected CASE Package Version: {case_version} is not in the available versions list.\n"
                                 f"CASEPackage download will proceed without validation"), style="bold yellow"))
            print()

        self._logger.info(f"Selected case package version: {self._casepackage_version}")
        self._casepackage_version = case_version
        return self._casepackage_version

    # Function to create the imageDetails folder
    def __create_cncf_image_details_folder(self):
        if os.path.exists(self._image_details_folder):
            self._logger.info("Backup existing imageDetails folder")
            if not os.path.exists(os.path.join(os.getcwd(), "backups")):
                os.mkdir(os.path.join(os.getcwd(), "backups"))
            now = datetime.now()
            dt_string = now.strftime("%Y-%m-%d_%H-%M")
            zip_folder(os.path.join(os.getcwd(), "backups", "imageDetails_" + dt_string),
                       os.path.join(os.getcwd(), "imageDetails"))
            shutil.rmtree(self._image_details_folder)
            os.mkdir(self._image_details_folder)
        else:
            self._logger.info("Creating imageDetails folder")
            os.mkdir(self._image_details_folder)

    # Function to create the airgap variables file
    def __create_airgap_details_folder(self):
        if os.path.exists(self._airgap_details_folder):
            self._logger.info("Backup existing Airgap folder")
            if not os.path.exists(os.path.join(os.getcwd(), "backups")):
                os.mkdir(os.path.join(os.getcwd(), "backups"))
            now = datetime.now()
            dt_string = now.strftime("%Y-%m-%d_%H-%M")
            zip_folder(os.path.join(os.getcwd(), "backups", "airgapDetails_" + dt_string),
                       os.path.join(os.getcwd(), "airgapDetails"))
            shutil.rmtree(self._airgap_details_folder)
            os.mkdir(self._airgap_details_folder)
        else:
            self._logger.info("Creating Airgap folder")
            os.mkdir(self._airgap_details_folder)

    # Function to retrieve all component tag and repositories
    def parse_content_template(self):
        self._logger.info(f"Retrieving the component tags and repositories")
        try:
            with open(self._content_pattern_path, 'r') as file:
                content_template_yaml = yaml.safe_load(file)

        except Exception as e:
            print(f"Error occurred while reading YAML file {self._content_pattern_path}: {e}")
            self._logger.info(f"Error occurred while reading YAML file {self._content_pattern_path}: {e}")

        if content_template_yaml:
            keys_to_parse = ['repository', 'tag']
            parsed_keys = parse_yaml_for_keys(content_template_yaml, keys_to_parse)

            num_components = len(parsed_keys['repository'])

            for i in range(num_components):
                component_dict = {}

                # Calculate Component Name
                component_name = parsed_keys['repository'][i].split("/")[-1]
                component_dict['components'] = component_name

                # Calculate Tag or Digest
                if "sha256:" in parsed_keys['tag'][i]:
                    component_dict['digest'] = parsed_keys['tag'][i]
                else:
                    component_dict['tag'] = parsed_keys['tag'][i]

                # Calculate Repository
                repository = parsed_keys['repository'][i]
                component_dict['repository'] = repository.lower()

                # Add the component dictionary to the repo_tag_list only if not duplicate
                if not self._is_duplicate_image(component_dict):
                    self._repo_tag_list.append(component_dict.copy())
                else:
                    self._logger.info(f"Skipping duplicate image: {component_name} - {repository}")

                # Check if the component is cpe or navigator for add the SSO image
                if component_name in ["cpe", "navigator"]:
                    self._logger.info(f"Getting {component_name} SSO repository and tag")
                    component_dict = {}
                    component_dict['components'] = f"{component_name}-sso"
                    if component_name == "cpe":
                        component_dict['repository'] = f"cp.icr.io/cp/cp4a/fncm/{component_name}-sso".lower()
                    else:
                        component_dict['repository'] = f"cp.icr.io/cp/cp4a/ban/{component_name}-sso".lower()
                    if "sha256:" in parsed_keys['tag'][i]:
                        component_dict['digest'] = parsed_keys['tag'][i]
                    else:
                        component_dict['tag'] = parsed_keys['tag'][i]
                    
                    # Add SSO image only if not duplicate
                    if not self._is_duplicate_image(component_dict):
                        self._repo_tag_list.append(component_dict.copy())
                    else:
                        self._logger.info(f"Skipping duplicate SSO image: {component_name}-sso")

            self._logger.info(self._repo_tag_list)

            # Modify repositories (and optionally tags) for dev environment
            if self._dev:
                for component_dict in self._repo_tag_list:
                    component_dict["repository"] = component_dict["repository"].replace("cp.icr.io", "preprod.icr.io")
                    if self._dev_image_tag and "tag" in component_dict:
                        component_dict["tag"] = self._dev_image_tag

            # # Add the component dictionary to the repo_tag_list
            # self._repo_tag_list.append(component_dict.copy())

    # Function to parse AI Services CR template for image repositories and tags
    def parse_ai_services_template(self):
        self._logger.info(f"Retrieving AI Services component tags and repositories")
        try:
            with open(self._ai_services_pattern_path, 'r') as file:
                ai_services_template_yaml = yaml.safe_load(file)

        except Exception as e:
            print(f"Error occurred while reading YAML file {self._ai_services_pattern_path}: {e}")
            self._logger.info(f"Error occurred while reading YAML file {self._ai_services_pattern_path}: {e}")
            return

        if ai_services_template_yaml:
            keys_to_parse = ['repository', 'tag']
            parsed_keys = parse_yaml_for_keys(ai_services_template_yaml, keys_to_parse)

            num_components = len(parsed_keys['repository'])

            for i in range(num_components):
                component_dict = {}

                # Calculate Component Name
                component_name = parsed_keys['repository'][i].split("/")[-1]
                component_dict['components'] = component_name

                # Calculate Tag or Digest
                if "sha256:" in parsed_keys['tag'][i]:
                    component_dict['digest'] = parsed_keys['tag'][i]
                else:
                    component_dict['tag'] = parsed_keys['tag'][i]

                # Calculate Repository
                repository = parsed_keys['repository'][i]
                component_dict['repository'] = repository.lower()

                # Add the component dictionary to the repo_tag_list only if not duplicate
                if not self._is_duplicate_image(component_dict):
                    self._repo_tag_list.append(component_dict.copy())
                else:
                    self._logger.info(f"Skipping duplicate AI Services image: {component_name} - {repository}")

            self._logger.info(f"AI Services components: {self._repo_tag_list}")

            # Modify repositories (and optionally tags) for dev environment
            if self._dev:
                for component_dict in self._repo_tag_list:
                    component_dict["repository"] = component_dict["repository"].replace("cp.icr.io", "preprod.icr.io")
                    if self._dev_image_tag and "tag" in component_dict:
                        component_dict["tag"] = self._dev_image_tag

    # Function to parse and retrieve operator image tag and repository from deployment YAML
    def parse_operator_template(self, operator_path=None, operator_name="ibm-fncm-operator"):
        """
        Parse operator deployment YAML to extract image repository and tag/digest.
        
        Args:
            operator_path: Path to operator.yaml file. If None, uses self._operator_path
            operator_name: Name to use for the component in the image list
        """
        if operator_path is None:
            operator_path = self._operator_path
            
        self._logger.info(f"Getting {operator_name} digest, tag and repository from {operator_path}")
        try:
            with open(operator_path, 'r') as file:
                operator_template_yaml = yaml.safe_load(file)

        except Exception as e:
            print(f"Error occurred while reading YAML file {operator_path}: {e}")
            self._logger.info(f"Error occurred while reading YAML file {operator_path}: {e}")
            return

        component_dict = {}

        if operator_template_yaml:
            # Check if operator image is using a tag vs digest
            image = operator_template_yaml["spec"]["template"]["spec"]["containers"][0].get("image", "")
            if "@" in image:
                # If using digest, split by '@' to get the repository and digest
                operator_repository, operator_digest = image.split("@")
                component_dict["digest"] = operator_digest
            else:
                # If using tag, split by ':' to get the repository and tag
                operator_repository, operator_tag = image.split(":")
                component_dict["tag"] = operator_tag
            # In dev mode rewrite CCX operator images (icr.io/cpopen → preprod.icr.io/cpopen).
            # Third-party / Common Services operators have no staging equivalent and must
            # always be pulled from the production registry, regardless of dev mode.
            if self._dev and not self._is_production_only_image(operator_repository):
                operator_repository = operator_repository.replace("cp.icr.io", "preprod.icr.io")
                operator_repository = operator_repository.replace("icr.io/cpopen", "preprod.icr.io/cpopen")

            # Add the repository to the component dictionary
            component_dict['repository'] = operator_repository.lower()
            # Add the component name
            component_dict["components"] = operator_name

            # Add operator image only if not duplicate
            if not self._is_duplicate_image(component_dict):
                self._repo_tag_list.append(component_dict)
            else:
                self._logger.info(f"Skipping duplicate operator image: {operator_name}")
            
            # Check for additional images in env variables (e.g., operand images injected
            # by the operator at runtime).  Skip any env var whose value is the same image
            # as the operator container itself — those are self-referencing vars like
            # OPERATOR_IMAGE_NAME and would otherwise create a duplicate entry.
            containers = operator_template_yaml["spec"]["template"]["spec"]["containers"]
            for container in containers:
                main_image = container.get("image", "")
                if "env" in container:
                    for env_var in container["env"]:
                        # Look for image environment variables
                        if "IMAGE" in env_var.get("name", "") and "value" in env_var:
                            env_image = env_var["value"]

                            # Skip env vars that reference the same image as the container
                            if env_image == main_image:
                                self._logger.info(
                                    f"Skipping self-referencing env var {env_var['name']}"
                                )
                                continue

                            env_component_dict = {}
                            
                            if "@" in env_image:
                                env_repository, env_digest = env_image.split("@")
                                env_component_dict["digest"] = env_digest
                            else:
                                env_repository, env_tag = env_image.split(":")
                                env_component_dict["tag"] = env_tag
                                
                            if self._dev and not self._is_production_only_image(env_repository):
                                env_repository = env_repository.replace("cp.icr.io", "preprod.icr.io")
                                env_repository = env_repository.replace("icr.io/cpopen", "preprod.icr.io/cpopen")
                                
                            env_component_dict['repository'] = env_repository.lower()
                            # Extract component name from env variable name or image path
                            component_name = env_var["name"].lower().replace("_image", "").replace("ibm_", "").replace("_", "-")
                            env_component_dict["components"] = component_name
                            
                            # Add env image only if not duplicate
                            if not self._is_duplicate_image(env_component_dict):
                                self._repo_tag_list.append(env_component_dict)
                            else:
                                self._logger.info(f"Skipping duplicate env image: {component_name}")



        # if operator_template_yaml:
        #     operator_repository, operator_tag = operator_template_yaml["spec"]["template"]["spec"]["containers"][0][
        #         "image"].split(":")
        #     if self._dev:
        #         operator_repository = operator_repository.replace("icr.io/cpopen", "preprod.icr.io/cp")
        #     self._repo_tag_dict["repository"].append(operator_repository)
        #     self._repo_tag_dict["tag"].append(operator_tag)
        #     self._repo_tag_dict["components"].append("ibm-fncm-operator")

    def parse_wdu_cr_template(self):
        """
        Parse WDU operand images from ibm_wdu_services_full_cr.yaml.

        The CR exposes a repository prefix (e.g. cp.icr.io/cp/cp4a/iadp) and a
        shared tag.  The two concrete sub-images the operator pulls at runtime are:
            <repository>/wdu_runtime:<tag>
            <repository>/wdu_models:<tag>

        These names are baked into the operator binary and not listed in any
        file in this repo, but must be present in the private registry for
        air-gap deployments.
        """
        self._logger.info(f"Parsing WDU CR template for operand images: {self._wdu_pattern_path}")
        try:
            with open(self._wdu_pattern_path, "r") as f:
                wdu_yaml = yaml.safe_load(f)
        except Exception as e:
            self._logger.warning(f"Could not read WDU CR {self._wdu_pattern_path}: {e}")
            return

        try:
            image_block = wdu_yaml["spec"]["ccx_wdu_configuration"]["image"]
        except (KeyError, TypeError) as e:
            self._logger.warning(f"Could not find spec.ccx_wdu_configuration.image in WDU CR: {e}")
            return

        repository = (image_block.get("repository") or "").strip().rstrip("/")
        tag = (image_block.get("tag") or "").strip()

        if not repository:
            self._logger.warning("No repository found in WDU CR image block")
            return
        if not tag:
            self._logger.warning("No tag found in WDU CR image block — cannot resolve WDU sub-images")
            return

        for sub_image in ("wdu_runtime", "wdu_models"):
            repo = f"{repository}/{sub_image}".lower()
            if self._dev:
                repo = repo.replace("cp.icr.io", "preprod.icr.io")
            component_dict = {
                "components": sub_image,
                "repository": repo,
                "tag": self._dev_image_tag if (self._dev and self._dev_image_tag) else tag,
            }
            if not self._is_duplicate_image(component_dict):
                self._repo_tag_list.append(component_dict)
            else:
                self._logger.info(f"Skipping duplicate WDU sub-image: {sub_image}")

    def parse_images_txt(self, images_txt_path: str, component_prefix: str = "") -> None:
        """
        Parse a plain-text ``images.txt`` file and add every listed image to the
        internal repo-tag list so it is included in ``imageDetails.toml``.

        Each non-empty, non-comment line must be a fully-qualified image reference:
            <repository>@<digest>   (digest-pinned, preferred)
            <repository>:<tag>      (tag-pinned)

        These images are used verbatim — no dev-registry rewriting and no tag
        substitution is applied regardless of the ``--dev`` flag.

        Args:
            images_txt_path:  Absolute path to the ``images.txt`` file.
            component_prefix: Optional prefix prepended to the derived component
                              name (e.g. "cnpg-" → "cnpg-ibm-pg-16").
        """
        self._logger.info(f"Parsing operand images from {images_txt_path}")
        try:
            with open(images_txt_path, "r") as fh:
                lines = fh.readlines()
        except Exception as exc:
            self._logger.warning(f"Could not read {images_txt_path}: {exc}")
            return

        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            # Bundle and catalog images are OLM-only artifacts — skip them.
            if "-bundle@" in line or "-catalog@" in line or "-bundle:" in line or "-catalog:" in line:
                self._logger.info(f"Skipping OLM-only image: {line}")
                continue

            component_dict: dict = {}

            if "@" in line:
                repository, digest = line.split("@", 1)
                component_dict["digest"] = digest
            elif ":" in line:
                repository, tag = line.rsplit(":", 1)
                component_dict["tag"] = tag
            else:
                self._logger.warning(f"Skipping unrecognised image line (no '@' or ':'): {line!r}")
                continue

            # Derive a readable component name from the last path segment.
            component_name = f"{component_prefix}{repository.split('/')[-1]}"
            component_dict["components"] = component_name
            component_dict["repository"] = repository.lower()

            if not self._is_duplicate_image(component_dict):
                self._repo_tag_list.append(component_dict)
                self._logger.info(f"Added operand image: {component_name} — {repository}")
            else:
                self._logger.info(f"Skipping duplicate operand image: {component_name} — {repository}")

    def create_image_details_file(self):

        self._logger.info(f"Creating file with image details")
        # Create the CNCF Image Details folder
        self.__create_cncf_image_details_folder()

        try:
            image_doc = document()
            image_doc.add(comment("##########################################################"))
            image_doc.add(comment("##  IBM Content Cortex Component Image Details ##"))
            image_doc.add(comment("##########################################################"))

            # Track component names to handle duplicates
            component_name_counts = {}

            for component in self._repo_tag_list:
                component_section = table()

                self.__write_property_table(section=component_section,
                                            key="REPOSITORY",
                                            value=component.get("repository", ''),
                                            note='')

                if 'digest' in component:
                    self.__write_property_table(section=component_section,
                                                key="DIGEST",
                                                value=component.get("digest", ''),
                                                note='')
                else:
                    self.__write_property_table(section=component_section,
                                                key="TAG",
                                                value=component.get("tag", ''),
                                                note='')

                component_name = component.get("components", '').upper()
                
                # Handle duplicate component names by adding a suffix
                if component_name in component_name_counts:
                    component_name_counts[component_name] += 1
                    unique_component_name = f"{component_name}_{component_name_counts[component_name]}"
                    self._logger.info(f"Duplicate component name detected: {component_name}, using {unique_component_name}")
                else:
                    component_name_counts[component_name] = 1
                    unique_component_name = component_name
                
                image_doc.add(f"{unique_component_name}", component_section)
                image_doc.add(nl())

            f = TOMLFile(self._image_details_file)
            f.write(image_doc)
            self._logger.info("Generating image details toml file completed successfully")


        except Exception as e:
            self._logger.exception(f"Exception while trying to create image details toml - {e}")

    # # Function to create the TOML file
    # def create_image_details_file(self):
    #
    #     # Create the CNCF Image Details folder
    #     self.__create_cncf_image_details_folder()
    #
    #     if (len(self._repo_tag_dict["repository"]) != len(self._repo_tag_dict["tag"])) or len(
    #             self._repo_tag_dict["repository"]) == 0:
    #         self._logger.exception(
    #             "Error with the content pattern template, matching pairs of repositories and tags not found")
    #         exit(0)
    #     try:
    #         image_doc = document()
    #         image_doc.add(comment("####################################################"))
    #         image_doc.add(comment("##           FNCM Component Image Details          ##"))
    #         image_doc.add(comment("####################################################"))
    #
    #         for i in range(len(self._repo_tag_dict["components"])):
    #             component_section = table()
    #             for key, value in self._image_details_template.items():
    #                 if key.lower() == "repository":
    #                     self.__write_property_table(section=component_section,
    #                                                 key=key,
    #                                                 value=self._repo_tag_dict["repository"][i],
    #                                                 note=value['comment'])
    #
    #                 else:
    #                     self.__write_property_table(section=component_section,
    #                                                 key=key,
    #                                                 value=self._repo_tag_dict["tag"][i],
    #                                                 note=value['comment'])
    #
    #             component_name = self._repo_tag_dict["components"][i].upper()
    #             image_doc.add(f"{component_name}", component_section)
    #             image_doc.add(nl())
    #
    #         f = TOMLFile(self._image_details_file)
    #         f.write(image_doc)
    #         self._logger.info("Generating image details toml file completed successfully")
    #
    #
    #     except Exception as e:
    #         self._logger.exception(f"Exception while trying to create image details toml - {e}")

    # Parsing toml file into a dictionary
    def parse_toml_file(self, image_details_dict=None):
        self._logger.info(f"Creating image details dictionary using toml file: {self._image_details_file}")
        if image_details_dict is None:
            image_details_dict = toml.loads(open(self._image_details_file, encoding="utf-8").read())
        self._repo_tag_dict_from_file["components"] = list(image_details_dict.keys())
        self._number_of_images = len(image_details_dict.keys())

        self._repo_tag_dict_from_file["repository"] = [value['REPOSITORY'].lower() for value in
                                                       image_details_dict.values()]
        # Handle both TAG and DIGEST fields - use TAG if present, otherwise use DIGEST
        self._repo_tag_dict_from_file["tag"] = [
            value.get('TAG', value.get('DIGEST', '')) for value in image_details_dict.values()
        ]
        for repository in self._repo_tag_dict_from_file["repository"]:
            if self._dev:
                if "icr.io/cpopen" in repository:
                    repository = repository.replace("icr.io/cpopen", "preprod.icr.io/cp")
                if "cp.icr.io" in repository:
                    repository = repository.replace("cp.icr.io", "preprod.icr.io")

    # Function to enable generate image mirror config
    def generate_mirror_manifests(self, progress, task):
        self._logger.info(f"Generating mirror manifests")
        try:
            env_vars = self._airgap_vars.copy()
            env_vars["PATH"] = os.environ["PATH"]
            env_vars["HOME"] = os.environ["HOME"]

            case_name = env_vars["CASE_NAME"]
            target_registry = env_vars["TARGET_REGISTRY"]
            case_version = env_vars["CASE_VERSION"]

            command = f"oc ibm-pak generate mirror-manifests {case_name} {target_registry} --version {case_version}"

            process = subprocess.run(command, env=env_vars, shell=True, capture_output=True)


            if process.returncode != 0:
                progress.log(Panel.fit(Text("Error enabling generate-mirror", style="bold red")))
                progress.log(process.stderr.decode("utf-8"))
                self._logger.info(f"Error occurred while enabling generate-mirror: {process.stderr.decode('utf-8')}")
                progress.update(task, advance=1)
                return None

            progress.update(task, advance=1)
            return process.stdout.decode("utf-8")

        except Exception as e:
            print(Panel.fit(Text("Error enabling generate-mirror", style="bold red")))
            self._logger.info(f"Error occurred while enabling generate-mirror: {e}")
            return False

    # Private Function to parse channel files
    def __parse_channel_files(self, file_path=None) -> list:
        self._logger.info(f"Getting the channels")
        try:
            with open(file_path, 'r') as file:
                image_set = yaml.safe_load(file)

            parsed_channel_list = []
            # Collect channels from the image-set-config.yaml
            if 'channels' in image_set['mirror']['operators'][0]['packages'][0]:
                channels = image_set['mirror']['operators'][0]['packages'][0]['channels']

                # Parse list of channels
                for channel in channels:
                    parsed_channel_list.append(channel['name'])

            return parsed_channel_list
        except Exception as e:
            self._logger.info(f"Error occurred while reading YAML file {file_path}: {e}")
            return []

    # Function to update channels in the image-set-config.yaml
    def update_image_channels(self, channels=None):
        try:

            self._logger.info(f"Updating the channels")
            env_vars = self._airgap_vars.copy()
            env_vars["HOME"] = os.environ["HOME"]

            file_path = os.path.join(env_vars['IBMPAK_HOME'], '.ibm-pak', 'data', 'mirror', env_vars['CASE_NAME'],
                                          env_vars['CASE_VERSION'], 'image-set-config.yaml')

            with open(file_path, 'r') as file:
                image_set = yaml.safe_load(file)

            # Build the list of channels
            channels_list = []
            channels.sort()
            for channel in channels:
                channels_list.append({'name': channel})

            # Update channels in the image-set-config.yaml
            if 'channels' in image_set['mirror']['operators'][0]['packages'][0]:
                image_set['mirror']['operators'][0]['packages'][0]['channels'] = channels_list

            with open(file_path, 'w') as file:
                yaml.dump(image_set, file)

            print()
            print(Panel.fit(Text("Channels updated successfully", style="bold green")))
            print()
            self._logger.info(f"Channels updated successfully")

            return True
        except Exception as e:
            self._logger.info(f"Error occurred while updating YAML file {file_path}: {e}")
            return False

    # Function to select channel for mirror
    def select_channel(self, channels=None):
        try:
            print()
            print(Panel.fit("Airgap Mirror Channels"))
            self._logger.info(f"Getting the channels to be mirrored")

            if self._silent_mode:


                num_channels = len(channels)
                choices_set = set()
                choices_list = channels

                if not self._all_channel:
                    # Calculate channel based on FNCM Version
                    current_channel = self.AirgapChannel.Channel(self._ccx_version).name
                    choices_set.add(current_channel)
                else:
                    choices_set = set(channels)

                print()
                print("Select the channels you want to mirror.")
                print("All images in the selected channels will be mirrored.")
                print("Reducing the number of channels will reduce the size of the total image set.")
                print()
                print("Enter a number to toggle selection")
                print("Enter [[b]0[/b]] to finish selection")
                for i, choice in enumerate(channels, 1):
                    print(f"{i}. {choice} {':heavy_check_mark:' if choice in choices_set else ''}")

            else:
                # Use questionary for channel selection
                print()
                print(Panel.fit(
                    "[bold cyan]Select Channels to Mirror[/bold cyan]\n\n"
                    "All images in the selected channels will be mirrored.\n"
                    "Reducing the number of channels will reduce the size of the total image set.",
                    style="cyan"
                ))
                print()
                
                # Create choices for questionary checkbox
                channel_choices = [
                    questionary.Choice(title=channel, value=channel, checked=True)
                    for channel in channels
                ]
                
                try:
                    selected_channels = questionary.checkbox(
                        "Select channels to mirror (use Space to select/deselect, Enter to confirm):",
                        choices=channel_choices,
                        style=Style([
                            ('selected', 'fg:green bold'),
                            ('pointer', 'fg:cyan bold'),
                            ('highlighted', 'fg:cyan'),
                            ('answer', 'fg:green bold'),
                            ('checkbox', 'fg:cyan bold'),
                            ('checkbox-selected', 'fg:green bold')
                        ]),
                        validate=lambda x: len(x) > 0 or "At least one mirror channel must be selected"
                    ).ask()
                    
                    if selected_channels is None:
                        # User cancelled, default to all channels
                        print()
                        print("[yellow]⚠ Selection cancelled. Defaulting to all channels.[/yellow]")
                        choices_set = set(channels)
                    elif len(selected_channels) == 0:
                        # No channels selected (shouldn't happen due to validation)
                        print()
                        print("[yellow]⚠ No channels selected. Defaulting to all channels.[/yellow]")
                        choices_set = set(channels)
                    else:
                        choices_set = set(selected_channels)
                        
                except Exception as e:
                    # Fallback to all channels if questionary fails
                    print()
                    print(f"[yellow]⚠ Error with channel selection: {e}[/yellow]")
                    print("[yellow]Defaulting to all channels.[/yellow]")
                    choices_set = set(channels)

            return list(choices_set)
        except Exception as e:
            self._logger.info(f"Error occurred while selecting channels: {e}")
            return []

    # Function to apply ImageMirrorPolicy to the cluster
    def apply_image_mirror_policy(self, progress, task):
        try:
            progress.log(Panel.fit(Text("Starting Cluster Setup"), style="bold cyan"))
            progress.log()
            self._logger.info(f"Starting the cluster setup")

            progress.log(f"Applying ImageContentSourcePolicy to the cluster")
            progress.log()
            self._logger.info(f"Applying the ICSP to the cluster")

            env_vars = self._airgap_vars.copy()
            env_vars["HOME"] = os.environ["HOME"]

            case_name = env_vars["CASE_NAME"]
            case_version = env_vars["CASE_VERSION"]
            pak_home = env_vars["IBMPAK_HOME"]

            image_mirror_policy_file = os.path.join(pak_home, '.ibm-pak', 'data', 'mirror', case_name, case_version, 'image-content-source-policy.yaml')

            self._kube.apply_cluster_resource_files(
                resource_file=image_mirror_policy_file,
                resource_type="image policy")

            progress.log(Text(f"ImageContentSourcePolicy applied to the cluster successfully!", style="bold green"))
            progress.log()
            self._logger.info(f"ICSP is applied successfully to the cluster")


            progress.update(task, advance=1)
            return True
        except Exception as e:
            progress.log(Panel(Text(f"Error occurred while applying ImageMirrorPolicy"), style="bold red"))
            progress.log()
            self._logger.info(f"Error occurred while applying ImageMirrorPolicy: {e}")
            return False


    # Function to mirror images to private registry
    def mirror_images(self, progress, task):
        try:
            progress.log(Panel.fit(Text("Starting Airgap Mirror"), style="bold cyan"))
            progress.log()
            self._logger.info(f"Starting airgap mirroring")

            env_vars = self._airgap_vars.copy()
            env_vars["PATH"] = os.environ["PATH"]
            env_vars["HOME"] = os.environ["HOME"]

            case_name = env_vars["CASE_NAME"]
            target_registry = env_vars["TARGET_REGISTRY"]
            case_version = env_vars["CASE_VERSION"]
            pak_home = env_vars["IBMPAK_HOME"]

            # Construct image path to image-set-config.yaml
            image_set_yaml = os.path.join(pak_home, '.ibm-pak', 'data', 'mirror', case_name, case_version, 'image-set-config.yaml')

            # Construct the command to mirror images
            command = f"oc mirror --config {image_set_yaml} docker://{target_registry} --dest-skip-tls --max-per-registry=6"

            # Execute Image Mirror command
            process = subprocess.Popen(command, stdout=subprocess.PIPE, env=env_vars, shell=True, stderr=subprocess.PIPE)

            while True:
                line = process.stdout.readline().decode('utf-8')
                if not line:
                    break
                progress.log(line)

            error = process.stderr.read().decode('utf-8')
            error_split = error.split("msg=")
            error_msg = error_split[-1]
            status_code = process.wait()

            self._logger.info(f"Image Mirror process completed with error: {error_msg}")
            self._logger.info(f"Image Mirror process completed with status code: {status_code}")

            if status_code != 0:
                progress.log(Text(error_msg, style="bold red"))
                progress.log(Text(f"Error mirroring images to private registry", style="bold red"))
                progress.log()
                progress.update(task, total=1)
                progress.update(task, advance=1)
                return False

            progress.log(Text(f"All images mirrored to private registry successfully!", style="bold green"))
            progress.log()
            progress.update(task, total=1)
            progress.update(task, advance=1)
            return True

        except Exception as e:
            self._logger.info(f"Error: {e}")
            progress.update(task, total=1)
            progress.update(task, advance=1)
            return False

    # Function to select channel
    def collect_image_channels(self):
        self._logger.info(f"Collecting image channels")
        env_vars = self._airgap_vars.copy()
        env_vars["HOME"] = os.environ["HOME"]

        image_set_yaml = os.path.join(env_vars['IBMPAK_HOME'], '.ibm-pak', 'data', 'mirror', env_vars['CASE_NAME'],
                                      env_vars['CASE_VERSION'], 'image-set-config.yaml')

        channels = self.__parse_channel_files(image_set_yaml)

        selected_channels = self.select_channel(channels)

        # If there are differences between the selected channels and the channels in the image-set-config.yaml
        # Update the image-set-config.yaml
        if selected_channels != channels:
            self.update_image_channels(selected_channels)
            # Return true if the channels were updated
            return True

        return False

    # Function to enable oc image mirror
    def enable_oc_image(self, progress, task):
        self._logger.info(f"Enabling oc-mirror")
        try:
            env_vars = self._airgap_vars.copy()
            env_vars["PATH"] = os.environ["PATH"]
            env_vars["HOME"] = os.environ["HOME"]

            command = "oc ibm-pak config mirror-tools --enabled oc-mirror"

            process = subprocess.run(command, env=env_vars, shell=True, capture_output=True, text=True)

            if process.returncode == 0:
                progress.update(task, advance=1)

            else:
                self._logger.info(f"Error occurred while enabling oc-mirror: {process.stderr}")
                progress.update(task, advance=1)
                return False

            return True

        except Exception as e:
            print(Panel.fit(Text("Error enabling oc-mirror", style="bold red")))
            self._logger.info(f"Error occurred while enabling oc-mirror: {e}")
            return False

    # Function to Download Case
    def download_case(self):
        self._logger.info(f"Downloading case-package")
        try:

            env_vars = self._airgap_vars.copy()
            env_vars["PATH"] = os.environ["PATH"]
            env_vars["HOME"] = os.environ["HOME"]

            command1 = "oc ibm-pak config repo 'IBM Cloud-Pak OCI registry' -r oci:cp.icr.io/cpopen --enable"

            process1 = subprocess.run(command1, env=env_vars, shell=True, capture_output=True, text=True)

            if process1.returncode == 0:
                repo_enabled = True
            else:
                repo_enabled = False

            command2 = f"oc ibm-pak get {self._casename} --version {self._casepackage_version}"

            process2 = subprocess.run(command2, env=env_vars, shell=True, capture_output=True, text=True)

            if process2.returncode != 0:
                print()
                print(Panel.fit(Text("Case Download Failed\n"
                                     "Please check logs for additional information"), style="bold red"))
                self._logger.info(f"Error occurred while downloading case: {process2.stderr}")
                return False

        except Exception as e:
            print()
            print(Panel.fit(Text("Case Download Failed\n"
                                 "Please check logs for additional information"), style="bold red"))
            self._logger.info(f"Error occurred while downloading case: {e}")
            return False

        layout = generate_casepackage_results(ibmpak_folder=os.path.join(self.ibmpak_home, '.ibm-pak'),
                                              download_output=process2.stdout,
                                              repo=repo_enabled)

        return layout

    # Function to read all env variables from the airgap variables file
    def read_airgap_vars(self):
        airgap_vars = {}
        # Need to ignore comments and "remove" the export keyword
        with open(self._airgap_details_file, 'r') as file:
            for line in file:
                if line and not line.startswith('#'):
                    key, value = line.strip().split("=")
                    key = key.replace("export ", "")
                    airgap_vars[key] = value

        return airgap_vars

    # Function to copy all images to private registry with new Live tracker (recommended)
    def copy_images_with_live_tracker(self):
        """
        Copy images to private registry using the new image_push_progress module.
        This provides a clean Live display with multi-threading support similar to deployment_progress.
        
        This is the recommended method for image copying as it provides:
        - Clean Live display updates
        - Multi-threaded parallel copying
        - Graceful interrupt handling
        - Real-time progress tracking
        """
        from ..utilities.image_push_progress import create_image_push_progress, display_push_complete
        
        # Log to file only to avoid breaking the live display UI
        # Use file handler directly to prevent console output
        if self._logger:
            for handler in self._logger.handlers:
                if isinstance(handler, logging.FileHandler):
                    record = self._logger.makeRecord(
                        self._logger.name,
                        logging.INFO,
                        "(load_extract.py)",
                        1293,
                        "Copying images to the private registry with Live tracker",
                        (),
                        None
                    )
                    handler.emit(record)
                    break
        
        # Prepare image list from the parsed TOML file
        images = []
        for i in range(len(self._repo_tag_dict_from_file["repository"])):
            tag_or_digest = self._repo_tag_dict_from_file["tag"][i]
            repository = self._repo_tag_dict_from_file["repository"][i]
            
            # Use only the image name (leaf segment of the source path) when
            # building the destination.  The customer's PRIVATE_REGISTRY_URL
            # already contains their full namespace/path; appending the IBM
            # source namespace folders (cpopen/, cp/cp4a/fncm/, etc.) on top
            # would create an unintended double-path.
            #   icr.io/cpopen/ibm-usage-metering-operator → <registry>/ibm-usage-metering-operator
            #   cp.icr.io/cp/cp4a/fncm/cpe               → <registry>/cpe
            image_name_only = repository.split("/")[-1]

            # Handle both tag and digest formats
            if tag_or_digest.startswith("sha256:"):
                # Using digest
                source_image = f"{repository}@{tag_or_digest}"
                dest_image = f"{self._private_registry_full_server}/{image_name_only}@{tag_or_digest}"
                image_name = f"{image_name_only}@{tag_or_digest[:15]}..."
            else:
                # Using tag
                source_image = f"{repository}:{tag_or_digest}"
                dest_image = f"{self._private_registry_full_server}/{image_name_only}:{tag_or_digest}"
                image_name = f"{image_name_only}:{tag_or_digest}"
            
            images.append((image_name, source_image, dest_image))
        
        # Create tracker and live display
        tracker, live = create_image_push_progress(
            images=images,
            max_workers=4,
            tls_verify=self._tls_verify,
            src_creds=self._src_creds,
            prod_src_creds=self._prod_src_creds,
            dest_creds=self._dest_creds,
            dest_cert_dir=self._dest_cert_dir,
            console=self._console,
            logger=self._logger
        )
        
        try:
            # Start live display
            live.start()
            
            # Start background thread to update display
            import threading
            
            def update_display():
                """
                Background thread to refresh the display.
                Continues running even if individual updates fail.
                """
                while not tracker.is_complete() and not tracker.shutdown_event.is_set():
                    try:
                        live.update(tracker.create_progress_display())
                        time.sleep(0.25)  # Update 4 times per second
                    except Exception as e:
                        # Log the error but continue updating
                        # This prevents UI breakage from stopping the display
                        if tracker._logger:
                            tracker._logger.debug(f"Display update error (non-fatal): {e}")
                        time.sleep(0.5)  # Slow down on errors
                        continue  # Keep trying to update
            
            display_thread = threading.Thread(target=update_display, daemon=True)
            display_thread.start()
            
            # Push images in parallel
            results = tracker.push_images_parallel()
            
            # Wait for display thread to finish
            display_thread.join(timeout=1.0)
            
            # Final display update
            live.update(tracker.create_progress_display())
            
        finally:
            # Stop live display
            if live._started:
                live.stop()
        
        # Display completion summary
        display_push_complete(tracker, self._console)
        
        # Set summary in expected format for compatibility
        self._image_push_summary["completed"] = results["completed"]
        self._image_push_summary["failed"] = results["failed"]
        self._image_push_summary["total"] = results["total"]
        self._image_push_summary["private_registry"] = self._private_registry_full_server
    
