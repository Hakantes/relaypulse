from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse
from typing import Tuple


BLOCKED_NETWORKS = [
    # Cloud instance metadata (AWS, GCP, Azure, DigitalOcean)
    ipaddress.ip_network("169.254.0.0/16"),
    # Current network / loopback
    ipaddress.ip_network("0.0.0.0/8"),
]

PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def validate_destination_url(url: str, allow_local: Optional[bool] = None) -> Tuple[bool, str]:
    """
    Validates a destination URL against SSRF, metadata endpoint abuse, and invalid schemes.
    Returns: (is_valid, error_message)
    """
    if not url or not isinstance(url, str):
        return False, "Destination URL must be a non-empty string."

    try:
        parsed = urlparse(url)
    except Exception as exc:
        return False, f"Malformed URL: {exc}"

    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"Unsupported URL scheme '{parsed.scheme}'. Only http and https are permitted."

    hostname = parsed.hostname
    if not hostname:
        return False, "Destination URL is missing a valid hostname."

    # Determine if local addresses are permitted (e.g. for development/testing)
    if allow_local is None:
        allow_local = os.getenv("RELAYPULSE_ALLOW_LOCAL", "true").lower() in ("true", "1", "yes")

    # Check if hostname is an IP literal
    try:
        ip = ipaddress.ip_address(hostname)
        for net in BLOCKED_NETWORKS:
            if ip in net:
                return False, f"Destination URL targets restricted network address: {ip}"

        if not allow_local:
            for net in PRIVATE_NETWORKS:
                if ip in net:
                    return False, f"Destination URL targets private/local network address: {ip}"
        return True, ""
    except ValueError:
        pass

    # Special hostname checks
    blocked_hostnames = {"metadata.google.internal", "instance-data"}
    if hostname.lower() in blocked_hostnames:
        return False, f"Destination URL targets restricted cloud metadata host: {hostname}"

    if not allow_local and hostname.lower() in ("localhost", "127.0.0.1", "::1"):
        return False, "Destination URL cannot target localhost in production mode."

    return True, ""
