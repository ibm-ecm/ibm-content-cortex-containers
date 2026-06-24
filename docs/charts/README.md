# Helm Charts Repository

This directory contains the Helm chart packages and repository index for IBM Content Cortex.

## Repository Structure

```
docs/
├── charts/                    # Helm chart repository
│   ├── index.yaml            # Helm repository index
│   ├── *.tgz                 # Helm chart packages
│   └── README.md             # This file
├── assets/                    # Website assets (CSS, JS, images)
├── index.html                # Main documentation page
├── helm-charts.html          # Helm charts catalog page
└── releases.html             # Releases and patches page
```

## Adding the Repository

```bash
helm repo add ibm-content-cortex https://ibm-ecm.github.io/ibm-content-cortex-containers/charts
helm repo update
```

## Available Charts

- **ibm-content-operator** - IBM Content Cortex operator for CPE and ICN
- **ibm-ccx-ai-services-operator** - AI Services operator for MCP and reasoning services
- **ibm-licensing-cluster-scoped** - IBM License Service (cluster-scoped)
- **ibm-usage-metering** - IBM Usage Metering service

## Updating the Repository

When adding new chart versions:

1. Place the `.tgz` file in this directory
2. Update `index.yaml` using `helm repo index`
3. Commit and push changes to GitHub

```bash
# Generate/update index.yaml
helm repo index docs/charts --url https://ibm-ecm.github.io/ibm-content-cortex-containers/charts

# Commit changes
git add docs/charts/
git commit -m "Add new chart version"
git push
```

## GitHub Pages Configuration

- **Source**: `/docs` directory
- **Branch**: `gh-pages` (or main)
- **Base URL**: `https://ibm-ecm.github.io/ibm-content-cortex-containers`
- **Charts URL**: `https://ibm-ecm.github.io/ibm-content-cortex-containers/charts`