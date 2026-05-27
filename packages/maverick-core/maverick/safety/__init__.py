"""Safety utilities for Maverick.

Currently:
  - ``secret_detector``: regex-based credential scrubbing for tool outputs.
  - ``consent``: prompt the user before destructive actions; ledger
    of granted approvals.
  - ``tool_acl``: allow-list / deny-list filtering of registered tools.

This package is intentionally lightweight (no fancy ML deps). Heavier
classifiers live behind optional extras and are loaded on demand.
"""
from .consent import (  # noqa: F401
    ConsentDecision,
    ConsentDenied,
    grant_persistent,
    list_grants,
    require_consent,
    revoke,
)
from .pii_detector import PIIMatch  # noqa: F401
from .pii_detector import redact as pii_redact  # noqa: F401
from .pii_detector import scan as pii_scan  # noqa: F401
from .secret_detector import SecretMatch, redact, scan  # noqa: F401
from .tool_acl import apply_to_registry, filter_tools  # noqa: F401


__all__ = [
    "redact", "scan", "SecretMatch",
    "pii_redact", "pii_scan", "PIIMatch",
    "ConsentDecision", "ConsentDenied", "require_consent",
    "grant_persistent", "revoke", "list_grants",
    "filter_tools", "apply_to_registry",
]
