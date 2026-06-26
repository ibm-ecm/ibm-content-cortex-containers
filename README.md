# IBM Content Cortex 26.0.0

[![Release](https://img.shields.io/badge/Release-26.0.0-blue.svg)](https://github.com/ibm-ecm/ibm-content-cortex-containers/releases/tag/v26.0.0)
[![Helm](https://img.shields.io/badge/Helm-v4.0+-blue.svg)](https://helm.sh)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-v1.24+-blue.svg)](https://kubernetes.io)
[![OpenShift](https://img.shields.io/badge/OpenShift-v4.12+-red.svg)](https://www.openshift.com)
[![Python](https://img.shields.io/badge/Python-3.12+-yellow.svg)](https://www.python.org)

## 📋 Table of Contents

- [Overview](#overview)
- [Release Information](#release-information)
- [Repository Structure](#repository-structure)
- [Quick Start](#quick-start)
- [Python DevOps Scripts](#python-devops-scripts)
- [Documentation](#documentation)
- [Support](#support)

## 🎯 Overview

This repository provides comprehensive resources for deploying and managing **IBM Content Cortex (CCx)** on Kubernetes and OpenShift platforms. It includes:

- **Python DevOps Scripts**: Modern CLI tools for deployment automation and lifecycle management
- **Deployment Descriptors**: YAML manifests for operators and supporting services
- **Helm Charts**: Available via public Helm repository
- **Documentation**: Comprehensive guides, examples, and troubleshooting resources

### What is IBM Content Cortex?

IBM Content Cortex is an enterprise content management platform that centralizes, governs, and activates content across organizations. It provides:

- **Content Platform Engine (CPE)**: High-performance content repository and workflow engine
- **Content Navigator (ICN)**: Modern web-based user interface
- **AI Services**: Intelligent content processing with watsonx.ai, Azure OpenAI, and other AI providers
- **GraphQL & REST APIs**: Modern APIs for content access and integration
- **Enterprise Records Management**: Compliance and governance capabilities
- **Advanced Integration**: SAP, Microsoft Office, and third-party system connectivity

## 📊 Release Information

|    Release    |   Tag   | CASE Version |      Date      |
|:-------------:|:-------:|:------------:|:--------------:|
| CCX 26.0.0 GA | v26.0.0 |    26.0.0    | 06 / 26 / 2026 |

> **Note**: For iFix releases, detailed component versions, specific fixes, and new features, see the [**Releases**](https://github.com/ibm-ecm/ibm-content-cortex-containers/releases) tab.

### Resources

- **Documentation**: [IBM Content Cortex Docs](https://www.ibm.com/docs/SSL4SY_26.0.0/com.ibm.p8.containers.doc/containers.html)
- **Helm Charts**: [Helm Chart Repository](https://ibm-ecm.github.io/ibm-content-cortex-containers/helm-charts.html)

## 📁 Repository Structure

```
container-samples/
├── README.md                          # This file
├── descriptors/                       # Kubernetes/OpenShift deployment descriptors
│   ├── content-cortex/               # Content Cortex operator manifests
│   │   ├── ai-services/              # AI Services operator and CRs
│   │   ├── op-olm/                   # OLM-based deployment (CatalogSource, Subscription)
│   │   └── turbonomics/              # Turbonomics integration
│   ├── license-service/              # IBM License Service operator
│   └── usage-metering/               # IBM Usage Metering operator
│
└── scripts/                           # Python DevOps automation suite
    ├── README.rst                    # Comprehensive script documentation
    ├── requirements.txt              # Python dependencies
    ├── prerequisites.py              # Deployment preparation and validation
    ├── deploy_operator.py            # Operator deployment automation
    ├── upgrade_deployment.py         # Upgrade workflow automation
    ├── clean_deployment.py           # Cleanup and removal automation
    ├── load_images.py                # Image management for air-gap deployments
    ├── must_gather.py                # Diagnostic data collection
    ├── silent_config/                # Silent mode configuration files
    └── helper_scripts/               # Modular helper libraries
        ├── gather/                   # Prerequisite gathering
        ├── deploy/                   # Deployment orchestration
        ├── helm/                     # Helm integration
        ├── loadimages/               # Image loading utilities
        ├── mustgather/               # Diagnostics collection
        ├── property/                 # Configuration management
        ├── utilities/                # Shared utilities
        └── validate/                 # Validation frameworks
```

## 🚀 Quick Start

### Prerequisites

Before you begin, ensure you have:

- **Kubernetes/OpenShift Cluster**: v1.24+ (Kubernetes) or v4.12+ (OpenShift)
- **Helm**: v4.x or later (for Helm-based deployments)
- **kubectl/oc**: Configured with cluster access
- **Python**: 3.12 or later (for DevOps scripts)
- **IBM Entitlement Key**: From [IBM Container Library](https://myibm.ibm.com/products-services/containerlibrary)

### Method 1: Helm Installation

IBM Content Cortex operators are available as Helm charts for streamlined deployment:

```bash
# 1. Add Helm repository
helm repo add ibm-content-cortex https://ibm-ecm.github.io/ibm-content-cortex-containers/charts
helm repo update

# 2. Create namespace
kubectl create namespace ibm-content

# 3. Create image pull secret
kubectl create secret docker-registry ibm-entitlement-key \
  --docker-server=cp.icr.io \
  --docker-username=cp \
  --docker-password=<your-entitlement-key> \
  --namespace ibm-content

# 4. Install Content Operator
helm install content-operator ibm-content-cortex/ibm-content-operator \
  --namespace ibm-content

# 5. Install AI Services Operator (optional)
helm install ai-services-operator ibm-content-cortex/ibm-ccx-ai-services-operator \
  --namespace ibm-content

# 6. Verify installation
kubectl get pods -n ibm-content
helm list -n ibm-content
```

**Available Charts**:
- `ibm-content-operator` - Content Cortex operator (CPE, ICN, GraphQL)
- `ibm-ccx-ai-services-operator` - AI Services operator (Reasoning Service and Core MCP Server)
- `ibm-license-service-operator` - IBM License Service operator
- `ibm-usage-metering-operator` - IBM Usage Metering operator


### Method 2: Python DevOps Scripts (Guided Workflow)

```bash
# 1. Navigate to scripts directory
cd scripts/

# 2. Create Python virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install dependencies
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

# 4. For air-gap environments, load images first
python3 load_images.py generate
python3 load_images.py push

# 5. Deploy operators (interactive mode)
python3 deploy_operator.py

# 6. Run prerequisite gathering and validation
python3 prerequisites.py gather
python3 prerequisites.py generate
python3 prerequisites.py validate
```

### Method 3: OpenShift Helm Repository Integration

For OpenShift environments, integrate the Helm repository directly into the Developer Catalog:

**Step 1: Create HelmChartRepository Resource**

```yaml
apiVersion: helm.openshift.io/v1beta1
kind: HelmChartRepository
metadata:
  name: ibm-content-cortex
spec:
  connectionConfig:
    url: https://ibm-ecm.github.io/ibm-content-cortex-containers/charts
  name: IBM Content Cortex
```

**Step 2: Apply the Configuration**

```bash
# Login to OpenShift
oc login --token=<your-token> --server=https://api.your-cluster.com:6443

# Apply HelmChartRepository (requires cluster-admin)
oc apply -f helmchartrepo-content-cortex.yaml

# Verify repository was added
oc get helmchartrepository ibm-content-cortex
```

**Step 3: Install from OpenShift Console**

1. Navigate to **Developer** perspective → **+Add** → **Helm Chart**
2. Select **IBM Content Cortex** repository
3. Choose **IBM Content Operator** or **IBM AI Services Operator**
4. Click **Install Helm Chart**
5. Configure values and click **Install**

For OLM-based deployment and additional installation methods, see the [IBM Content Cortex Documentation](https://www.ibm.com/docs/SSL4SY_26.0.0/com.ibm.p8.containers.doc/containers.html).

## 🐍 Python DevOps Scripts

The [`scripts/`](scripts/) directory contains a comprehensive suite of Python-based CLI tools for Content Cortex lifecycle management:

### Available Scripts

| Script | Purpose | Key Features |
|--------|---------|--------------|
| [`prerequisites.py`](scripts/prerequisites.py) | Deployment preparation | Gather inputs, generate artifacts, validate dependencies |
| [`deploy_operator.py`](scripts/deploy_operator.py) | Operator deployment | Deploy operators with Helm, support multiple chart sources |
| [`upgrade_deployment.py`](scripts/upgrade_deployment.py) | Upgrade automation | Upgrade CRs and deployments with validation |
| [`clean_deployment.py`](scripts/clean_deployment.py) | Cleanup automation | Remove deployments and operators safely |
| [`load_images.py`](scripts/load_images.py) | Image management | Push images to private registries, air-gap support |
| [`must_gather.py`](scripts/must_gather.py) | Diagnostics | Collect logs and troubleshooting data |

### Common Features

- 🎨 **Rich Terminal UI**: Colored output, progress bars, tables, and panels
- 🤖 **Interactive Prompts**: Guided workflows with validation
- 🔇 **Silent Mode**: Configuration-driven automation
- 📝 **Comprehensive Logging**: Detailed logs for troubleshooting
- 🧪 **Dry-Run Support**: Preview changes before applying
- ✅ **Validation**: Pre-flight checks for cluster, storage, databases, LDAP, and more

### Quick Examples

```bash
# Interactive deployment preparation
python3 prerequisites.py gather
python3 prerequisites.py generate
python3 prerequisites.py validate

# Deploy operators 
python3 deploy_operator.py 

# Silent mode deployment (automation)
python3 deploy_operator.py --silent

# Dry-run upgrade preview
python3 upgrade_deployment.py --dryrun

# Collect diagnostics
python3 must_gather.py 
```

**Full Documentation**: [`scripts/README.rst`](scripts/README.rst)

## 📚 Documentation

### Getting Started

- [Quick Start Guide](#quick-start) - Get up and running quickly
- [Python Scripts Guide](scripts/README.rst) - DevOps automation suite documentation
- [IBM Documentation](https://www.ibm.com/docs/SSL4SY_26.0.0/com.ibm.p8.containers.doc/containers.html) - Complete installation guides

### Advanced Topics

- [Air-Gap Deployments](scripts/README.rst#image-loading-load_imagespy) - Offline installation guide
- [Silent Mode Configuration](scripts/README.rst#silent-configuration) - Automation setup
- [Troubleshooting](scripts/README.rst#troubleshooting) - Common issues and solutions
- [Upgrade Procedures](scripts/README.rst#upgrade-workflow-upgrade_deploymentpy) - Lifecycle management

### IBM Documentation

- **Product Documentation**: [IBM Content Cortex Docs](https://www.ibm.com/docs/SSL4SY_26.0.0/com.ibm.p8.containers.doc/containers.html)

## 🔧 Support

### Getting Help

- **IBM Support Portal**: [https://www.ibm.com/mysupport](https://www.ibm.com/mysupport)
- **GitHub Issues**: [Report Issues](https://github.com/ibm-ecm/ibm-content-cortex-containers/issues)
- **Community Forums**: [IBM ECM Community](https://community.ibm.com/community/user/groups/community-home?communitykey=2b67f465-a5fe-4a66-ad25-f5e767b607e3)
- **Email**: ecm-container-service@ibm.com

### Useful Resources

- **Product Website**: [IBM Content Cortex](https://www.ibm.com/products/content-cortex)
- **Container Library**: [IBM Entitled Registry](https://myibm.ibm.com/products-services/containerlibrary)
- **Release Notes**: [What's New](https://www.ibm.com/docs/SSL4SY_26.0.0/com.ibm.p8.containers.doc/containers_whatsnew.html)
- **Helm Charts**: [Available via Github Repository](https://ibm-ecm.github.io/ibm-content-cortex-containers/charts) or manual download.

### Prerequisites for Support

When opening a support case, please provide:

1. **Environment Details**: Kubernetes/OpenShift version, cluster configuration
2. **Deployment Method**: Helm, Python scripts, or OLM
3. **Logs**: Operator logs, pod logs, and must-gather output
4. **Configuration**: Helm values files or CR YAML (sanitized)
5. **Error Messages**: Complete error output and stack traces

Use [`must_gather.py`](scripts/must_gather.py) to collect comprehensive diagnostic data:

```bash
python3 must_gather.py --verbose
```

## 📄 License

Licensed Materials - Property of IBM

© Copyright IBM Corp. 2026. All Rights Reserved.

US Government Users Restricted Rights - Use, duplication or disclosure restricted by GSA ADP Schedule Contract with IBM Corp.

---

**Repository**: [ibm-ecm/ibm-content-cortex-containers](https://github.com/ibm-ecm/ibm-content-cortex-containers)
**Version**: 26.0.0
**Last Updated**: 2026-06-16

