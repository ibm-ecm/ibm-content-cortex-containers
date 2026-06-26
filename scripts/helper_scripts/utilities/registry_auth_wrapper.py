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
Backward-compatible wrappers for registry authentication.

This module provides backward-compatible wrapper functions that use the new
registry_auth module internally. This allows existing code to continue working
while gradually migrating to the new API.

These functions are DEPRECATED and will be removed in a future version.
New code should use the registry_auth module directly.
"""

import logging
import warnings
from pathlib import Path
from typing import Optional

from .registry_auth import (
    RegistryConfig,
    RegistryCredentials,
    RegistryAuthenticator,
    AuthenticationTool
)


def login_to_registry_podman(
    registry_host: str,
    username: str,
    password: str,
    logger: logging.Logger,
    ssl_enabled: bool = False,
    ssl_cert_path: str = '',
    registry_port: str = '',
    registry_path: str = '',
    tls_verify: bool = True
) -> bool:
    """
    DEPRECATED: Use RegistryAuthenticator.authenticate_podman() instead.
    
    Log in to a container registry using podman.
    
    This function is maintained for backward compatibility but will be removed
    in a future version. Please migrate to the new registry_auth module:
    
    Example migration:
        # Old way:
        success = login_to_registry_podman(
            registry_host="registry.example.com",
            username="user",
            password="pass",
            logger=logger,
            ssl_enabled=True,
            ssl_cert_path="/path/to/certs",
            registry_port="5000",
            registry_path="namespace",
            tls_verify=True
        )
        
        # New way:
        from helper_scripts.utilities.registry_auth import (
            RegistryConfig, RegistryCredentials, RegistryAuthenticator
        )
        
        config = RegistryConfig.from_url(
            "https://registry.example.com:5000/namespace",
            tls_verify=True,
            ssl_cert_path=Path("/path/to/certs")
        )
        creds = RegistryCredentials(username="user", password="pass")
        authenticator = RegistryAuthenticator(config, creds, logger)
        result = authenticator.authenticate_podman()
        success = result.success
    
    Args:
        registry_host: Registry hostname
        username: Registry username
        password: Registry password
        logger: Logger instance
        ssl_enabled: Whether SSL is enabled (deprecated, use protocol in URL)
        ssl_cert_path: Path to SSL certificate directory
        registry_port: Registry port
        registry_path: Registry path
        tls_verify: Whether to verify TLS certificates
        
    Returns:
        bool: True if login succeeded, False otherwise
    """
    warnings.warn(
        "login_to_registry_podman is deprecated and will be removed in a future version. "
        "Use RegistryAuthenticator from registry_auth module instead. "
        "See REGISTRY_AUTH_ENHANCEMENT.md for migration guide.",
        DeprecationWarning,
        stacklevel=2
    )
    
    try:
        # Build registry URL
        protocol = "https" if ssl_enabled else "http"
        url = f"{protocol}://{registry_host}"
        if registry_port:
            url += f":{registry_port}"
        if registry_path:
            url += f"/{registry_path}"
        
        # Create config and credentials
        config = RegistryConfig.from_url(
            url,
            tls_verify=tls_verify,
            ssl_cert_path=Path(ssl_cert_path) if ssl_cert_path else None
        )
        creds = RegistryCredentials(username=username, password=password)
        
        # Authenticate
        authenticator = RegistryAuthenticator(config, creds, logger)
        result = authenticator.authenticate_podman()
        
        return result.success
    
    except Exception as e:
        logger.error(f"Registry authentication error: {e}")
        return False


def login_to_registry_skopeo(
    registry_host: str,
    username: str,
    password: str,
    logger: logging.Logger,
    ssl_enabled: bool = False,
    ssl_cert_path: str = '',
    registry_port: str = '',
    registry_path: str = '',
    tls_verify: bool = True
) -> bool:
    """
    DEPRECATED: Use RegistryAuthenticator.authenticate_skopeo() instead.
    
    Log in to a container registry using skopeo.
    
    This function is maintained for backward compatibility but will be removed
    in a future version. Please migrate to the new registry_auth module.
    
    Args:
        registry_host: Registry hostname
        username: Registry username
        password: Registry password
        logger: Logger instance
        ssl_enabled: Whether SSL is enabled
        ssl_cert_path: Path to SSL certificate directory
        registry_port: Registry port
        registry_path: Registry path
        tls_verify: Whether to verify TLS certificates
        
    Returns:
        bool: True if login succeeded, False otherwise
    """
    warnings.warn(
        "login_to_registry_skopeo is deprecated and will be removed in a future version. "
        "Use RegistryAuthenticator from registry_auth module instead.",
        DeprecationWarning,
        stacklevel=2
    )
    
    try:
        # Build registry URL
        protocol = "https" if ssl_enabled else "http"
        url = f"{protocol}://{registry_host}"
        if registry_port:
            url += f":{registry_port}"
        if registry_path:
            url += f"/{registry_path}"
        
        # Create config and credentials
        config = RegistryConfig.from_url(
            url,
            tls_verify=tls_verify,
            ssl_cert_path=Path(ssl_cert_path) if ssl_cert_path else None
        )
        creds = RegistryCredentials(username=username, password=password)
        
        # Authenticate
        authenticator = RegistryAuthenticator(config, creds, logger)
        result = authenticator.authenticate_skopeo()
        
        return result.success
    
    except Exception as e:
        logger.error(f"Registry authentication error: {e}")
        return False


def login_to_registry_both(
    registry_host: str,
    username: str,
    password: str,
    logger: logging.Logger,
    ssl_enabled: bool = False,
    ssl_cert_path: str = '',
    registry_port: str = '',
    registry_path: str = '',
    tls_verify: bool = True
) -> bool:
    """
    DEPRECATED: Use RegistryAuthenticator.authenticate_all() instead.
    
    Log in to a container registry using both podman and skopeo.
    
    This function is maintained for backward compatibility but will be removed
    in a future version. Please migrate to the new registry_auth module.
    
    Args:
        registry_host: Registry hostname
        username: Registry username
        password: Registry password
        logger: Logger instance
        ssl_enabled: Whether SSL is enabled
        ssl_cert_path: Path to SSL certificate directory
        registry_port: Registry port
        registry_path: Registry path
        tls_verify: Whether to verify TLS certificates
        
    Returns:
        bool: True if both logins succeeded, False otherwise
    """
    warnings.warn(
        "login_to_registry_both is deprecated and will be removed in a future version. "
        "Use RegistryAuthenticator from registry_auth module instead.",
        DeprecationWarning,
        stacklevel=2
    )
    
    try:
        # Build registry URL
        protocol = "https" if ssl_enabled else "http"
        url = f"{protocol}://{registry_host}"
        if registry_port:
            url += f":{registry_port}"
        if registry_path:
            url += f"/{registry_path}"
        
        # Create config and credentials
        config = RegistryConfig.from_url(
            url,
            tls_verify=tls_verify,
            ssl_cert_path=Path(ssl_cert_path) if ssl_cert_path else None
        )
        creds = RegistryCredentials(username=username, password=password)
        
        # Authenticate with both tools
        authenticator = RegistryAuthenticator(config, creds, logger)
        results = authenticator.authenticate_all()
        
        # Check if podman succeeded (required)
        podman_success = any(
            r.success and r.tool == AuthenticationTool.PODMAN 
            for r in results
        )
        
        if not podman_success:
            return False
        
        # Skopeo is optional - warn if it failed but don't fail overall
        skopeo_success = any(
            r.success and r.tool == AuthenticationTool.SKOPEO 
            for r in results
        )
        
        if not skopeo_success:
            logger.warning(
                "Skopeo authentication failed. Image copy operations may be affected."
            )
        
        return True
    
    except Exception as e:
        logger.error(f"Registry authentication error: {e}")
        return False


def check_registry_reachability(
    registry_host: str,
    registry_port: Optional[str] = None,
    registry_path: Optional[str] = None,
    ssl_enabled: bool = True,
    ssl_cert_path: Optional[str] = None,
    tls_verify: bool = True,
    logger: Optional[logging.Logger] = None,
    timeout: int = 10
) -> tuple[bool, Optional[str]]:
    """
    Check if a registry is reachable using HTTP API and socket checks.
    
    This is a NEW function that leverages the registry_auth module's
    comprehensive reachability checking.
    
    Args:
        registry_host: Registry hostname
        registry_port: Registry port (optional)
        registry_path: Registry path (optional)
        ssl_enabled: Whether to use HTTPS
        ssl_cert_path: Path to SSL certificate directory
        tls_verify: Whether to verify TLS certificates
        logger: Logger instance
        timeout: Connection timeout in seconds
        
    Returns:
        tuple: (reachable: bool, error_message: Optional[str])
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    try:
        # Build registry URL
        protocol = "https" if ssl_enabled else "http"
        url = f"{protocol}://{registry_host}"
        if registry_port:
            url += f":{registry_port}"
        if registry_path:
            url += f"/{registry_path}"
        
        # Create config (credentials not needed for reachability check)
        config = RegistryConfig.from_url(
            url,
            tls_verify=tls_verify,
            ssl_cert_path=Path(ssl_cert_path) if ssl_cert_path else None
        )
        
        # Dummy credentials (not used for reachability check)
        creds = RegistryCredentials(username="", password="")
        
        # Check reachability
        authenticator = RegistryAuthenticator(config, creds, logger)
        result = authenticator.check_reachability(timeout=timeout)
        
        return result.reachable, result.error
    
    except Exception as e:
        error_msg = f"Error checking registry reachability: {e}"
        logger.error(error_msg)
        return False, error_msg

# Made with Bob
