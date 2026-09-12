"""Sensor platform for OpenWrt Mesh Presence."""

from __future__ import annotations

from datetime import datetime
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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
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

    tracked_sensor_macs: set[str] = set()

    # 1. Total mesh clients sensor
    entities: list[SensorEntity] = [OpenWrtTotalClientsSensor(coordinator)]

    # 2. Router diagnostic sensors (clients per AP)
    for client in coordinator.clients:
        entities.append(OpenWrtNodeClientsSensor(coordinator, client.node_name))

    async_add_entities(entities)

    # 3. Dynamic sensors for tracked devices
    @callback
    def _update_device_sensors(new_macs: list[str] | None = None) -> None:
        """Add sensors for newly discovered or configured tracked devices."""
        new_sensors: list[SensorEntity] = []
        for mac in coordinator.data.devices:
            if mac not in tracked_sensor_macs and coordinator.is_device_tracked(mac):
                tracked_sensor_macs.add(mac)
                new_sensors.append(OpenWrtConnectedApSensor(coordinator, mac))
                new_sensors.append(OpenWrtDeviceRssiSensor(coordinator, mac))
                new_sensors.append(OpenWrtDeviceLastSeenSensor(coordinator, mac))

        if new_sensors:
            async_add_entities(new_sensors)

    coordinator.register_new_device_callback(_update_device_sensors)
    _update_device_sensors()

    # 4. Clean up entities for devices that were removed from tracking
    ent_reg = er.async_get(hass)
    entries = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    for reg_entry in entries:
        if reg_entry.domain == "sensor":
            unique_id = reg_entry.unique_id
            # If unique_id is device-specific, check if device is still tracked
            for prefix in ("openwrt_ap_", "openwrt_rssi_", "openwrt_seen_"):
                if unique_id.startswith(prefix):
                    clean_mac = unique_id.replace(prefix, "")
                    mac = clean_mac.replace("_", ":").upper()
                    if not coordinator.is_device_tracked(mac):
                        _LOGGER.info("Removing obsolete sensor entity %s for untracked MAC %s", reg_entry.entity_id, mac)
                        ent_reg.async_remove(reg_entry.entity_id)


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


class OpenWrtTotalClientsSensor(CoordinatorEntity[OpenWrtMeshCoordinator], SensorEntity):
    """Sensor reporting total active clients across the entire mesh network."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:account-group"

    def __init__(self, coordinator: OpenWrtMeshCoordinator) -> None:
        """Initialize total clients sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"openwrt_mesh_total_clients_{coordinator.entry.entry_id}"
        self._attr_name = "Всего клиентов в сети"

    @property
    def device_info(self) -> DeviceInfo:
        """Link to the single unified device."""
        return _get_shared_device_info(self.coordinator)

    @property
    def native_value(self) -> int:
        """Return total clients count."""
        return self.coordinator.data.total_clients


