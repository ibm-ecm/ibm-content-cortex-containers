=====================================================
IBM Content Cortex Deployment DevOps Suite
=====================================================

.. image:: https://img.shields.io/badge/version-26.0.0-blue
   :alt: Version 26.0.0

------------
Introduction
------------

The IBM Content Cortex Deployment DevOps Suite provides Python-based command line tools to help engineers prepare, deploy, upgrade, troubleshoot, and maintain IBM Content Cortex standalone environments on Kubernetes and OpenShift.

This directory contains modernized CLIs built with `typer~=0.26.7 <scripts/requirements.txt>`_, `rich~=15.0.0 <scripts/requirements.txt>`_, and `questionary~=2.1.1 <scripts/requirements.txt>`_. The scripts support guided interactive workflows, silent configuration-driven execution, verbose logging, and dry-run validation where applicable.

The suite currently includes these primary scripts:

- ``prerequisites.py``
    Gather deployment inputs, generate deployment artifacts, validate external dependencies, and prepare installation assets.
- ``deploy_operator.py``
    Deploy IBM Content Cortex operators and supporting services, including License Service and Usage Metering, using packaged charts, GitHub, local charts, public repositories, or direct chart URLs.
- ``upgrade_deployment.py``
    Upgrade the IBM Content Cortex Custom Resource and deployment configuration using guided workflows with validation, chart source selection, and dry-run support.
- ``clean_deployment.py``
    Clean up IBM Content Cortex deployments and operators with interactive selection, dry-run preview, and multi-operator support for Content, AI Services, License Service, and Usage Metering operators.
- ``load_images.py``
    Generate image manifests and push images to a private registry for connected or air-gapped environments.
- ``must_gather.py``
    Collect deployment diagnostics, logs, Kubernetes resources, and troubleshooting artifacts.

.. note::

    Use the current script filenames in this repository:
    `scripts/prerequisites.py <scripts/prerequisites.py>`_,
    `scripts/deploy_operator.py <scripts/deploy_operator.py>`_,
    `scripts/upgrade_deployment.py <scripts/upgrade_deployment.py>`_,
    `scripts/clean_deployment.py <scripts/clean_deployment.py>`_,
    `scripts/load_images.py <scripts/load_images.py>`_,
    and `scripts/must_gather.py <scripts/must_gather.py>`_.

-----------
Quick Start
-----------

1. Clone or extract the IBM Content Cortex container samples repository::

      git clone <repository-url>
      cd container-samples/scripts

2. Create and activate a Python virtual environment (recommended)::

      python3 -m venv .venv
      source .venv/bin/activate

   On Windows::

      python -m venv .venv
      .venv\Scripts\activate

3. Install the required Python packages from `requirements.txt <scripts/requirements.txt>`_::

      python3 -m pip install --upgrade pip
      python3 -m pip install -r requirements.txt

4. Verify scripts are available and view help output::

      python3 prerequisites.py --help
      python3 deploy_operator.py --help
      python3 upgrade_deployment.py --help
      python3 clean_deployment.py --help
      python3 load_images.py --help
      python3 must_gather.py --help

5. Run a new deployment end-to-end::

      # Step 1 — (air-gap only) push images to a private registry
      python3 load_images.py generate
      python3 load_images.py push

      # Step 2 — deploy the IBM Content Cortex operator
      python3 deploy_operator.py

      # Step 3 — gather inputs and generate deployment artifacts
      python3 prerequisites.py gather
      python3 prerequisites.py generate
      python3 prerequisites.py validate

      # Step 4 — (when needed) upgrade an existing deployment
      python3 upgrade_deployment.py

      # Step 5 — collect diagnostics
      python3 must_gather.py

.. important::

    All scripts must be run from the ``scripts/`` directory so that relative paths to ``silent_config/``, ``imageDetails/``, ``generatedFiles/``, ``CCxHelm/``, and ``CCxUpgrade/`` resolve correctly.

-------------------------
Environment Requirements
-------------------------

Before running the scripts, ensure the following prerequisites are available:

- Python 3.12 or later
- Access to a Kubernetes or OpenShift cluster
- A valid ``kubectl`` or ``oc`` context configured for the target cluster
- Network access to required registries, databases, LDAP servers, identity providers, and storage classes as needed by your deployment
- Java and ``keytool`` for validation flows used by `prerequisites.py <scripts/prerequisites.py>`_, especially when validating certificates and external integrations
- Sufficient permissions to create namespaces, operators, secrets, and custom resources
- Access to IBM Content Cortex deployment assets and container images

