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
Date range prompt for the validate command.
"""

import calendar
from datetime import date

import questionary
from questionary import Style
from rich import print
from rich.panel import Panel

from helper_scripts.license.setup.questionary_utils import safe_prompt

_STYLE = Style([
    ('qmark',       'fg:#61afef bold'),
    ('question',    'bold'),
    ('answer',      'fg:#98c379 bold'),
    ('pointer',     'fg:#61afef bold'),
    ('highlighted', 'fg:#ffffff'),
    ('selected',    'fg:#98c379 bold'),
    ('instruction', 'fg:#abb2bf'),
])


def parse_date(s: str) -> date:
    """
    Parse 'MM/DD/YYYY' into a date. Raises ValueError on bad input.
    """
    parts = s.strip().split("/")
    if len(parts) != 3:
        raise ValueError
    month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
    return date(year, month, day)  # raises ValueError for invalid dates


def month_range(start: date, end: date) -> list[tuple[int, int]]:
    """
    Return an ordered list of (year, month) tuples from start's month to
    end's month inclusive.
    """
    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def prompt_date_range() -> tuple[date, date]:
    """
    Interactively prompt for a start and end date in DD/MM/YYYY format.
    Returns (start_date, end_date) as date objects.
    """
    print()
    print(Panel.fit(
        "[bold cyan]Date Range[/bold cyan]\n\n"
        "Enter the date range to validate content operation usage.\n"
        "[dim]Format: MM/DD/YYYY  (e.g. 05/01/2026)  —  start and end dates are inclusive.[/dim]",
        border_style="cyan",
    ))
    print()

    # Start date
    while True:
        raw = safe_prompt(
            questionary.text,
            "Date range entry cancelled.",
            message="Start date (MM/DD/YYYY):",
            style=_STYLE,
        )
        try:
            start = parse_date(raw)
            break
        except (ValueError, IndexError):
            print("[red]  Invalid format. Please enter MM/DD/YYYY (e.g. 05/01/2026).[/red]")

    # End date
    while True:
        raw = safe_prompt(
            questionary.text,
            "Date range entry cancelled.",
            message="End date   (MM/DD/YYYY):",
            style=_STYLE,
        )
        try:
            end = parse_date(raw)
            if end < start:
                print("[red]  End date must be the same as or after the start date.[/red]")
                continue
            break
        except (ValueError, IndexError):
            print("[red]  Invalid format. Please enter MM/DD/YYYY (e.g. 07/31/2026).[/red]")

    return start, end
