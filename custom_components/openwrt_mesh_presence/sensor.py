"""Sensor platform for OpenWrt Mesh Presence."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DeviceState, NodeState, OpenWrtMeshCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities based on a config entry."""
    coordinator: OpenWrtMeshCoordinator = hass.data[DOMAIN][entry.entry_id]

    tracked_device_sensors: set[str] = set()

    # 1. Add router diagnostic sensors (Clients count)
    node_entities: list[SensorEntity] = [
        OpenWrtNodeClientsSensor(coordinator, node_name)
        for node_name in coordinator.data.nodes
    ]
    async_add_entities(node_entities)

    # 2. Dynamic device sensors (Connected AP & RSSI)
    @callback
    def _update_device_sensors(new_macs: list[str] | None = None) -> None:
        """Add sensors for newly discovered or tracked devices."""
        new_sensors: list[SensorEntity] = []
        for mac, dev in coordinator.data.devices.items():
            if mac not in tracked_device_sensors and coordinator.is_device_tracked(mac):
                tracked_device_sensors.add(mac)
                new_sensors.append(OpenWrtConnectedApSensor(coordinator, mac))
                new_sensors.append(OpenWrtDeviceRssiSensor(coordinator, mac))

        if new_sensors:
            async_add_entities(new_sensors)

    coordinator.register_new_device_callback(_update_device_sensors)
    _update_device_sensors()


class OpenWrtConnectedApSensor(CoordinatorEntity[OpenWrtMeshCoordinator], SensorEntity):
    """Sensor indicating which specific Mesh AP a client is connected to."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:wifi-marker"

    def __init__(self, coordinator: OpenWrtMeshCoordinator, mac: str) -> None:
        """Initialize connected AP sensor."""
        super().__init__(coordinator)
        self._mac = mac.upper()
        clean_mac = self._mac.replace(":", "_").lower()
        self._attr_unique_id = f"openwrt_mesh_ap_{clean_mac}"
        dev = self._current_device
        device_name = dev.name if dev else f"Device {self._mac[-8:]}"
        self._attr_name = f"{device_name} Connected AP"

    @property
    def _current_device(self) -> DeviceState | None:
        """Get device state from coordinator."""
        return self.coordinator.data.devices.get(self._mac)

    @property
    def native_value(self) -> str | None:
        """Return name of connected AP or None if disconnected."""
        dev = self._current_device
        if dev and dev.is_home:
            return dev.connected_ap
        return "Не подключено"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return wireless attributes."""
        dev = self._current_device
        if not dev:
            return {}
        return {
            "mac": self._mac,
            "bssid": dev.bssid,
            "ssid": dev.ssid,
            "interface": dev.interface,
        }


class OpenWrtDeviceRssiSensor(CoordinatorEntity[OpenWrtMeshCoordinator], SensorEntity):
    """Sensor reporting the Wi-Fi RSSI of a connected client."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT

    def __init__(self, coordinator: OpenWrtMeshCoordinator, mac: str) -> None:
        """Initialize RSSI sensor."""
        super().__init__(coordinator)
        self._mac = mac.upper()
        clean_mac = self._mac.replace(":", "_").lower()
        self._attr_unique_id = f"openwrt_mesh_rssi_{clean_mac}"
        dev = self._current_device
        device_name = dev.name if dev else f"Device {self._mac[-8:]}"
        self._attr_name = f"{device_name} Signal"

    @property
    def _current_device(self) -> DeviceState | None:
        """Get device state from coordinator."""
        return self.coordinator.data.devices.get(self._mac)

    @property
    def native_value(self) -> int | None:
        """Return signal strength in dBm."""
        dev = self._current_device
        if dev and dev.is_home:
            return dev.signal
        return None

    @property
    def icon(self) -> str:
        """Dynamically pick Wi-Fi icon based on signal quality."""
        rssi = self.native_value
        if rssi is None:
            return "mdi:wifi-off"
        if rssi >= -50:
            return "mdi:wifi-strength-4"
        if rssi >= -65:
            return "mdi:wifi-strength-3"
        if rssi >= -75:
            return "mdi:wifi-strength-2"
        if rssi >= -85:
            return "mdi:wifi-strength-1"
        return "mdi:wifi-strength-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return signal quality description."""
        rssi = self.native_value
        quality = "Offline"
        if rssi is not None:
            if rssi >= -55:
                quality = "Отличное"
            elif rssi >= -68:
                quality = "Хорошее"
            elif rssi >= -78:
                quality = "Удовлетворительное"
            else:
                quality = "Слабое"

        return {"quality": quality, "mac": self._mac}


class OpenWrtNodeClientsSensor(CoordinatorEntity[OpenWrtMeshCoordinator], SensorEntity):
    """Sensor reporting active client count on an OpenWrt mesh node."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:account-multiple"

    def __init__(self, coordinator: OpenWrtMeshCoordinator, node_name: str) -> None:
        """Initialize node clients sensor."""
        super().__init__(coordinator)
        self._node_name = node_name
        clean_name = self._node_name.replace(" ", "_").lower()
        self._attr_unique_id = f"openwrt_node_clients_{clean_name}"
        self._attr_name = f"{self._node_name} Active Clients"

    @property
    def _current_node(self) -> NodeState | None:
        """Get node state from coordinator."""
        return self.coordinator.data.nodes.get(self._node_name)

    @property
    def native_value(self) -> int:
        """Return count of active clients."""
        node = self._current_node
        return node.clients_count if node and node.is_online else 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return node status attributes."""
        node = self._current_node
        if not node:
            return {}
        return {
            "host": node.host,
            "is_online": node.is_online,
            "last_error": node.last_error,
        }