Additional tools may be required depending on the workflow:

- **Helm** for operator deployment workflows in `deploy_operator.py <scripts/deploy_operator.py>`_
- **Skopeo** and registry access for image loading workflows in `load_images.py <scripts/load_images.py>`_

--------------------
Installation Notes
--------------------

The Python dependencies currently used by the suite are defined in `requirements.txt <scripts/requirements.txt>`_, including:

- ``typer`` — CLI structure and subcommand routing
- ``rich`` — formatted terminal output, progress bars, tables, and panels
- ``questionary`` — interactive prompts with real-time input validation
- ``pydantic`` — configuration model validation
- ``kubernetes`` — Kubernetes Python API integration
- ``toml`` and ``tomlkit`` — TOML configuration file parsing
- ``requests`` — HTTP API calls
- ``xmltodict`` — XML parsing for registry and operator metadata
- ``PyYAML`` and ``ruamel.yaml`` — YAML processing with comment preservation
- ``cryptography`` and ``pyOpenSSL`` — TLS certificate handling
- ``urllib3`` — HTTP connection pooling and TLS verification control
- ``click`` and ``Jinja2`` — CLI utilities and template rendering
- ``packaging`` — version comparison and constraint evaluation
- ``typing-extensions`` — backported typing annotations

If you are upgrading an existing local environment, reinstall dependencies after pulling the latest script updates::

    python3 -m pip install --upgrade -r requirements.txt

----------------
Common Features
----------------

Most scripts in this suite provide the following usability features:

- ``--help`` output with command and option details
- ``--version`` support (version ``26.0.0``)
- Interactive guided prompts for engineers with minimal Kubernetes experience
- ``--silent`` mode for configuration-driven execution using TOML files in `scripts/silent_config/ <scripts/silent_config>`_
- ``--verbose`` logging for troubleshooting
- ``--dryrun`` support for non-destructive preview flows where implemented
- ``--no-validate`` to skip entitlement key or private registry validation
- Rich terminal panels, tables, and progress indicators
- Log file generation in the current working directory

Typical examples::

    python3 prerequisites.py --help
    python3 prerequisites.py --version
    python3 prerequisites.py --verbose gather
    python3 load_images.py --silent push
    python3 upgrade_deployment.py --dryrun
    python3 clean_deployment.py --verbose
    python3 must_gather.py --verbose

.. note::

    Silent mode configuration files are stored in `scripts/silent_config/ <scripts/silent_config>`_. Update the appropriate TOML file before using ``--silent``.

-------------------
Script Overview
-------------------

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Deployment Preparation: ``prerequisites.py``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

`prerequisites.py <scripts/prerequisites.py>`_ is the main preparation workflow for IBM Content Cortex deployments. It supports three primary subcommands:

1. **gather**
    Collect deployment information interactively or from silent configuration.

    Example::

        python3 prerequisites.py gather

    Common usage patterns::

        python3 prerequisites.py --verbose gather
        python3 prerequisites.py --silent gather
        python3 prerequisites.py gather --move /path/to/existing/environment

2. **generate**
    Generate deployment artifacts such as Custom Resource YAML, SQL templates, Kubernetes secrets, and property documentation based on gathered inputs.

    Output is written to `scripts/generatedFiles/<namespace>/ <scripts/generatedFiles>`_.

    Example::

        python3 prerequisites.py generate

3. **validate**
    Validate cluster connectivity, Java and keytool prerequisites, storage classes, databases, LDAP, identity providers, and related external dependencies.

    Example::

        python3 prerequisites.py validate

    Skip selected validations when needed::

        python3 prerequisites.py validate --skip-storageclass
        python3 prerequisites.py validate --skip-database
        python3 prerequisites.py validate --skip-ldap
        python3 prerequisites.py validate --skip-idp
        python3 prerequisites.py validate --skip-scim

    Apply generated artifacts after successful validation::

        python3 prerequisites.py validate --apply

Key capabilities include:

- Guided prerequisite collection and validation with rich status tables
- Generation of Custom Resource YAML, SQL scripts, Kubernetes secrets, and property documentation
- Support for silent installs and migration-oriented gather flows via ``--move``
- AI Services setting detection from an existing ``FNCMCluster`` deployment when AI Services is being configured alongside an existing Content deployment
- Identity provider discovery support that can automatically parse OpenID Connect discovery metadata and populate endpoint settings for AI Services authentication flows
- Unified validation display with issue summaries and remediation hints

