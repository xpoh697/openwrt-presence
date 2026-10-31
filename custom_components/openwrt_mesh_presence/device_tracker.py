"""Device tracker platform for OpenWrt Mesh Presence."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import ScannerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DeviceState, OpenWrtMeshCoordinator, UserState

_LOGGER = logging.getLogger(__name__)


def _get_shared_device_info(coordinator: OpenWrtMeshCoordinator) -> DeviceInfo:
    """Return unified DeviceInfo linking all entities to ONE main device."""
    first_host = coordinator.clients[0].host if coordinator.clients else None
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.entry.entry_id)},
        name="OpenWrt Mesh Presence",
        manufacturer="OpenWrt",
        model="Mesh Presence Hub",
        sw_version="1.0.0",
        configuration_url=f"http://{first_host}" if first_host else None,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up device tracker entities based on a config entry."""
    coordinator: OpenWrtMeshCoordinator = hass.data[DOMAIN][entry.entry_id]

    tracked_device_entities: dict[str, OpenWrtDeviceTracker] = {}
    tracked_user_entities: dict[str, OpenWrtUserDeviceTracker] = {}

    @callback
    def _update_entities() -> None:
        """Add new device trackers or user trackers dynamically."""
        new_entities: list[ScannerEntity] = []

        # 1. User trackers (aggregating multiple MACs per person)
        for user_id in coordinator.data.users:
            if user_id not in tracked_user_entities:
                entity = OpenWrtUserDeviceTracker(coordinator, user_id)
                tracked_user_entities[user_id] = entity
                new_entities.append(entity)

        # 2. Standalone device trackers (single MACs not in user groups)
        for mac in coordinator.data.devices:
            if mac not in tracked_device_entities and coordinator.is_device_tracked(mac):
                # If MAC belongs to an aggregated user group, skip standalone tracker
                if not any(mac in u.macs for u in coordinator.data.users.values()):
                    entity = OpenWrtDeviceTracker(coordinator, mac)
                    tracked_device_entities[mac] = entity
                    new_entities.append(entity)

        if new_entities:
            async_add_entities(new_entities)

    coordinator.register_new_device_callback(_update_entities)
    _update_entities()

    # Clean up device trackers for devices/users that were removed
    ent_reg = er.async_get(hass)
    entries = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    for reg_entry in entries:
        if reg_entry.domain == "device_tracker":
            unique_id = reg_entry.unique_id
            if unique_id.startswith("openwrt_user_tracker_"):
                # Format: openwrt_user_tracker_{user_id}_{entry_id}
                prefix = "openwrt_user_tracker_"
                suffix = f"_{entry.entry_id}"
                if unique_id.endswith(suffix):
                    user_id = unique_id[len(prefix) : -len(suffix)]
                    if user_id not in coordinator.data.users:
                        _LOGGER.info("Removing obsolete user tracker entity %s for user %s", reg_entry.entity_id, user_id)
                        ent_reg.async_remove(reg_entry.entity_id)
            elif unique_id.startswith("openwrt_tracker_"):
                clean_mac = unique_id.replace("openwrt_tracker_", "")
                mac = clean_mac.replace("_", ":").upper()
                # Remove if not tracked or if moved into a user group
                is_in_user = any(mac in u.macs for u in coordinator.data.users.values())
                if not coordinator.is_device_tracked(mac) or is_in_user:
                    _LOGGER.info("Removing obsolete standalone tracker entity %s for MAC %s", reg_entry.entity_id, mac)
                    ent_reg.async_remove(reg_entry.entity_id)


