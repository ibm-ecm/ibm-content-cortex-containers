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
Registry Authentication Module

This module provides a modern, Pythonic approach to container registry authentication
and validation. It supports both podman and skopeo authentication, SSL/non-SSL connections,
and comprehensive registry reachability checks.

Key Features:
- HTTP-based registry API validation (OCI Distribution Spec)
- Socket-based connectivity checks
- Support for both SSL and non-SSL registries
- Unified authentication for podman and skopeo
- Comprehensive error handling and reporting
- Type hints and dataclasses for better code clarity
"""

import logging
import socket
import ssl
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple, Dict, List, Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from rich.console import Console
from rich.panel import Panel
from rich.text import Text


class RegistryProtocol(Enum):
    """Registry connection protocol types."""
    HTTP = "http"
    HTTPS = "https"


class AuthenticationTool(Enum):
    """Container registry authentication tools."""
    PODMAN = "podman"
    SKOPEO = "skopeo"


@dataclass
class RegistryConfig:
    """Configuration for a container registry."""
    host: str
    port: Optional[int] = None
    path: Optional[str] = None
    protocol: RegistryProtocol = RegistryProtocol.HTTPS
    ssl_cert_path: Optional[Path] = None
    tls_verify: bool = True
    
    @property
    def url(self) -> str:
        """Construct the full registry URL."""
        url = f"{self.protocol.value}://{self.host}"
        if self.port:
            url += f":{self.port}"
        if self.path:
            url += f"/{self.path.strip('/')}"
        return url
    
    @property
    def registry_address(self) -> str:
        """
        Get registry address without protocol (for podman/skopeo authentication).
        
        NOTE: Authentication is always against the base registry (hostname:port).
        The path (e.g., /cp in cp.stg.icr.io/cp) is NOT included in authentication.
        """
        address = self.host
        if self.port:
            address += f":{self.port}"
        # Path is intentionally NOT included for authentication
        return address
    
    @property
    def registry_address_with_path(self) -> str:
        """Get registry address with path (for image references)."""
        address = self.host
        if self.port:
            address += f":{self.port}"
        if self.path:
            address += f"/{self.path.strip('/')}"
        return address
    
    @classmethod
    def from_url(cls, url: str, tls_verify: bool = True, ssl_cert_path: Optional[Path] = None) -> 'RegistryConfig':
        """
        Create RegistryConfig from a URL string.
        
        Args:
            url: Registry URL (e.g., "https://registry.example.com:5000/path")
            tls_verify: Whether to verify TLS certificates
            ssl_cert_path: Path to SSL certificate directory
            
        Returns:
            RegistryConfig instance
        """
        # Add default scheme if missing
        if not url.startswith(('http://', 'https://')):
            url = f"https://{url}"
        
        parsed = urlparse(url)
        protocol = RegistryProtocol.HTTPS if parsed.scheme == 'https' else RegistryProtocol.HTTP
        
        # Default ports
        port = parsed.port
        if port is None:
            port = 443 if protocol == RegistryProtocol.HTTPS else 80
        
        return cls(
            host=parsed.hostname or parsed.netloc,
            port=port,
            path=parsed.path.strip('/') if parsed.path else None,
            protocol=protocol,
            ssl_cert_path=ssl_cert_path,
            tls_verify=tls_verify
        )


@dataclass
class RegistryCredentials:
    """Credentials for registry authentication."""
    username: str
    password: str


@dataclass
class AuthenticationResult:
    """Result of a registry authentication attempt."""
    success: bool
    tool: AuthenticationTool
    message: str
    error: Optional[str] = None


@dataclass
class ReachabilityResult:
    """Result of a registry reachability check."""
    reachable: bool
    method: str  # 'http', 'socket', 'both'
    response_time_ms: Optional[float] = None
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class RegistryAuthenticator:
    """
    Modern, Pythonic registry authentication and validation.
    
    This class provides comprehensive registry authentication supporting:
    - Multiple authentication tools (podman, skopeo)
    - HTTP-based registry API validation
    - Socket-based connectivity checks
    - SSL and non-SSL connections
    - Detailed error reporting
    
    Example:
        >>> config = RegistryConfig.from_url("https://registry.example.com:5000")
        >>> creds = RegistryCredentials(username="user", password="pass")
        >>> authenticator = RegistryAuthenticator(config, creds, logger)
        >>> 
        >>> # Check if registry is reachable
        >>> if authenticator.check_reachability():
        >>>     # Authenticate with both tools
        >>>     results = authenticator.authenticate_all()
        >>>     if all(r.success for r in results):
        >>>         print("Successfully authenticated!")
    """
    
    def __init__(
        self,
        config: RegistryConfig,
        credentials: RegistryCredentials,
        logger: Optional[logging.Logger] = None,
        console: Optional[Console] = None
    ):
        """
        Initialize the registry authenticator.
        
        Args:
            config: Registry configuration
            credentials: Authentication credentials
            logger: Optional logger instance
            console: Optional Rich console for output
        """
        self.config = config
        self.credentials = credentials
        self.logger = logger or logging.getLogger(__name__)
        self.console = console or Console()
        
        # Create HTTP session with retries
        self._session = self._create_http_session()
    
    def _create_http_session(self) -> requests.Session:
        """Create an HTTP session with retry logic."""
        session = requests.Session()
        
        # Configure retries
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # Configure SSL verification
        if not self.config.tls_verify:
            session.verify = False
            # Suppress only the single InsecureRequestWarning
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        elif self.config.ssl_cert_path:
            session.verify = str(self.config.ssl_cert_path)
        
        return session
    
    def check_reachability(self, timeout: int = 10) -> ReachabilityResult:
        """
        Check if the registry is reachable using multiple methods.
        
        This performs both HTTP-based API checks (OCI Distribution Spec)
        and socket-based connectivity checks for comprehensive validation.
        
        Args:
            timeout: Connection timeout in seconds
            
        Returns:
            ReachabilityResult with detailed information
        """
        self.logger.info(f"Checking reachability for registry: {self.config.url}")
        
        # Try HTTP-based check first (preferred for registries)
        http_result = self._check_http_reachability(timeout)
        
        # Try socket-based check as fallback
        socket_result = self._check_socket_reachability(timeout)
        
        # Determine overall reachability
        if http_result['reachable']:
            return ReachabilityResult(
                reachable=True,
                method='http',
                response_time_ms=http_result['response_time_ms'],
                details={
                    'http': http_result,
                    'socket': socket_result
                }
            )
        elif socket_result['reachable']:
            return ReachabilityResult(
                reachable=True,
                method='socket',
                response_time_ms=socket_result['response_time_ms'],
                details={
                    'http': http_result,
                    'socket': socket_result
                },
                error="Registry reachable via socket but HTTP API check failed"
            )
        else:
            return ReachabilityResult(
                reachable=False,
                method='none',
                error=f"HTTP: {http_result.get('error', 'Unknown')}; Socket: {socket_result.get('error', 'Unknown')}",
                details={
                    'http': http_result,
                    'socket': socket_result
                }
            )
    
    def _check_http_reachability(self, timeout: int) -> Dict:
        """
        Check registry reachability using HTTP API (OCI Distribution Spec).
        
        Tries the /v2/ endpoint which is the standard OCI registry API endpoint.
        """
        import time
        
        result = {
            'reachable': False,
            'response_time_ms': None,
            'error': None,
            'status_code': None,
            'api_version': None
        }
        
        # OCI Distribution Spec: /v2/ endpoint should return 200 or 401
        api_url = f"{self.config.url}/v2/"
        
        try:
            self.logger.debug(f"Checking HTTP API endpoint: {api_url}")
            start_time = time.time()
            
            response = self._session.get(
                api_url,
                timeout=timeout,
                allow_redirects=True
            )
            
            end_time = time.time()
            response_time_ms = (end_time - start_time) * 1000
            
            result['status_code'] = response.status_code
            result['response_time_ms'] = response_time_ms
            
            # OCI registries return 200 (authenticated) or 401 (needs auth)
            # Both indicate the registry is reachable and functioning
            if response.status_code in [200, 401]:
                result['reachable'] = True
                result['api_version'] = response.headers.get('Docker-Distribution-Api-Version', 'unknown')
                self.logger.info(f"Registry API reachable (HTTP {response.status_code}) in {response_time_ms:.2f}ms")
            else:
                result['error'] = f"Unexpected HTTP status: {response.status_code}"
                self.logger.warning(f"Registry returned unexpected status: {response.status_code}")
        
        except requests.exceptions.SSLError as e:
            result['error'] = f"SSL Error: {str(e)}"
            self.logger.warning(f"SSL error connecting to registry: {e}")
        
        except requests.exceptions.ConnectionError as e:
            result['error'] = f"Connection Error: {str(e)}"
            self.logger.warning(f"Connection error: {e}")
        
        except requests.exceptions.Timeout as e:
            result['error'] = f"Timeout after {timeout}s"
            self.logger.warning(f"Connection timeout: {e}")
        
        except Exception as e:
            result['error'] = f"Unexpected error: {str(e)}"
            self.logger.error(f"Unexpected error checking HTTP reachability: {e}")
        
        return result
    
    def _check_socket_reachability(self, timeout: int) -> Dict:
        """
        Check registry reachability using socket connection.
        
        This is a lower-level check that verifies basic network connectivity.
        """
        import time
        
        result = {
            'reachable': False,
            'response_time_ms': None,
            'error': None,
            'resolved_ips': []
        }
        
        try:
            # Resolve hostname to IP addresses
            addr_info = socket.getaddrinfo(
                self.config.host,
                self.config.port or (443 if self.config.protocol == RegistryProtocol.HTTPS else 80),
                socket.AF_UNSPEC,
                socket.SOCK_STREAM
            )
            
            result['resolved_ips'] = list(set(addr[4][0] for addr in addr_info))
            self.logger.debug(f"Resolved IPs: {result['resolved_ips']}")
            
            # Try to connect to the first resolved address
            for family, socktype, proto, canonname, sockaddr in addr_info:
                try:
                    start_time = time.time()
                    
                    sock = socket.socket(family, socktype, proto)
                    sock.settimeout(timeout)
                    
                    # For HTTPS, wrap with SSL
                    if self.config.protocol == RegistryProtocol.HTTPS:
                        context = ssl.create_default_context()
                        
                        if not self.config.tls_verify:
                            context.check_hostname = False
                            context.verify_mode = ssl.CERT_NONE
                        elif self.config.ssl_cert_path:
                            context.load_verify_locations(cafile=str(self.config.ssl_cert_path))
                        
                        sock = context.wrap_socket(sock, server_hostname=self.config.host)
                    
                    sock.connect(sockaddr)
                    end_time = time.time()
                    
                    result['reachable'] = True
                    result['response_time_ms'] = (end_time - start_time) * 1000
                    
                    sock.close()
                    self.logger.info(f"Socket connection successful in {result['response_time_ms']:.2f}ms")
                    break
                
                except (socket.timeout, socket.error) as e:
                    self.logger.debug(f"Socket connection failed for {sockaddr}: {e}")
                    continue
        
        except socket.gaierror as e:
            result['error'] = f"DNS resolution failed: {str(e)}"
            self.logger.warning(f"Failed to resolve hostname: {e}")
        
        except Exception as e:
            result['error'] = f"Unexpected error: {str(e)}"
            self.logger.error(f"Unexpected error checking socket reachability: {e}")
        
        if not result['reachable'] and not result['error']:
            result['error'] = "Could not establish socket connection to any resolved IP"
        
        return result
    
    def authenticate_http(self) -> AuthenticationResult:
        """
        Authenticate with the registry using HTTP API (Docker Registry HTTP API V2).
        
        This method validates credentials without requiring podman or skopeo,
        using the standard Docker Registry HTTP API V2 specification.
        
        Returns:
            AuthenticationResult with success status and details
        """
        self.logger.info(f"Authenticating via HTTP API to {self.config.registry_address}")
        
        try:
            import base64
            
            # OCI Distribution Spec: /v2/ endpoint requires authentication
            api_url = f"{self.config.url}/v2/"
            
            # Create Basic Auth header
            credentials = f"{self.credentials.username}:{self.credentials.password}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            headers = {
                'Authorization': f'Basic {encoded_credentials}'
            }
            
            self.logger.debug(f"HTTP API authentication to: {api_url}")
            
            # Attempt authenticated request with Basic Auth
            response = self._session.get(
                api_url,
                headers=headers,
                timeout=10,
                allow_redirects=True
            )
            
            # HTTP 200 = authenticated successfully
            # HTTP 401 = may need Bearer token (Docker Registry v2 auth flow)
            # HTTP 404 = endpoint not found (not a registry)
            
            if response.status_code == 200:
                self.logger.info("HTTP API authentication successful")
                return AuthenticationResult(
                    success=True,
                    tool=AuthenticationTool.PODMAN,
                    message="Successfully authenticated via HTTP API (no podman required)"
                )
            elif response.status_code == 401:
                # Check if registry requires Bearer token authentication
                www_auth = response.headers.get('Www-Authenticate', '')
                
                if 'Bearer' in www_auth:
                    # Docker Registry v2 authentication flow
                    self.logger.debug("Registry requires Bearer token authentication")
                    token_result = self._get_bearer_token(www_auth, headers)
                    
                    if token_result['success']:
                        # Retry with Bearer token
                        bearer_headers = {'Authorization': f"Bearer {token_result['token']}"}
                        retry_response = self._session.get(api_url, headers=bearer_headers, timeout=10)
                        
                        if retry_response.status_code == 200:
                            self.logger.info("HTTP API authentication successful (Bearer token)")
                            return AuthenticationResult(
                                success=True,
                                tool=AuthenticationTool.PODMAN,
                                message="Successfully authenticated via HTTP API with Bearer token"
                            )
                    
                    # Bearer token auth failed
                    error_msg = token_result.get('error', 'Bearer token authentication failed')
                    self.logger.warning(f"HTTP API authentication failed: {error_msg}")
                    return AuthenticationResult(
                        success=False,
                        tool=AuthenticationTool.PODMAN,
                        message="HTTP API authentication failed",
                        error=error_msg
                    )
                else:
                    # Basic Auth failed, no Bearer token option
                    error_msg = "Invalid credentials"
                    try:
                        error_data = response.json()
                        if 'errors' in error_data and error_data['errors']:
                            error_msg = error_data['errors'][0].get('message', error_msg)
                    except:
                        pass
                    
                    self.logger.warning(f"HTTP API authentication failed: {error_msg}")
                    return AuthenticationResult(
                        success=False,
                        tool=AuthenticationTool.PODMAN,
                        message="HTTP API authentication failed",
                        error=error_msg
                    )
            else:
                error_msg = f"Unexpected HTTP status: {response.status_code}"
                self.logger.warning(f"HTTP API authentication error: {error_msg}")
                return AuthenticationResult(
                    success=False,
                    tool=AuthenticationTool.PODMAN,
                    message="HTTP API authentication error",
                    error=error_msg
                )
        
        except requests.exceptions.SSLError as e:
            error_msg = f"SSL Error: {str(e)}"
            self.logger.warning(f"SSL error during HTTP authentication: {e}")
            return AuthenticationResult(
                success=False,
                tool=AuthenticationTool.PODMAN,
                message="SSL error during authentication",
                error=error_msg
            )
        
        except requests.exceptions.ConnectionError as e:
            error_msg = f"Connection Error: {str(e)}"
            self.logger.warning(f"Connection error during HTTP authentication: {e}")
            return AuthenticationResult(
                success=False,
                tool=AuthenticationTool.PODMAN,
                message="Connection error during authentication",
                error=error_msg
            )
        
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            self.logger.error(f"HTTP API authentication error: {e}")
            return AuthenticationResult(
                success=False,
                tool=AuthenticationTool.PODMAN,
                message="HTTP API authentication error",
                error=error_msg
            )
    
    def _get_bearer_token(self, www_auth_header: str, basic_auth_headers: Dict[str, str]) -> Dict[str, Any]:
        """
        Get Bearer token from registry auth server (Docker Registry v2 auth flow).
        
        Args:
            www_auth_header: The Www-Authenticate header from the 401 response
            basic_auth_headers: Headers with Basic Auth credentials
            
        Returns:
            Dict with 'success', 'token', and optional 'error' keys
        """
        import re
        
        result = {'success': False, 'token': None, 'error': None}
        
        try:
            # Parse Www-Authenticate header
            # Format: Bearer realm="https://auth.server.com/token",service="registry.server.com",scope="repository:repo:pull"
            realm_match = re.search(r'realm="([^"]+)"', www_auth_header)
            service_match = re.search(r'service="([^"]+)"', www_auth_header)
            scope_match = re.search(r'scope="([^"]+)"', www_auth_header)
            
            if not realm_match:
                result['error'] = "Could not parse auth realm from Www-Authenticate header"
                return result
            
            auth_url = realm_match.group(1)
            params = {}
            
            if service_match:
                params['service'] = service_match.group(1)
            if scope_match:
                params['scope'] = scope_match.group(1)
            
            self.logger.debug(f"Requesting Bearer token from: {auth_url}")
            
            # Request token with Basic Auth credentials
            token_response = self._session.get(
                auth_url,
                params=params,
                headers=basic_auth_headers,
                timeout=10
            )
            
            if token_response.status_code == 200:
                token_data = token_response.json()
                if 'token' in token_data:
                    result['success'] = True
                    result['token'] = token_data['token']
                    self.logger.debug("Successfully obtained Bearer token")
                elif 'access_token' in token_data:
                    result['success'] = True
                    result['token'] = token_data['access_token']
                    self.logger.debug("Successfully obtained Bearer access token")
                else:
                    result['error'] = "Token response missing 'token' or 'access_token' field"
            else:
                result['error'] = f"Token request failed with HTTP {token_response.status_code}"
                try:
                    error_data = token_response.json()
                    if 'errors' in error_data and error_data['errors']:
                        result['error'] = error_data['errors'][0].get('message', result['error'])
                except:
                    pass
        
        except Exception as e:
            result['error'] = f"Bearer token request failed: {str(e)}"
            self.logger.error(f"Error getting Bearer token: {e}")
        
        return result
    
    def authenticate_podman(self) -> AuthenticationResult:
        """
        Authenticate with the registry using podman.
        
        Returns:
            AuthenticationResult with success status and details
        """
        self.logger.info(f"Authenticating with podman to {self.config.registry_address}")
        
        try:
            # Build podman login command
            command = [
                "podman", "login",
                self.config.registry_address,
                "-u", self.credentials.username,
                "--password-stdin"
            ]
            
            # Add TLS verification flag
            command.append(f"--tls-verify={str(self.config.tls_verify).lower()}")
            
            # Add certificate directory if SSL is enabled and cert path provided
            if self.config.protocol == RegistryProtocol.HTTPS and self.config.ssl_cert_path and self.config.tls_verify:
                command.extend(["--cert-dir", str(self.config.ssl_cert_path)])
            
            self.logger.debug(f"Podman command: {' '.join(command[:-1])} [password hidden]")
            
            # Execute podman login
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            stdout, stderr = process.communicate(input=self.credentials.password)
            
            if process.returncode == 0:
                self.logger.info("Podman authentication successful")
                return AuthenticationResult(
                    success=True,
                    tool=AuthenticationTool.PODMAN,
                    message="Successfully authenticated with podman"
                )
            else:
                error_msg = stderr.strip() or stdout.strip()
                self.logger.warning(f"Podman authentication failed: {error_msg}")
                return AuthenticationResult(
                    success=False,
                    tool=AuthenticationTool.PODMAN,
                    message="Podman authentication failed",
                    error=error_msg
                )
        
        except FileNotFoundError:
            error_msg = "Podman command not found. Please install podman."
            self.logger.error(error_msg)
            return AuthenticationResult(
                success=False,
                tool=AuthenticationTool.PODMAN,
                message="Podman not available",
                error=error_msg
            )
        
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            self.logger.error(f"Podman authentication error: {e}")
            return AuthenticationResult(
                success=False,
                tool=AuthenticationTool.PODMAN,
                message="Podman authentication error",
                error=error_msg
            )
    
    def authenticate_skopeo(self) -> AuthenticationResult:
        """
        Authenticate with the registry using skopeo.
        
        Returns:
            AuthenticationResult with success status and details
        """
        self.logger.info(f"Authenticating with skopeo to {self.config.registry_address}")
        
        try:
            # Build skopeo login command
            # Note: TLS flags must come before the registry address
            command = ["skopeo", "login"]
            
            # Add TLS verification flag before registry address
            if not self.config.tls_verify:
                command.append("--tls-verify=false")
            
            # Add certificate directory if SSL is enabled and cert path provided
            if self.config.protocol == RegistryProtocol.HTTPS and self.config.ssl_cert_path:
                command.extend(["--cert-dir", str(self.config.ssl_cert_path)])
            
            # Add registry address and credentials
            command.extend([
                self.config.registry_address,
                "-u", self.credentials.username,
                "--password-stdin"
            ])
            
            self.logger.debug(f"Skopeo command: {' '.join(command[:-1])} [password hidden]")
            
            # Execute skopeo login
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            stdout, stderr = process.communicate(input=self.credentials.password)
            
            if process.returncode == 0:
                self.logger.info("Skopeo authentication successful")
                return AuthenticationResult(
                    success=True,
                    tool=AuthenticationTool.SKOPEO,
                    message="Successfully authenticated with skopeo"
                )
            else:
                error_msg = stderr.strip() or stdout.strip()
                self.logger.warning(f"Skopeo authentication failed: {error_msg}")
                return AuthenticationResult(
                    success=False,
                    tool=AuthenticationTool.SKOPEO,
                    message="Skopeo authentication failed",
                    error=error_msg
                )
        
        except FileNotFoundError:
            error_msg = "Skopeo command not found. Skopeo is optional but recommended for image operations."
            self.logger.warning(error_msg)
            return AuthenticationResult(
                success=False,
                tool=AuthenticationTool.SKOPEO,
                message="Skopeo not available",
                error=error_msg
            )
        
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            self.logger.error(f"Skopeo authentication error: {e}")
            return AuthenticationResult(
                success=False,
                tool=AuthenticationTool.SKOPEO,
                message="Skopeo authentication error",
                error=error_msg
            )
    
    def authenticate_all(self, require_skopeo: bool = False, use_http: bool = False) -> List[AuthenticationResult]:
        """
        Authenticate with all available tools (podman and skopeo).
        
        Args:
            require_skopeo: If True, skopeo authentication failure will be treated as critical
            use_http: If True, use HTTP API authentication instead of podman (no podman dependency)
            
        Returns:
            List of AuthenticationResult for each tool
        """
        results = []
        
        # Authenticate with podman or HTTP API
        if use_http:
            self.logger.info("Using HTTP API authentication (no podman required)")
            auth_result = self.authenticate_http()
        else:
            auth_result = self.authenticate_podman()
        
        results.append(auth_result)
        
        if not auth_result.success:
            self.logger.error("Authentication failed - this is required")
            return results
        
        # Authenticate with skopeo (optional unless required)
        # Only if not using HTTP-only mode
        if not use_http:
            skopeo_result = self.authenticate_skopeo()
            results.append(skopeo_result)
            
            if not skopeo_result.success:
                if require_skopeo:
                    self.logger.error("Skopeo authentication failed - this is required for image operations")
                else:
                    self.logger.warning("Skopeo authentication failed - image copy operations may be affected")
        
        return results
    
    def verify_credentials(self) -> AuthenticationResult:
        """
        Verify credentials using HTTP API without requiring podman/skopeo.
        
        This is a convenience method that uses HTTP API authentication
        to validate credentials. It's useful for:
        - Pre-flight credential validation
        - Environments without podman/skopeo
        - Quick credential checks
        
        Returns:
            AuthenticationResult with success status
            
        Example:
            >>> config = RegistryConfig.from_url("https://registry.example.com")
            >>> creds = RegistryCredentials(username="user", password="pass")
            >>> authenticator = RegistryAuthenticator(config, creds, logger)
            >>> result = authenticator.verify_credentials()
            >>> if result.success:
            >>>     print("Credentials are valid!")
        """
        return self.authenticate_http()
    
    def display_results(self, reachability: Optional[ReachabilityResult] = None, 
                       auth_results: Optional[List[AuthenticationResult]] = None):
        """
        Display authentication and reachability results in a user-friendly format.
        
        Args:
            reachability: Optional reachability check result
            auth_results: Optional list of authentication results
        """
        if reachability:
            if reachability.reachable:
                status_text = Text()
                status_text.append("✓ Registry Reachable\n\n", style="bold green")
                status_text.append(f"URL: {self.config.url}\n", style="white")
                status_text.append(f"Method: {reachability.method.upper()}\n", style="cyan")
                if reachability.response_time_ms:
                    status_text.append(f"Response Time: {reachability.response_time_ms:.2f}ms\n", style="cyan")
                
                self.console.print(Panel(status_text, title="Registry Reachability", border_style="green"))
            else:
                status_text = Text()
                status_text.append("✗ Registry Unreachable\n\n", style="bold red")
                status_text.append(f"URL: {self.config.url}\n", style="white")
                if reachability.error:
                    status_text.append(f"Error: {reachability.error}\n", style="red")
                
                self.console.print(Panel(status_text, title="Registry Reachability", border_style="red"))
        
        if auth_results:
            for result in auth_results:
                if result.success:
                    status_text = Text()
                    status_text.append(f"✓ {result.tool.value.capitalize()} Authentication Successful\n", style="bold green")
                    status_text.append(f"{result.message}", style="white")
                    
                    self.console.print(Panel(status_text, border_style="green"))
                else:
                    status_text = Text()
                    status_text.append(f"✗ {result.tool.value.capitalize()} Authentication Failed\n\n", style="bold red")
                    status_text.append(f"{result.message}\n", style="white")
                    if result.error:
                        status_text.append(f"\nError: {result.error}", style="red")
                    
                    self.console.print(Panel(status_text, border_style="red"))


def check_tool_available(tool: str) -> bool:
    """
    Check if a container tool (podman/skopeo) is available.
    
    Args:
        tool: Tool name ('podman' or 'skopeo')
        
    Returns:
        True if tool is available, False otherwise
    """
    try:
        result = subprocess.run(
            [tool, "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

# Made with Bob
