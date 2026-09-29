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
Validate command orchestrator.

Queries all configured UMS and ILMT servers for the requested date range,
sums content_operation_count per month across all servers, compares against
purchased license entitlements, and displays a Rich table with per-month
compliance results.
"""

import sys
from calendar import month_abbr
from datetime import datetime, timezone

import requests

from rich import print
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.text import Text

from helper_scripts.license.validate.config_loader import load_servers, load_license_counts, compute_monthly_entitlement
from helper_scripts.license.validate.date_range import prompt_date_range, month_range
from helper_scripts.license.validate.report import ReportData, write_report
import helper_scripts.license.validate.ums_client  as _ums
import helper_scripts.license.validate.ilmt_client as _ilmt

console = Console()


def run(insecure: bool = False, report_fmt: str | None = None, report_path: str | None = None) -> None:
    """Entry point for `license.py validate`."""

    # ── Step 1: prompt for date range ─────────────────────────────────────────
    start_date, end_date = prompt_date_range()
    months = month_range(start_date, end_date)

    # ── Step 2: load config ───────────────────────────────────────────────────
    servers    = load_servers()
    if insecure:
        for s in servers:
            s.tls_verify = False
    counts     = load_license_counts()
    entitlement = compute_monthly_entitlement(counts)

    if entitlement == 0:
        print()
        print(Panel.fit(
            "[yellow]All license counts in license.toml are set to 0.\n"
            "Total entitlement is 0 ops/month — every month will show as over quota.\n\n"
            "Run [bold]license.py setup[/bold] to update your license counts.[/yellow]",
            border_style="yellow",
            title="[bold yellow]⚠  No Licenses Configured[/bold yellow]",
        ))
        print()

    # ── Step 3: query each server for each month ──────────────────────────────
    print()
    monthly_totals: dict[tuple[int, int], int] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Querying servers...", total=len(months) * len(servers))

        for year, month in months:
            # Pin boundaries for first/last month; full month otherwise.
            m_start = start_date if (year, month) == (start_date.year, start_date.month) else None
            m_end   = end_date   if (year, month) == (end_date.year,   end_date.month)   else None

            month_total = 0
            for server in servers:
                label = f"[cyan]server_{server.index}[/cyan] {month_abbr[month]} {year}"
                progress.update(task, description=f"Querying {label}")
                try:
                    client = _ums if server.type == "UMS" else _ilmt
                    month_total += client.query_month(
                        server, year, month,
                        insecure=insecure,
                        start_date=m_start,
                        end_date=m_end,
                    )
                except requests.HTTPError as e:
                    # Auth failures, bad tokens, etc. — abort immediately
                    progress.stop()
                    console.print()
                    console.print(Panel.fit(
                        f"[red]HTTP {e.response.status_code} from server_{server.index} "
                        f"({server.url})\n{e.response.text[:300]}[/red]",
                        title="[bold red]✗  Server Error[/bold red]",
                        border_style="red",
                    ))
                    sys.exit(1)
                except requests.ConnectionError as e:
                    progress.stop()
                    console.print()
                    console.print(Panel.fit(
                        f"[red]Could not connect to server_{server.index} ({server.url})\n{e}[/red]",
                        title="[bold red]✗  Connection Error[/bold red]",
                        border_style="red",
                    ))
                    sys.exit(1)
                except Exception as e:
                    # Unexpected errors (bad zip, parse failure, etc.) — warn and continue
                    console.print(
                        f"[yellow]  ⚠  server_{server.index} {month_abbr[month]} {year}: {e}[/yellow]"
                    )
                progress.advance(task)

            monthly_totals[(year, month)] = month_total

    # ── Step 4: build results table ───────────────────────────────────────────
    table = Table(
        title="Content Operation Usage vs Entitlement",
        show_header=True,
        header_style="bold cyan",
        border_style="bright_black",
        show_lines=True,
    )
    table.add_column("Month",       style="bold", width=12)
    table.add_column("Ops Used",    justify="right", width=16)
    table.add_column("Entitlement", justify="right", width=16)
    table.add_column("Usage %",     justify="right", width=10)
    table.add_column("Status",      width=30)

    over_months   = 0
    total_used    = 0
    total_entitled = len(months) * entitlement

    for year, month in months:
        used = monthly_totals[(year, month)]
        total_used += used

        pct = (used / entitlement * 100) if entitlement > 0 else float("inf")
        pct_str = f"{pct:.1f}%" if entitlement > 0 else "—"

        if entitlement == 0 or used > entitlement:
            over_months += 1
            overage = used - entitlement
            status = Text(f"✗  Over by {overage:,}", style="bold red")
        elif pct >= 90:
            status = Text(f"⚠  {pct:.1f}% used", style="bold yellow")
        else:
            status = Text("✓  Within quota", style="bold green")

        table.add_row(
            f"{month_abbr[month]} {year}",
            f"{used:,}",
            f"{entitlement:,}",
            pct_str,
            status,
        )

    console.print()
    console.print(table)

    # ── Step 5: summary panel ─────────────────────────────────────────────────
    summary = Text()
    summary.append(f"Months checked:    ", style="white")
    summary.append(f"{len(months)}\n", style="bold white")
    summary.append(f"Months over quota: ", style="white")
    if over_months > 0:
        summary.append(f"{over_months}", style="bold red")
    else:
        summary.append(f"{over_months}", style="bold green")
    summary.append(f"\nTotal ops used:    ", style="white")
    summary.append(f"{total_used:,}\n", style="bold white")
    summary.append(f"Total entitlement: ", style="white")
    summary.append(f"{total_entitled:,}", style="bold white")
    border = "red" if over_months > 0 else "green"
    title  = (
        f"[bold red]✗  {over_months} month(s) over quota[/bold red]"
        if over_months > 0
        else "[bold green]✓  All months within quota[/bold green]"
    )

    console.print()
    console.print(Panel(summary, title=title, border_style=border, padding=(1, 2)))
    console.print()

    # ── Step 6: write report if requested ─────────────────────────────────────
    if report_fmt and report_path:
        report_data = ReportData(
            generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            start_date=start_date,
            end_date=end_date,
            servers=servers,
            entitlement_per_month=entitlement,
            license_counts=counts,
            months=months,
            monthly_totals=monthly_totals,
            over_months=over_months,
            total_used=total_used,
            total_entitled=total_entitled,
        )
        write_report(report_data, report_fmt, report_path)
