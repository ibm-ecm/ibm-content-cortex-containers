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
import os.path
import re
import shutil
import yaml

from kubernetes import client
from kubernetes.client import ApiException
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from time import sleep

from ..utilities import kubernetes_utilites as k
from ..utilities.utilities import replace_namespace_in_file, create_tmp_folder


# CLass that contains functions to delete the CR as well delete the Operator
class Deploy:

    def __init__(self, console, setup=None, logger=None, required_files=None):
        self._logger = logger
        self._kube = k.KubernetesUtilities(logger)
        self._setup = setup
        self._console = console
        self._stop_polling = False  # Flag to stop background polling loops

        self.required_file_paths = {}
        for file in required_files:
            file_name = file.split("/")[-1]
            self.required_file_paths[file_name] = file
        
        # Extract catalog and operator names from descriptor files
        self._catalog_name = self._extract_catalog_name()
        self._operator_deployment_name = self._extract_operator_name()

        # Tmp File paths for the resources
        # Use catalog name to create unique temp files per operator to avoid conflicts
        # when deploying multiple operators simultaneously
        create_tmp_folder()
        modified_files = [
            "cluster_role_binding.yaml",
            "catalogsource.yaml",
            "operator_group.yaml",
            "subscription.yaml",
            "operator.yaml"
        ]
        self.tmp_file_paths = {}
        for file in modified_files:
            # Create unique temp filename using catalog name to prevent overwrites
            # Example: catalogsource.yaml -> ibm-content-operator-catalog_catalogsource.yaml
            unique_filename = f"{self._catalog_name}_{file}"
            self.tmp_file_paths[file] = os.path.join(os.getcwd(), ".tmp", unique_filename)

        self._apps_v1_api = self._kube.apps_v1
        self._core_v1_api = self._kube.core_v1
        self._custom_api = self._kube.custom_api

        if self._setup.private_catalog:
            self._catalog_namespace = self._setup.namespace
        else:
            self._catalog_namespace = "openshift-marketplace"

        # Deployment type is now determined by private_catalog setting
        # Helm is the default for both OCP and CNCF platforms
        if self._setup.private_catalog:
            self._deployment_type = "olm"
            self._task_numbers = {
                "ClusterSetup": 4,
                "DeploymentSetup": 3,
                "Install": 3,
            }
        else:
            self._deployment_type = "helm"
            self._task_numbers = {
                "ClusterSetup": 2,
                "DeploymentSetup": 4,
                "Install": 2,
            }

    @property
    def task_numbers(self):
        return self._task_numbers

    @property
    def deployment_type(self):
        return self._deployment_type
    
    def stop_polling(self):
        """Stop all background polling loops gracefully."""
        self._logger.info("Stopping background polling loops...")
        self._stop_polling = True
    
    def _extract_catalog_name(self):
        """Extract catalog source name from catalogsource.yaml file."""
        try:
            catalog_file = self.required_file_paths.get("catalogsource.yaml")
            if catalog_file and os.path.exists(catalog_file):
                with open(catalog_file, 'r') as f:
                    catalog_yaml = yaml.safe_load(f)
                    name = catalog_yaml.get('metadata', {}).get('name', 'ibm-fncm-operator-catalog')
                    self._logger.info(f"Extracted catalog name from descriptor: {name}")
                    self._logger.info(f"Using catalog file: {catalog_file}")
                    return name
        except Exception as e:
            self._logger.info(f"Could not extract catalog name, using default: {e}")
        return "ibm-fncm-operator-catalog"  # Fallback default
    
    def _extract_operator_name(self):
        """Extract operator deployment name from operator.yaml file."""
        try:
            operator_file = self.required_file_paths.get("operator.yaml")
            if operator_file and os.path.exists(operator_file):
                with open(operator_file, 'r') as f:
                    operator_yaml = yaml.safe_load(f)
                    name = operator_yaml.get('metadata', {}).get('name', 'ibm-fncm-operator')
                    self._logger.info(f"Extracted operator deployment name from descriptor: {name}")
                    return name
        except Exception as e:
            self._logger.info(f"Could not extract operator name, using default: {e}")
        return "ibm-fncm-operator"  # Fallback default

    # Function to create the entitlement key secret for either entitlement key or the private registry

    def create_entitlement_key_secret(self, progress, task, live=None, tracker=None):
        try:
            from ..utilities.interface import format_deployment_step
            from ..utilities.deployment_progress import DeploymentPhase
            
            # Create secret subtask
            if self._setup.private_registry_valid:
                if live is None:
                    secret_task = progress.add_task("[cyan]  ↳ Creating private registry secret...", total=1)
                else:
                    tracker.update_cluster_setup(
                        "Creating private registry secret",
                        progress=55,
                        phase=DeploymentPhase.PREPARING
                    )
                    live.update(tracker.create_progress_display())
                self._logger.info(f"Creating image pull secret for private registry: {self._setup.private_registry_full_server}")
                data = {
                    '.dockerconfigjson': base64.b64encode(
                        bytes(
                            '{{"auths": {{"{}": {{"username": "{}", "password": "{}", "email": "example@example.com"}}}}}}'.format(
                                self._setup.private_registry_full_server,
                                self._setup.private_registry_username,
                                self._setup.private_registry_password),
                            'utf-8'
                        )
                    ).decode('utf-8')
                }
            else:
                if live is None:
                    secret_task = progress.add_task("[cyan]  ↳ Creating IBM Entitlement Registry secret...", total=1)
                else:
                    tracker.update_cluster_setup(
                        "Creating IBM Entitlement Registry secret",
                        progress=55,
                        phase=DeploymentPhase.PREPARING
                    )
                    live.update(tracker.create_progress_display())
                self._logger.info('Creating image pull secret for IBM Entitlement Registry')
                data = {
                    '.dockerconfigjson': base64.b64encode(
                        bytes(
                            '{{"auths": {{"{}": {{"username": "{}", "password": "{}", "email": "example@example.com"}}}}}}'.format(
                                self._setup.registry, "cp",
                                self._setup.entitlement_key),
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
            self._core_v1_api.read_namespaced_secret(name="ibm-entitlement-key", namespace=self._setup.namespace)
        except client.ApiException as e:
            if e.status == 404:
                self._core_v1_api.create_namespaced_secret(namespace=self._setup.namespace, body=secret)
                self._logger.info("Secret 'ibm-entitlement-key' created successfully")
                if live is None:
                    progress.update(secret_task, completed=1, description="[green]  ✓ Secret 'ibm-entitlement-key' created")
                    progress.remove_task(secret_task)
                    progress.advance(task, advance=1)
                else:
                    tracker.update_cluster_setup(
                        "Image pull secret created",
                        progress=70,
                        phase=DeploymentPhase.PREPARING,
                        completed=True
                    )
                    live.update(tracker.create_progress_display())
                return

        if live is None:
            progress.update(secret_task, completed=1, description="[yellow]  ⚠ Secret 'ibm-entitlement-key' already exists")
            progress.remove_task(secret_task)
            progress.advance(task, advance=1)
        else:
            tracker.update_cluster_setup(
                "Image pull secret already exists",
                progress=70,
                phase=DeploymentPhase.PREPARING,
                completed=True
            )
            live.update(tracker.create_progress_display())
        self._logger.info("Secret 'ibm-entitlement-key' already exists")

    def cluster_setup(self, progress, task, live=None, tracker=None):
        # Number of tasks = 1
        try:
            from ..utilities.interface import format_deployment_step
            from ..utilities.deployment_progress import DeploymentPhase
            from ..utilities.operator_config import OperatorType
            
            self._logger.info("Starting Cluster Setup")
            
            if live is None:
                progress.log()

            # Create namespace subtask
            if live is None:
                ns_task = progress.add_task("[cyan]  ↳ Creating namespace...", total=1)
            else:
                tracker.update_cluster_setup(
                    "Creating namespace",
                    progress=25,
                    phase=DeploymentPhase.PREPARING
                )
                live.update(tracker.create_progress_display())
            
            self._logger.info("Creating namespace for the IBM Content Cortex Deployment")

            # Check if the namespace is already present in the cluster
            try:
                api_response = self._core_v1_api.read_namespace_status(self._setup.namespace)

                if api_response.status.phase == "Active":
                    self._logger.info(f"Namespace '{self._setup.namespace}' already exists")
                    if live is None:
                        progress.update(ns_task, completed=1, description=f"[green]  ✓ Namespace '{self._setup.namespace}' already exists")
            except ApiException as e:
                if e.status == 404:
                    self._kube.create_namespace(self._setup.namespace)
                    self._logger.info(f"Namespace '{self._setup.namespace}' created successfully")
                    if live is None:
                        progress.update(ns_task, completed=1, description=f"[green]  ✓ Namespace '{self._setup.namespace}' created")
            
            # Create ibm-licensing namespace if License Service operator is being deployed
            if hasattr(self._setup, 'selected_operators') and OperatorType.LICENSE_ADVISOR in self._setup.selected_operators:
                self._logger.info("License Service operator detected - ensuring ibm-licensing namespace exists")
                try:
                    api_response = self._core_v1_api.read_namespace_status("ibm-licensing")
                    if api_response.status.phase == "Active":
                        self._logger.info("Namespace 'ibm-licensing' already exists")
                        if live is None:
                            progress.update(ns_task, description=f"[green]  ✓ Namespaces '{self._setup.namespace}' and 'ibm-licensing' ready")
                except ApiException as e:
                    if e.status == 404:
                        self._kube.create_namespace("ibm-licensing")
                        self._logger.info("Namespace 'ibm-licensing' created successfully for License Service")
                        if live is None:
                            progress.update(ns_task, description=f"[green]  ✓ Namespaces '{self._setup.namespace}' and 'ibm-licensing' created")
            
            if live is None:
                progress.remove_task(ns_task)
                progress.update(task, advance=1)
            else:
                tracker.update_cluster_setup(
                    "Namespace ready",
                    progress=35,
                    phase=DeploymentPhase.PREPARING,
                    completed=True
                )
                live.update(tracker.create_progress_display())

            self.create_entitlement_key_secret(progress, task, live, tracker)

            if self._deployment_type == "olm":
                # Network policy subtask
                if live is None:
                    net_task = progress.add_task("[cyan]  ↳ Applying network policies...", total=1)
                else:
                    tracker.update_cluster_setup(
                        "Applying network policies",
                        progress=75,
                        phase=DeploymentPhase.PREPARING
                    )
                    live.update(tracker.create_progress_display())
                
                patch_body = [
                    {"op": "replace", "path": "/metadata/labels/network.openshift.io~1policy-group", "value": "ingress"}
                ]
                try:
                    self._core_v1_api.patch_namespace(name="default", body=patch_body)
                    if live is None:
                        progress.update(net_task, completed=1, description="[green]  ✓ Network policy label applied")
                        progress.remove_task(net_task)
                        progress.update(task, advance=1)
                except Exception as e:
                    if live is None:
                        progress.update(net_task, completed=1, description=f"[red]  ✗ Error: {e}")
                        progress.remove_task(net_task)

            if live is None:
                progress.log()
                progress.update(task, advance=1)
            else:
                tracker.update_cluster_setup(
                    "Cluster setup complete",
                    progress=95,
                    phase=DeploymentPhase.PREPARING,
                    completed=True
                )
                tracker.complete_cluster_setup()
                live.update(tracker.create_progress_display())
        except Exception as e:
            if live is None:
                progress.log(format_deployment_step(f"Error in cluster setup: {e}", "error"))
                progress.log()
            else:
                self._logger.error(f"Error in cluster setup: {e}")

    # Function to prepare the installation of the operator, includes applying CRD, RBAC resources
    def apply_cncf(self, progress, task, live=None, tracker=None, operator_type=None):
        """
        Apply CNCF/YAML-style deployment resources for operators.
        
        This method applies resources in the correct order for CNCF platforms:
        1. Custom Resource Definition (CRD)
        2. Service Account
        3. Role
        4. Role Binding
        5. Cluster Role (if present)
        6. Cluster Role Binding (if present)
        
        Args:
            progress: Rich progress object for display
            task: Task ID for progress tracking
            live: Live display object (for multi-operator deployments)
            tracker: Deployment tracker (for multi-operator deployments)
            operator_type: Type of operator being deployed
        """
        try:
            from ..utilities.interface import format_deployment_step
            from ..utilities.deployment_progress import DeploymentPhase, DeploymentStep
            
            # Number of Tasks = 4 (base) + optional cluster-level RBAC
            self._logger.info("Starting CRD and RBAC Setup for CNCF deployment")
            if live is None:
                progress.log()
                progress.log(format_deployment_step("Applying YAML resources for CNCF platform", "info"))

            # Step 1: Apply the CRD
            if live is None:
                crd_task = progress.add_task("[cyan]  ↳ Applying Custom Resource Definition (CRD)...", total=1)
            else:
                tracker.update_operator(
                    operator_type,
                    phase=DeploymentPhase.DEPLOYING,
                    step=DeploymentStep.CRD_DEPLOYMENT,
                    progress=15
                )
                live.update(tracker.create_progress_display())
            
            # Find CRD file dynamically
            crd_file = None
            for filename, filepath in self.required_file_paths.items():
                if filename.endswith("_crd.yaml"):
                    crd_file = filepath
                    break
            
            if not crd_file:
                raise FileNotFoundError("CRD file not found in required files")
            
            self._logger.info(f"Applying Custom Resource Definition: {crd_file}")
            self._kube.apply_cluster_resource_files(
                resource_file=crd_file,
                resource_type="Custom Resource Definition")
            
            if live is None:
                progress.update(crd_task, completed=1, description="[green]  ✓ CRD applied successfully")
                progress.remove_task(crd_task)
                progress.update(task, advance=1)
            else:
                tracker.update_operator(
                    operator_type,
                    step=DeploymentStep.CRD_DEPLOYMENT,
                    progress=25
                )
                live.update(tracker.create_progress_display())

            # Step 2: Apply the Service Account
            if live is None:
                sa_task = progress.add_task("[cyan]  ↳ Applying Service Account...", total=1)
            else:
                tracker.update_operator(
                    operator_type,
                    step=DeploymentStep.RBAC_SETUP,
                    progress=30
                )
                live.update(tracker.create_progress_display())
            
            self._logger.info("Applying Service Account")
            self._kube.apply_cluster_resource_files(
                resource_file=self.required_file_paths["service_account.yaml"],
                resource_type="Service Account",
                namespace=self._setup.namespace)
            
            if live is None:
                progress.update(sa_task, completed=1, description="[green]  ✓ Service Account applied successfully")
                progress.remove_task(sa_task)
                progress.update(task, advance=1)
            else:
                tracker.update_operator(
                    operator_type,
                    step=DeploymentStep.RBAC_SETUP,
                    progress=40
                )
                live.update(tracker.create_progress_display())

            # Step 3: Apply the Role
            if live is None:
                role_task = progress.add_task("[cyan]  ↳ Applying Role (namespace-scoped permissions)...", total=1)
            
            self._logger.info("Applying Role")
            self._kube.apply_cluster_resource_files(
                resource_file=self.required_file_paths["role.yaml"],
                resource_type="Role",
                namespace=self._setup.namespace)
            
            if live is None:
                progress.update(role_task, completed=1, description="[green]  ✓ Role applied successfully")
                progress.remove_task(role_task)
                progress.update(task, advance=1)
            else:
                tracker.update_operator(
                    operator_type,
                    step=DeploymentStep.RBAC_SETUP,
                    progress=50
                )
                live.update(tracker.create_progress_display())

            # Step 4: Apply the Role Binding
            if live is None:
                rb_task = progress.add_task("[cyan]  ↳ Applying Role Binding...", total=1)
            
            self._logger.info("Applying Role Binding")
            self._kube.apply_role_binding(
                namespace=self._setup.namespace,
                resource_file=self.required_file_paths["role_binding.yaml"])
            
            if live is None:
                progress.update(rb_task, completed=1, description="[green]  ✓ Role Binding applied successfully")
                progress.remove_task(rb_task)
                progress.update(task, advance=1)
            else:
                tracker.update_operator(
                    operator_type,
                    step=DeploymentStep.RBAC_SETUP,
                    progress=55
                )
                live.update(tracker.create_progress_display())
            
            # Step 5: Apply Cluster Role (if present)
            if "cluster_role.yaml" in self.required_file_paths:
                if live is None:
                    cr_task = progress.add_task("[cyan]  ↳ Applying Cluster Role (cluster-wide permissions)...", total=1)
                
                self._logger.info("Applying Cluster Role")
                self._kube.apply_cluster_resource_files(
                    resource_file=self.required_file_paths["cluster_role.yaml"],
                    resource_type="Cluster Role")
                
                if live is None:
                    progress.update(cr_task, completed=1, description="[green]  ✓ Cluster Role applied successfully")
                    progress.remove_task(cr_task)
                else:
                    tracker.update_operator(
                        operator_type,
                        step=DeploymentStep.RBAC_SETUP,
                        progress=58
                    )
                    live.update(tracker.create_progress_display())
            
            # Step 6: Apply Cluster Role Binding (if present)
            if "cluster_role_binding.yaml" in self.required_file_paths:
                if live is None:
                    crb_task = progress.add_task("[cyan]  ↳ Applying Cluster Role Binding...", total=1)
                
                self._logger.info("Applying Cluster Role Binding")
                self._kube.apply_cluster_resource_files(
                    resource_file=self.required_file_paths["cluster_role_binding.yaml"],
                    resource_type="Cluster Role Binding")
                
                if live is None:
                    progress.update(crb_task, completed=1, description="[green]  ✓ Cluster Role Binding applied successfully")
                    progress.remove_task(crb_task)
                else:
                    tracker.update_operator(
                        operator_type,
                        step=DeploymentStep.RBAC_SETUP,
                        progress=60
                    )
                    live.update(tracker.create_progress_display())

            self._logger.info("CRD and RBAC Setup Completed")
            if live is None:
                progress.log(format_deployment_step("All YAML resources applied successfully", "success"))
                progress.log()
        except Exception as e:
            self._logger.error(f"Error applying CNCF resources: {e}")
            if live is None:
                progress.log(format_deployment_step(f"Error applying resources: {e}", "error"))
            else:
                tracker.complete_operator(operator_type, success=False, error=str(e))
                live.update(tracker.create_progress_display())
            raise

    # Function to apply OLM , for OCP only
    def apply_olm(self, progress, task, live=None, tracker=None, operator_type=None):
        # Number of tasks = 3
        try:
            from ..utilities.interface import format_deployment_step
            from ..utilities.deployment_progress import DeploymentPhase, DeploymentStep
            
            self._logger.info("Starting OLM Installation")
            if live is None:
                progress.log()
            
            if self._setup.private_catalog:
                self._catalog_namespace = self._setup.namespace
                self._logger.info(f"Using private catalog namespace: {self._catalog_namespace}")
                if live is None:
                    progress.log(format_deployment_step(f"Using private catalog namespace: {self._catalog_namespace}", "info"))
            else:
                self._logger.info(f"Using global catalog namespace (GCN): {self._catalog_namespace}")
                if live is None:
                    progress.log(format_deployment_step(f"Using global catalog namespace: {self._catalog_namespace}", "info"))
                
            # Log the file paths for debugging multi-operator deployments
            self._logger.info(f"Processing catalog source for: {self._catalog_name}")
            self._logger.info(f"  Input file: {self.required_file_paths['catalogsource.yaml']}")
            self._logger.info(f"  Output file: {self.tmp_file_paths['catalogsource.yaml']}")
            
            replace_namespace_in_file(project_name=self._catalog_namespace,
                                      input_file=self.required_file_paths["catalogsource.yaml"],
                                      output_file=self.tmp_file_paths["catalogsource.yaml"],
                                      resource_type="catalog source")

            # Apply Catalog Source with live progress
            if live is None:
                cs_task = progress.add_task("[cyan]  ↳ Applying Catalog Source...", total=1)
            else:
                tracker.update_operator(
                    operator_type,
                    phase=DeploymentPhase.DEPLOYING,
                    step=DeploymentStep.CATALOG_SOURCE,
                    progress=20
                )
                live.update(tracker.create_progress_display())
            
            self._logger.info("Applying/Patching Catalog Source")

            self._kube.apply_cluster_resource_files(
                resource_file=self.tmp_file_paths["catalogsource.yaml"],
                namespace=self._catalog_namespace, resource_type="Catalog Source")
            
            if live is None:
                progress.update(cs_task, completed=1, description="[green]  ✓ Catalog Source applied successfully")
                progress.remove_task(cs_task)
                progress.update(task, advance=1)

            retries = 0
            max_retries = 80
            catalogsource_name = self._catalog_name
            
            if live is None:
                progress.log(format_deployment_step("Waiting for Operator Catalog Pod to start", "info"))
                # Create a subtask for the catalog pod wait with live updates
                catalog_task = progress.add_task(
                    "[cyan]  ↳ Checking catalog pod status...",
                    total=max_retries
                )
            
            while retries < max_retries:
                catalog_ready = self._kube.check_catalogsource_rollout_status(catalogsource_name,
                                                                              self._catalog_namespace)
                if catalog_ready:
                    if live is None:
                        progress.update(catalog_task, completed=max_retries)
                        progress.remove_task(catalog_task)
                        progress.log(format_deployment_step("Operator Catalog Pod is running", "success", indent=1))
                    else:
                        tracker.update_operator(
                            operator_type,
                            step=DeploymentStep.CATALOG_SOURCE,
                            progress=40
                        )
                        live.update(tracker.create_progress_display())
                    break
                else:
                    retries = retries + 1
                    if live is None:
                        progress.update(
                            catalog_task,
                            completed=retries,
                            description=f"[cyan]  ↳ Waiting for catalog pod... ({retries}/{max_retries}) - {retries * 5}s elapsed"
                        )
                    else:
                        # Update progress proportionally
                        catalog_progress = 20 + int((retries / max_retries) * 20)
                        tracker.update_operator(
                            operator_type,
                            step=DeploymentStep.CATALOG_SOURCE,
                            progress=catalog_progress
                        )
                        live.update(tracker.create_progress_display())
                    sleep(5)

            if retries == max_retries:
                if live is None:
                    progress.remove_task(catalog_task)
                    progress.log(format_deployment_step("Timeout waiting for Operator Catalog pod", "error", indent=1))
                    progress.log()
                    progress.log("Check pod status with:")
                    progress.log(Syntax(
                        f"kubectl describe pod $(kubectl get pod -n {self._catalog_namespace} | grep {self._catalog_name} | awk '{{print $1}}') -n {self._catalog_namespace}",
                        "bash"))
                self._logger.debug("Timeout waiting for Operator Catalog pod")

            if live is None:
                progress.update(task, advance=1)

            # Apply Operator Group with live progress
            if live is None:
                og_task = progress.add_task("[cyan]  ↳ Applying Operator Group...", total=1)
            else:
                tracker.update_operator(
                    operator_type,
                    step=DeploymentStep.OPERATOR_GROUP,
                    progress=50
                )
                live.update(tracker.create_progress_display())
            
            self._logger.info("Applying/Patching Operator Group")

            # Check if existing operator group file is present, if not create a new one
            operator_groups = self._kube.list_operator_groups(namespace=self._setup.namespace)
            if operator_groups:
                self._logger.info("Operator Group already exists")
                if live is None:
                    progress.update(og_task, completed=1, description="[yellow]  ⚠ Operator Group already exists")
            else:
                replace_namespace_in_file(project_name=self._setup.namespace,
                                          input_file=self.required_file_paths["operator_group.yaml"],
                                          output_file=self.tmp_file_paths["operator_group.yaml"],
                                          resource_type="operator group")

                self._kube.apply_cluster_resource_files(
                    resource_file=self.tmp_file_paths["operator_group.yaml"],
                    namespace=self._setup.namespace,
                    resource_type="Operator Group")
                if live is None:
                    progress.update(og_task, completed=1, description="[green]  ✓ Operator Group applied successfully")
            
            if live is None:
                progress.remove_task(og_task)
                progress.update(task, advance=1)
            else:
                tracker.update_operator(
                    operator_type,
                    step=DeploymentStep.OPERATOR_GROUP,
                    progress=60
                )
                live.update(tracker.create_progress_display())

            self._logger.info("OLM Installation Completed")
            if live is None:
                progress.log()
        except Exception as e:
            self._logger.debug(f"Error in OLM installation: {e}")
            if live is None:
                progress.log(format_deployment_step(f"Error in OLM installation: {e}", "error"))
            else:
                self._logger.error(f"Error in OLM installation: {e}")

    def wait_for_operator(self, progress, task, live=None, tracker=None, operator_type=None):
        try:
            from ..utilities.interface import format_deployment_step
            from ..utilities.deployment_progress import DeploymentPhase, DeploymentStep
            
            # Initialize attempts counter
            # Number of tasks = 1
            retries = 0
            max_retries = 40
            deployment_name = self._operator_deployment_name
            self._logger.info("Waiting for operator deployment")
            
            if live is None:
                progress.log(format_deployment_step("Waiting for operator pod to start", "info"))
                # Create a subtask for the operator pod wait with live updates
                operator_task = progress.add_task(
                    "[cyan]  ↳ Checking operator pod status...",
                    total=max_retries
                )
            else:
                # Explicitly transition to verifying phase with health check
                tracker.update_operator(
                    operator_type,
                    phase=DeploymentPhase.VERIFYING,
                    step=DeploymentStep.HEALTH_CHECK,
                    progress=85
                )
                live.update(tracker.create_progress_display())
                
                # Small delay to ensure display updates before polling starts
                sleep(0.1)
            
            while retries < max_retries and not self._stop_polling:
                deployed = self._kube.check_deployment_rollout_status(deployment_name, self._setup.namespace)

                if deployed:
                    if live is None:
                        progress.update(operator_task, completed=max_retries)
                        progress.remove_task(operator_task)
                        progress.log(format_deployment_step("Operator pod is running", "success", indent=1))
                        progress.update(task, advance=1)
                    else:
                        tracker.update_operator(
                            operator_type,
                            phase=DeploymentPhase.VERIFYING,
                            step=DeploymentStep.HEALTH_CHECK,
                            progress=95
                        )
                        live.update(tracker.create_progress_display())
                    break
                else:
                    retries = retries + 1
                    if live is None:
                        progress.update(
                            operator_task,
                            completed=retries,
                            description=f"[cyan]  ↳ Waiting for operator pod... ({retries}/{max_retries}) - {retries * 15}s elapsed"
                        )
                    else:
                        # Update progress proportionally
                        wait_progress = 80 + int((retries / max_retries) * 15)
                        tracker.update_operator(
                            operator_type,
                            step=DeploymentStep.HEALTH_CHECK,
                            progress=wait_progress
                        )
                        live.update(tracker.create_progress_display())
                    
                    # Sleep in smaller increments to allow faster exit
                    for _ in range(15):
                        if self._stop_polling:
                            break
                        sleep(1)

            if retries == max_retries:
                if live is None:
                    progress.remove_task(operator_task)
                    progress.log(format_deployment_step("Timeout waiting for operator pod", "error", indent=1))
                    progress.log()
                    progress.log("Check pod status with:")
                    progress.log(Syntax(
                        f"kubectl describe pod $(kubectl get pod -n {self._setup.namespace} | grep {self._operator_deployment_name} | awk '{{ print $1 }}') -n {self._setup.namespace}",
                        "bash"))
                    exit()
                else:
                    self._logger.error("Timeout waiting for operator pod")

            self._logger.info("Operator deployment completed")
            if live is None:
                progress.update(task, advance=1)
            else:
                tracker.complete_operator(operator_type, success=True)
                live.update(tracker.create_progress_display())
        except Exception as e:
            self._logger.debug(f"Error waiting for operator: {e}")
            if live is None:
                progress.log(format_deployment_step(f"Error waiting for operator: {e}", "error"))
                progress.log()
            else:
                self._logger.error(f"Error waiting for operator: {e}")

    def apply_operator_olm(self, progress, task, live=None, tracker=None, operator_type=None):
        # Number of tasks = 2
        from ..utilities.interface import format_deployment_step
        from ..utilities.deployment_progress import DeploymentPhase, DeploymentStep

        self._logger.info("Starting operator installation")
        if live is None:
            progress.log()

        # Apply Subscription with live progress
        if live is None:
            sub_task = progress.add_task("[cyan]  ↳ Applying Subscription...", total=1)
        else:
            tracker.update_operator(
                operator_type,
                phase=DeploymentPhase.DEPLOYING,
                step=DeploymentStep.SUBSCRIPTION,
                progress=65
            )
            live.update(tracker.create_progress_display())
        
        # Log the file paths for debugging multi-operator deployments
        self._logger.info(f"Processing subscription for: {self._catalog_name}")
        self._logger.info(f"  Input file: {self.required_file_paths['subscription.yaml']}")
        self._logger.info(f"  Output file: {self.tmp_file_paths['subscription.yaml']}")
        
        self._logger.info("Applying subscription")

        if self._setup.private_catalog:
            replace_namespace_in_file(project_name=self._setup.namespace,
                                      input_file=self.required_file_paths["subscription.yaml"],
                                      output_file=self.tmp_file_paths["subscription.yaml"],
                                      resource_type="subscription",
                                      private=True)
            self._logger.info(f"Using private catalog: {self._setup.namespace}")
            if live is None:
                progress.update(sub_task, description=f"[cyan]  ↳ Applying Subscription (private catalog: {self._setup.namespace})...")
        else:
            replace_namespace_in_file(project_name=self._setup.namespace,
                                      input_file=self.required_file_paths["subscription.yaml"],
                                      output_file=self.tmp_file_paths["subscription.yaml"],
                                      resource_type="subscription")
            self._logger.info(f"Using global catalog: {self._catalog_namespace}")
            if live is None:
                progress.update(sub_task, description=f"[cyan]  ↳ Applying Subscription (global catalog: {self._catalog_namespace})...")
        
        # Update display to show we're applying the subscription (70% progress)
        if live is not None:
            tracker.update_operator(
                operator_type,
                step=DeploymentStep.SUBSCRIPTION,
                progress=70
            )
            live.update(tracker.create_progress_display())

        # Now apply the subscription (this may take time)
        self._kube.apply_cluster_resource_files(
            resource_file=self.tmp_file_paths["subscription.yaml"],
            namespace=self._setup.namespace,
            resource_type="Subscription")
        
        if live is None:
            progress.update(sub_task, completed=1, description="[green]  ✓ Subscription applied successfully")
            progress.remove_task(sub_task)
            progress.update(task, advance=1)
        else:
            # Mark subscription as complete after API call succeeds
            tracker.update_operator(
                operator_type,
                step=DeploymentStep.SUBSCRIPTION,
                progress=80
            )
            live.update(tracker.create_progress_display())
            
            # Small delay to ensure display updates before transitioning
            sleep(0.1)

        self.wait_for_operator(progress, task, live, tracker, operator_type)

    # Function to install operator on CNCF platforms
    def apply_operator_cncf(self, progress, task, live=None, tracker=None, operator_type=None):
        """
        Deploy operator on CNCF/YAML platforms.
        
        This method:
        1. Configures the operator YAML (license acceptance, registry settings)
        2. Applies the operator Deployment resource
        3. Waits for operator pod to become ready
        
        Args:
            progress: Rich progress object for display
            task: Task ID for progress tracking
            live: Live display object (for multi-operator deployments)
            tracker: Deployment tracker (for multi-operator deployments)
            operator_type: Type of operator being deployed
        """
        # Number of tasks = 2
        from ..utilities.interface import format_deployment_step
        from ..utilities.deployment_progress import DeploymentPhase, DeploymentStep
        
        self._logger.info("Starting operator installation for CNCF platform")
        if live is None:
            progress.log()
            progress.log(format_deployment_step("Deploying operator to cluster", "info"))

        # Step 1: Configure operator deployment YAML
        if live is None:
            config_task = progress.add_task("[cyan]  ↳ Configuring operator deployment YAML...", total=1)
        else:
            tracker.update_operator(
                operator_type,
                phase=DeploymentPhase.DEPLOYING,
                step=DeploymentStep.OPERATOR_DEPLOYMENT,
                progress=65
            )
            live.update(tracker.create_progress_display())
        
        # Copy operator.yaml to temp location for modification
        shutil.copy(self.required_file_paths["operator.yaml"], self.tmp_file_paths["operator.yaml"])

        with open(self.tmp_file_paths["operator.yaml"], 'r') as file:
            content = file.read()

        self._logger.info("Configuring operator deployment settings")

        # Update the 'fncm_license' value to 'accept' (for Content operator)
        # This is safe for operators that don't have this field - regex won't match
        content = re.sub(r'fncm_license:\n  value:.*', 'fncm_license:\n  value: accept', content)

        # Write the modified content back to the temporary operator file
        with open(self.tmp_file_paths["operator.yaml"], 'w') as file:
            file.write(content)

        # Configure registry settings
        with open(self.tmp_file_paths["operator.yaml"], 'r') as file:
            content = file.read()
        registry_in_file = "icr.io/cpopen"

        if self._setup.entitlement_key_valid:
            self._logger.info("Configuring IBM Entitlement Registry")
            if self._setup.runtime_mode == "dev":
                self._logger.info("Using development registry (cp.stg.icr.io)")
                pattern = re.compile(re.escape(registry_in_file) + r'\b')
                replacement = "cp.stg.icr.io" + '/cp'
                content = pattern.sub(replacement, content)

                with open(self.tmp_file_paths["operator.yaml"], 'w') as file:
                    file.write(content)
        else:
            self._logger.info(f"Configuring private registry: {self._setup.private_registry_full_server}")
            pattern = re.compile(re.escape(registry_in_file) + r'\b')
            replacement = self._setup.private_registry_full_server
            content = pattern.sub(replacement, content)

            with open(self.tmp_file_paths["operator.yaml"], 'w') as file:
                file.write(content)

        if live is None:
            progress.update(config_task, completed=1, description="[green]  ✓ Operator YAML configured successfully")
            progress.remove_task(config_task)
            progress.update(task, advance=1)
        else:
            tracker.update_operator(
                operator_type,
                step=DeploymentStep.OPERATOR_DEPLOYMENT,
                progress=70
            )
            live.update(tracker.create_progress_display())

        # Step 2: Apply operator deployment to cluster
        if live is None:
            deploy_task = progress.add_task("[cyan]  ↳ Applying operator Deployment to cluster...", total=1)
        else:
            tracker.update_operator(
                operator_type,
                step=DeploymentStep.OPERATOR_DEPLOYMENT,
                progress=75
            )
            live.update(tracker.create_progress_display())
        
        self._logger.info(f"Applying operator Deployment: {self.tmp_file_paths['operator.yaml']}")

        self._kube.apply_cluster_resource_files(
            resource_file=self.tmp_file_paths["operator.yaml"],
            resource_type="Deployment",
            namespace=self._setup.namespace)
        
        if live is None:
            progress.update(deploy_task, completed=1, description="[green]  ✓ Operator Deployment applied successfully")
            progress.remove_task(deploy_task)
            progress.update(task, advance=1)
        else:
            tracker.update_operator(
                operator_type,
                step=DeploymentStep.OPERATOR_DEPLOYMENT,
                progress=80
            )
            live.update(tracker.create_progress_display())

        # Step 3: Wait for operator pod to become ready
        self.wait_for_operator(progress, task, live, tracker, operator_type)