class OpenWrtUserDeviceTracker(CoordinatorEntity[OpenWrtMeshCoordinator], ScannerEntity):
    """Represents an aggregated user (tracking multiple MACs across 2.4/5GHz)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OpenWrtMeshCoordinator, user_id: str) -> None:
        """Initialize the user device tracker entity."""
        super().__init__(coordinator)
        self._user_id = user_id
        self._attr_unique_id = f"openwrt_user_tracker_{self._user_id}_{coordinator.entry.entry_id}"

    @property
    def device_info(self) -> DeviceInfo:
        """Link to the single unified device."""
        return _get_shared_device_info(self.coordinator)

    @property
    def _current_user(self) -> UserState | None:
        """Get current state of the user from coordinator."""
        return self.coordinator.data.users.get(self._user_id)

    @property
    def name(self) -> str:
        """Return friendly user name."""
        user = self._current_user
        return user.name if user else self._user_id

    @property
    def source_type(self) -> SourceType:
        """Return the source type of the device tracker."""
        return SourceType.ROUTER

    @property
    def is_connected(self) -> bool:
        """Return true if any associated MAC is connected to mesh."""
        user = self._current_user
        return user.is_home if user else False

    @property
    def mac_address(self) -> str:
        """Return active MAC or primary MAC."""
        user = self._current_user
        if user and user.active_mac:
            return user.active_mac
        if user and user.macs:
            return user.macs[0]
        return ""

    @property
    def hostname(self) -> str | None:
        """Return friendly name."""
        user = self._current_user
        return user.name if user else None

    @property
    def ip_address(self) -> str | None:
        """Return IP address of active device."""
        user = self._current_user
        return user.ip_address if user else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return aggregated user tracker attributes."""
        user = self._current_user
        if not user:
            return {"user_id": self._user_id}

        return {
            "user_id": self._user_id,
            "name": user.name,
            "connected_ap": user.connected_ap,
            "signal_strength_dbm": user.signal,
            "active_mac": user.active_mac,
            "mac_addresses": user.macs,
            "ssid": user.ssid,
            "bssid": user.bssid,
            "interface": user.interface,
            "last_seen": user.last_seen.isoformat() if user.last_seen else None,
        }


class OpenWrtDeviceTracker(CoordinatorEntity[OpenWrtMeshCoordinator], ScannerEntity):
    """Represents an individual wireless client tracked across the OpenWrt mesh."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OpenWrtMeshCoordinator, mac: str) -> None:
        """Initialize the device tracker entity."""
        super().__init__(coordinator)
        self._mac = mac.upper()
        self._attr_unique_id = f"openwrt_tracker_{self._mac.replace(':', '_').lower()}"

    @property
    def device_info(self) -> DeviceInfo:
        """Link to the single unified device."""
        return _get_shared_device_info(self.coordinator)

    @property
    def _current_device(self) -> DeviceState | None:
        """Get current state of the device from coordinator."""
        return self.coordinator.data.devices.get(self._mac)

    @property
    def name(self) -> str:
        """Return friendly name."""
        dev = self._current_device
        return dev.name if dev else f"Device {self._mac[-8:]}"

    @property
    def source_type(self) -> SourceType:
        """Return the source type of the device tracker."""
        return SourceType.ROUTER

    @property
    def is_connected(self) -> bool:
        """Return true if device is currently connected to mesh."""
        dev = self._current_device
        return dev.is_home if dev else False

    @property
    def mac_address(self) -> str:
        """Return the MAC address of the device."""
        return self._mac

    @property
    def hostname(self) -> str | None:
        """Return friendly name or hostname."""
        dev = self._current_device
        return dev.name if dev else None

    @property
    def ip_address(self) -> str | None:
        """Return IP address of the device."""
        dev = self._current_device
        return dev.ip_address if dev else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return device tracker attributes."""
        dev = self._current_device
        if not dev:
            return {"mac": self._mac}

        return {
            "mac": self._mac,
            "connected_ap": dev.connected_ap,
            "signal_strength_dbm": dev.signal,
            "ssid": dev.ssid,
            "bssid": dev.bssid,
            "interface": dev.interface,
            "last_seen": dev.last_seen.isoformat() if dev.last_seen else None,
        }
