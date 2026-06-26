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
Image Push Progress Tracking Module

This module provides comprehensive progress tracking and visualization for
multi-threaded image push operations with live updates and detailed status information.
"""

import logging
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class ImagePushStatus(str, Enum):
    """Status of individual image push operations."""
    PENDING = "pending"
    COPYING = "copying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ImagePushInfo:
    """
    Tracks the push status of a single image.
    """
    image_name: str
    source_image: str
    dest_image: str
    status: ImagePushStatus = ImagePushStatus.PENDING
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None
    current_message: str = "Queued"
    
    @property
    def duration(self) -> Optional[timedelta]:
        """Calculate push duration."""
        if self.start_time:
            end = self.end_time or datetime.now()
            return end - self.start_time
        return None
    
    @property
    def is_complete(self) -> bool:
        """Check if push is complete."""
        return self.status in [ImagePushStatus.COMPLETED, ImagePushStatus.FAILED, ImagePushStatus.CANCELLED]
    
    @property
    def is_successful(self) -> bool:
        """Check if push was successful."""
        return self.status == ImagePushStatus.COMPLETED
    
    def get_status_icon(self) -> str:
        """Get status icon for current status."""
        icons = {
            ImagePushStatus.PENDING: "⏳",
            ImagePushStatus.COPYING: "🔄",
            ImagePushStatus.COMPLETED: "✅",
            ImagePushStatus.FAILED: "❌",
            ImagePushStatus.CANCELLED: "⚠️"
        }
        return icons.get(self.status, "❓")
    
    def get_status_color(self) -> str:
        """Get color for current status."""
        colors = {
            ImagePushStatus.PENDING: "dim",
            ImagePushStatus.COPYING: "cyan",
            ImagePushStatus.COMPLETED: "green",
            ImagePushStatus.FAILED: "red",
            ImagePushStatus.CANCELLED: "yellow"
        }
        return colors.get(self.status, "white")


class ImagePushTracker:
    """
    Tracks image push progress with live updates and multi-threading support.
    """
    
    def __init__(
        self,
        images: List[Tuple[str, str, str]],
        console: Optional[Console] = None,
        max_workers: int = 4,
        tls_verify: bool = False,
        logger = None
    ):
        """
        Initialize the image push tracker.
        
        Args:
            images: List of (image_name, source_image, dest_image) tuples
            console: Rich console for output
            max_workers: Maximum number of concurrent image copies
            tls_verify: Whether to verify TLS certificates
            logger: Logger instance for file logging
        """
        self.console = console or Console()
        self.max_workers = min(max_workers, len(images))
        self.tls_verify = tls_verify
        self.logger = logger
        # Get file handler for file-only logging
        self.file_handler = None
        if logger:
            for handler in logger.handlers:
                if isinstance(handler, logging.FileHandler):
                    self.file_handler = handler
                    break
        self.images: Dict[int, ImagePushInfo] = {}
        self.overall_start_time = datetime.now()
        self.overall_end_time: Optional[datetime] = None
        
        # Thread-safe structures
        self.shutdown_event = threading.Event()
        self.table_lock = threading.Lock()
        self.active_processes: Dict[int, subprocess.Popen] = {}
        self.process_lock = threading.Lock()
        
        # Output log for displaying skopeo output (keep last 15 lines)
        self.output_log: List[str] = []
        self.output_lock = threading.Lock()
        self.max_output_lines = 15
        
        # Initialize image info
        for idx, (image_name, source_image, dest_image) in enumerate(images):
            self.images[idx] = ImagePushInfo(
                image_name=image_name,
                source_image=source_image,
                dest_image=dest_image
            )
    
    def add_output_line(self, line: str) -> None:
        """Add a line to the output log (thread-safe)."""
        with self.output_lock:
            self.output_log.append(line)
            # Keep only the last N lines
            if len(self.output_log) > self.max_output_lines:
                self.output_log.pop(0)
    
    def start_image(self, index: int) -> None:
        """Mark image push as started."""
        if index in self.images:
            self.images[index].status = ImagePushStatus.COPYING
            self.images[index].start_time = datetime.now()
            self.images[index].current_message = "Starting copy..."
    
    def update_image(
        self,
        index: int,
        status: Optional[ImagePushStatus] = None,
        message: Optional[str] = None,
        error: Optional[str] = None
    ) -> None:
        """Update image push status."""
        if index not in self.images:
            return
        
        image_info = self.images[index]
        
        if status:
            image_info.status = status
        
        if message:
            image_info.current_message = message
        
        if error:
            image_info.error_message = error
            image_info.status = ImagePushStatus.FAILED
    
    def log_to_file_only(self, level: int, message: str) -> None:
        """
        Log message only to file, not to console.
        This prevents log messages from corrupting the live display.
        
        Args:
            level: Logging level (e.g., logging.INFO, logging.ERROR)
            message: Message to log
        """
        if self.logger and self.file_handler:
            # Create a log record manually
            record = self.logger.makeRecord(
                self.logger.name,
                level,
                "(image_push_progress.py)",
                0,
                message,
                (),
                None
            )
            # Send only to file handler
            self.file_handler.emit(record)
    
    def complete_image(
        self,
        index: int,
        success: bool = True,
        error: Optional[str] = None
    ) -> None:
        """Mark image push as complete."""
        if index in self.images:
            image_info = self.images[index]
            image_info.status = ImagePushStatus.COMPLETED if success else ImagePushStatus.FAILED
            image_info.end_time = datetime.now()
            if error:
                image_info.error_message = error
            image_info.current_message = "Complete" if success else f"Failed: {error}"
    
    def cancel_image(self, index: int) -> None:
        """Mark image as cancelled."""
        if index in self.images:
            self.images[index].status = ImagePushStatus.CANCELLED
            self.images[index].current_message = "Cancelled"
    
    def is_complete(self) -> bool:
        """Check if all images are complete."""
        return all(img.is_complete for img in self.images.values())
    
    def get_summary(self) -> Dict[str, int]:
        """Get push summary statistics."""
        return {
            "total": len(self.images),
            "completed": sum(1 for img in self.images.values() if img.status == ImagePushStatus.COMPLETED),
            "failed": sum(1 for img in self.images.values() if img.status == ImagePushStatus.FAILED),
            "copying": sum(1 for img in self.images.values() if img.status == ImagePushStatus.COPYING),
            "pending": sum(1 for img in self.images.values() if img.status == ImagePushStatus.PENDING),
            "cancelled": sum(1 for img in self.images.values() if img.status == ImagePushStatus.CANCELLED)
        }
    
    def create_progress_display(self) -> Panel:
        """
        Create the main progress display with live updates including skopeo output.
        Wrapped in error handling to prevent display corruption.
        """
        try:
            summary = self.get_summary()
            elapsed = datetime.now() - self.overall_start_time
            elapsed_str = str(elapsed).split('.')[0]
            
            # Create progress table
            table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
            table.add_column("Image", style="cyan", width=35, no_wrap=True)
            table.add_column("Status", justify="center", width=15)
            table.add_column("Duration", style="dim", width=10)
            
            # Add rows for each image
            for idx in sorted(self.images.keys()):
                img = self.images[idx]
                
                # Truncate long image names
                display_name = img.image_name
                if len(display_name) > 33:
                    display_name = display_name[:30] + "..."
                
                # Status with icon and color
                status_text = Text()
                status_text.append(f"{img.get_status_icon()} ", style=img.get_status_color())
                status_text.append(img.status.value.title(), style=img.get_status_color())
                
                # Duration
                if img.is_complete and img.duration:
                    duration_str = str(img.duration).split('.')[0]
                elif img.status == ImagePushStatus.COPYING and img.start_time:
                    current_duration = datetime.now() - img.start_time
                    duration_str = str(current_duration).split('.')[0]
                else:
                    duration_str = "—"
                
                table.add_row(display_name, status_text, duration_str)
            
            # Overall status
            status_text = Text(justify="center")
            status_text.append(f"{summary['completed']}/{summary['total']} Complete")
            status_text.append(" • ")
            status_text.append(f"{summary['copying']} Copying")
            if summary['failed'] > 0:
                status_text.append(" • ")
                status_text.append(f"{summary['failed']} Failed", style="red")
            status_text.append(" • ")
            status_text.append(elapsed_str)
            
            # Create output log section
            output_section = []
            output_section.append(Text(""))
            output_section.append(Text("─" * 60, style="dim"))
            output_section.append(Text("Skopeo Output:", style="bold yellow"))
            
            with self.output_lock:
                if self.output_log:
                    for line in self.output_log:
                        output_section.append(Text(line, style="dim"))
                else:
                    output_section.append(Text("Waiting for output...", style="dim italic"))
            
            # Combine into panel
            content = Group(
                table,
                Text(""),
                status_text,
                *output_section
            )
            
            return Panel(
                content,
                title="🚀 Image Push Progress",
                border_style="cyan",
                padding=(1, 2)
            )
        
        except Exception as e:
            # If display creation fails, return a simple error panel
            # This prevents the entire UI from breaking
            # Log to file only to avoid breaking the live display
            self.log_to_file_only(logging.ERROR, f"Error creating progress display: {e}")
            
            return Panel(
                Text(f"Display Error: {str(e)}\nImage push continues in background...", style="yellow"),
                title="⚠ Display Issue",
                border_style="yellow"
            )
    
    def copy_image_with_skopeo(
        self,
        index: int,
        source_image: str,
        dest_image: str
    ) -> bool:
        """
        Copy a single image using skopeo with real-time progress updates.
        Streams skopeo output directly to console for full visibility.
        
        Args:
            index: Image index
            source_image: Source image path
            dest_image: Destination image path
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Check for shutdown before starting
            if self.shutdown_event.is_set():
                self.cancel_image(index)
                return False
            
            # Mark as started
            self.start_image(index)
            
            img = self.images[index]
            
            # Add header to output log
            self.add_output_line(f"→ Copying {img.image_name}")
            self.add_output_line(f"  From: {source_image}")
            self.add_output_line(f"  To:   {dest_image}")
            
            # Build skopeo command
            # The tls_verify flag controls TLS verification for the DESTINATION (private registry)
            # Source registry (IBM's public registry) should always use TLS verification
            # Note: We need both --src-tls-verify and --dest-tls-verify flags
            # The order matters - put them before the image references
            # Use --all to copy all architectures and --preserve-digests to maintain image digests
            if self.tls_verify:
                # Verify TLS for both source and destination
                command = f"skopeo copy --src-tls-verify=true --dest-tls-verify=true docker://{source_image} docker://{dest_image} --all --preserve-digests --remove-signatures"
            else:
                # Skip TLS verification for destination only (source always verified)
                command = f"skopeo copy --src-tls-verify=true --dest-tls-verify=false docker://{source_image} docker://{dest_image} --all --preserve-digests --remove-signatures"
            
            # Log the command being executed (file only, not console)
            self.log_to_file_only(logging.INFO, f"Executing skopeo command for image: {img.image_name}")
            self.log_to_file_only(logging.INFO, f"  Command: {command}")
            
            # Execute skopeo command with real-time output streaming
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Merge stderr into stdout
                shell=True,
                bufsize=1,  # Line buffered
                universal_newlines=True
            )
            
            # Register process for potential cleanup
            with self.process_lock:
                self.active_processes[index] = process
            
            # Stream output in real-time - print directly without truncation
            output_lines = []
            if process.stdout:
                for line in process.stdout:
                    if self.shutdown_event.is_set():
                        break
                    
                    line = line.strip()
                    if line:
                        output_lines.append(line)
                        # Add to output log for Live display
                        self.add_output_line(f"  {line}")
            
            # Wait for process to complete
            process.wait()
            
            # Unregister process
            with self.process_lock:
                self.active_processes.pop(index, None)
            
            # Check for shutdown during execution
            if self.shutdown_event.is_set():
                self.cancel_image(index)
                self.add_output_line(f"✗ Cancelled")
                return False
            
            # Check result
            if process.returncode == 0:
                self.complete_image(index, success=True)
                self.add_output_line(f"✓ Successfully copied {img.image_name}")
                self.add_output_line("")  # Blank line for separation
                # Log success to file only (not console)
                self.log_to_file_only(logging.INFO, f"Successfully copied image: {img.image_name}")
                self.log_to_file_only(logging.DEBUG, f"  Source: {source_image}")
                self.log_to_file_only(logging.DEBUG, f"  Destination: {dest_image}")
                return True
            else:
                # Extract error from output
                error_msg = output_lines[-1] if output_lines else "Unknown error"
                if "msg=" in error_msg:
                    error_msg = error_msg.split("msg=")[-1]
                self.complete_image(index, success=False, error=error_msg[:50])
                self.add_output_line(f"✗ Failed: {error_msg}")
                self.add_output_line("")  # Blank line for separation
                # Log failure to file only (not console) with full details
                self.log_to_file_only(logging.ERROR, f"Failed to copy image: {img.image_name}")
                self.log_to_file_only(logging.ERROR, f"  Source: {source_image}")
                self.log_to_file_only(logging.ERROR, f"  Destination: {dest_image}")
                self.log_to_file_only(logging.ERROR, f"  Error: {error_msg}")
                self.log_to_file_only(logging.ERROR, f"  Return code: {process.returncode}")
                if output_lines:
                    self.log_to_file_only(logging.ERROR, f"  Full output: {' | '.join(output_lines)}")
                return False
        
        except Exception as e:
            # Handle any unexpected errors gracefully without breaking live display
            error_msg = str(e)[:50]
            self.complete_image(index, success=False, error=error_msg)
            self.add_output_line(f"✗ Unexpected Error: {e}")
            self.add_output_line("")  # Blank line for separation
            
            # Log the full exception to file only (not console) for debugging
            img_name = self.images[index].image_name if index in self.images else "unknown"
            self.log_to_file_only(logging.ERROR, f"Unexpected error copying image {img_name}")
            self.log_to_file_only(logging.ERROR, f"  Source: {source_image}")
            self.log_to_file_only(logging.ERROR, f"  Destination: {dest_image}")
            self.log_to_file_only(logging.ERROR, f"  Exception type: {type(e).__name__}")
            self.log_to_file_only(logging.ERROR, f"  Exception message: {str(e)}")
            # Log stack trace separately
            import traceback
            self.log_to_file_only(logging.ERROR, f"  Stack trace: {traceback.format_exc()}")
            
            return False
    
    def push_images_parallel(self) -> Dict[str, Any]:
        """
        Push all images in parallel using ThreadPoolExecutor.
        
        Returns:
            Dict with summary of push results
        """
        results = {
            "completed": [],
            "failed": [],
            "cancelled": [],
            "total": len(self.images)
        }
        
        def copy_worker(index: int) -> Tuple[int, bool]:
            """Worker function for copying a single image."""
            img = self.images[index]
            success = self.copy_image_with_skopeo(index, img.source_image, img.dest_image)
            return (index, success)
        
        try:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit all tasks
                futures = {
                    executor.submit(copy_worker, idx): idx
                    for idx in self.images.keys()
                }
                
                # Process completed tasks
                for future in as_completed(futures):
                    if self.shutdown_event.is_set():
                        break
                    
                    try:
                        idx, success = future.result()
                        img = self.images[idx]
                        
                        if success:
                            results["completed"].append(img.image_name)
                        elif img.status == ImagePushStatus.CANCELLED:
                            results["cancelled"].append(img.image_name)
                        else:
                            results["failed"].append(img.image_name)
                    
                    except Exception as e:
                        # Handle any unexpected errors
                        pass
        
        except KeyboardInterrupt:
            self.shutdown_event.set()
            # Cancel remaining images
            for idx, img in self.images.items():
                if not img.is_complete:
                    self.cancel_image(idx)
                    results["cancelled"].append(img.image_name)
        
        finally:
            self.overall_end_time = datetime.now()
        
        return results