class OpenWrtNodeClientsSensor(CoordinatorEntity[OpenWrtMeshCoordinator], SensorEntity):
    """Sensor reporting active client count on an individual OpenWrt mesh node."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:wifi-marker"

    def __init__(self, coordinator: OpenWrtMeshCoordinator, node_name: str) -> None:
        """Initialize node clients sensor."""
        super().__init__(coordinator)
        self._node_name = node_name
        clean_name = self._node_name.replace(" ", "_").lower()
        self._attr_unique_id = f"openwrt_node_clients_{clean_name}_{coordinator.entry.entry_id}"
        self._attr_name = f"{self._node_name} Active Clients"

    @property
    def device_info(self) -> DeviceInfo:
        """Link to the single unified device."""
        return _get_shared_device_info(self.coordinator)

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


class OpenWrtConnectedApSensor(CoordinatorEntity[OpenWrtMeshCoordinator], SensorEntity):
    """Sensor indicating which specific Mesh AP a client is currently connected to."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:router-wireless"

    def __init__(self, coordinator: OpenWrtMeshCoordinator, mac: str) -> None:
        """Initialize connected AP sensor."""
        super().__init__(coordinator)
        self._mac = mac.upper()
        clean_mac = self._mac.replace(":", "_").lower()
        self._attr_unique_id = f"openwrt_ap_{clean_mac}"

    @property
    def device_info(self) -> DeviceInfo:
        """Link to the single unified device."""
        return _get_shared_device_info(self.coordinator)

    @property
    def _current_device(self) -> DeviceState | None:
        """Get device state from coordinator."""
        return self.coordinator.data.devices.get(self._mac)

    @property
    def name(self) -> str:
        """Return entity name with friendly device name."""
        dev = self._current_device
        device_name = dev.name if dev else f"Device {self._mac[-8:]}"
        return f"{device_name} Connected AP"

    @property
    def native_value(self) -> str:
        """Return name of connected AP or 'Не в сети'."""
        dev = self._current_device
        if dev and dev.is_home and dev.connected_ap:
            return dev.connected_ap
        return "Не в сети"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return wireless attributes."""
        dev = self._current_device
        if not dev:
            return {"mac": self._mac}
        return {
            "mac": self._mac,
            "ip_address": dev.ip_address,
            "bssid": dev.bssid,
            "ssid": dev.ssid,
            "interface": dev.interface,
            "is_home": dev.is_home,
        }


class OpenWrtDeviceRssiSensor(CoordinatorEntity[OpenWrtMeshCoordinator], SensorEntity):
    """Sensor reporting Wi-Fi RSSI in dBm of a connected client."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT

    def __init__(self, coordinator: OpenWrtMeshCoordinator, mac: str) -> None:
        """Initialize RSSI sensor."""
        super().__init__(coordinator)
        self._mac = mac.upper()
        clean_mac = self._mac.replace(":", "_").lower()
        self._attr_unique_id = f"openwrt_rssi_{clean_mac}"

    @property
    def device_info(self) -> DeviceInfo:
        """Link to the single unified device."""
        return _get_shared_device_info(self.coordinator)

    @property
    def _current_device(self) -> DeviceState | None:
        """Get device state from coordinator."""
        return self.coordinator.data.devices.get(self._mac)

    @property
    def name(self) -> str:
        """Return entity name."""
        dev = self._current_device
        device_name = dev.name if dev else f"Device {self._mac[-8:]}"
        return f"{device_name} Signal"

    @property
    def native_value(self) -> int | None:
        """Return signal strength in dBm."""
        dev = self._current_device
        if dev and dev.is_home:
            return dev.signal
        return None

    @property
    def icon(self) -> str:
        """Dynamically select Wi-Fi icon based on signal quality."""
        rssi = self.native_value
        if rssi is None:
            return "mdi:wifi-off"
        if rssi >= -50:
            return "mdi:wifi-strength-4"
        if rssi >= -65:
            return "mdi:wifi-strength-3"
        if rssi >= -75:
            return "mdi:wifi-strength-2"
        return "mdi:wifi-strength-1"


class OpenWrtDeviceLastSeenSensor(CoordinatorEntity[OpenWrtMeshCoordinator], SensorEntity):
    """Sensor reporting last confirmation timestamp of a client."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, coordinator: OpenWrtMeshCoordinator, mac: str) -> None:
        """Initialize last seen sensor."""
        super().__init__(coordinator)
        self._mac = mac.upper()
        clean_mac = self._mac.replace(":", "_").lower()
        self._attr_unique_id = f"openwrt_seen_{clean_mac}"

    @property
    def device_info(self) -> DeviceInfo:
        """Link to the single unified device."""
        return _get_shared_device_info(self.coordinator)

    @property
    def _current_device(self) -> DeviceState | None:
        """Get device state from coordinator."""
        return self.coordinator.data.devices.get(self._mac)

    @property
    def name(self) -> str:
        """Return entity name."""
        dev = self._current_device
        device_name = dev.name if dev else f"Device {self._mac[-8:]}"
        return f"{device_name} Last Seen"

    @property
    def native_value(self) -> datetime | None:
        """Return last seen timestamp."""
        dev = self._current_device
        return dev.last_seen if dev else None
