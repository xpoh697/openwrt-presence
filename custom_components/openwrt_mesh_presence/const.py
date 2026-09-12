"""Constants for OpenWrt Mesh Presence integration."""

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
CONF_DEVICE_NAMES: Final = "device_names"

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
PLATFORMS: Final = ["device_tracker", "sensor", "binary_sensor"]