def create_image_push_progress(
    images: List[Tuple[str, str, str]],
    max_workers: int = 4,
    tls_verify: bool = False,
    console: Optional[Console] = None,
    logger = None
) -> Tuple[ImagePushTracker, Live]:
    """
    Create a live image push progress tracker with graceful interrupt handling.
    
    Args:
        images: List of (image_name, source_image, dest_image) tuples
        max_workers: Maximum number of concurrent image copies
        tls_verify: Whether to verify TLS certificates
        console: Rich console for output
        logger: Logger instance for file logging
        
    Returns:
        Tuple of (tracker, live_display)
    """
    console = console or Console()
    tracker = ImagePushTracker(images, console, max_workers, tls_verify, logger)
    
    # Create live display with proper signal handling
    live = Live(
        tracker.create_progress_display(),
        console=console,
        refresh_per_second=4,
        screen=True,
        transient=False,
        auto_refresh=True
    )
    
    # Store original signal handler
    original_sigint_handler = signal.getsignal(signal.SIGINT)
    
    def graceful_interrupt_handler(signum, frame):
        """Handle SIGINT (Ctrl+C) gracefully by stopping the live display."""
        try:
            # Set shutdown event
            tracker.shutdown_event.set()
            
            # Terminate active processes
            with tracker.process_lock:
                for idx, proc in list(tracker.active_processes.items()):
                    try:
                        proc.terminate()
                        tracker.cancel_image(idx)
                    except Exception:
                        pass
            
            # Stop the live display cleanly
            if live._started:
                live.stop()
        except Exception:
            pass
        finally:
            # Restore original handler and re-raise
            signal.signal(signal.SIGINT, original_sigint_handler)
            raise KeyboardInterrupt()
    
    # Install graceful interrupt handler
    signal.signal(signal.SIGINT, graceful_interrupt_handler)
    
    return tracker, live


def display_push_complete(
    tracker: ImagePushTracker,
    console: Optional[Console] = None
) -> None:
    """
    Display final push summary.
    
    Args:
        tracker: Image push tracker with final status
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
    
    console.print()
    console.print(Panel.fit(
        f"[bold cyan]Image Push Complete[/bold cyan]\n\n"
        f"[green]✓[/green] {summary['completed']}/{summary['total']} images pushed successfully\n"
        f"[cyan]⏱[/cyan]  Total time: {total_time_str}" +
        (f"\n[red]✗[/red] {summary['failed']} failed" if summary['failed'] > 0 else "") +
        (f"\n[yellow]⚠[/yellow] {summary['cancelled']} cancelled" if summary['cancelled'] > 0 else ""),
        border_style="cyan"
    ))
    console.print()

# Made with Bob