.. note::

    Passwords, usernames, and client secrets may require escaping when they contain special characters. Review generated configuration carefully before applying artifacts.

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Operator Deployment: ``deploy_operator.py``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

`deploy_operator.py <scripts/deploy_operator.py>`_ deploys IBM Content Cortex operators and related dependencies with an interactive or silent workflow, including required supporting operators such as License Service and Usage Metering.

Basic usage::

    python3 deploy_operator.py

All options::

    python3 deploy_operator.py --help
    python3 deploy_operator.py --verbose
    python3 deploy_operator.py --silent
    python3 deploy_operator.py --dryrun
    python3 deploy_operator.py --force
    python3 deploy_operator.py --no-validate

Helm chart source selection is controlled by the ``--helm-chart-source`` option. The default is ``github``. Supported sources:

- ``github`` *(default)* — downloads charts directly from GitHub at runtime
- ``packaged`` — uses pre-packaged ``.tgz`` chart archives already present locally
- ``local`` — uses unpacked chart directories already present locally
- ``public`` — uses a public Helm repository
- ``url`` — uses a direct chart URL

Examples::

    python3 deploy_operator.py --helm-chart-source github
    python3 deploy_operator.py --helm-chart-source packaged
    python3 deploy_operator.py --helm-chart-source local

Development and internal testing example::

    export GITHUB_TOKEN="your_github_token"
    python3 deploy_operator.py --helm-chart-source github --dev

For ``packaged`` and ``local`` chart sources, the required Helm charts must already be present in the repository-level `helm-charts/ <helm-charts>`_ directory:

- ``packaged`` source expects archives such as ``helm-charts/ibm-content-operator-26.0.0.tgz`` and ``helm-charts/ibm-ccx-ai-services-operator-26.0.0.tgz``
- ``local`` source expects unpacked directories such as ``helm-charts/content-operator/`` and ``helm-charts/ai-services-operator/``

If those charts are not present locally, use ``--helm-chart-source github`` or another remote source so the script can retrieve charts automatically.

Deployment features include:

- Pre-deployment system detection that checks the target namespace for existing YAML, OLM, and Helm-based operator installations
- Helm values file generation for repeatable deployments (rather than relying solely on ``--set`` flags)
- Parallel operator deployment with live progress display
- Timestamped deployment folders created under `scripts/CCxHelm/ <scripts/CCxHelm>`_
- Generated per-deployment ``README.md`` files with upgrade and rollback commands
- Deployment of supporting operators (License Service and Usage Metering) when required
- Post-deployment health checks with metrics and warnings summary
- Private registry override support for air-gap deployments
- ``--force`` flag to redeploy even when operators are already at the target version

.. important::

    `deploy_operator.py <scripts/deploy_operator.py>`_ detects the current deployment state of the target system before proceeding and provides guidance based on what it finds. This helps users understand whether they are performing a fresh install, whether an upgrade path should be used instead, or whether the existing deployment is already up to date.

.. important::

    Use ``--force`` with caution. It bypasses the version check and redeploys the operator even if the target version is already running in the namespace. This can cause a brief disruption to the operator and its managed workloads. Only use ``--force`` when explicitly directed to do so, such as when recovering from a failed or partial deployment.

After a Helm deployment, the script saves reusable files inside a timestamped folder under ``scripts/CCxHelm/<namespace>/``:

- ``content-values.yaml``
- ``ai-services-values.yaml``
- License Service values files when License Service is deployed
- Usage Metering values files when Usage Metering is deployed
- ``README.md`` with manual upgrade and rollback commands

These generated files can be reused for future manual Helm operations.

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Upgrade Workflow: ``upgrade_deployment.py``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

`upgrade_deployment.py <scripts/upgrade_deployment.py>`_ upgrades the IBM Content Cortex Custom Resource and deployment configuration using interactive or silent workflows.

Basic usage::

    python3 upgrade_deployment.py

All options::

    python3 upgrade_deployment.py --help
    python3 upgrade_deployment.py --verbose
    python3 upgrade_deployment.py --dryrun
    python3 upgrade_deployment.py --silent
    python3 upgrade_deployment.py --no-validate

Key capabilities include:

