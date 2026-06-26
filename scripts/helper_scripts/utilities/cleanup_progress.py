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
Cleanup Progress Tracking Module

This module provides comprehensive progress tracking and visualization for
multi-operator cleanup operations with live updates and detailed status information.
"""

import signal
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    MofNCompleteColumn
)
from rich.table import Table
from rich.text import Text

from .operator_config import OperatorType, get_operator_metadata


class CleanupPhase(str, Enum):
    """Phases of operator cleanup."""
    PENDING = "pending"
    PREPARING = "preparing"
    CLEANING = "cleaning"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class CleanupStep(str, Enum):
    """Individual steps within cleanup."""
    OPERATOR_DELETION = "operator_deletion"
    CRD_DELETION = "crd_deletion"
    RBAC_CLEANUP = "rbac_cleanup"
    SECRET_CLEANUP = "secret_cleanup"
    NAMESPACE_CLEANUP = "namespace_cleanup"
    VERIFICATION = "verification"
    # OLM-specific steps
    SUBSCRIPTION_DELETION = "subscription_deletion"
    CSV_DELETION = "csv_deletion"
    OPERATOR_GROUP_DELETION = "operator_group_deletion"
    CATALOG_SOURCE_DELETION = "catalog_source_deletion"
    # Helm-specific steps
    HELM_UNINSTALL = "helm_uninstall"


@dataclass
class OperatorCleanupStatus:
    """
    Tracks the cleanup status of a single operator.
    """
    operator: OperatorType
    operator_type: str = "YAML"  # YAML, OLM, or Helm
    phase: CleanupPhase = CleanupPhase.PENDING
    current_step: Optional[CleanupStep] = None
    progress: int = 0  # 0-100
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None
    steps_completed: List[CleanupStep] = field(default_factory=list)
    steps_total: int = 6  # Total number of cleanup steps
    
    @property
    def duration(self) -> Optional[timedelta]:
        """Calculate cleanup duration."""
        if self.start_time:
            end = self.end_time or datetime.now()
            return end - self.start_time
        return None
    
    @property
    def is_complete(self) -> bool:
        """Check if cleanup is complete."""
        return self.phase in [CleanupPhase.COMPLETED, CleanupPhase.FAILED, CleanupPhase.SKIPPED]
    
    @property
    def is_successful(self) -> bool:
        """Check if cleanup was successful."""
        return self.phase == CleanupPhase.COMPLETED
    
    def get_status_icon(self) -> str:
        """Get status icon for current phase."""
        icons = {
            CleanupPhase.PENDING: "⏳",
            CleanupPhase.PREPARING: "🔧",
            CleanupPhase.CLEANING: "🧹",
            CleanupPhase.VERIFYING: "🔍",
            CleanupPhase.COMPLETED: "✅",
            CleanupPhase.FAILED: "❌",
            CleanupPhase.SKIPPED: "⏭️"
        }
        return icons.get(self.phase, "❓")
    
    def get_status_color(self) -> str:
        """Get color for current phase."""
        colors = {
            CleanupPhase.PENDING: "dim",
            CleanupPhase.PREPARING: "yellow",
            CleanupPhase.CLEANING: "cyan",
            CleanupPhase.VERIFYING: "blue",
            CleanupPhase.COMPLETED: "green",
            CleanupPhase.FAILED: "red",
            CleanupPhase.SKIPPED: "dim"
        }
        return colors.get(self.phase, "white")


class MultiOperatorCleanupTracker:
    """
    Tracks cleanup progress for multiple operators with live updates.
    """
    
    def __init__(
        self,
        operators: Dict[str, Dict],  # operator_key -> operator_info
        console: Optional[Console] = None,
        parallel: bool = False
    ):
        """
        Initialize the cleanup tracker.
        
        Args:
            operators: Dictionary of operators to track (key -> info dict)
            console: Rich console for output
            parallel: Whether cleanup is parallel
        """
        self.console = console or Console()
        self.parallel = parallel
        self.operators = operators
        self.statuses: Dict[str, OperatorCleanupStatus] = {}
        self.overall_start_time = datetime.now()
        self.overall_end_time: Optional[datetime] = None
        
        # Initialize status for each operator
        for op_key, op_info in operators.items():
            operator_type_enum = OperatorType(op_key)
            self.statuses[op_key] = OperatorCleanupStatus(
                operator=operator_type_enum,
                operator_type=op_info.get("type", "YAML")
            )
    
    def start_operator(self, operator_key: str) -> None:
        """Mark operator cleanup as started."""
        if operator_key in self.statuses:
            self.statuses[operator_key].phase = CleanupPhase.PREPARING
            self.statuses[operator_key].start_time = datetime.now()
    
    def update_operator(
        self,
        operator_key: str,
        phase: Optional[CleanupPhase] = None,
        step: Optional[CleanupStep] = None,
        progress: Optional[int] = None,
        error: Optional[str] = None
    ) -> None:
        """Update operator cleanup status."""
        if operator_key not in self.statuses:
            return
        
        status = self.statuses[operator_key]
        
        if phase:
            status.phase = phase
        
        if step:
            status.current_step = step
            if step not in status.steps_completed:
                status.steps_completed.append(step)
        
        if progress is not None:
            status.progress = min(100, max(0, progress))
        
        if error:
            status.error_message = error
            status.phase = CleanupPhase.FAILED
    
    def complete_operator(
        self,
        operator_key: str,
        success: bool = True,
        error: Optional[str] = None
    ) -> None:
        """Mark operator cleanup as complete."""
        if operator_key in self.statuses:
            status = self.statuses[operator_key]
            status.phase = CleanupPhase.COMPLETED if success else CleanupPhase.FAILED
            status.progress = 100 if success else status.progress
            status.end_time = datetime.now()
            if error:
                status.error_message = error
    
    def skip_operator(self, operator_key: str, reason: str) -> None:
        """Mark operator as skipped."""
        if operator_key in self.statuses:
            self.statuses[operator_key].phase = CleanupPhase.SKIPPED
            self.statuses[operator_key].error_message = reason
    
    def is_complete(self) -> bool:
        """Check if all operators are complete."""
        return all(status.is_complete for status in self.statuses.values())
    
    def get_summary(self) -> Dict[str, int]:
        """Get cleanup summary statistics."""
        return {
            "total": len(self.statuses),
            "completed": sum(1 for s in self.statuses.values() if s.phase == CleanupPhase.COMPLETED),
            "failed": sum(1 for s in self.statuses.values() if s.phase == CleanupPhase.FAILED),
            "in_progress": sum(1 for s in self.statuses.values() 
                             if s.phase in [CleanupPhase.PREPARING, CleanupPhase.CLEANING, CleanupPhase.VERIFYING]),
            "pending": sum(1 for s in self.statuses.values() if s.phase == CleanupPhase.PENDING),
            "skipped": sum(1 for s in self.statuses.values() if s.phase == CleanupPhase.SKIPPED)
        }
    
    def create_progress_display(self):
        """Create the main progress display with sleek, minimal design for parallel cleanup."""
        # Use parallel display for any multi-operator cleanup (2+ operators)
        if len(self.operators) > 1:
            return self._create_parallel_display()
        else:
            return self._create_sequential_display()
    
    def _create_parallel_display(self) -> Panel:
        """Create sleek parallel cleanup display showing operators side-by-side."""
        from rich.columns import Columns
        
        # Determine cleanup mode label
        mode_label = "⚡ Parallel Cleanup" if self.parallel else "🧹 Multi-Operator Cleanup"
        
        # Create individual operator cards
        operator_cards = []
        for op_key in self.operators.keys():
            status = self.statuses[op_key]
            metadata = get_operator_metadata(status.operator)
            
            # Build compact operator card with Rich Text objects for proper rendering
            card_content = []
            
            # Operator name with icon
            icon = status.get_status_icon()
            color = status.get_status_color()
            name_text = Text()
            name_text.append(f"{icon} {metadata.display_name}", style=f"bold {color}")
            card_content.append(name_text)
            
            # Operator type badge
            type_text = Text()
            type_text.append(f"[{status.operator_type}]", style="dim")
            card_content.append(type_text)
            
            # Progress bar (compact) using Text for proper color rendering
            bar_text = Text()
            if status.is_complete:
                if status.is_successful:
                    bar_text.append("━" * 20, style="green")
                else:
                    bar_text.append("━" * 20, style="red")
            else:
                filled = int(status.progress / 100 * 20)
                bar_text.append("━" * filled, style="cyan")
                bar_text.append("━" * (20 - filled), style="dim")
            card_content.append(bar_text)
            
            # Status and progress percentage
            status_text = Text()
            status_text.append(status.phase.value.title(), style=color)
            status_text.append(" • ")
            status_text.append(f"{status.progress}%")
            card_content.append(status_text)
            
            # Current step (if active) - this provides traceability
            step_text = Text()
            if status.current_step and not status.is_complete:
                # Map step values to user-friendly display names
                step_display_names = {
                    "operator_deletion": "Deleting Operator",
                    "crd_deletion": "Removing CRDs",
                    "rbac_cleanup": "Cleaning RBAC",
                    "secret_cleanup": "Removing Secrets",
                    "namespace_cleanup": "Cleaning Namespace",
                    "verification": "Verifying Cleanup",
                    "subscription_deletion": "Removing Subscription",
                    "csv_deletion": "Removing CSV",
                    "operator_group_deletion": "Removing Operator Group",
                    "catalog_source_deletion": "Removing Catalog Source",
                    "helm_uninstall": "Uninstalling Helm Release"
                }
                step_name = step_display_names.get(status.current_step.value,
                                                   status.current_step.value.replace('_', ' ').title())
                step_text.append(step_name, style="dim")
            elif status.duration:
                duration_str = str(status.duration).split('.')[0]
                step_text.append(duration_str, style="dim")
            else:
                step_text.append("")
            card_content.append(step_text)
            
            # Create panel for this operator
            operator_panel = Panel(
                Group(*card_content),
                border_style=color,
                padding=(0, 1),
                width=28
            )
            operator_cards.append(operator_panel)
        
        # Arrange operators in columns
        columns = Columns(operator_cards, equal=True, expand=True)
        
        # Overall status with proper Text rendering
        summary = self.get_summary()
        elapsed = datetime.now() - self.overall_start_time
        elapsed_str = str(elapsed).split('.')[0]
        
        status_text = Text(justify="center")
        status_text.append(f"{summary['completed']}/{summary['total']} Complete")
        status_text.append(" • ")
        status_text.append(elapsed_str)
        
        # Combine into main panel - create a fresh Group each time to prevent accumulation
        content = Group(
            columns,
            Text(""),
            status_text
        )
        
        # Return a fresh Panel instance each time to ensure proper replacement
        return Panel(
            content,
            title=f"🧹 {mode_label}",
            border_style="cyan",
            padding=(1, 2)
        )
    
    def _create_sequential_display(self) -> Panel:
        """Create sequential cleanup display (original layout)."""
        layout = Layout()
        
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="operators", ratio=2),
            Layout(name="summary", size=8)
        )
        
        # Header
        layout["header"].update(self._create_header())
        
        # Operator progress
        layout["operators"].update(self._create_operator_progress())
        
        # Summary
        layout["summary"].update(self._create_summary())
        
        return Panel(layout, border_style="cyan")
    
    def _create_header(self) -> Panel:
        """Create header panel."""
        elapsed = datetime.now() - self.overall_start_time
        elapsed_str = str(elapsed).split('.')[0]  # Remove microseconds
        
        mode = "Parallel" if self.parallel else "Sequential"
        title = f"🧹 Multi-Operator Cleanup ({mode} Mode)"
        
        content = f"[bold]Elapsed Time:[/bold] {elapsed_str}"
        
        return Panel(content, title=title, border_style="cyan")
    
    def _create_operator_progress(self) -> Panel:
        """Create operator progress panel."""
        table = Table(show_header=True, header_style="bold cyan", box=None)
        table.add_column("Operator", style="cyan", width=25)
        table.add_column("Type", justify="center", width=8)
        table.add_column("Status", justify="center", width=12)
        table.add_column("Progress", width=30)
        table.add_column("Step", style="yellow", width=20)
        table.add_column("Time", style="green", width=10)
        
        for op_key in self.operators.keys():
            status = self.statuses[op_key]
            metadata = get_operator_metadata(status.operator)
            
            # Operator name
            name = metadata.display_name
            
            # Operator type
            op_type = status.operator_type
            
            # Status with icon
            status_text = f"{status.get_status_icon()} {status.phase.value.title()}"
            status_colored = f"[{status.get_status_color()}]{status_text}[/{status.get_status_color()}]"
            
            # Progress bar
            if status.is_complete:
                if status.is_successful:
                    progress_bar = "[green]" + "█" * 30 + "[/green]"
                else:
                    progress_bar = "[red]" + "█" * 30 + "[/red]"
            else:
                filled = int(status.progress / 100 * 30)
                progress_bar = "[cyan]" + "█" * filled + "[/cyan]" + "░" * (30 - filled)
            progress_text = f"{progress_bar} {status.progress}%"
            
            # Current step
            if status.current_step:
                step_display_names = {
                    "operator_deletion": "Deleting Operator",
                    "crd_deletion": "Removing CRDs",
                    "rbac_cleanup": "Cleaning RBAC",
                    "secret_cleanup": "Removing Secrets",
                    "namespace_cleanup": "Cleaning Namespace",
                    "verification": "Verifying Cleanup",
                    "subscription_deletion": "Removing Subscription",
                    "csv_deletion": "Removing CSV",
                    "operator_group_deletion": "Removing Operator Group",
                    "catalog_source_deletion": "Removing Catalog Source",
                    "helm_uninstall": "Uninstalling Helm Release"
                }
                step_text = step_display_names.get(status.current_step.value,
                                                   status.current_step.value.replace('_', ' ').title())
            elif status.is_complete:
                step_text = "—"
            else:
                step_text = "Waiting..."
            
            # Duration
            if status.duration:
                duration_str = str(status.duration).split('.')[0]
            else:
                duration_str = "—"
            
            table.add_row(name, op_type, status_colored, progress_text, step_text, duration_str)
        
        return Panel(table, title="📊 Operator Cleanup Progress", border_style="blue")
    
    def _create_summary(self) -> Panel:
        """Create summary panel."""
        summary = self.get_summary()
        
        # Create summary table
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Metric", style="bold")
        table.add_column("Count", justify="right")
        
        table.add_row("Total Operators", str(summary["total"]))
        table.add_row("[green]✅ Completed[/green]", f"[green]{summary['completed']}[/green]")
        
        if summary["failed"] > 0:
            table.add_row("[red]❌ Failed[/red]", f"[red]{summary['failed']}[/red]")
        
        if summary["in_progress"] > 0:
            table.add_row("[cyan]🧹 In Progress[/cyan]", f"[cyan]{summary['in_progress']}[/cyan]")
        
        if summary["pending"] > 0:
            table.add_row("[dim]⏳ Pending[/dim]", f"[dim]{summary['pending']}[/dim]")
        
        if summary["skipped"] > 0:
            table.add_row("[dim]⏭️  Skipped[/dim]", f"[dim]{summary['skipped']}[/dim]")
        
        # Add overall progress
        overall_progress = int((summary["completed"] + summary["failed"]) / summary["total"] * 100)
        table.add_row("", "")  # Spacer
        table.add_row("[bold]Overall Progress[/bold]", f"[bold]{overall_progress}%[/bold]")
        
        return Panel(table, title="📈 Cleanup Summary", border_style="green")


def create_cleanup_progress(
    operators: Dict[str, Dict],
    parallel: bool = False,
    console: Optional[Console] = None
) -> tuple[MultiOperatorCleanupTracker, Live]:
    """
    Create a live cleanup progress tracker with graceful interrupt handling.
    
    Args:
        operators: Dictionary of operators to track (key -> info dict)
        parallel: Whether cleanup is parallel
        console: Rich console for output
        
    Returns:
        Tuple of (tracker, live_display)
    """
    console = console or Console()
    tracker = MultiOperatorCleanupTracker(operators, console, parallel)
    
    # Create live display with proper signal handling
    live = Live(
        tracker.create_progress_display(),
        console=console,
        refresh_per_second=4,
        screen=True,  # Use alternate screen buffer for clean rendering
        transient=False,
        auto_refresh=True  # Enable auto-refresh during display
    )
    
    # Store original signal handler
    original_sigint_handler = signal.getsignal(signal.SIGINT)
    
    def graceful_interrupt_handler(signum, frame):
        """Handle SIGINT (Ctrl+C) gracefully by stopping the live display."""
        try:
            # Stop the live display cleanly
            if live._started:
                live.stop()
        except Exception:
            pass  # Ignore errors during cleanup
        finally:
            # Restore original handler and re-raise
            signal.signal(signal.SIGINT, original_sigint_handler)
            raise KeyboardInterrupt()
    
    # Install graceful interrupt handler
    signal.signal(signal.SIGINT, graceful_interrupt_handler)
    
    return tracker, live


def display_cleanup_complete(
    tracker: MultiOperatorCleanupTracker,
    console: Optional[Console] = None
) -> None:
    """
    Display final cleanup summary.
    
    Args:
        tracker: Cleanup tracker with final status
        console: Rich console for output
    """
    console = console or Console()
    summary = tracker.get_summary()
    
    # Calculate total time
    if tracker.overall_end_time:
        total_time = tracker.overall_end_time - tracker.overall_start_time
    else:
        total_time = datetime.now() - tracker.overall_start_time
    
    total_time_str = str(total_time).split('.')[0]
    
    # Create sleek completion display for multi-operator cleanups (2+ operators)
    if len(tracker.operators) > 1:
        from rich.rule import Rule
        
        # Calculate time saved
        sequential_time = sum(
            (s.duration.total_seconds() if s.duration else 0)
            for s in tracker.statuses.values()
        )
        time_saved = sequential_time - total_time.total_seconds()
        
        # Determine completion title based on cleanup mode
        if tracker.parallel:
            completion_title = "⚡ Parallel Cleanup Complete"
        else:
            completion_title = "🧹 Multi-Operator Cleanup Complete"
        
        # Display header with rule
        console.print()
        console.print(Rule(f"[bold cyan]🎉 Cleanup Complete[/bold cyan]", style="cyan"))
        console.print()
        
        # Display summary statistics
        console.print(f"  [bold cyan]{completion_title}[/bold cyan]")
        console.print()
        console.print(f"  [green]✓[/green] {summary['completed']}/{summary['total']} operators cleaned successfully")
        console.print(f"  [cyan]⏱[/cyan]  Total time: {total_time_str}")
        
        if tracker.parallel and time_saved > 0:
            console.print(f"  [yellow]⚡[/yellow] Time saved: ~{int(time_saved)}s")
        
        if summary["failed"] > 0:
            console.print(f"  [red]✗[/red] {summary['failed']} failed")
        
        console.print()
        console.print(Rule("[bold cyan]Operator Status[/bold cyan]", style="cyan"))
        console.print()
        
        # Create compact results table without box borders
        results_table = Table(
            show_header=True,
            header_style="bold cyan",
            box=None,
            padding=(0, 2),
            show_edge=False
        )
        results_table.add_column("Operator", style="cyan", width=25)
        results_table.add_column("Type", justify="center", width=8)
        results_table.add_column("Status", justify="center", width=15)
        results_table.add_column("Duration", style="green", width=12)
        
        for op_key, status in tracker.statuses.items():
            metadata = get_operator_metadata(status.operator)
            
            # Status with icon
            if status.is_successful:
                status_text = "[green]✅ Success[/green]"
            elif status.phase == CleanupPhase.FAILED:
                status_text = "[red]❌ Failed[/red]"
            elif status.phase == CleanupPhase.SKIPPED:
                status_text = "[dim]⏭️  Skipped[/dim]"
            else:
                status_text = "[yellow]⚠️  Incomplete[/yellow]"
            
            # Duration
            duration_str = str(status.duration).split('.')[0] if status.duration else "—"
            
            results_table.add_row(metadata.display_name, status.operator_type, status_text, duration_str)
        
        console.print(results_table)
        console.print()
        console.print(Rule(style="cyan"))
    else:
        # Single operator display
        table = Table(title="🎉 Cleanup Complete", show_header=True, header_style="bold cyan")
        table.add_column("Operator", style="cyan")
        table.add_column("Type", justify="center")
        table.add_column("Status", justify="center")
        table.add_column("Duration", style="green")
        
        for op_key, status in tracker.statuses.items():
            metadata = get_operator_metadata(status.operator)
            
            # Status
            if status.is_successful:
                status_text = "[green]✅ Success[/green]"
            elif status.phase == CleanupPhase.FAILED:
                status_text = "[red]❌ Failed[/red]"
            elif status.phase == CleanupPhase.SKIPPED:
                status_text = "[dim]⏭️  Skipped[/dim]"
            else:
                status_text = "[yellow]⚠️  Incomplete[/yellow]"
            
            # Duration
            duration_str = str(status.duration).split('.')[0] if status.duration else "—"
            
            table.add_row(metadata.display_name, status.operator_type, status_text, duration_str)
        
        console.print()
        console.print(table)
        console.print()
        
        # Summary panel
        success_rate = int(summary["completed"] / summary["total"] * 100) if summary["total"] > 0 else 0
        
        summary_lines = [
            f"[bold]Total Operators:[/bold] {summary['total']}",
            f"[green]Successful:[/green] {summary['completed']}",
            f"[red]Failed:[/red] {summary['failed']}" if summary["failed"] > 0 else f"Failed: {summary['failed']}",
        ]
        
        if summary["skipped"] > 0:
            summary_lines.append(f"[dim]Skipped:[/dim] {summary['skipped']}")
        
        summary_lines.extend([
            "",
            f"[bold]Success Rate:[/bold] {success_rate}%",
            f"[bold]Total Time:[/bold] {total_time_str}"
        ])
        
        if tracker.parallel:
            # Estimate time saved
            sequential_time = sum(
                (s.duration.total_seconds() if s.duration else 0)
                for s in tracker.statuses.values()
            )
            time_saved = sequential_time - total_time.total_seconds()
            if time_saved > 0:
                summary_lines.append(f"[yellow]Time Saved (Parallel):[/yellow] ~{int(time_saved)}s")
        
        console.print(Panel(
            "\n".join(summary_lines),
            title="📊 Cleanup Summary",
            border_style="cyan"
        ))
    
    console.print()


# Deployment Cleanup Tracking Classes

class DeploymentCleanupPhase(str, Enum):
    """Phases of deployment CR cleanup."""
    PENDING = "pending"
    PREPARING = "preparing"
    DELETING_CR = "deleting_cr"
    CLEANING_RESOURCES = "cleaning_resources"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class DeploymentCleanupStatus:
    """
    Tracks the cleanup status of a single deployment CR.
    """
    deployment_type: str  # "Content" or "AI Services"
    cr_name: str
    version: str
    phase: DeploymentCleanupPhase = DeploymentCleanupPhase.PENDING
    progress: int = 0  # 0-100
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None
    current_step: Optional[str] = None
    
    @property
    def duration(self) -> Optional[timedelta]:
        """Calculate cleanup duration."""
        if self.start_time:
            end = self.end_time or datetime.now()
            return end - self.start_time
        return None
    
    @property
    def is_complete(self) -> bool:
        """Check if cleanup is complete."""
        return self.phase in [DeploymentCleanupPhase.COMPLETED, DeploymentCleanupPhase.FAILED]
    
    @property
    def is_successful(self) -> bool:
        """Check if cleanup was successful."""
        return self.phase == DeploymentCleanupPhase.COMPLETED
    
    def get_status_icon(self) -> str:
        """Get status icon for current phase."""
        icons = {
            DeploymentCleanupPhase.PENDING: "⏳",
            DeploymentCleanupPhase.PREPARING: "🔧",
            DeploymentCleanupPhase.DELETING_CR: "🗑️",
            DeploymentCleanupPhase.CLEANING_RESOURCES: "🧹",
            DeploymentCleanupPhase.VERIFYING: "🔍",
            DeploymentCleanupPhase.COMPLETED: "✅",
            DeploymentCleanupPhase.FAILED: "❌"
        }
        return icons.get(self.phase, "❓")
    
    def get_status_color(self) -> str:
        """Get color for current phase."""
        colors = {
            DeploymentCleanupPhase.PENDING: "dim",
            DeploymentCleanupPhase.PREPARING: "yellow",
            DeploymentCleanupPhase.DELETING_CR: "cyan",
            DeploymentCleanupPhase.CLEANING_RESOURCES: "cyan",
            DeploymentCleanupPhase.VERIFYING: "blue",
            DeploymentCleanupPhase.COMPLETED: "green",
            DeploymentCleanupPhase.FAILED: "red"
        }
        return colors.get(self.phase, "white")


class DeploymentCleanupTracker:
    """
    Tracks cleanup progress for multiple deployment CRs with live updates.
    """
    
    def __init__(
        self,
        deployments: Dict[str, Dict],  # deployment_key -> deployment_info
        console: Optional[Console] = None,
        parallel: bool = False
    ):
        """
        Initialize the deployment cleanup tracker.
        
        Args:
            deployments: Dictionary of deployments to track (key -> info dict)
            console: Rich console for output
            parallel: Whether cleanup is parallel
        """
        self.console = console or Console()
        self.parallel = parallel
        self.deployments = deployments
        self.statuses: Dict[str, DeploymentCleanupStatus] = {}
        self.overall_start_time = datetime.now()
        self.overall_end_time: Optional[datetime] = None
        
        # Initialize status for each deployment
        for dep_key, dep_info in deployments.items():
            self.statuses[dep_key] = DeploymentCleanupStatus(
                deployment_type=dep_info.get("type", "Unknown"),
                cr_name=dep_info.get("cr_name", "unknown"),
                version=dep_info.get("version", "Unknown")
            )
    
    def start_deployment(self, deployment_key: str) -> None:
        """Mark deployment cleanup as started."""
        if deployment_key in self.statuses:
            self.statuses[deployment_key].phase = DeploymentCleanupPhase.PREPARING
            self.statuses[deployment_key].start_time = datetime.now()
    
    def update_deployment(
        self,
        deployment_key: str,
        phase: Optional[DeploymentCleanupPhase] = None,
        step: Optional[str] = None,
        progress: Optional[int] = None,
        error: Optional[str] = None
    ) -> None:
        """Update deployment cleanup status."""
        if deployment_key not in self.statuses:
            return
        
        status = self.statuses[deployment_key]
        
        if phase:
            status.phase = phase
        
        if step:
            status.current_step = step
        
        if progress is not None:
            status.progress = min(100, max(0, progress))
        
        if error:
            status.error_message = error
            status.phase = DeploymentCleanupPhase.FAILED
    
    def complete_deployment(
        self,
        deployment_key: str,
        success: bool = True,
        error: Optional[str] = None
    ) -> None:
        """Mark deployment cleanup as complete."""
        if deployment_key in self.statuses:
            status = self.statuses[deployment_key]
            status.phase = DeploymentCleanupPhase.COMPLETED if success else DeploymentCleanupPhase.FAILED
            status.progress = 100 if success else status.progress
            status.end_time = datetime.now()
            if error:
                status.error_message = error
    
    def is_complete(self) -> bool:
        """Check if all deployments are complete."""
        return all(status.is_complete for status in self.statuses.values())
    
    def get_summary(self) -> Dict[str, int]:
        """Get cleanup summary statistics."""
        return {
            "total": len(self.statuses),
            "completed": sum(1 for s in self.statuses.values() if s.phase == DeploymentCleanupPhase.COMPLETED),
            "failed": sum(1 for s in self.statuses.values() if s.phase == DeploymentCleanupPhase.FAILED),
            "in_progress": sum(1 for s in self.statuses.values()
                             if s.phase in [DeploymentCleanupPhase.PREPARING,
                                          DeploymentCleanupPhase.DELETING_CR,
                                          DeploymentCleanupPhase.CLEANING_RESOURCES,
                                          DeploymentCleanupPhase.VERIFYING]),
            "pending": sum(1 for s in self.statuses.values() if s.phase == DeploymentCleanupPhase.PENDING)
        }
    
    def create_progress_display(self) -> Panel:
        """Create the main progress display."""
        if len(self.deployments) > 1:
            return self._create_parallel_display()
        else:
            return self._create_single_display()
    
    def _create_parallel_display(self) -> Panel:
        """Create parallel deployment cleanup display."""
        from rich.columns import Columns
        
        mode_label = "⚡ Parallel Cleanup" if self.parallel else "🧹 Multi-Deployment Cleanup"
        
        # Create individual deployment cards
        deployment_cards = []
        for dep_key in self.deployments.keys():
            status = self.statuses[dep_key]
            
            # Build compact deployment card
            card_content = []
            
            # Deployment name with icon
            icon = status.get_status_icon()
            color = status.get_status_color()
            name_text = Text()
            name_text.append(f"{icon} {status.deployment_type}", style=f"bold {color}")
            card_content.append(name_text)
            
            # CR name
            cr_text = Text()
            cr_text.append(f"{status.cr_name}", style="dim")
            card_content.append(cr_text)
            
            # Progress bar
            bar_text = Text()
            if status.is_complete:
                if status.is_successful:
                    bar_text.append("━" * 20, style="green")
                else:
                    bar_text.append("━" * 20, style="red")
            else:
                filled = int(status.progress / 100 * 20)
                bar_text.append("━" * filled, style="cyan")
                bar_text.append("━" * (20 - filled), style="dim")
            card_content.append(bar_text)
            
            # Status and progress
            status_text = Text()
            status_text.append(status.phase.value.replace('_', ' ').title(), style=color)
            status_text.append(" • ")
            status_text.append(f"{status.progress}%")
            card_content.append(status_text)
            
            # Current step or duration
            step_text = Text()
            if status.current_step and not status.is_complete:
                step_text.append(status.current_step, style="dim")
            elif status.duration:
                duration_str = str(status.duration).split('.')[0]
                step_text.append(duration_str, style="dim")
            else:
                step_text.append("")
            card_content.append(step_text)
            
            # Create panel for this deployment
            deployment_panel = Panel(
                Group(*card_content),
                border_style=color,
                padding=(0, 1),
                width=28
            )
            deployment_cards.append(deployment_panel)
        
        # Arrange deployments in columns
        columns = Columns(deployment_cards, equal=True, expand=True)
        
        # Overall status
        summary = self.get_summary()
        elapsed = datetime.now() - self.overall_start_time
        elapsed_str = str(elapsed).split('.')[0]
        
        status_text = Text(justify="center")
        status_text.append(f"{summary['completed']}/{summary['total']} Complete")
        status_text.append(" • ")
        status_text.append(elapsed_str)
        
        # Combine into main panel
        content = Group(
            columns,
            Text(""),
            status_text
        )
        
        return Panel(
            content,
            title=f"🧹 {mode_label}",
            border_style="cyan",
            padding=(1, 2)
        )
    
    def _create_single_display(self) -> Panel:
        """Create single deployment cleanup display."""
        dep_key = list(self.deployments.keys())[0]
        status = self.statuses[dep_key]
        
        # Create progress table
        table = Table(show_header=True, header_style="bold cyan", box=None)
        table.add_column("Deployment", style="cyan", width=20)
        table.add_column("CR Name", style="white", width=25)
        table.add_column("Status", justify="center", width=15)
        table.add_column("Progress", width=30)
        table.add_column("Step", style="yellow", width=25)
        
        # Status with icon
        status_text = f"{status.get_status_icon()} {status.phase.value.replace('_', ' ').title()}"
        status_colored = f"[{status.get_status_color()}]{status_text}[/{status.get_status_color()}]"
        
        # Progress bar
        if status.is_complete:
            if status.is_successful:
                progress_bar = "[green]" + "█" * 30 + "[/green]"
            else:
                progress_bar = "[red]" + "█" * 30 + "[/red]"
        else:
            filled = int(status.progress / 100 * 30)
            progress_bar = "[cyan]" + "█" * filled + "[/cyan]" + "░" * (30 - filled)
        progress_text = f"{progress_bar} {status.progress}%"
        
        # Current step
        step_text = status.current_step if status.current_step else "—"
        
        table.add_row(
            status.deployment_type,
            status.cr_name,
            status_colored,
            progress_text,
            step_text
        )
        
        # Overall status
        elapsed = datetime.now() - self.overall_start_time
        elapsed_str = str(elapsed).split('.')[0]
        
        content = Group(
            table,
            Text(""),
            Text(f"Elapsed Time: {elapsed_str}", justify="center", style="dim")
        )
        
        return Panel(
            content,
            title="🧹 Deployment Cleanup Progress",
            border_style="cyan",
            padding=(1, 2)
        )


def display_deployment_cleanup_complete(
    tracker: DeploymentCleanupTracker,
    console: Optional[Console] = None
) -> None:
    """
    Display final deployment cleanup summary.
    
    Args:
        tracker: Deployment cleanup tracker with final status
        console: Rich console for output
    """
    console = console or Console()
    summary = tracker.get_summary()
    
    # Calculate total time
    if tracker.overall_end_time:
        total_time = tracker.overall_end_time - tracker.overall_start_time
    else:
        total_time = datetime.now() - tracker.overall_start_time
    
    total_time_str = str(total_time).split('.')[0]
    
    # Create completion display
    if len(tracker.deployments) > 1:
        from rich.rule import Rule
        
        # Display header
        console.print()
        console.print(Rule(f"[bold cyan]🎉 Deployment Cleanup Complete[/bold cyan]", style="cyan"))
        console.print()
        
        # Display summary
        mode_label = "⚡ Parallel Cleanup" if tracker.parallel else "🧹 Multi-Deployment Cleanup"
        console.print(f"  [bold cyan]{mode_label} Complete[/bold cyan]")
        console.print()
        console.print(f"  [green]✓[/green] {summary['completed']}/{summary['total']} deployments cleaned successfully")
        console.print(f"  [cyan]⏱[/cyan]  Total time: {total_time_str}")
        
        if summary["failed"] > 0:
            console.print(f"  [red]✗[/red] {summary['failed']} failed")
        
        console.print()
        console.print(Rule("[bold cyan]Deployment Status[/bold cyan]", style="cyan"))
        console.print()
        
        # Create results table
        results_table = Table(
            show_header=True,
            header_style="bold cyan",
            box=None,
            padding=(0, 2),
            show_edge=False
        )
        results_table.add_column("Deployment", style="cyan", width=20)
        results_table.add_column("CR Name", style="white", width=25)
        results_table.add_column("Status", justify="center", width=15)
        results_table.add_column("Duration", style="green", width=12)
        
        for dep_key, status in tracker.statuses.items():
            # Status with icon
            if status.is_successful:
                status_text = "[green]✅ Success[/green]"
            elif status.phase == DeploymentCleanupPhase.FAILED:
                status_text = "[red]❌ Failed[/red]"
            else:
                status_text = "[yellow]⚠️  Incomplete[/yellow]"
            
            # Duration
            duration_str = str(status.duration).split('.')[0] if status.duration else "—"
            
            results_table.add_row(status.deployment_type, status.cr_name, status_text, duration_str)
        
        console.print(results_table)
        console.print()
        console.print(Rule(style="cyan"))
    else:
        # Single deployment display
        table = Table(title="🎉 Deployment Cleanup Complete", show_header=True, header_style="bold cyan")
        table.add_column("Deployment", style="cyan")
        table.add_column("CR Name", style="white")
        table.add_column("Status", justify="center")
        table.add_column("Duration", style="green")
        
        for dep_key, status in tracker.statuses.items():
            # Status
            if status.is_successful:
                status_text = "[green]✅ Success[/green]"
            elif status.phase == DeploymentCleanupPhase.FAILED:
                status_text = "[red]❌ Failed[/red]"
            else:
                status_text = "[yellow]⚠️  Incomplete[/yellow]"
            
            # Duration
            duration_str = str(status.duration).split('.')[0] if status.duration else "—"
            
            table.add_row(status.deployment_type, status.cr_name, status_text, duration_str)
        
        console.print()
        console.print(table)
        console.print()
        
        # Summary panel
        success_rate = int(summary["completed"] / summary["total"] * 100) if summary["total"] > 0 else 0
        
        summary_lines = [
            f"[bold]Total Deployments:[/bold] {summary['total']}",
            f"[green]Successful:[/green] {summary['completed']}",
            f"[red]Failed:[/red] {summary['failed']}" if summary["failed"] > 0 else f"Failed: {summary['failed']}",
            "",
            f"[bold]Success Rate:[/bold] {success_rate}%",
            f"[bold]Total Time:[/bold] {total_time_str}"
        ]
        
        console.print(Panel(
            "\n".join(summary_lines),
            title="📊 Cleanup Summary",
            border_style="cyan"
        ))
    
    console.print()


# Made with Bob