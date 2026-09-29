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
Questionary Utilities

Provides safe wrappers around questionary prompts with graceful
cancellation handling — matching the pattern used in fncm-prerequisites.
"""

import sys
from typing import Any

import questionary
from rich import print
from rich.panel import Panel


def handle_cancelled_prompt(result: Any, exit_message: str = "Operation cancelled by user") -> Any:
    """Exit cleanly when a questionary .ask() returns None (Ctrl+C / ESC)."""
    if result is None:
        print()
        print(Panel.fit(
            f"[yellow]{exit_message}[/yellow]",
            border_style="yellow"
        ))
        print()
        sys.exit(0)
    return result


def safe_prompt(prompt_func, exit_message: str = "Operation cancelled by user", **kwargs) -> Any:
    """
    Execute a questionary prompt and handle cancellation automatically.

    Args:
        prompt_func: A questionary prompt class (e.g. questionary.text).
        exit_message: Message shown when the user cancels.
        **kwargs: Arguments forwarded to prompt_func.

    Returns:
        The prompt result if not cancelled.
    """
    try:
        result = prompt_func(**kwargs).ask()
        return handle_cancelled_prompt(result, exit_message)
    except KeyboardInterrupt:
        print()
        print(Panel.fit(
            f"[yellow]{exit_message}[/yellow]",
            border_style="yellow"
        ))
        print()
        sys.exit(0)
    except Exception as e:
        print()
        print(Panel.fit(
            f"[red]Error during prompt: {e}[/red]",
            border_style="red"
        ))
        print()
        sys.exit(1)
