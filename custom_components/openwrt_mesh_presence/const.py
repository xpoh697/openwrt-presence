"""Constants for OpenWrt Mesh Presence integration."""

from __future__ import annotations

import re
from typing import Final

DOMAIN: Final = "openwrt_mesh_presence"

# Configuration keys
CONF_ROUTERS: Final = "routers"
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_SSL: Final = "ssl"
CONF_VERIFY_SSL: Final = "verify_ssl"
CONF_NAME: Final = "name"
CONF_NODE_ID: Final = "node_id"

CONF_POLL_INTERVAL: Final = "poll_interval"
CONF_ROAMING_GRACE_PERIOD: Final = "roaming_grace_period"
CONF_TRACKING_MODE: Final = "tracking_mode"
CONF_TRACKED_MACS: Final = "tracked_macs"
CONF_MANUAL_MACS: Final = "manual_macs"
CONF_DEVICE_NAMES: Final = "device_names"
CONF_DEVICE_NAMES_TEXT: Final = "device_names_text"

# Tracking Modes
TRACK_MODE_SELECTED: Final = "selected"
TRACK_MODE_ALL: Final = "all"

# Default values
DEFAULT_PORT: Final = 80
DEFAULT_SSL_PORT: Final = 443
DEFAULT_USERNAME: Final = "root"
DEFAULT_SSL: Final = False
DEFAULT_VERIFY_SSL: Final = False
DEFAULT_POLL_INTERVAL: Final = 5  # seconds
DEFAULT_ROAMING_GRACE_PERIOD: Final = 15  # seconds
DEFAULT_REQUEST_TIMEOUT: Final = 4  # seconds
DEFAULT_DEVICE_EXPIRY_HOURS: Final = 24  # prune inactive MACs after 24h

# Platforms
PLATFORMS: Final = ["device_tracker", "sensor", "binary_sensor", "button"]


def normalize_mac(raw_mac: str) -> str | None:
    """Normalize any MAC address string to standard XX:XX:XX:XX:XX:XX format."""
    if not raw_mac:
        return None
    # Extract all hex characters
    clean = re.sub(r"[^0-9A-Fa-f]", "", raw_mac).upper()
    if len(clean) != 12:
        return None
    return ":".join(clean[i : i + 2] for i in range(0, 12, 2))


def parse_mac_list(raw_input: str | list[str] | None) -> set[str]:
    """Parse a list or string of MAC addresses and return a normalized set."""
    if not raw_input:
        return set()

    result: set[str] = set()
    if isinstance(raw_input, list):
        for item in raw_input:
            norm = normalize_mac(str(item))
            if norm:
                result.add(norm)
    elif isinstance(raw_input, str):
        # Split by comma, semicolon, whitespace, newline
        tokens = re.split(r"[,;\s\n\r]+", raw_input)
        for token in tokens:
            norm = normalize_mac(token)
            if norm:
                result.add(norm)
    return result


def parse_name_mapping(raw_text: str | dict[str, str] | None) -> dict[str, str]:
    """Parse custom name mapping string like 'AA:BB:CC:DD:EE:FF=Phone, 11:22:33:44:55:66=Laptop'."""
    if not raw_text:
        return {}
    if isinstance(raw_text, dict):
        return {normalize_mac(k) or k.upper(): str(v).strip() for k, v in raw_text.items() if str(v).strip()}

    mapping: dict[str, str] = {}
    lines = re.split(r"[,;\n\r]+", str(raw_text))
    for line in lines:
        line = line.strip()
        if "=" in line:
            parts = line.split("=", 1)
            norm = normalize_mac(parts[0].strip())
            name = parts[1].strip()
            if norm and name:
                mapping[norm] = name
        elif ":" in line and not line.count(":") == 5:
            parts = line.split(":", 1)
            norm = normalize_mac(parts[0].strip())
            name = parts[1].strip()
            if norm and name:
                mapping[norm] = name
    return mapping
