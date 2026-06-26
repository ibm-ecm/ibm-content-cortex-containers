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
Parallel Deployment Module

This module provides parallel deployment capabilities for operators,
allowing independent operators to be deployed simultaneously to reduce
total deployment time.
"""

import asyncio
import logging
from typing import List, Dict, Callable, Optional
from concurrent.futures import ThreadPoolExecutor
from rich.progress import Progress, TaskID
from rich.console import Console

from .operator_config import OperatorType, get_operator_metadata


class ParallelDeploymentEngine:
    """
    Manages parallel deployment of independent operators.
    
    This class coordinates the deployment of multiple operators simultaneously,
    respecting dependency constraints and managing resources efficiently.
    """
    
    def __init__(
        self,
        max_workers: int = 3,
        logger: Optional[logging.Logger] = None,
        console: Optional[Console] = None
    ):
        """
        Initialize the parallel deployment engine.
        
        Args:
            max_workers: Maximum number of operators to deploy in parallel
            logger: Optional logger for debugging
            console: Optional Rich console for output
        """
        self.max_workers = max_workers
        self.logger = logger or logging.getLogger(__name__)
        self.console = console or Console()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        
        self.logger.info(f"Initialized parallel deployment engine with {max_workers} workers")
    
    async def deploy_wave(
        self,
        wave: List[OperatorType],
        deploy_func: Callable,
        progress: Progress,
        wave_task: TaskID
    ) -> Dict[OperatorType, bool]:
        """
        Deploy all operators in a wave in parallel.
        
        Args:
            wave: List of operators to deploy in this wave
            deploy_func: Function to call for deploying each operator
            progress: Rich Progress object for tracking
            wave_task: Task ID for the wave progress bar
            
        Returns:
            Dictionary mapping operators to their deployment success status
        """
        self.logger.info(f"Starting parallel deployment of wave: {[op.value for op in wave]}")
        
        results = {}
        tasks = []
        
        # Create async tasks for each operator
        for operator in wave:
            task = asyncio.create_task(
                self._deploy_operator_async(operator, deploy_func, progress)
            )
            tasks.append((operator, task))
        
        # Wait for all tasks to complete
        for operator, task in tasks:
            try:
                success = await task
                results[operator] = success
                progress.update(wave_task, advance=1)
                
                metadata = get_operator_metadata(operator)
                status = "[green]✓[/green]" if success else "[red]✗[/red]"
                self.console.print(
                    f"{status} {metadata.display_name} deployment "
                    f"{'completed' if success else 'failed'}"
                )
                
            except Exception as e:
                results[operator] = False
                metadata = get_operator_metadata(operator)
                self.logger.error(f"Failed to deploy {operator.value}: {e}")
                self.console.print(
                    f"[red]✗[/red] Failed to deploy {metadata.display_name}: {e}"
                )
        
        successful = sum(1 for v in results.values() if v)
        self.logger.info(
            f"Wave deployment complete: {successful}/{len(wave)} operators successful"
        )
        
        return results
    
    async def _deploy_operator_async(
        self,
        operator: OperatorType,
        deploy_func: Callable,
        progress: Progress
    ) -> bool:
        """
        Deploy a single operator asynchronously.
        
        Args:
            operator: The operator to deploy
            deploy_func: Function to call for deployment
            progress: Rich Progress object
            
        Returns:
            True if deployment succeeded, False otherwise
        """
        metadata = get_operator_metadata(operator)
        self.logger.debug(f"Starting async deployment of {metadata.display_name}")
        
        try:
            # Run the deployment function in the thread pool
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self.executor,
                deploy_func,
                operator
            )
            
            self.logger.debug(f"Completed async deployment of {metadata.display_name}")
            return result
            
        except asyncio.CancelledError:
            self.logger.warning(f"Deployment of {metadata.display_name} was cancelled")
            return False
        except KeyboardInterrupt:
            self.logger.warning(f"Deployment of {metadata.display_name} interrupted by user")
            raise
        except Exception as e:
            self.logger.error(f"Error in async deployment of {metadata.display_name}: {e}")
            return False
    
    async def deploy_all_waves(
        self,
        waves: List[List[OperatorType]],
        deploy_func: Callable,
        progress: Progress
    ) -> Dict[OperatorType, bool]:
        """
        Deploy all waves sequentially, with parallel deployment within each wave.
        
        Args:
            waves: List of waves, where each wave is a list of operators
            deploy_func: Function to call for deploying each operator
            progress: Rich Progress object for tracking
            
        Returns:
            Dictionary mapping all operators to their deployment success status
        """
        self.logger.info(f"Starting deployment of {len(waves)} waves")
        
        all_results = {}
        
        try:
            for wave_num, wave in enumerate(waves, 1):
                self.logger.info(f"Deploying wave {wave_num}/{len(waves)}")
                
                # Create progress task for this wave
                wave_task = progress.add_task(
                    f"[cyan]Wave {wave_num}[/cyan]",
                    total=len(wave)
                )
                
                # Deploy this wave
                wave_results = await self.deploy_wave(wave, deploy_func, progress, wave_task)
                all_results.update(wave_results)
                
                # Check if wave was successful
                failed = [op for op, success in wave_results.items() if not success]
                if failed:
                    self.logger.warning(
                        f"Wave {wave_num} had failures: {[op.value for op in failed]}"
                    )
                    # Optionally stop on failure
                    # break
            
            successful = sum(1 for v in all_results.values() if v)
            self.logger.info(
                f"All waves complete: {successful}/{len(all_results)} operators successful"
            )
            
        except KeyboardInterrupt:
            self.logger.warning("Wave deployment interrupted by user")
            # Mark any operators that haven't been processed as failed
            for wave in waves:
                for op in wave:
                    if op not in all_results:
                        all_results[op] = False
            raise
        
        return all_results
    
    def shutdown(self, wait: bool = True):
        """
        Cleanup the thread pool executor.
        
        Args:
            wait: If True, wait for all threads to complete. If False, cancel pending tasks.
        """
        self.logger.info(f"Shutting down parallel deployment engine (wait={wait})")
        try:
            self.executor.shutdown(wait=wait)
        except Exception as e:
            self.logger.error(f"Error during executor shutdown: {e}")


def display_parallel_deployment_summary(
    results: Dict[OperatorType, bool],
    duration: float,
    console: Optional[Console] = None
) -> None:
    """
    Display summary of parallel deployment results.
    
    Args:
        results: Dictionary mapping operators to their success status
        duration: Total deployment duration in seconds
        console: Optional Rich console for output
    """
    from rich.table import Table
    from rich.panel import Panel
    
    console = console or Console()
    
    table = Table(title="⚡ Parallel Deployment Results")
    table.add_column("Operator", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Estimated Time Saved", style="green")
    
    successful = 0
    failed = 0
    
    for operator, success in results.items():
        metadata = get_operator_metadata(operator)
        
        if success:
            status = "[green]✓ Success[/green]"
            successful += 1
        else:
            status = "[red]✗ Failed[/red]"
            failed += 1
        
        # Estimate time saved (rough estimate: 2-3 min per operator)
        time_saved = "~2-3 min" if len(results) > 1 else "—"
        
        table.add_row(metadata.display_name, status, time_saved)
    
    console.print(table)
    console.print()
    
    # Summary statistics
    summary_lines = [
        f"[bold]Total Operators:[/bold] {len(results)}",
        f"[green]Successful:[/green] {successful}",
    ]
    
    if failed > 0:
        summary_lines.append(f"[red]Failed:[/red] {failed}")
    
    summary_lines.extend([
        f"[cyan]Total Time:[/cyan] {duration:.1f}s",
        f"[yellow]Estimated Time Saved:[/yellow] ~{len(results) * 2}min"
    ])
    
    console.print(Panel(
        "\n".join(summary_lines),
        title="📊 Deployment Summary",
        border_style="cyan"
    ))
    console.print()

# Made with Bob
