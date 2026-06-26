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
LDAP Distinguished Name (DN) Validator

This module provides comprehensive validation for LDAP Distinguished Names (DNs)
according to RFC 4514 and RFC 2253 standards. It validates DN syntax, structure,
and common LDAP attribute types.

DN Format Examples:
- cn=John Doe,ou=Users,dc=example,dc=com
- uid=jdoe,ou=People,o=MyOrg,c=US
- CN=Admin User,OU=IT Department,DC=corp,DC=example,DC=com
"""

import re
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class DNValidationResult:
    """Result of DN validation."""
    is_valid: bool
    error_message: Optional[str] = None
    normalized_dn: Optional[str] = None
    components: Optional[List[Tuple[str, str]]] = None


class DNValidator:
    """
    Validator for LDAP Distinguished Names (DNs).
    
    Validates DN syntax according to RFC 4514 and RFC 2253 standards.
    Supports common LDAP attribute types and proper escaping.
    """
    
    # Common LDAP attribute types (case-insensitive)
    VALID_ATTRIBUTE_TYPES = {
        'cn', 'commonname',           # Common Name
        'ou', 'organizationalunitname',  # Organizational Unit
        'o', 'organizationname',      # Organization
        'dc', 'domaincomponent',      # Domain Component
        'uid', 'userid',              # User ID
        'c', 'countryname',           # Country
        'l', 'localityname',          # Locality
        'st', 'stateorprovincename',  # State or Province
        'street', 'streetaddress',    # Street Address
        'sn', 'surname',              # Surname
        'givenname',                  # Given Name
        'initials',                   # Initials
        'generationqualifier',        # Generation Qualifier
        'title',                      # Title
        'description',                # Description
        'mail', 'email',              # Email Address
        'telephoneNumber',            # Telephone Number
        'postalcode',                 # Postal Code
        'postaladdress',              # Postal Address
        'serialnumber',               # Serial Number
        'distinguishedname',          # Distinguished Name
        'member',                     # Member
        'uniquemember',               # Unique Member
        'objectclass',                # Object Class
    }
    
    # Regex patterns for DN validation
    # Attribute type: letters, digits, hyphens (must start with letter)
    ATTR_TYPE_PATTERN = r'[a-zA-Z][a-zA-Z0-9\-]*'
    
    # Attribute value: can contain escaped special chars, spaces, etc.
    # Special chars that need escaping: , + " \ < > ; = and leading/trailing spaces
    ATTR_VALUE_PATTERN = r'(?:[^,+\"\\<>;=]|\\[,+\"\\<>;=#\s]|\\[0-9a-fA-F]{2})+'
    
    # Complete RDN pattern (Relative Distinguished Name)
    RDN_PATTERN = rf'({ATTR_TYPE_PATTERN})\s*=\s*({ATTR_VALUE_PATTERN})'
    
    # Complete DN pattern (multiple RDNs separated by commas)
    DN_PATTERN = rf'^{RDN_PATTERN}(?:\s*,\s*{RDN_PATTERN})*$'
    
    def __init__(self, strict_mode: bool = False):
        """
        Initialize DN validator.
        
        Args:
            strict_mode: If True, only allow standard LDAP attribute types.
                        If False, allow custom attribute types.
        """
        self.strict_mode = strict_mode
        self.dn_regex = re.compile(self.DN_PATTERN)
        self.rdn_regex = re.compile(self.RDN_PATTERN)
    
    def validate(self, dn: str) -> DNValidationResult:
        """
        Validate a Distinguished Name.
        
        Args:
            dn: The DN string to validate
            
        Returns:
            DNValidationResult with validation status and details
        """
        if not dn or not isinstance(dn, str):
            return DNValidationResult(
                is_valid=False,
                error_message="DN cannot be empty or None"
            )
        
        # Remove leading/trailing whitespace
        dn = dn.strip()
        
        # Check for placeholder values
        if dn in ['<Required>', '<Optional>', '']:
            return DNValidationResult(
                is_valid=False,
                error_message="DN contains placeholder value '<Required>' or '<Optional>'"
            )
        
        # Basic format validation
        if not self.dn_regex.match(dn):
            return DNValidationResult(
                is_valid=False,
                error_message=self._get_format_error_message(dn)
            )
        
        # Parse and validate individual RDNs
        components = self._parse_dn(dn)
        if components is None:
            return DNValidationResult(
                is_valid=False,
                error_message="Failed to parse DN components"
            )
        
        # Validate attribute types
        for attr_type, attr_value in components:
            if self.strict_mode:
                if attr_type.lower() not in self.VALID_ATTRIBUTE_TYPES:
                    return DNValidationResult(
                        is_valid=False,
                        error_message=f"Unknown LDAP attribute type: '{attr_type}'. "
                                    f"Common types: cn, ou, dc, uid, o, c"
                    )
            
            # Validate attribute value is not empty
            if not attr_value or attr_value.strip() == '':
                return DNValidationResult(
                    is_valid=False,
                    error_message=f"Empty value for attribute '{attr_type}'"
                )
        
        # Normalize DN (consistent spacing, case)
        normalized = self._normalize_dn(components)
        
        return DNValidationResult(
            is_valid=True,
            normalized_dn=normalized,
            components=components
        )
    
    def _parse_dn(self, dn: str) -> Optional[List[Tuple[str, str]]]:
        """
        Parse DN into list of (attribute_type, attribute_value) tuples.
        
        Args:
            dn: The DN string to parse
            
        Returns:
            List of (attr_type, attr_value) tuples, or None if parsing fails
        """
        components = []
        
        # Split by commas (but not escaped commas)
        rdns = self._split_dn(dn)
        
        for rdn in rdns:
            match = self.rdn_regex.match(rdn.strip())
            if not match:
                return None
            
            attr_type = match.group(1).strip()
            attr_value = match.group(2).strip()
            
            # Unescape special characters in value
            attr_value = self._unescape_value(attr_value)
            
            components.append((attr_type, attr_value))
        
        return components
    
    def _split_dn(self, dn: str) -> List[str]:
        """
        Split DN by commas, respecting escaped commas.
        
        Args:
            dn: The DN string to split
            
        Returns:
            List of RDN strings
        """
        rdns = []
        current_rdn = []
        i = 0
        
        while i < len(dn):
            char = dn[i]
            
            if char == '\\' and i + 1 < len(dn):
                # Escaped character - include both backslash and next char
                current_rdn.append(char)
                current_rdn.append(dn[i + 1])
                i += 2
            elif char == ',':
                # Unescaped comma - end of RDN
                rdns.append(''.join(current_rdn))
                current_rdn = []
                i += 1
            else:
                current_rdn.append(char)
                i += 1
        
        # Add the last RDN
        if current_rdn:
            rdns.append(''.join(current_rdn))
        
        return rdns
    
    def _unescape_value(self, value: str) -> str:
        """
        Unescape special characters in attribute value.
        
        Args:
            value: The escaped attribute value
            
        Returns:
            Unescaped value
        """
        # Replace escaped special characters
        replacements = {
            r'\,': ',',
            r'\+': '+',
            r'\"': '"',
            r'\\': '\\',
            r'\<': '<',
            r'\>': '>',
            r'\;': ';',
            r'\=': '=',
            r'\#': '#',
        }
        
        result = value
        for escaped, unescaped in replacements.items():
            result = result.replace(escaped, unescaped)
        
        return result
    
    def _normalize_dn(self, components: List[Tuple[str, str]]) -> str:
        """
        Normalize DN to consistent format.
        
        Args:
            components: List of (attr_type, attr_value) tuples
            
        Returns:
            Normalized DN string
        """
        normalized_rdns = []
        
        for attr_type, attr_value in components:
            # Normalize attribute type to lowercase
            normalized_rdns.append(f"{attr_type.lower()}={attr_value}")
        
        return ','.join(normalized_rdns)
    
    def _get_format_error_message(self, dn: str) -> str:
        """
        Generate helpful error message for DN format issues.
        
        Args:
            dn: The invalid DN string
            
        Returns:
            Descriptive error message
        """
        # Check for common issues
        if '=' not in dn:
            return "DN must contain '=' to separate attribute types and values"
        
        if dn.startswith(',') or dn.endswith(','):
            return "DN cannot start or end with a comma"
        
        if ',,' in dn:
            return "DN cannot contain consecutive commas"
        
        if not any(c.isalpha() for c in dn.split('=')[0]):
            return "DN must start with a valid attribute type (e.g., cn, ou, dc)"
        
        # Check for unescaped special characters
        special_chars = ['+', '"', '\\', '<', '>', ';']
        for char in special_chars:
            if char in dn and f'\\{char}' not in dn:
                return f"Special character '{char}' must be escaped with backslash (\\{char})"
        
        return (
            "Invalid DN format. Expected format: "
            "attribute=value,attribute=value,... "
            "(e.g., cn=John Doe,ou=Users,dc=example,dc=com)"
        )
    
    def get_dn_examples(self) -> List[str]:
        """
        Get example DNs for documentation.
        
        Returns:
            List of valid DN examples
        """
        return [
            "cn=John Doe,ou=Users,dc=example,dc=com",
            "uid=jdoe,ou=People,o=MyOrg,c=US",
            "CN=Admin User,OU=IT Department,DC=corp,DC=example,DC=com",
            "cn=Service Account,ou=Applications,ou=Services,dc=company,dc=local",
            "uid=admin,cn=users,cn=accounts,dc=ipa,dc=example,dc=com",
        ]


def validate_dn(dn: str, strict_mode: bool = False) -> DNValidationResult:
    """
    Convenience function to validate a DN.
    
    Args:
        dn: The DN string to validate
        strict_mode: If True, only allow standard LDAP attribute types
        
    Returns:
        DNValidationResult with validation status and details
    """
    validator = DNValidator(strict_mode=strict_mode)
    return validator.validate(dn)


# Made with Bob