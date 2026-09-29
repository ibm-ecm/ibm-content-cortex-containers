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
Setup Gatherer

Interactive questionnaire that collects licensing server configuration from
the user and writes:
  - licensingInfo/license.toml   (license counts)
  - licensingInfo/servers.toml   (one [server_N] section per server)
"""

import sys
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

import questionary
import tomlkit
from questionary import Style
from rich import print
from rich.panel import Panel
from rich.text import Text

from .questionary_utils import safe_prompt, handle_cancelled_prompt
from helper_scripts.license.constants import LICENSINGINFO_DIR, SERVERS_TOML, LICENSE_TOML, SSL_CERTS_DIR, LICENSE_TYPES

# ── Styles ────────────────────────────────────────────────────────────────────
_STYLE = Style([
    ('qmark',       'fg:#61afef bold'),
    ('question',    'bold'),
    ('answer',      'fg:#98c379 bold'),
    ('pointer',     'fg:#61afef bold'),
    ('highlighted', 'fg:#ffffff'),
    ('selected',    'fg:#98c379 bold'),
    ('separator',   'fg:#e5c07b'),
    ('instruction', 'fg:#abb2bf'),
])


class GatherOptions:
    """Collects all setup configuration interactively and writes output files."""

    class ServerType(Enum):
        UMS  = "UMS"
        ILMT = "ILMT"

    def __init__(self):
        self._servers: list[dict] = []
        self._license_counts: dict[str, int] = {k: 0 for k in LICENSE_TYPES}

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self, silent : bool) -> None:
        """Run the full interactive setup questionnaire."""
        if not silent:
            self._print_welcome()
            self._collect_license_counts()

            while True:
                raw = safe_prompt(
                    questionary.text,
                    "Server count entry cancelled.",
                    message="How many licensing servers do you want to configure?",
                    default="1",
                    style=_STYLE,
                )
                try:
                    count = int(raw)
                    if count < 1:
                        raise ValueError
                    break
                except ValueError:
                    print("[red]  Please enter a whole number greater than 0.[/red]")

            for i in range(count):
                print()
                print(f"[bold cyan]Server {i + 1} of {count}[/bold cyan]")
                self._collect_server(index=i + 1)
            
            self._write_outputs()
            self._print_summary()
        else:
            init_server = {
                "type": "<server type>",
                "url": "<url>"
            } 
            self._servers = [init_server]
            self._write_outputs()
            

    # ── Welcome ───────────────────────────────────────────────────────────────

    def _print_welcome(self) -> None:
        info = Text()
        info.append("This wizard will guide you through setting up your IBM Content Cortex\n", style="white")
        info.append("license metric configuration.\n\n", style="white")
        info.append("You will be asked to:\n", style="white")
        info.append("  1. Enter the count of each license type you have purchased\n", style="white")
        info.append("  2. Configure one or more licensing servers (UMS or ILMT)\n\n", style="white")
        info.append("Output files will be written to:\n", style="white")
        info.append(f"  • {LICENSE_TOML}\n", style="bold cyan")
        info.append(f"  • {SERVERS_TOML}\n", style="bold cyan")
        print()
        print(Panel(
            info,
            title="[bold cyan]IBM Content Cortex — License Metric Setup[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        ))
        print()

    # ── License counts ────────────────────────────────────────────────────────

    def _collect_license_counts(self) -> None:
        print(Panel.fit(
            "[bold cyan]Step 1 of 2 — License Counts[/bold cyan]\n\n"
            "Enter the number of purchased licenses for each type.\n"
            "[dim]Leave blank and press Enter to default to 0.[/dim]",
            border_style="cyan",
        ))
        print()

        for key, meta in LICENSE_TYPES.items():
            # Section header banners
            if key == "CCx_Ess_AU":
                print("[bold]IBM Content Cortex Essentials:[/bold]")
            elif key == "CCx_AR":
                print()
                print("[bold]IBM Content Cortex Restricted:[/bold]")
            elif key == "CCx_Pre_AU":
                print()
                print("[bold]IBM Content Cortex Premium:[/bold]")
            elif key == "CCx_CP4BA_Pre_AU":
                print()
                print("[bold]IBM Content Cortex Premium Edition Add-On for CP4BA:[/bold]")

            while True:
                raw = safe_prompt(
                    questionary.text,
                    "License count entry cancelled.",
                    message=f"  {meta['label']}:",
                    default="",
                    style=_STYLE,
                )
                try:
                    count = int(raw) if raw.strip() else 0
                    if count < 0:
                        raise ValueError
                    self._license_counts[key] = count
                    break
                except ValueError:
                    print("[red]  Please enter a non-negative whole number.[/red]")

        # Entitlement summary
        total_ops = sum(
            self._license_counts[k] * LICENSE_TYPES[k]["ops"]
            for k in LICENSE_TYPES
        )
        summary = Text()
        summary.append("Purchased license summary:\n\n", style="bold white")
        for key, meta in LICENSE_TYPES.items():
            count = self._license_counts[key]
            if count > 0:
                monthly = count * meta["ops"]
                summary.append(f"  {meta['label']}\n", style="white")
                summary.append(f"    {count:,} license(s) × {meta['ops']:,} ops = ", style="dim")
                summary.append(f"{monthly:,} ops/month\n", style="green")
        summary.append(f"\n  Total entitlement: ", style="bold white")
        summary.append(f"{total_ops:,} content operations / month", style="bold green")

        print()
        print(Panel(summary, title="[bold]License Entitlement[/bold]", border_style="green", padding=(1, 2)))
        print()

    # ── Server configuration ──────────────────────────────────────────────────

    def _collect_server(self, index: int) -> None:
        print(Panel.fit(
            "[bold cyan]Step 2 of 2 — Licensing Server[/bold cyan]\n\n"
            "Configure a UMS (containers) or ILMT (on-premises) server.\n"
            f"[dim]Will be written to {SERVERS_TOML} under [server_{index}].[/dim]",
            border_style="cyan",
        ))
        print()

        # Server type
        server_type_raw = safe_prompt(
            questionary.select,
            "Server type selection cancelled.",
            message="Select server type:",
            choices=[
                questionary.Choice("UMS  — IBM Usage Metering Service (containers)", value="UMS"),
                questionary.Choice("ILMT — IBM License Metric Tool (on-premises)",   value="ILMT"),
            ],
            style=_STYLE,
        )
        server_type = self.ServerType(server_type_raw)

        # URL
        url = self._collect_url(server_type)

        self._servers.append({
            "type": server_type.value,
            "url":  url,
        })

    def _collect_url(self, server_type: "GatherOptions.ServerType") -> str:
        hint = (
            "https://ums.example.com:9443"
            if server_type == self.ServerType.UMS
            else "https://ilmt.example.com:9081"
        )
        while True:
            url = safe_prompt(
                questionary.text,
                "URL entry cancelled.",
                message=f"Base URL of the {server_type.value} instance:",
                placeholder=hint,
                style=_STYLE,
            ).strip()
            parsed = urlparse(url)
            if parsed.scheme in ("http", "https") and parsed.netloc:
                return url
            print("[red]  Please enter a valid URL starting with http:// or https://[/red]")

    # ── Write outputs ─────────────────────────────────────────────────────────

    def _write_outputs(self) -> None:
        LICENSINGINFO_DIR.mkdir(parents=True, exist_ok=True)
        for i in range(1, len(self._servers) + 1):
            (SSL_CERTS_DIR / f"server_{i}").mkdir(parents=True, exist_ok=True)
        self._write_license_toml()
        self._write_servers_toml()

    def _write_license_toml(self) -> None:
        doc = tomlkit.document()
        doc.add(tomlkit.comment("####################################################"))
        doc.add(tomlkit.comment("##         IBM Content Cortex License Counts     ##"))
        doc.add(tomlkit.comment("####################################################"))
        doc.add(tomlkit.comment(""))
        doc.add(tomlkit.comment("Content operation entitlements per license per month:"))
        doc.add(tomlkit.comment("  CCx.Ess.AU  (Authorized User)           = 30,000 ops/license/month"))
        doc.add(tomlkit.comment("  CCx.Ess.EP  (Eligible Participant)       =    150 ops/license/month"))
        doc.add(tomlkit.comment("  CCx.EE      (Employee Authorized User)   = 15,000 ops/license/month"))
        doc.add(tomlkit.comment("  CCx.AR      (Authorized User Restricted) = 30,000 ops/license/month"))
        doc.add(tomlkit.comment("  CCx.PR      (Infrequent User Restricted) =  3,000 ops/license/month"))
        doc.add(tomlkit.comment("  CCx.ER      (Employee User Restricted)   = 15,000 ops/license/month"))
        doc.add(tomlkit.comment("  CCx.Pre.AU      (Authorized User Premium)          = 30,000 ops/license/month"))
        doc.add(tomlkit.comment("  CCx.Pre.EP      (Eligible Participant Prem.)        =    150 ops/license/month"))
        doc.add(tomlkit.comment("  CCx.Pre.EE      (Employee Auth. User Prem.)         = 15,000 ops/license/month"))
        doc.add(tomlkit.comment("  CCx.CP4BA.Pre.AU (Auth. User Premium CP4BA)         = 30,000 ops/license/month"))
        doc.add(tomlkit.comment("  CCx.CP4BA.Pre.EP (Elig. Participant Premium CP4BA)  =    150 ops/license/month"))
        doc.add(tomlkit.comment("  CCx.CP4BA.Pre.PE (Employee Add-On Premium CP4BA)    = 15,000 ops/license/month"))
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment("####################################################"))
        doc.add(tomlkit.comment("##          Essentials Licenses                  ##"))
        doc.add(tomlkit.comment("####################################################"))
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment("Number of Authorized User (CCx.Ess.AU) licenses purchased."))
        doc.add("CCx_Ess_AU", self._license_counts["CCx_Ess_AU"])
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment("Number of Eligible Participant (CCx.Ess.EP) licenses purchased."))
        doc.add("CCx_Ess_EP", self._license_counts["CCx_Ess_EP"])
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment("Number of Employee Authorized User (CCx.EE) licenses purchased."))
        doc.add("CCx_EE", self._license_counts["CCx_EE"])
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment("####################################################"))
        doc.add(tomlkit.comment("##          Restricted Licenses                  ##"))
        doc.add(tomlkit.comment("####################################################"))
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment("Number of Authorized User Restricted (CCx.AR) licenses purchased."))
        doc.add("CCx_AR", self._license_counts["CCx_AR"])
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment("Number of Infrequent User Restricted (CCx.PR) licenses purchased."))
        doc.add("CCx_PR", self._license_counts["CCx_PR"])
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment("Number of Employee User Restricted (CCx.ER) licenses purchased."))
        doc.add("CCx_ER", self._license_counts["CCx_ER"])
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment("####################################################"))
        doc.add(tomlkit.comment("##          Premium Licenses                      ##"))
        doc.add(tomlkit.comment("####################################################"))
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment("Number of Authorized User (CCx.Pre.AU) licenses purchased."))
        doc.add("CCx_Pre_AU", self._license_counts["CCx_Pre_AU"])
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment("Number of Eligible Participant (CCx.Pre.EP) licenses purchased."))
        doc.add("CCx_Pre_EP", self._license_counts["CCx_Pre_EP"])
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment("Number of Employee Authorized User (CCx.Pre.EE) licenses purchased."))
        doc.add("CCx_Pre_EE", self._license_counts["CCx_Pre_EE"])
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment("####################################################"))
        doc.add(tomlkit.comment("##          Premium CP4BA Add-On Licenses         ##"))
        doc.add(tomlkit.comment("####################################################"))
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment("Number of Authorized User (CCx.CP4BA.Pre.AU) licenses purchased."))
        doc.add("CCx_CP4BA_Pre_AU", self._license_counts["CCx_CP4BA_Pre_AU"])
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment("Number of Eligible Participant (CCx.CP4BA.Pre.EP) licenses purchased."))
        doc.add("CCx_CP4BA_Pre_EP", self._license_counts["CCx_CP4BA_Pre_EP"])
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment("Number of Employee Add-On (CCx.CP4BA.Pre.PE) licenses purchased."))
        doc.add("CCx_CP4BA_Pre_PE", self._license_counts["CCx_CP4BA_Pre_PE"])

        LICENSE_TOML.write_text(tomlkit.dumps(doc))

    def _write_servers_toml(self) -> None:
        doc = tomlkit.document()
        doc.add(tomlkit.comment("####################################################"))
        doc.add(tomlkit.comment("##         IBM Content Cortex Licensing Servers   ##"))
        doc.add(tomlkit.comment("####################################################"))

        for i, server in enumerate(self._servers, start=1):
            stype    = server["type"]
            cred_key = "API_KEY" if stype == "UMS" else "API_TOKEN"
            cred_label = "API key" if stype == "UMS" else "REST API token"

            doc.add(tomlkit.nl())
            doc.add(tomlkit.comment("####################################################"))
            doc.add(tomlkit.comment(f"##  Server {i:<44}##"))
            doc.add(tomlkit.comment("####################################################"))

            tbl = tomlkit.table()
            tbl.add(tomlkit.comment("Server type — Valid values: UMS | ILMT"))
            tbl.add("TYPE", stype)
            tbl.add(tomlkit.nl())
            tbl.add(tomlkit.comment(f"Base URL of the {stype} instance."))
            tbl.add("URL", server["url"])
            tbl.add(tomlkit.nl())
            tbl.add(tomlkit.comment(f"{cred_label} for authentication."))
            tbl.add(cred_key, "<Required>")
            tbl.add(tomlkit.nl())
            tbl.add(tomlkit.comment("Verify the server TLS certificate."))
            tbl.add("TLS_VERIFY", True)

            doc.add(f"server_{i}", tbl)


        SERVERS_TOML.write_text(tomlkit.dumps(doc))

    # ── Summary ───────────────────────────────────────────────────────────────

    def _print_summary(self) -> None:
        summary = Text()
        summary.append("Configuration written successfully.\n\n", style="bold green")
        summary.append(f"  • {LICENSE_TOML}\n", style="cyan")
        summary.append(f"  • {SERVERS_TOML}\n", style="cyan")
        for i in range(1, len(self._servers) + 1):
            summary.append(f"  • {SSL_CERTS_DIR}/server_{i}/ (drop certs here)\n", style="cyan")
        cred_keys = " / ".join(sorted({
            "API_KEY" if s["type"] == "UMS" else "API_TOKEN"
            for s in self._servers
        }))
        summary.append(f"\n⚠ Fill in {cred_keys} in {SERVERS_TOML} before running validate.", style="yellow")

        print()
        print(Panel(
            summary,
            title="[bold green]✓ Setup Complete[/bold green]",
            border_style="green",
            padding=(1, 2),
        ))
        print()
