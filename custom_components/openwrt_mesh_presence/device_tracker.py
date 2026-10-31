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
from .coordinator import DeviceState, OpenWrtMeshCoordinator

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

    tracked_entities: dict[str, OpenWrtDeviceTracker] = {}

    @callback
    def _update_entities() -> None:
        """Add new device trackers dynamically as devices are configured."""
        new_entities: list[OpenWrtDeviceTracker] = []
        for mac in coordinator.data.devices:
            if mac not in tracked_entities:
                entity = OpenWrtDeviceTracker(coordinator, mac)
                tracked_entities[mac] = entity
                new_entities.append(entity)

        if new_entities:
            async_add_entities(new_entities)

    coordinator.register_new_device_callback(_update_entities)
    _update_entities()

    # Clean up device trackers for secondary merged MACs or devices removed from tracking
    ent_reg = er.async_get(hass)
    entries = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    for reg_entry in entries:
        if reg_entry.domain == "device_tracker":
            unique_id = reg_entry.unique_id
            if unique_id.startswith("openwrt_tracker_"):
                clean_mac = unique_id.replace("openwrt_tracker_", "")
                mac = clean_mac.replace("_", ":").upper()
                # If MAC is merged under another primary MAC or is no longer tracked:
                if mac in coordinator.secondary_macs or not coordinator.is_device_tracked(mac):
                    _LOGGER.info("Removing merged/obsolete tracker entity %s for MAC %s", reg_entry.entity_id, mac)
                    ent_reg.async_remove(reg_entry.entity_id)


class OpenWrtDeviceTracker(CoordinatorEntity[OpenWrtMeshCoordinator], ScannerEntity):
    """Represents a wireless target (single device or multi-MAC user) tracked across the mesh."""

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
        """Return true if device or any of its associated MACs is currently connected."""
        dev = self._current_device
        return dev.is_home if dev else False

    @property
    def mac_address(self) -> str:
        """Return active MAC or primary MAC."""
        dev = self._current_device
        if dev and dev.active_mac:
            return dev.active_mac
        return self._mac

    @property
    def hostname(self) -> str | None:
        """Return friendly name or hostname."""
        dev = self._current_device
        return dev.name if dev else None

    @property
    def ip_address(self) -> str | None:
        """Return IP address of the active device."""
        dev = self._current_device
        return dev.ip_address if dev else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return device tracker attributes including all associated MACs for 2.4/5GHz."""
        dev = self._current_device
        if not dev:
            return {"primary_mac": self._mac}

        return {
            "primary_mac": self._mac,
            "active_mac": dev.active_mac or self._mac,
            "mac_addresses": dev.mac_addresses or [self._mac],
            "connected_ap": dev.connected_ap,
            "signal_strength_dbm": dev.signal,
            "ssid": dev.ssid,
            "bssid": dev.bssid,
            "interface": dev.interface,
            "last_seen": dev.last_seen.isoformat() if dev.last_seen else None,
        }
