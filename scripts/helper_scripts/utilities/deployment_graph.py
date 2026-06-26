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
Deployment Graph Module

This module provides dependency graph management for operator deployments,
ensuring operators are deployed in the correct order based on their dependencies.
"""

from typing import List, Set, Dict, Optional, Any
from dataclasses import dataclass, field
import logging

from .operator_config import OperatorType, get_operator_metadata


@dataclass
class DeploymentNode:
    """
    Represents an operator in the deployment graph.
    
    Attributes:
        operator: The operator type
        dependencies: Set of operators this operator depends on
        deployed: Whether this operator has been deployed
        deployment_order: The order in which this operator should be deployed
    """
    operator: OperatorType
    dependencies: Set[OperatorType] = field(default_factory=set)
    deployed: bool = False
    deployment_order: int = 0


class DeploymentGraph:
    """
    Manages operator deployment order based on dependencies.
    
    This class builds a dependency graph from a list of operators and provides
    methods to determine the optimal deployment order using topological sorting.
    It can also group operators into "waves" where operators in the same wave
    can be deployed in parallel.
    """
    
    def __init__(self, operators: List[OperatorType], logger: Optional[logging.Logger] = None):
        """
        Initialize the deployment graph.
        
        Args:
            operators: List of operators to deploy
            logger: Optional logger for debugging
        """
        self.logger = logger or logging.getLogger(__name__)
        self.nodes: Dict[OperatorType, DeploymentNode] = {}
        self._build_graph(operators)
    
    def _build_graph(self, operators: List[OperatorType]) -> None:
        """
        Build dependency graph from operator list.
        
        Args:
            operators: List of operators to include in the graph
        """
        self.logger.debug(f"Building deployment graph for operators: {[op.value for op in operators]}")
        
        for op in operators:
            metadata = get_operator_metadata(op)
            self.nodes[op] = DeploymentNode(
                operator=op,
                dependencies=set(metadata.dependencies)
            )
            self.logger.debug(
                f"Added node for {op.value} with dependencies: "
                f"{[d.value for d in metadata.dependencies]}"
            )
    
    def topological_sort(self) -> List[OperatorType]:
        """
        Return operators in deployment order using topological sort.
        
        Uses depth-first search to perform topological sorting, ensuring
        that dependencies are always deployed before dependent operators.
        
        Returns:
            List of operators in deployment order
            
        Raises:
            ValueError: If a circular dependency is detected
        """
        self.logger.info("Performing topological sort to determine deployment order")
        
        result = []
        visited = set()
        temp_mark = set()
        
        def visit(node: OperatorType, path: List[OperatorType]) -> None:
            """
            Visit a node in the dependency graph.
            
            Args:
                node: The operator to visit
                path: Current path in the graph (for cycle detection)
                
            Raises:
                ValueError: If a circular dependency is detected
            """
            if node in temp_mark:
                cycle_path = " -> ".join([op.value for op in path + [node]])
                error_msg = f"Circular dependency detected: {cycle_path}"
                self.logger.error(error_msg)
                raise ValueError(error_msg)
            
            if node in visited:
                return
            
            temp_mark.add(node)
            
            # Visit dependencies first
            for dep in self.nodes[node].dependencies:
                if dep in self.nodes:  # Only visit if dependency is being deployed
                    visit(dep, path + [node])
            
            temp_mark.remove(node)
            visited.add(node)
            result.append(node)
            
            self.logger.debug(f"Added {node.value} to deployment order (position {len(result)})")
        
        # Visit all nodes
        for node in self.nodes:
            if node not in visited:
                visit(node, [])
        
        self.logger.info(f"Deployment order determined: {[op.value for op in result]}")
        return result
    
    def get_deployment_waves(self) -> List[List[OperatorType]]:
        """
        Group operators into deployment waves.
        
        Operators in the same wave have all their dependencies satisfied
        and can be deployed in parallel. Each wave must complete before
        the next wave can begin.
        
        Returns:
            List of waves, where each wave is a list of operators
            
        Raises:
            ValueError: If unable to resolve deployment order
        """
        self.logger.info("Calculating deployment waves for parallel deployment")
        
        ordered = self.topological_sort()
        waves = []
        deployed = set()
        
        while len(deployed) < len(ordered):
            wave = []
            
            # Find all operators whose dependencies are satisfied
            for op in ordered:
                if op not in deployed:
                    deps = self.nodes[op].dependencies
                    if deps.issubset(deployed):
                        wave.append(op)
            
            if not wave:
                error_msg = "Unable to resolve deployment order - possible circular dependency"
                self.logger.error(error_msg)
                raise ValueError(error_msg)
            
            waves.append(wave)
            deployed.update(wave)
            
            self.logger.debug(
                f"Wave {len(waves)}: {[op.value for op in wave]} "
                f"(can deploy in parallel)"
            )
        
        self.logger.info(f"Calculated {len(waves)} deployment waves")
        return waves
    
    def validate_dependencies(self) -> List[str]:
        """
        Validate that all dependencies are satisfied.
        
        Checks that all operators referenced as dependencies are actually
        included in the deployment.
        
        Returns:
            List of error messages (empty if all dependencies are satisfied)
        """
        errors = []
        
        for op, node in self.nodes.items():
            for dep in node.dependencies:
                if dep not in self.nodes:
                    metadata = get_operator_metadata(op)
                    dep_metadata = get_operator_metadata(dep)
                    error = (
                        f"{metadata.display_name} requires {dep_metadata.display_name}, "
                        f"but it is not selected for deployment"
                    )
                    errors.append(error)
                    self.logger.warning(error)
        
        if errors:
            self.logger.error(f"Found {len(errors)} dependency validation errors")
        else:
            self.logger.info("All dependencies validated successfully")
        
        return errors
    
    def get_deployment_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the deployment plan.
        
        Returns:
            Dictionary containing deployment statistics and information
        """
        try:
            ordered = self.topological_sort()
            waves = self.get_deployment_waves()
            
            return {
                "total_operators": len(self.nodes),
                "deployment_order": [op.value for op in ordered],
                "total_waves": len(waves),
                "waves": [[op.value for op in wave] for wave in waves],
                "max_parallel": max(len(wave) for wave in waves) if waves else 0,
                "has_dependencies": any(node.dependencies for node in self.nodes.values())
            }
        except ValueError as e:
            return {
                "error": str(e),
                "total_operators": len(self.nodes)
            }

# Made with Bob
