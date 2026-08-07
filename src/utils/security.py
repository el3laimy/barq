"""
Security and Redaction Utilities for Barq Download Manager.
Protects user credentials, session cookies, and authentication tokens from appearing in logs or export diagnostics.
"""

import re
from typing import Any, Dict, Union

SECRET_KEYWORDS = {'cookie', 'cookies', 'token', 'auth', 'authorization', 'password', 'secret', 'key', 'session', 'bearer'}

def redact_sensitive_data(data: Any) -> Any:
    """
    Recursively redacts sensitive values from dictionaries, lists, strings, and URLs.
    """
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if any(kw in str(k).lower() for kw in SECRET_KEYWORDS):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = redact_sensitive_data(v)
        return sanitized
    elif isinstance(data, list):
        return [redact_sensitive_data(item) for item in data]
    elif isinstance(data, str):
        # Redact query string secrets (e.g. ?token=12345 or &key=abc)
        return re.sub(
            r'([?&](?:token|key|access_token|auth|password|secret|session)=)[^&]+',
            r'\1[REDACTED]',
            data,
            flags=re.IGNORECASE
        )
    return data


def sanitize_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """
    Sanitizes HTTP Headers dictionary for logging or debugging output.
    """
    sanitized = {}
    for key, val in headers.items():
        if key.lower() in {'cookie', 'authorization', 'proxy-authorization', 'x-api-key'}:
            sanitized[key] = "[REDACTED_HEADER]"
        else:
            sanitized[key] = val
    return sanitized
