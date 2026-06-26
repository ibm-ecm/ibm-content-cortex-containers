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

This module provides utility functions for handling questionary prompts
with proper cancellation handling.
"""

import sys
from typing import Any, Optional
from rich import print
from rich.panel import Panel


def handle_cancelled_prompt(result: Any, exit_message: str = "Operation cancelled by user") -> Any:
    """
    Handle the result of a questionary prompt, exiting gracefully if cancelled.
    
    When a user cancels a questionary prompt (Ctrl+C or ESC), the .ask() method
    returns None. This function checks for None and exits the script with a
    user-friendly message.
    
    Args:
        result: The result from questionary.ask()
        exit_message: Custom message to display on cancellation
        
    Returns:
        The result if not None
        
    Exits:
        Exits with code 0 if result is None (user cancelled)
    """
    if result is None:
        print()
        print(Panel.fit(
            f"[yellow]{exit_message}[/yellow]",
            border_style="yellow"
        ))
        print()
        sys.exit(0)
    return result


def safe_questionary_prompt(prompt_func, exit_message: str = "Operation cancelled by user", **kwargs) -> Any:
    """
    Safely execute a questionary prompt with automatic cancellation handling.
    
    This is a wrapper function that executes a questionary prompt and automatically
    handles cancellation (None result) by exiting gracefully.
    
    Args:
        prompt_func: A questionary prompt function (e.g., questionary.confirm)
        exit_message: Custom message to display on cancellation
        **kwargs: Arguments to pass to the prompt function
        
    Returns:
        The result from the prompt if not cancelled
        
    Exits:
        Exits with code 0 if user cancels (result is None)
        
    Example:
        >>> result = safe_questionary_prompt(
        ...     questionary.confirm,
        ...     "Do you want to continue?",
        ...     default=True
        ... )
    """
    try:
        result = prompt_func(**kwargs).ask()
        return handle_cancelled_prompt(result, exit_message)
    except KeyboardInterrupt:
        # Handle Ctrl+C explicitly
        print()
        print(Panel.fit(
            f"[yellow]{exit_message}[/yellow]",
            border_style="yellow"
        ))
        print()
        sys.exit(0)
    except Exception as e:
        # Handle any other exceptions
        print()
        print(Panel.fit(
            f"[red]Error during prompt: {str(e)}[/red]",
            border_style="red"
        ))
        print()
        sys.exit(1)

# Made with Bob
