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
Deployment Progress Tracking Module

This module provides comprehensive progress tracking and visualization for
multi-operator deployments with live updates and detailed status information.
"""

import signal
import sys
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


class DeploymentPhase(str, Enum):
    """Phases of operator deployment."""
    PENDING = "pending"
    PREPARING = "preparing"
    DEPLOYING = "deploying"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class DeploymentStep(str, Enum):
    """Individual steps within deployment."""
    OLM_CLEANUP = "olm_cleanup"  # Cleanup OLM resources before Helm upgrade
    NAMESPACE_SETUP = "namespace_setup"
    SECRET_CREATION = "secret_creation"
    CRD_DEPLOYMENT = "crd_deployment"
    RBAC_SETUP = "rbac_setup"
    OPERATOR_DEPLOYMENT = "operator_deployment"
    HEALTH_CHECK = "health_check"
    # OLM-specific steps
    CATALOG_SOURCE = "catalog_source"
    OPERATOR_GROUP = "operator_group"
    SUBSCRIPTION = "subscription"


@dataclass
class OperatorDeploymentStatus:
    """
    Tracks the deployment status of a single operator.
    """
    operator: OperatorType
    phase: DeploymentPhase = DeploymentPhase.PENDING
    current_step: Optional[DeploymentStep] = None
    progress: int = 0  # 0-100
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None
    error_details: Optional[Dict] = None  # Full error details including helm logs
    steps_completed: List[DeploymentStep] = field(default_factory=list)
    steps_total: int = 6  # Total number of deployment steps
    
    @property
    def duration(self) -> Optional[timedelta]:
        """Calculate deployment duration."""
        if self.start_time:
            end = self.end_time or datetime.now()
            return end - self.start_time
        return None
    
    @property
    def is_complete(self) -> bool:
        """Check if deployment is complete."""
        return self.phase in [DeploymentPhase.COMPLETED, DeploymentPhase.FAILED, DeploymentPhase.SKIPPED]
    
    @property
    def is_successful(self) -> bool:
        """Check if deployment was successful."""
        return self.phase == DeploymentPhase.COMPLETED
    
    def get_status_icon(self) -> str:
        """Get status icon for current phase."""
        icons = {
            DeploymentPhase.PENDING: "⏳",
            DeploymentPhase.PREPARING: "🔧",
            DeploymentPhase.DEPLOYING: "🚀",
            DeploymentPhase.VERIFYING: "🔍",
            DeploymentPhase.COMPLETED: "✅",
            DeploymentPhase.FAILED: "❌",
            DeploymentPhase.SKIPPED: "⏭️"
        }
        return icons.get(self.phase, "❓")
    
    def get_status_color(self) -> str:
        """Get color for current phase."""
        colors = {
            DeploymentPhase.PENDING: "dim",
            DeploymentPhase.PREPARING: "yellow",
            DeploymentPhase.DEPLOYING: "cyan",
            DeploymentPhase.VERIFYING: "blue",
            DeploymentPhase.COMPLETED: "green",
            DeploymentPhase.FAILED: "red",
            DeploymentPhase.SKIPPED: "dim"
        }
        return colors.get(self.phase, "white")


@dataclass
class SharedClusterSetupStatus:
    """
    Tracks shared cluster setup progress that runs once before operator deployment.
    """
    phase: DeploymentPhase = DeploymentPhase.PENDING
    current_task: str = "Waiting to start"
    completed_tasks: List[str] = field(default_factory=list)
    pending_tasks: List[str] = field(default_factory=lambda: [
        "Create or verify namespace",
        "Create image pull secret",
        "Apply shared cluster prerequisites"
    ])
    progress: int = 0


class MultiOperatorDeploymentTracker:
    """
    Tracks deployment progress for multiple operators with live updates.
    """
    
    def __init__(
        self,
        operators: List[OperatorType],
        console: Optional[Console] = None,
        parallel: bool = False
    ):
        """
        Initialize the deployment tracker.
        
        Args:
            operators: List of operators to track
            console: Rich console for output
            parallel: Whether deployment is parallel
        """
        self.console = console or Console()
        self.parallel = parallel
        self.operators = operators
        self.statuses: Dict[OperatorType, OperatorDeploymentStatus] = {}
        self.overall_start_time = datetime.now()
        self.overall_end_time: Optional[datetime] = None
        self.cluster_setup = SharedClusterSetupStatus()
        
        # Initialize status for each operator
        for op in operators:
            self.statuses[op] = OperatorDeploymentStatus(operator=op)
    
    def start_operator(self, operator: OperatorType) -> None:
        """Mark operator deployment as started."""
        if operator in self.statuses:
            self.statuses[operator].phase = DeploymentPhase.PREPARING
            self.statuses[operator].start_time = datetime.now()
    
    def update_operator(
        self,
        operator: OperatorType,
        phase: Optional[DeploymentPhase] = None,
        step: Optional[DeploymentStep] = None,
        progress: Optional[int] = None,
        error: Optional[str] = None
    ) -> None:
        """Update operator deployment status."""
        if operator not in self.statuses:
            return
        
        status = self.statuses[operator]
        
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
            status.phase = DeploymentPhase.FAILED
    
    def complete_operator(
        self,
        operator: OperatorType,
        success: bool = True,
        error: Optional[str] = None,
        error_details: Optional[Dict] = None
    ) -> None:
        """Mark operator deployment as complete."""
        if operator in self.statuses:
            status = self.statuses[operator]
            status.phase = DeploymentPhase.COMPLETED if success else DeploymentPhase.FAILED
            status.progress = 100 if success else status.progress
            status.end_time = datetime.now()
            if error:
                status.error_message = error
            if error_details:
                status.error_details = error_details
    
    def skip_operator(self, operator: OperatorType, reason: str) -> None:
        """Mark operator as skipped."""
        if operator in self.statuses:
            self.statuses[operator].phase = DeploymentPhase.SKIPPED
            self.statuses[operator].error_message = reason
    
    def is_complete(self) -> bool:
        """Check if all operators are complete."""
        return all(status.is_complete for status in self.statuses.values())
    
    def get_summary(self) -> Dict[str, int]:
        """Get deployment summary statistics."""
        return {
            "total": len(self.statuses),
            "completed": sum(1 for s in self.statuses.values() if s.phase == DeploymentPhase.COMPLETED),
            "failed": sum(1 for s in self.statuses.values() if s.phase == DeploymentPhase.FAILED),
            "in_progress": sum(1 for s in self.statuses.values() 
                             if s.phase in [DeploymentPhase.PREPARING, DeploymentPhase.DEPLOYING, DeploymentPhase.VERIFYING]),
            "pending": sum(1 for s in self.statuses.values() if s.phase == DeploymentPhase.PENDING),
            "skipped": sum(1 for s in self.statuses.values() if s.phase == DeploymentPhase.SKIPPED)
        }
    
    def update_cluster_setup(
        self,
        task_name: str,
        progress: int,
        phase: DeploymentPhase = DeploymentPhase.PREPARING,
        completed: bool = False
    ) -> None:
        """Update shared cluster setup progress."""
        self.cluster_setup.phase = phase
        self.cluster_setup.current_task = task_name
        self.cluster_setup.progress = min(100, max(0, progress))

        if completed:
            if task_name not in self.cluster_setup.completed_tasks:
                self.cluster_setup.completed_tasks.append(task_name)
            if task_name in self.cluster_setup.pending_tasks:
                self.cluster_setup.pending_tasks.remove(task_name)

    def complete_cluster_setup(self) -> None:
        """Mark shared cluster setup as complete."""
        self.cluster_setup.phase = DeploymentPhase.COMPLETED
        self.cluster_setup.current_task = "Shared cluster setup complete"
        self.cluster_setup.progress = 100
        for task_name in list(self.cluster_setup.pending_tasks):
            if task_name not in self.cluster_setup.completed_tasks:
                self.cluster_setup.completed_tasks.append(task_name)
        self.cluster_setup.pending_tasks.clear()

    def create_progress_display(self):
        """Create the main progress display with sleek, minimal design for parallel deployment."""
        # Use parallel display for any multi-operator deployment (2+ operators)
        if len(self.operators) > 1:
            return self._create_parallel_display()
        else:
            return self._create_sequential_display()
    
    def _create_parallel_display(self) -> Panel:
        """Create sleek parallel deployment display showing operators side-by-side."""
        from rich.columns import Columns
        
        # Determine deployment mode label
        mode_label = "⚡ Parallel Deployment" if self.parallel else "📦 Multi-Operator Deployment"
        
        # Create cluster setup section (without its own panel to avoid double borders)
        cluster_content = self._create_cluster_setup_content()
        
        # Create individual operator cards
        operator_cards = []
        for operator in self.operators:
            status = self.statuses[operator]
            metadata = get_operator_metadata(operator)
            
            # Build compact operator card with Rich Text objects for proper rendering
            card_content = []
            
            # Operator name with icon
            icon = status.get_status_icon()
            color = status.get_status_color()
            name_text = Text()
            name_text.append(f"{icon} {metadata.display_name}", style=f"bold {color}")
            card_content.append(name_text)
            
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
                    "namespace_setup": "Namespace Setup",
                    "secret_creation": "Secret Creation",
                    "crd_deployment": "CRD Deployment",
                    "rbac_setup": "RBAC Setup",
                    "operator_deployment": "Operator Deployment",
                    "health_check": "Health Check",
                    "catalog_source": "Applying Catalog Source",
                    "operator_group": "Creating Operator Group",
                    "subscription": "Creating Subscription"
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
        # This ensures the Live display completely replaces the previous content
        content = Group(
            cluster_content,
            Text(""),
            columns,
            Text(""),
            status_text
        )
        
        # Return a fresh Panel instance each time to ensure proper replacement
        return Panel(
            content,
            title=f"🚀 {mode_label}",
            border_style="cyan",
            padding=(1, 2)
        )
    
    def _create_cluster_setup_content(self) -> Group:
        """Create content for shared cluster setup (without wrapping panel)."""
        status = self.cluster_setup

        body = []
        
        # Title as part of content
        title_text = Text()
        title_text.append("🔧 Shared Cluster Setup", style="bold cyan")
        body.append(title_text)
        
        # Status summary
        summary = Text()
        summary.append(status.phase.value.title(), style="bold yellow" if status.phase != DeploymentPhase.COMPLETED else "bold green")
        summary.append(" • ")
        summary.append(f"{status.progress}%")
        body.append(summary)

        # Current task
        current = Text()
        current.append("Current: ", style="bold white")
        current.append(status.current_task, style="cyan" if status.phase != DeploymentPhase.COMPLETED else "green")
        body.append(current)

        body.append(Text(""))

        # Completed tasks
        for task_name in status.completed_tasks:
            completed_text = Text()
            completed_text.append("✅ ", style="green")
            completed_text.append(task_name, style="green")
            body.append(completed_text)

        # Pending tasks
        for task_name in status.pending_tasks:
            pending_text = Text()
            pending_text.append("⏳ ", style="yellow")
            pending_text.append(task_name, style="dim")
            body.append(pending_text)

        return Group(*body)
    
    def _create_cluster_setup_panel(self) -> Panel:
        """Create live panel for shared cluster setup tasks (legacy method for compatibility)."""
        status = self.cluster_setup
        border_style = "green" if status.phase == DeploymentPhase.COMPLETED else "cyan"
        
        title_text = Text()
        title_text.append("🔧 Shared Cluster Setup", style="bold cyan")

        return Panel(
            self._create_cluster_setup_content(),
            title=title_text,
            border_style=border_style,
            padding=(0, 1)
        )

    def _create_sequential_display(self) -> Panel:
        """Create sequential deployment display (original layout)."""
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
        title = f"🚀 Multi-Operator Deployment ({mode} Mode)"
        
        content = f"[bold]Elapsed Time:[/bold] {elapsed_str}"
        
        return Panel(content, title=title, border_style="cyan")
    
    def _create_operator_progress(self) -> Panel:
        """Create operator progress panel."""
        table = Table(show_header=True, header_style="bold cyan", box=None)
        table.add_column("Operator", style="cyan", width=25)
        table.add_column("Status", justify="center", width=12)
        table.add_column("Progress", width=30)
        table.add_column("Step", style="yellow", width=20)
        table.add_column("Time", style="green", width=10)
        
        for operator in self.operators:
            status = self.statuses[operator]
            metadata = get_operator_metadata(operator)
            
            # Operator name
            name = metadata.display_name
            
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
                # Map step values to user-friendly display names
                step_display_names = {
                    "namespace_setup": "Namespace Setup",
                    "secret_creation": "Secret Creation",
                    "crd_deployment": "CRD Deployment",
                    "rbac_setup": "RBAC Setup",
                    "operator_deployment": "Operator Deployment",
                    "health_check": "Health Check",
                    "catalog_source": "Applying Catalog Source",
                    "operator_group": "Creating Operator Group",
                    "subscription": "Creating Subscription"
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
            
            table.add_row(name, status_colored, progress_text, step_text, duration_str)
        
        return Panel(table, title="📊 Operator Deployment Progress", border_style="blue")
    
    def _create_summary(self) -> Panel:
        """Create summary panel."""
        summary = self.get_summary()
        
        # Create summary table
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Metric", style="bold")
        table.add_column("Count", justify="right")
        
        table.add_row("Total Operators", str(summary["total"]))
        table.add_row("[green]✓ Completed[/green]", f"[green]{summary['completed']}[/green]")

        if summary["failed"] > 0:
            table.add_row("[red]✗ Failed[/red]", f"[red]{summary['failed']}[/red]")

        if summary["in_progress"] > 0:
            table.add_row("[cyan]» In Progress[/cyan]", f"[cyan]{summary['in_progress']}[/cyan]")

        if summary["pending"] > 0:
            table.add_row("[dim]… Pending[/dim]", f"[dim]{summary['pending']}[/dim]")

        if summary["skipped"] > 0:
            table.add_row("[dim]— Skipped[/dim]", f"[dim]{summary['skipped']}[/dim]")
        
        # Add overall progress
        overall_progress = int((summary["completed"] + summary["failed"]) / summary["total"] * 100)
        table.add_row("", "")  # Spacer
        table.add_row("[bold]Overall Progress[/bold]", f"[bold]{overall_progress}%[/bold]")
        
        return Panel(table, title="📈 Deployment Summary", border_style="green")


def create_deployment_progress(
    operators: List[OperatorType],
    parallel: bool = False,
    console: Optional[Console] = None
) -> tuple[MultiOperatorDeploymentTracker, Live]:
    """
    Create a live deployment progress tracker with graceful interrupt handling.
    
    Args:
        operators: List of operators to track
        parallel: Whether deployment is parallel
        console: Rich console for output
        
    Returns:
        Tuple of (tracker, live_display)
    """
    console = console or Console()
    tracker = MultiOperatorDeploymentTracker(operators, console, parallel)
    
    # Create live display with proper signal handling
    # Use screen=True to use alternate screen buffer for clean updates
    # This prevents duplicate headers by ensuring proper terminal management
    # Set auto_refresh=False to prevent background thread from running after stop()
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


def display_deployment_complete(
    tracker: MultiOperatorDeploymentTracker,
    console: Optional[Console] = None
) -> None:
    """
    Display final deployment summary with detailed error information.
    
    Args:
        tracker: Deployment tracker with final status
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
    
    # Collect failed operators for detailed error display
    failed_operators = []
    successful_operators = []
    
    # Create results table (single-operator path, shown via the else branch below)
    table = Table(title="Deployment Complete", show_header=True, header_style="bold cyan")
    table.add_column("Operator", style="cyan", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Duration", style="green")
    table.add_column("Details", style="yellow")

    for operator, status in tracker.statuses.items():
        metadata = get_operator_metadata(operator)

        # Status
        if status.is_successful:
            status_text = "[green]✓ Success[/green]"
            successful_operators.append((operator, status))
        elif status.phase == DeploymentPhase.FAILED:
            status_text = "[red]✗ Failed[/red]"
            failed_operators.append((operator, status))
        elif status.phase == DeploymentPhase.SKIPPED:
            status_text = "[dim]— Skipped[/dim]"
        else:
            status_text = "[yellow]! Incomplete[/yellow]"
        
        # Duration
        if status.duration:
            duration_str = str(status.duration).split('.')[0]
        else:
            duration_str = "—"
        
        # Details
        if status.error_message:
            details = status.error_message[:50]
        elif status.is_successful:
            details = f"{len(status.steps_completed)}/{status.steps_total} steps"
        else:
            details = "—"
        
        table.add_row(metadata.display_name, status_text, duration_str, details)
    
    console.print()
    
    # Create sleek completion display for multi-operator deployments (2+ operators)
    if len(tracker.operators) > 1:
        from rich.rule import Rule
        
        # Calculate time saved
        sequential_time = sum(
            (s.duration.total_seconds() if s.duration else 0)
            for s in tracker.statuses.values()
        )
        time_saved = sequential_time - total_time.total_seconds()
        
        # Determine completion title based on deployment mode
        if tracker.parallel:
            completion_title = "⚡ Parallel Deployment Complete"
        else:
            completion_title = "📦 Multi-Operator Deployment Complete"
        
        # Display header with rule
        console.print()
        console.print(Rule(f"[bold cyan]🎉 Deployment Complete[/bold cyan]", style="cyan"))
        console.print()
        
        # Display summary statistics
        console.print(f"  [bold cyan]{completion_title}[/bold cyan]")
        console.print()
        console.print(f"  [green]✓[/green] {summary['completed']}/{summary['total']} operators deployed successfully")
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
        results_table.add_column("Operator", style="cyan", min_width=32, no_wrap=True)
        results_table.add_column("Status", justify="center", width=12)
        results_table.add_column("Duration", style="green", width=12)

        for operator, status in tracker.statuses.items():
            metadata = get_operator_metadata(operator)

            # Status with icon (text-only to avoid double-width glyph misalignment)
            if status.is_successful:
                status_text = "[green]✓ Success[/green]"
            elif status.phase == DeploymentPhase.FAILED:
                status_text = "[red]✗ Failed[/red]"
            elif status.phase == DeploymentPhase.SKIPPED:
                status_text = "[dim]— Skipped[/dim]"
            else:
                status_text = "[yellow]! Incomplete[/yellow]"
            
            # Duration
            duration_str = str(status.duration).split('.')[0] if status.duration else "—"
            
            results_table.add_row(metadata.display_name, status_text, duration_str)
        
        console.print(results_table)
        console.print()
        console.print(Rule(style="cyan"))
    else:
        # Original sequential display
        console.print(table)
        console.print()
        
        # Summary panel
        success_rate = int(summary["completed"] / summary["total"] * 100) if summary["total"] > 0 else 0
        
        summary_lines = [
            f"[bold]Total Operators:[/bold] {summary['total']}",
            f"[green]Successful:[/green] {summary['completed']}",
        ]
        
        if summary["failed"] > 0:
            summary_lines.append(f"[red]Failed:[/red] {summary['failed']}")
        
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
            title="📊 Deployment Summary",
            border_style="cyan"
        ))
    
    # Display detailed error information for failed operators
    if failed_operators:
        console.print()
        from rich.rule import Rule
        
        # Determine if this is a partial failure or complete failure
        if successful_operators:
            console.print(Rule("[bold yellow]Partial Deployment Failure[/bold yellow]", style="yellow"))
            console.print()
            console.print(f"  [yellow]⚠[/yellow]  {len(successful_operators)} operator(s) deployed successfully")
            console.print(f"  [red]✗[/red] {len(failed_operators)} operator(s) failed to deploy")
        else:
            console.print(Rule("[bold red]❌ Deployment Failed[/bold red]", style="red"))
            console.print()
            console.print(f"  [red]✗[/red] All {len(failed_operators)} operator(s) failed to deploy")
        
        console.print()
        console.print(Rule("[bold red]Error Details[/bold red]", style="red"))
        
        # Display detailed error for each failed operator
        for operator, status in failed_operators:
            metadata = get_operator_metadata(operator)
            console.print()
            
            # Operator header
            console.print(f"[bold red]❌ {metadata.display_name}[/bold red]")
            console.print()
            
            # Error message
            if status.error_message:
                console.print(f"  [yellow]Error:[/yellow] {status.error_message}")
            
            # Detailed helm logs if available
            if status.error_details:
                details = status.error_details
                
                # Show helm command that failed
                if 'command' in details:
                    console.print()
                    console.print(f"  [cyan]Command:[/cyan]")
                    console.print(f"    [dim]{details['command']}[/dim]")
                
                # Show exit code
                if 'exit_code' in details:
                    console.print()
                    console.print(f"  [cyan]Exit Code:[/cyan] {details['exit_code']}")
                
                # Show stderr (most important for debugging)
                if 'stderr' in details and details['stderr']:
                    console.print()
                    console.print(f"  [cyan]Helm Error Output:[/cyan]")
                    # Limit stderr to last 15 lines to keep it readable
                    stderr_lines = details['stderr'].strip().split('\n')
                    display_lines = stderr_lines[-15:] if len(stderr_lines) > 15 else stderr_lines
                    for line in display_lines:
                        if line.strip():
                            console.print(f"    [red]{line}[/red]")
                
                # Show stdout if available and contains useful info
                if 'stdout' in details and details['stdout']:
                    stdout_lines = details['stdout'].strip().split('\n')
                    # Only show stdout if it has meaningful content
                    meaningful_lines = [l for l in stdout_lines if l.strip() and not l.startswith('NAME:')]
                    if meaningful_lines:
                        console.print()
                        console.print(f"  [cyan]Additional Output:[/cyan]")
                        display_lines = meaningful_lines[-10:] if len(meaningful_lines) > 10 else meaningful_lines
                        for line in display_lines:
                            console.print(f"    [dim]{line}[/dim]")
            
            console.print()
            console.print("  [yellow]💡 Troubleshooting:[/yellow]")
            console.print("    • Check the full logs in deployoperator.log for complete error details")
            console.print("    • Verify cluster connectivity and permissions")
            console.print("    • Ensure all prerequisites are met (CRDs, RBAC, secrets)")
            console.print("    • Review the helm command and values used")
        
        console.print()
        console.print(Rule(style="red"))
    
    console.print()

# Made with Bob
