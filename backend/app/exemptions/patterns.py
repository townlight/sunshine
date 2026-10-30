"""Compatibility imports for the shared Core PII detector."""
from civiccore.exemptions.patterns import (
    PIIPattern as PIIPattern,
    PIIMatch as PIIMatch,
    SSN_PATTERN as SSN_PATTERN,
    CREDIT_CARD_PATTERN as CREDIT_CARD_PATTERN,
    PHONE_PATTERN as PHONE_PATTERN,
    EMAIL_PATTERN as EMAIL_PATTERN,
    BANK_ROUTING_PATTERN as BANK_ROUTING_PATTERN,
    BANK_ACCOUNT_PATTERN as BANK_ACCOUNT_PATTERN,
    DRIVERS_LICENSE_PATTERNS as DRIVERS_LICENSE_PATTERNS,
    UNIVERSAL_PATTERNS as UNIVERSAL_PATTERNS,
    _luhn_check as _luhn_check,
    scan_text as scan_text,
)
