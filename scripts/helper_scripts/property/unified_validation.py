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
Unified Validation Display System

This module provides a unified rich terminal display for ALL validation issues:
- Property file validation errors
- SSL certificate issues
- Masterkey issues
- Database password issues
- Naming convention issues
- And more

All issues are displayed in a single, cohesive rich UI with remediation guidance.
"""

from typing import Dict, List, Any, Optional, Tuple
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich.columns import Columns


class UnifiedValidationDisplay:
    """
    Unified display system for all validation issues.
    
    This class collects all validation issues from various sources and displays
    them in a single, cohesive rich terminal UI with comprehensive remediation guidance.
    """
    
    def __init__(self, console: Optional[Console] = None):
        """Initialize the unified validation display."""
        self.console = console or Console()
        self.issues: List[Dict[str, Any]] = []
        self.has_errors = False
    
    def add_property_validation_errors(self, prop_reader, file_type: str) -> None:
        """
        Add property validation errors from a property reader.
        
        Args:
            prop_reader: Property reader instance (ReadPropDb, ReadPropLdap, etc.) or None
            file_type: Type of property file (e.g., "Database", "LDAP", "IDP")
        """
        # Skip if property reader is None (file doesn't exist)
        if prop_reader is None:
            return
            
        if prop_reader.missing_required_fields():
            self.has_errors = True
            for error in prop_reader.get_validation_errors():
                self.issues.append({
                    'category': 'Property Validation',
                    'type': file_type,
                    'severity': 'high',
                    'field': error.get('loc', ['unknown'])[-1],
                    'message': error.get('msg', 'Unknown error'),
                    'location': ' → '.join(str(l) for l in error.get('loc', [])),
                    'file': str(prop_reader._prop_filepath.name),
                    'remediation': self._get_property_remediation(error)
                })
    
    def add_certificate_issues(self, missing_certs: Dict[str, List[str]], 
                              incorrect_certs: Dict[str, List[str]]) -> None:
        """
        Add SSL certificate validation issues.
        
        Args:
            missing_certs: Dictionary of missing certificates by connection
            incorrect_certs: Dictionary of incorrect certificates by connection
        """
        if missing_certs:
            self.has_errors = True
            for connection, cert_list in missing_certs.items():
                for cert in cert_list:
                    self.issues.append({
                        'category': 'SSL Certificates',
                        'type': 'Missing Certificate',
                        'severity': 'high',
                        'field': connection,
                        'message': f'Missing certificate: {cert}',
                        'location': f'{connection} → {cert}',
                        'file': 'ssl-certs/',
                        'remediation': {
                            'error': f'Missing SSL certificate for {connection}',
                            'fix': f'Add the certificate file "{cert}" to ./propertyFile/ssl-certs/{connection}/',
                            'example': f'# Obtain the certificate from your {connection} server\n'
                                     f'# Copy it to: ./propertyFile/ssl-certs/{connection}/{cert}'
                        }
                    })
        
        if incorrect_certs:
            self.has_errors = True
            for connection, cert_list in incorrect_certs.items():
                for cert in cert_list:
                    self.issues.append({
                        'category': 'SSL Certificates',
                        'type': 'Incorrect Certificate',
                        'severity': 'medium',
                        'field': connection,
                        'message': f'Incorrect certificate format: {cert}',
                        'location': f'{connection} → {cert}',
                        'file': 'ssl-certs/',
                        'remediation': {
                            'error': f'Certificate format issue for {connection}',
                            'fix': f'Verify the certificate file "{cert}" is in correct PEM format',
                            'example': '# Certificate should start with:\n'
                                     '-----BEGIN CERTIFICATE-----\n'
                                     '# And end with:\n'
                                     '-----END CERTIFICATE-----'
                        }
                    })
    
    def add_connection_issue(self, cluster_connected: bool) -> None:
        """Add Kubernetes/OpenShift cluster connection issue."""
        if not cluster_connected:
            self.has_errors = True
            self.issues.append({
                'category': 'Environment',
                'type': 'Cluster Connection',
                'severity': 'critical',
                'field': 'connection',
                'message': 'Kubernetes/OpenShift cluster is not connected',
                'location': 'Cluster context',
                'file': 'Environment',
                'remediation': {
                    'error': 'No active Kubernetes/OpenShift cluster connection detected',
                    'fix': 'Log in to your cluster and verify the active kube context before rerunning the command',
                    'example': '# Example\noc login --server=<cluster-url> --token=<token>\noc project <namespace>\noc whoami'
                }
            })

    def add_masterkey_issue(self, masterkey_present: bool) -> None:
        """Add masterkey validation issue if not present."""
        if not masterkey_present:
            self.has_errors = True
            self.issues.append({
                'category': 'Security',
                'type': 'Missing Masterkey',
                'severity': 'critical',
                'field': 'MASTERKEY_FILE',
                'message': 'Masterkey file is missing',
                'location': 'propertyFile/ssl-certs/',
                'file': 'ssl-certs/',
                'remediation': {
                    'error': 'Masterkey file not found',
                    'fix': 'Create a masterkey file in ./propertyFile/ssl-certs/',
                    'example': '# Generate a secure masterkey:\n'
                             'openssl rand -base64 32 > ./propertyFile/ssl-certs/masterkey.txt'
                }
            })
    
    def add_keystore_password_issue(self, keystore_password_valid: bool, fips_enabled: bool) -> None:
        """Add keystore password validation issue."""
        if not keystore_password_valid and fips_enabled:
            self.has_errors = True
            self.issues.append({
                'category': 'Security',
                'type': 'Invalid Keystore Password',
                'severity': 'high',
                'field': 'KEYSTORE_PASSWORD',
                'message': 'Keystore password must be at least 16 characters when FIPS is enabled',
                'location': 'fncm_user_group.toml → KEYSTORE_PASSWORD',
                'file': 'fncm_user_group.toml',
                'remediation': {
                    'error': 'Keystore password too short for FIPS mode',
                    'fix': 'Set KEYSTORE_PASSWORD to at least 16 characters in fncm_user_group.toml',
                    'example': 'KEYSTORE_PASSWORD = "YourSecurePassword123!"  # At least 16 characters'
                }
            })
    
    def add_database_password_issues(self, invalid_db_passwords: List[str]) -> None:
        """Add database password validation issues."""
        for db_name in invalid_db_passwords:
            self.has_errors = True
            self.issues.append({
                'category': 'Security',
                'type': 'Invalid Database Password',
                'severity': 'high',
                'field': f'{db_name}_PASSWORD',
                'message': f'Database password for {db_name} contains invalid characters',
                'location': f'fncm_db_server.toml → {db_name} → DATABASE_PASSWORD',
                'file': 'fncm_db_server.toml',
                'remediation': {
                    'error': f'Invalid characters in {db_name} database password',
                    'fix': 'Remove special characters that may cause issues (e.g., quotes, backslashes)',
                    'example': '# Use alphanumeric and safe special characters:\n'
                             'DATABASE_PASSWORD = "SecurePass123!@#"'
                }
            })
    
    def add_ssl_mode_issue(self, correct_ssl_mode: bool) -> None:
        """Add SSL mode validation issue."""
        if not correct_ssl_mode:
            self.has_errors = True
            self.issues.append({
                'category': 'Configuration',
                'type': 'Invalid SSL Mode',
                'severity': 'medium',
                'field': 'SSL_MODE',
                'message': 'SSL_MODE is required when DATABASE_SSL_ENABLE is true for PostgreSQL',
                'location': 'fncm_db_server.toml → SSL_MODE',
                'file': 'fncm_db_server.toml',
                'remediation': {
                    'error': 'Missing or invalid SSL_MODE for PostgreSQL',
                    'fix': 'Set SSL_MODE to one of: require, verify-ca, verify-full',
                    'example': 'SSL_MODE = "verify-full"  # Most secure option'
                }
            })
    
    def add_naming_convention_issues(self, incorrect_naming: List[str]) -> None:
        """Add naming convention validation issues."""
        for item in incorrect_naming:
            self.has_errors = True
            self.issues.append({
                'category': 'Configuration',
                'type': 'Naming Convention',
                'severity': 'low',
                'field': item,
                'message': f'Item "{item}" does not follow naming conventions',
                'location': 'Various property files',
                'file': 'property files',
                'remediation': {
                    'error': 'Naming convention violation',
                    'fix': 'Follow IBM Content Cortex naming conventions (alphanumeric, underscores, hyphens)',
                    'example': '# Good: my_database_01, ldap-server-1\n'
                             '# Bad: my database!, ldap@server'
                }
            })
    
    def _get_property_remediation(self, error: Dict[str, Any]) -> Dict[str, str]:
        """Get remediation guidance for property validation errors."""
        field = error.get('loc', ['unknown'])[-1]
        msg = error.get('msg', '')
        
        # Map common errors to remediation
        remediation_map = {
            'DATABASE_TYPE': {
                'error': 'Invalid database type',
                'fix': 'Use one of: db2, db2hadr, db2rds, db2rdshadr, oracle, postgresql, sqlserver',
                'example': 'DATABASE_TYPE = "postgresql"'
            },
            'LDAP_TYPE': {
                'error': 'Invalid LDAP type',
                'fix': 'Use one of: Microsoft Active Directory, IBM Tivoli Directory Server, CA eTrust, Novell eDirectory, Oracle Internet Directory',
                'example': 'LDAP_TYPE = "Microsoft Active Directory"'
            },
            'WATSONX_DEPLOYMENT_TYPE': {
                'error': 'Invalid WatsonX deployment type',
                'fix': 'Use either "saas" or "lightweightengine"',
                'example': 'WATSONX_DEPLOYMENT_TYPE = "saas"'
            },
        }
        
        # Check for DN validation errors
        if any(dn_field in field for dn_field in ['BASE_DN', 'BIND_DN', 'GROUP_BASE_DN']):
            if 'format' in msg.lower() or 'invalid' in msg.lower():
                return {
                    'error': 'Invalid Distinguished Name (DN) format',
                    'fix': 'Use proper LDAP DN format: attribute=value,attribute=value,...',
                    'example': f'{field} = "cn=admin,ou=Users,dc=example,dc=com"\n'
                             f'# See DN_VALIDATION.md for detailed DN format requirements'
                }
        
        # Check for specific field remediation
        for key, remediation in remediation_map.items():
            if key in field:
                return remediation
        
        # Default remediation
        if '<Required>' in msg or 'required' in msg.lower():
            return {
                'error': 'Required field not filled',
                'fix': 'Replace "<Required>" with an actual value',
                'example': f'{field} = "your-value-here"'
            }
        
        return {
            'error': msg,
            'fix': f'Check the property file documentation for valid values for {field}',
            'example': f'# Refer to the property file guide for {field} configuration'
        }
    
    def display(self) -> bool:
        """
        Display all validation issues in a unified rich UI.
        
        Returns:
            True if there are errors, False otherwise
        """
        if not self.has_errors:
            return False
        
        # Compact header
        self.console.print()
        self.console.print(f"[bold red]✗ Validation Failed:[/bold red] [yellow]{len(self.issues)} issue(s) found[/yellow]")
        self.console.print()
        
        # Group issues by category
        issues_by_category = {}
        for issue in self.issues:
            category = issue['category']
            if category not in issues_by_category:
                issues_by_category[category] = []
            issues_by_category[category].append(issue)
        
        # Display all issues grouped by file
        for category, category_issues in issues_by_category.items():
            self._display_category_by_file(category, category_issues)
        
        # Compact summary
        self.console.print(f"[bold yellow]⚠[/bold yellow] [yellow]Fix all issues above before proceeding[/yellow]")
        self.console.print()
        
        return True
    
    def _display_category_by_file(self, category: str, issues: List[Dict[str, Any]]) -> None:
        """Display issues grouped by file and issue type for maximum compactness."""
        self.console.print(f"[bold cyan]📋 {category}[/bold cyan] ([yellow]{len(issues)} issues[/yellow])")
        
        # Group issues by file
        issues_by_file = {}
        for issue in issues:
            file = issue.get('file', 'Unknown')
            if file not in issues_by_file:
                issues_by_file[file] = []
            issues_by_file[file].append(issue)
        
        # Display each file's issues grouped by issue type
        for file, file_issues in issues_by_file.items():
            self.console.print(f"\n[bold white]{file}[/bold white] ([yellow]{len(file_issues)} issues[/yellow])")
            
            # Special handling for AI services providers - group by provider
            if file == 'aiservices_providers.toml':
                self._display_aiservices_provider_issues(file_issues)
            else:
                # Standard display: group by issue message
                issues_by_message = {}
                for issue in file_issues:
                    msg = issue['message']
                    if msg not in issues_by_message:
                        issues_by_message[msg] = []
                    issues_by_message[msg].append(issue)
                
                # Display each unique issue type with its fields
                for msg, msg_issues in issues_by_message.items():
                    # Show issue type once
                    severity_icon = {
                        'critical': '🔴',
                        'high': '🟠',
                        'medium': '🟡',
                        'low': '🟢'
                    }.get(msg_issues[0]['severity'], '⚪')
                    
                    self.console.print(f"  {severity_icon} [dim]{msg}[/dim]")
                    
                    # List all fields with this issue as bullets
                    for issue in msg_issues:
                        self.console.print(f"     • [magenta]{issue['field']}[/magenta]")
        
        # Add remediation note for property validation
        if category == "Property Validation":
            self.console.print("\n[dim cyan]💡 Tip: Replace all '<Required>' placeholders with actual values[/dim cyan]")
        elif category == "Environment":
            self.console.print(
                "\n[dim cyan]💡 Tip: Verify your cluster login, current context, and namespace before rerunning[/dim cyan]"
            )
        
        self.console.print()
    
    def _display_aiservices_provider_issues(self, issues: List[Dict[str, Any]]) -> None:
        """
        Display AI services provider issues grouped by provider for better organization.
        
        Args:
            issues: List of issues for aiservices_providers.toml
        """
        # Group issues by provider (extract from location path)
        issues_by_provider = {}
        for issue in issues:
            location = issue.get('location', '')
            # Location format is like "PROVIDER_1 → MODEL_1 → API_KEY"
            parts = location.split(' → ')
            provider = parts[0] if parts else 'Unknown'
            
            if provider not in issues_by_provider:
                issues_by_provider[provider] = []
            issues_by_provider[provider].append(issue)
        
        # Display issues grouped by provider
        for provider, provider_issues in sorted(issues_by_provider.items()):
            # Group by message type within each provider
            issues_by_message = {}
            for issue in provider_issues:
                msg = issue['message']
                if msg not in issues_by_message:
                    issues_by_message[msg] = []
                issues_by_message[msg].append(issue)
            
            # Display provider header with issue count
            self.console.print(f"  [bold cyan]📦 {provider}[/bold cyan] ([yellow]{len(provider_issues)} issue(s)[/yellow])")
            
            # Display each unique issue type with its fields
            for msg, msg_issues in issues_by_message.items():
                severity_icon = {
                    'critical': '🔴',
                    'high': '🟠',
                    'medium': '🟡',
                    'low': '🟢'
                }.get(msg_issues[0]['severity'], '⚪')
                
                self.console.print(f"    {severity_icon} [dim]{msg}[/dim]")
                
                # List all fields with this issue, showing the path within the provider
                for issue in msg_issues:
                    location = issue.get('location', '')
                    parts = location.split(' → ')
                    # Skip the provider name (first part) and show the rest
                    field_path = ' → '.join(parts[1:]) if len(parts) > 1 else issue['field']
                    self.console.print(f"       • [magenta]{field_path}[/magenta]")

# Made with Bob