- Guided Custom Resource upgrade flow with rich progress displays and phase overview
- Interactive license model and metric selection (ESS or CP4BA, with per-metric options)
- Backs up the current CR configuration before applying changes
- Generates an updated CR for the target version
- Generates and applies usage metering metrics YAML for deployed components (CPE, GraphQL, CMIS)
- Silent mode support for repeatable automation
- Dry-run support for safer planning and review
- All generated files are saved under `scripts/CCxUpgrade/<namespace>/ <scripts/CCxUpgrade>`_
- Upgrade logging to ``upgradedeployment.log``

.. note::

    In silent mode, if no license model is specified in the configuration, the script defaults to ``CP4BA.Prod``. Review the `silent_install_upgradedeployment.toml <scripts/silent_config/silent_install_upgradedeployment.toml>`_ file and set the license before running.

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Cleanup Workflow: ``clean_deployment.py``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

`clean_deployment.py <scripts/clean_deployment.py>`_ removes IBM Content Cortex deployments and operators from a cluster with interactive selection and validation.

Basic usage::

    python3 clean_deployment.py

Supported subcommands:

- ``deployment`` — remove the Custom Resource and deployed workloads only; the operator is left in place
- ``operator`` — remove selected operators only; the deployment is left in place
- *(no subcommand)* — interactive cleanup of both deployment and all detected operators

Examples::

    python3 clean_deployment.py deployment
    python3 clean_deployment.py operator
    python3 clean_deployment.py --dryrun
    python3 clean_deployment.py --silent
    python3 clean_deployment.py --verbose

Four IBM Content Cortex operators are supported:

- **Content Operator** (``ibm-content-operator``)
- **AI Services Operator** (``ibm-ccx-ai-services-operator``)
- **License Service Operator** (``ibm-licensing-operator``)
- **Usage Metering Operator** (``ibm-usage-metering-operator``)

Key capabilities include:

- Interactive operator selection with checkbox prompts (when not in silent mode)
- Parallel multi-operator cleanup in a single run
- Support for YAML-based, OLM, and Helm-based operator cleanup
- CR backup written to `scripts/backups/ <scripts/backups>`_ before deletion
- Dry-run preview before any destructive action
- Completion summaries with next-step guidance
- Cleanup logging to ``cleandeployment.log``

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Image Loading: ``load_images.py``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

`load_images.py <scripts/load_images.py>`_ helps prepare and push IBM Content Cortex images into a private registry for connected and air-gap deployments.

The script supports two subcommands and a combined default mode:

Typical commands::

    # Generate image manifest AND push in one operation (default)
    python3 load_images.py

    # Generate the image details manifest only
    python3 load_images.py generate

    # Push images using an existing manifest
    python3 load_images.py push


Common options::

    python3 load_images.py --help
    python3 load_images.py --verbose generate
    python3 load_images.py --silent push
    python3 load_images.py --dryrun push

Key capabilities include:

- Generate image manifest files from descriptor YAML files for review before pushing
- Push images to a private registry using Skopeo
- Validate ``imageDetails.toml`` before execution
- SSL certificate handling with a clear selection menu (trusted certificate, self-signed, or skip TLS)
- Private registry URL normalization for Docker and Skopeo compatibility
- Failure logging and live progress display for image copy operations
- Generated manifest written to ``scripts/imageDetails/``

Image descriptor files expected in ``descriptors/``:

- ``content-cortex/content/ibm_content_full_cr.yaml``
- ``content-cortex/content/operator.yaml``
- ``content-cortex/ai-services/ibm_ai_services_full_cr.yaml``
- ``content-cortex/ai-services/operator.yaml``
- ``usage-metering/operator.yaml``
- ``license-service/operator.yaml``

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Diagnostics: ``must_gather.py``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

`must_gather.py <scripts/must_gather.py>`_ collects troubleshooting data from a target deployment and packages it for analysis or support cases.

Basic usage::

    python3 must_gather.py

Useful options::

    python3 must_gather.py --help
    python3 must_gather.py --verbose
    python3 must_gather.py --silent
    python3 must_gather.py --dryrun

The script collects:

- Cluster-level information and namespace overview
- Operator resources and logs
- Deployment resources and Custom Resource state
- Services, PVCs, storage classes, routes and ingresses
- Component-specific diagnostics (CPE, Navigator, GraphQL, CMIS)
- Optional sensitive data when explicitly requested

Output is written to a ``MustGather`` working directory and then packaged as an archive for sharing. Log file is written to ``must_gather.log``.

.. note::

    After completion, review the generated archive and logs before sending them to support to ensure they match your data handling requirements.

------------------------
Silent Configuration
------------------------

Silent mode is supported across the suite through TOML configuration files in `scripts/silent_config/ <scripts/silent_config>`_.

