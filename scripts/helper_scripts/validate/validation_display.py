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
ValidationDisplay - Modern rich Live display for validation tests

This module provides a clean, real-time updating interface for displaying
validation test results using rich Live display and tables.
"""

from enum import Enum
from typing import Dict, List, Optional
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout
from rich.console import Group


class ValidationStatus(Enum):
    """Status indicators for validation tests"""
    PENDING = ("⏸", "dim white", "Pending")
    RUNNING = ("⏳", "cyan", "Running")
    SUCCESS = ("✓", "green", "Success")
    FAILED = ("✗", "red", "Failed")
    SKIPPED = ("⊘", "yellow", "Skipped")
    WARNING = ("⚠", "yellow", "Warning")
    COMPLETED = ("●", "white", "Completed")  # Neutral completion indicator


class ValidationTest:
    """Represents a single validation test"""
    
    def __init__(self, name: str, category: str, total_items: int = 1):
        self.name = name
        self.category = category
        self.total_items = total_items
        self.completed_items = 0
        self.status = ValidationStatus.PENDING
        self.details = ""
        self.messages: List[str] = []
        self.failure_reason: Optional[str] = None
        self.remediation: Optional[str] = None
    
    def start(self):
        """Mark test as running"""
        self.status = ValidationStatus.RUNNING
        self.details = f"0/{self.total_items}"
    
    def update_progress(self, completed: int, detail: str = ""):
        """Update test progress"""
        self.completed_items = completed
        if detail:
            self.details = detail
        else:
            self.details = f"{completed}/{self.total_items}"
    
    def complete(self, success: bool = True, message: str = "", failure_reason: str = "", remediation: str = ""):
        """Mark test as complete"""
        self.status = ValidationStatus.SUCCESS if success else ValidationStatus.FAILED
        # Show meaningful summary in details column
        if success:
            if self.total_items > 1:
                self.details = f"All {self.total_items} items validated"
            else:
                self.details = message or "Validated successfully"
        else:
            # For failures, show the error in details
            if failure_reason:
                self.details = f"FAILED: {failure_reason[:60]}..."  # Truncate for table
            else:
                self.details = message or "Validation failed"
            self.failure_reason = failure_reason or message
            self.remediation = remediation
    
    def skip(self, reason: str = ""):
        """Mark test as skipped"""
        self.status = ValidationStatus.SKIPPED
        self.details = reason or "Skipped"
    
    def add_message(self, message: str):
        """Add a detail message"""
        self.messages.append(message)


class ValidationDisplay:
    """
    Modern validation display using rich Live display
    
    Provides a real-time updating interface showing:
    - Status table with all validation tests
    - Current test details
    - Summary statistics
    """
    
    def __init__(self, console: Console):
        self.console = console
        self.tests: Dict[str, ValidationTest] = {}
        self.current_test: Optional[str] = None
        self.live: Optional[Live] = None
        self.detail_messages: List[str] = []
        
    def add_test(self, test_id: str, name: str, category: str, total_items: int = 1):
        """Add a validation test to track"""
        self.tests[test_id] = ValidationTest(name, category, total_items)
    
    def start_test(self, test_id: str):
        """Start a validation test"""
        if test_id in self.tests:
            self.tests[test_id].start()
            self.current_test = test_id
            self.update()  # Refresh display
    
    def update_test(self, test_id: str, completed: int, detail: str = ""):
        """Update test progress"""
        if test_id in self.tests:
            self.tests[test_id].update_progress(completed, detail)
            self.update()  # Refresh display
    
    def complete_test(self, test_id: str, success: bool = True, message: str = "",
                     failure_reason: str = "", remediation: str = ""):
        """Complete a validation test"""
        if test_id in self.tests:
            self.tests[test_id].complete(success, message, failure_reason, remediation)
            self.update()  # Refresh display
    
    def skip_test(self, test_id: str, reason: str = ""):
        """Skip a validation test"""
        if test_id in self.tests:
            self.tests[test_id].skip(reason)
            self.update()  # Refresh display
    
    def add_detail(self, message: str):
        """Add a detail message to current output"""
        self.detail_messages.append(message)
        # Keep only last 10 messages
        if len(self.detail_messages) > 10:
            self.detail_messages.pop(0)
        self.update()  # Refresh display
    
    def _create_status_table(self) -> Table:
        """Create the status table"""
        table = Table(
            title="Validation Status",
            show_header=True,
            header_style="bold cyan",
            border_style="cyan",
            title_style="bold white"
        )
        
        table.add_column("Category", style="white", width=25)
        table.add_column("Status", width=10, justify="center")
        table.add_column("Result", width=50)
        
        # Group tests by category
        categories = {}
        for test in self.tests.values():
            if test.category not in categories:
                categories[test.category] = []
            categories[test.category].append(test)
        
        # Add rows for each category
        for category, tests in categories.items():
            for test in tests:
                icon, color, _ = test.status.value
                status_text = Text(icon, style=color)
                
                # Build result text based on status
                if test.status == ValidationStatus.RUNNING:
                    result_text = Text(f"Testing... {test.completed_items}/{test.total_items}", style="cyan")
                elif test.status == ValidationStatus.PENDING:
                    result_text = Text("Waiting...", style="dim")
                elif test.status == ValidationStatus.SUCCESS:
                    if test.total_items > 1:
                        result_text = Text(f"✓ All {test.total_items} items validated", style="green")
                    else:
                        result_text = Text(f"✓ {test.details}", style="green")
                elif test.status == ValidationStatus.FAILED:
                    # Show error inline for failures
                    result_text = Text()
                    result_text.append("✗ ", style="bold red")
                    if test.failure_reason:
                        # Truncate long error messages
                        error_msg = test.failure_reason[:80] + "..." if len(test.failure_reason) > 80 else test.failure_reason
                        result_text.append(error_msg, style="red")
                    else:
                        result_text.append(test.details or "Validation failed", style="red")
                elif test.status == ValidationStatus.SKIPPED:
                    result_text = Text(f"⊘ {test.details}", style="yellow")
                else:
                    result_text = Text(test.details, style="white")
                
                table.add_row(
                    test.name,
                    status_text,
                    result_text
                )
        
        return table
    
    def _create_summary(self) -> Text:
        """Create summary statistics"""
        total = len(self.tests)
        success = sum(1 for t in self.tests.values() if t.status == ValidationStatus.SUCCESS)
        failed = sum(1 for t in self.tests.values() if t.status == ValidationStatus.FAILED)
        running = sum(1 for t in self.tests.values() if t.status == ValidationStatus.RUNNING)
        skipped = sum(1 for t in self.tests.values() if t.status == ValidationStatus.SKIPPED)
        
        summary = Text()
        summary.append(f"Total: {total}  ", style="white")
        summary.append(f"✓ {success}  ", style="green")
        summary.append(f"✗ {failed}  ", style="red")
        summary.append(f"⏳ {running}  ", style="cyan")
        summary.append(f"⊘ {skipped}", style="yellow")
        
        return summary
    
    def _create_detail_panel(self) -> Optional[Panel]:
        """Create detail panel for current test"""
        if not self.detail_messages:
            return None
        
        detail_text = Text()
        for msg in self.detail_messages[-5:]:  # Show last 5 messages
            detail_text.append(msg + "\n", style="dim")
        
        return Panel(
            detail_text,
            title="[bold white]Current Test Details[/bold white]",
            border_style="dim",
            padding=(0, 1)
        )
    
    def _generate_display(self) -> Group:
        """Generate the complete display"""
        components = []
        
        # Add status table
        components.append(self._create_status_table())
        components.append(Text())  # Spacing
        
        # Add summary
        components.append(self._create_summary())
        
        # Add detail panel if there are messages
        detail_panel = self._create_detail_panel()
        if detail_panel:
            components.append(Text())  # Spacing
            components.append(detail_panel)
        
        return Group(*components)
    
    def start(self):
        """Start the live display"""
        self.live = Live(
            self._generate_display(),
            console=self.console,
            refresh_per_second=4,
            transient=False
        )
        self.live.start()
    
    def update(self):
        """Update the live display"""
        if self.live:
            self.live.update(self._generate_display())
    
    def stop(self):
        """Stop the live display"""
        if self.live:
            self.live.stop()
            self.live = None
    
    def __enter__(self):
        """Context manager entry"""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.stop()
    
    def display_failures(self):
        """Display detailed failure information after validation completes"""
        failed_tests = [test for test in self.tests.values() if test.status == ValidationStatus.FAILED]
        
        if not failed_tests:
            return
        
        self.console.print()
        
        # Create a comprehensive failure summary
        summary_text = Text()
        summary_text.append("⚠ ", style="bold red")
        summary_text.append(f"{len(failed_tests)} Validation Check(s) Failed\n\n", style="bold red")
        summary_text.append("The following issues must be resolved before deployment:", style="white")
        
        self.console.print(Panel(
            summary_text,
            border_style="red",
            padding=(1, 2),
            title="[bold red]Validation Failures[/bold red]"
        ))
        self.console.print()
        
        # Display each failure with detailed information
        for idx, test in enumerate(failed_tests, 1):
            # Create failure detail panel
            failure_text = Text()
            failure_text.append(f"{idx}. ", style="bold white")
            failure_text.append(f"{test.name}\n", style="bold red")
            failure_text.append(f"   Category: {test.category}\n", style="dim")
            failure_text.append("\n")
            
            if test.failure_reason:
                failure_text.append("   ❌ Error:\n", style="bold yellow")
                # Format multi-line error messages with indentation
                for line in test.failure_reason.split('\n'):
                    if line.strip():
                        failure_text.append(f"      {line}\n", style="white")
                failure_text.append("\n")
            
            if test.remediation:
                failure_text.append("   🔧 How to Fix:\n", style="bold green")
                # Format multi-line remediation with indentation
                for line in test.remediation.split('\n'):
                    if line.strip():
                        failure_text.append(f"      {line}\n", style="white")
            else:
                # Provide generic remediation if none specified
                failure_text.append("   🔧 How to Fix:\n", style="bold green")
                failure_text.append(
                    "      1. Review the validation logs above for specific error messages\n"
                    "      2. Check your property files for correct configuration\n"
                    "      3. Verify connectivity and credentials\n"
                    "      4. Consult the documentation for this component\n",
                    style="white"
                )
            
            self.console.print(Panel(
                failure_text,
                border_style="red",
                padding=(1, 2)
            ))
            self.console.print()
        
        # Add final reminder
        reminder = Text()
        reminder.append("💡 Tip: ", style="bold cyan")
        reminder.append("Fix these issues and re-run validation before applying artifacts to your cluster.", style="white")
        self.console.print(Panel(
            reminder,
            border_style="cyan",
            padding=(0, 2)
        ))
        self.console.print()
        
        return False

# Made with Bob



class DisplayProgressAdapter:
    """
    Adapter to bridge between old progress interface and new ValidationDisplay.
    
    This allows existing validation methods to work with ValidationDisplay
    without requiring complete rewrites.
    """
    
    def __init__(self, display: 'ValidationDisplay', test_id: str):
        self.display = display
        self.test_id = test_id
        self._task_counter = 0
    
    def add_task(self, description: str, total: Optional[int] = None) -> int:
        """Add a task (compatibility method)"""
        self._task_counter += 1
        return self._task_counter
    
    def update(self, task_id: int, advance: Optional[int] = None, completed: Optional[int] = None):
        """Update task progress"""
        if completed is not None:
            # Get the test to find total
            test = self.display.tests.get(self.test_id)
            if test:
                self.display.update_test(self.test_id, completed, 
                    f"Progress: {completed}/{test.total_items}")
    
    def advance(self, task_id: int, advance: int = 1):
        """Advance task progress"""
        test = self.display.tests.get(self.test_id)
        if test:
            new_completed = test.completed_items + advance
            self.display.update_test(self.test_id, new_completed)
    
    def log(self, *args, **kwargs):
        """Log a message to the display"""
        if args:
            # Convert rich objects to plain text
            from rich.panel import Panel
            from rich.text import Text
            
            message = ""
            for arg in args:
                if isinstance(arg, Panel):
                    # Extract text from Panel
                    renderable = arg.renderable
                    if isinstance(renderable, Text):
                        message += renderable.plain
                    elif isinstance(renderable, str):
                        message += renderable
                    else:
                        message += str(renderable)
                elif isinstance(arg, Text):
                    # Extract plain text from Text object
                    message += arg.plain
                elif isinstance(arg, str):
                    message += arg
                else:
                    # For other objects, convert to string
                    message += str(arg)
            
            # Clean up the message
            message = message.strip()
            if message and not message.startswith('<rich.'):
                self.display.add_detail(message)
    
    @property
    def console(self):
        """Return the console for compatibility"""
        return self.display.console
