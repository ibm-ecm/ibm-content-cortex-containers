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
Config loader for the validate command.

Reads licensingInfo/servers.toml and licensingInfo/license.toml and returns
typed Python objects ready for use by the UMS/ILMT clients and orchestrator.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

import tomlkit
from rich import print
from rich.panel import Panel

from helper_scripts.license.constants import (
    LICENSE_TYPES,
    LICENSE_TOML,
    SERVERS_TOML,
    SSL_CERTS_DIR,
)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ServerConfig:
    index: int          # 1-based, matches ssl-certs/server_N/ dir name
    type: str           # "UMS" or "ILMT"
    url: str
    api_key: str
    tls_verify: bool
    ssl_certs_dir: Path


# ── Helpers ───────────────────────────────────────────────────────────────────

def _error(msg: str) -> None:
    print()
    print(Panel.fit(f"[red]{msg}[/red]", border_style="red"))
    print()
    sys.exit(1)


# ── Public API ────────────────────────────────────────────────────────────────

def load_servers() -> list[ServerConfig]:
    """
    Parse licensingInfo/servers.toml and return a list of ServerConfig objects
    for all configured UMS and ILMT servers.

    UMS  servers use API_KEY  (Bearer token for the UMS snapshot API).
    ILMT servers use API_TOKEN (static token for the ILMT v2 REST API).

    Both are stored in the `api_key` field of ServerConfig for uniform access.
    Exits with an error if the file is missing or any credential is still
    '<Required>'.
    """
    if not SERVERS_TOML.exists():
        _error(
            f"{SERVERS_TOML} not found.\n"
            "Run [bold]license.py setup[/bold] first to generate it."
        )

    raw = tomlkit.loads(SERVERS_TOML.read_text())

    servers: list[ServerConfig] = []
    for key, value in raw.items():
        if not key.startswith("server_") or not isinstance(value, dict):
            continue

        index = int(key.split("_")[1])
        stype = str(value.get("TYPE", "")).upper()

        if stype not in ("UMS", "ILMT"):
            _error(
                f"[{key}] Unknown TYPE '{stype}' in {SERVERS_TOML}.\n"
                "Valid values: UMS | ILMT"
            )

        url = str(value.get("URL", "")).strip()
        if not url or url == "<Required>":
            _error(f"[{key}] URL is not set in {SERVERS_TOML}.")

        # UMS uses API_KEY; ILMT uses API_TOKEN — both stored as api_key
        cred_field = "API_KEY" if stype == "UMS" else "API_TOKEN"
        api_key = str(value.get(cred_field, "")).strip()
        if not api_key or api_key == "<Required>":
            _error(
                f"[{key}] {cred_field} is still '<Required>' in {SERVERS_TOML}.\n"
                "Fill in the credential before running validate."
            )

        tls_verify = bool(value.get("TLS_VERIFY", True))
        certs_dir  = SSL_CERTS_DIR / f"server_{index}"

        servers.append(ServerConfig(
            index=index,
            type=stype,
            url=url.rstrip("/"),
            api_key=api_key,
            tls_verify=tls_verify,
            ssl_certs_dir=certs_dir,
        ))

    if not servers:
        _error(
            f"No servers found in {SERVERS_TOML}.\n"
            "Run [bold]license.py setup[/bold] to configure at least one server."
        )

    return servers


def load_license_counts() -> dict[str, int]:
    """
    Parse licensingInfo/license.toml and return a dict of license type → count.
    Exits with an error if the file is missing.
    """
    if not LICENSE_TOML.exists():
        _error(
            f"{LICENSE_TOML} not found.\n"
            "Run [bold]license.py setup[/bold] first to generate it."
        )

    raw = tomlkit.loads(LICENSE_TOML.read_text())

    counts: dict[str, int] = {}
    for key in LICENSE_TYPES:
        counts[key] = int(raw.get(key, 0))

    return counts


def compute_monthly_entitlement(counts: dict[str, int]) -> int:
    """
    Compute total content operations entitlement per month from license counts.
    e.g. 10 CCx_Ess_AU × 30,000 + 5 CCx_PR × 3,000 = 315,000
    """
    return sum(counts[k] * LICENSE_TYPES[k]["ops"] for k in LICENSE_TYPES)