Available configuration files:

- `silent_install_prerequisites.toml <scripts/silent_config/silent_install_prerequisites.toml>`_
- `silent_install_deployoperator.toml <scripts/silent_config/silent_install_deployoperator.toml>`_
- `silent_install_upgradedeployment.toml <scripts/silent_config/silent_install_upgradedeployment.toml>`_
- `silent_install_cleandeployment.toml <scripts/silent_config/silent_install_cleandeployment.toml>`_
- `silent_install_loadimages.toml <scripts/silent_config/silent_install_loadimages.toml>`_
- `silent_install_mustgather.toml <scripts/silent_config/silent_install_mustgather.toml>`_

Typical silent mode examples::

    python3 prerequisites.py --silent gather
    python3 deploy_operator.py --silent
    python3 upgrade_deployment.py --silent
    python3 clean_deployment.py --silent
    python3 load_images.py --silent push
    python3 must_gather.py --silent

Review and update the matching TOML file before running a silent workflow.

-------------------------
Logs and Generated Output
-------------------------

Each script writes a log file in the current working directory:

+----------------------------+----------------------------------+
| Script                     | Log file                         |
+============================+==================================+
| ``prerequisites.py``       | ``prerequisites.log``            |
+----------------------------+----------------------------------+
| ``deploy_operator.py``     | ``deployoperator.log``           |
+----------------------------+----------------------------------+
| ``upgrade_deployment.py``  | ``upgradedeployment.log``        |
+----------------------------+----------------------------------+
| ``clean_deployment.py``    | ``cleandeployment.log``          |
+----------------------------+----------------------------------+
| ``load_images.py``         | ``loadimages.log``               |
+----------------------------+----------------------------------+
| ``must_gather.py``         | ``must_gather.log``              |
+----------------------------+----------------------------------+

Additional generated output may include:

- Deployment artifacts (Custom Resource YAML, secrets, SQL scripts) under `scripts/generatedFiles/<namespace>/ <scripts/generatedFiles>`_
- Helm deployment folders and per-deployment README under `scripts/CCxHelm/<namespace>/ <scripts/CCxHelm>`_
- Upgrade artifacts and CR backups under `scripts/CCxUpgrade/<namespace>/ <scripts/CCxUpgrade>`_
- CR backups before deletion under `scripts/backups/ <scripts/backups>`_
- Image detail manifest under ``scripts/imageDetails/``
- MustGather archive and extracted troubleshooting artifacts

---------------
Recommended Run Order
---------------

For a new deployment, the typical workflow is:

1. If using a private registry or air-gap environment, run `load_images.py <scripts/load_images.py>`_ to push images first.
2. Deploy operators with `deploy_operator.py <scripts/deploy_operator.py>`_, including any required supporting operators such as License Service and Usage Metering.
3. Run `prerequisites.py <scripts/prerequisites.py>`_ in ``gather``, ``generate``, and ``validate`` modes.
4. Use `upgrade_deployment.py <scripts/upgrade_deployment.py>`_ for lifecycle upgrades after initial deployment.
5. Use `clean_deployment.py <scripts/clean_deployment.py>`_ when removing deployments or operators.
6. Use `must_gather.py <scripts/must_gather.py>`_ when troubleshooting or collecting support data.

---------------
Troubleshooting
---------------

If a script fails:

- Re-run with ``--verbose`` to capture more detail in the terminal
- Review the corresponding log file for the full debug trace
- Confirm cluster connectivity and current ``kubectl`` or ``oc`` context
- Verify registry, certificate, LDAP, database, and storage inputs
- Use ``--dryrun`` where supported before making changes
- Confirm silent configuration values if using ``--silent`` mode
- Use ``python3 must_gather.py`` to collect a full diagnostic bundle

Common issues:

- **Chart not found locally**: Use ``--helm-chart-source github`` so the script downloads the chart automatically instead of looking for local files.
- **Validation failures on entitlement key or registry**: Use ``--no-validate`` to skip registry validation if credentials are known-good but the check fails in restricted network environments.
- **Upgrade not finding deployment**: Confirm ``kubectl get fncmclusters -n <namespace>`` returns a result before running the upgrade script.

----------
Conclusion
----------

The scripts in this directory provide a practical deployment path for IBM Content Cortex preparation, operator deployment, image management, upgrades, cleanup, and diagnostics. Use the built-in ``--help`` for each script and keep the generated logs and output artifacts for auditability and troubleshooting.

.. Made with Bob
