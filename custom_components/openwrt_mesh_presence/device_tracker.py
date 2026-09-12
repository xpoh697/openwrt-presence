"""Device tracker platform for OpenWrt Mesh Presence."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import ScannerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DeviceState, OpenWrtMeshCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up device tracker entities based on a config entry."""
    coordinator: OpenWrtMeshCoordinator = hass.data[DOMAIN][entry.entry_id]

    tracked_entities: dict[str, OpenWrtDeviceTracker] = {}

    @callback
    def _update_entities(new_macs: list[str] | None = None) -> None:
        """Add new device trackers dynamically as devices are discovered."""
        new_entities: list[OpenWrtDeviceTracker] = []
        for mac, dev in coordinator.data.devices.items():
            if mac not in tracked_entities and coordinator.is_device_tracked(mac):
                entity = OpenWrtDeviceTracker(coordinator, mac)
                tracked_entities[mac] = entity
                new_entities.append(entity)

        if new_entities:
            async_add_entities(new_entities)

    coordinator.register_new_device_callback(_update_entities)
    _update_entities()


class OpenWrtDeviceTracker(CoordinatorEntity[OpenWrtMeshCoordinator], ScannerEntity):
    """Represents a wireless client tracked across the OpenWrt mesh."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OpenWrtMeshCoordinator, mac: str) -> None:
        """Initialize the device tracker entity."""
        super().__init__(coordinator)
        self._mac = mac.upper()
        self._attr_unique_id = f"openwrt_mesh_tracker_{self._mac.replace(':', '_').lower()}"
        self._attr_name = self._current_device.name if self._current_device else f"Device {self._mac[-8:]}"

    @property
    def _current_device(self) -> DeviceState | None:
        """Get current state of the device from coordinator."""
        return self.coordinator.data.devices.get(self._mac)

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
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return device tracker attributes."""
        dev = self._current_device
        if not dev:
            return {}

        return {
            "connected_ap": dev.connected_ap,
            "signal_strength_dbm": dev.signal,
            "ssid": dev.ssid,
            "bssid": dev.bssid,
            "interface": dev.interface,
            "last_seen": dev.last_seen.isoformat() if dev.last_seen else None,
        }
