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
"""
Shared constants for ccx-license-metric.
"""

from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
LICENSINGINFO_DIR = Path("licensingInfo")
SERVERS_TOML      = LICENSINGINFO_DIR / "servers.toml"
LICENSE_TOML      = LICENSINGINFO_DIR / "license.toml"
SSL_CERTS_DIR     = LICENSINGINFO_DIR / "ssl-certs"

# ── License type metadata ─────────────────────────────────────────────────────
# ops = content operations entitlement per purchased license per month
LICENSE_TYPES: dict[str, dict] = {
    "CCx_Ess_AU": {"label": "CCx.Ess.AU — Authorized User (Essentials)",         "ops": 30_000},
    "CCx_Ess_EP": {"label": "CCx.Ess.EP — Eligible Participant (Essentials)",    "ops":    150},
    "CCx_EE":     {"label": "CCx.EE     — Employee Authorized User (Essentials)", "ops": 15_000},
    "CCx_AR":     {"label": "CCx.AR     — Authorized User (Restricted)",          "ops": 30_000},
    "CCx_PR":     {"label": "CCx.PR     — Infrequent User (Restricted)",          "ops":  3_000},
    "CCx_ER":     {"label": "CCx.ER     — Employee User (Restricted)",            "ops": 15_000},
    "CCx_Pre_AU":      {"label": "CCx.Pre.AU      — Authorized User (Premium)",                       "ops": 30_000},
    "CCx_Pre_EP":      {"label": "CCx.Pre.EP      — Eligible Participant (Premium)",                  "ops":    150},
    "CCx_Pre_EE":      {"label": "CCx.Pre.EE      — Employee Authorized User (Premium)",              "ops": 15_000},
    "CCx_CP4BA_Pre_AU": {"label": "CCx.CP4BA.Pre.AU — Authorized User (Premium CP4BA Add-On)",        "ops": 30_000},
    "CCx_CP4BA_Pre_EP": {"label": "CCx.CP4BA.Pre.EP — Eligible Participant (Premium CP4BA Add-On)",   "ops":    150},
    "CCx_CP4BA_Pre_PE": {"label": "CCx.CP4BA.Pre.PE — Employee Add-On (Premium CP4BA)",               "ops": 15_000},
}

# ── UMS mappingId prefixes that carry content_operation_count ─────────────────
# The full mappingId has a deployment-specific suffix (e.g. 000000000001) that
# varies per customer environment, so we match on prefix only.
CCX_MAPPING_PREFIXES: tuple[str, ...] = (
    "cpedeploymentessau",
    "cpedeploymentessep",
    "cpedeploymentee",
    "cpedeploymenter",
    "cpedeploymentar",
    "cpedeploymentpr",
    "cpedeploymentpreau",
    "cpedeploymentpreep",
    "cpedeploymentpreee",
    "cpedeploymentcp4bapreau",
    "cpedeploymentcp4bapreep",
    "cpedeploymentcp4baprepe",
)
