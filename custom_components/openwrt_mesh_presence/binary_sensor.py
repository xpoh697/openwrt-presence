"""Binary sensor platform for OpenWrt Mesh Presence."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NodeState, OpenWrtMeshCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor entities based on a config entry."""
    coordinator: OpenWrtMeshCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BinarySensorEntity] = [
        OpenWrtNodeStatusBinarySensor(coordinator, client.node_name)
        for client in coordinator.clients
    ]
    async_add_entities(entities)


class OpenWrtNodeStatusBinarySensor(CoordinatorEntity[OpenWrtMeshCoordinator], BinarySensorEntity):
    """Binary sensor representing whether an OpenWrt mesh node is online."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: OpenWrtMeshCoordinator, node_name: str) -> None:
        """Initialize node status binary sensor."""
        super().__init__(coordinator)
        self._node_name = node_name
        clean_name = self._node_name.replace(" ", "_").lower()
        self._attr_unique_id = f"openwrt_node_status_{clean_name}_{coordinator.entry.entry_id}"
        self._attr_name = f"{self._node_name} Status"

    @property
    def device_info(self) -> DeviceInfo:
        """Link to the single unified device."""
        first_host = self.coordinator.clients[0].host if self.coordinator.clients else None
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.entry_id)},
            name="OpenWrt Mesh Presence",
            manufacturer="OpenWrt",
            model="Mesh Presence Hub",
            sw_version="1.0.0",
            configuration_url=f"http://{first_host}" if first_host else None,
        )

    @property
    def _current_node(self) -> NodeState | None:
        """Get node state from coordinator."""
        return self.coordinator.data.nodes.get(self._node_name)

    @property
    def is_on(self) -> bool:
        """Return true if node is online."""
        node = self._current_node
        return node.is_online if node else False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic attributes."""
        node = self._current_node
        if not node:
            return {}
        return {
            "host": node.host,
            "clients_count": node.clients_count,
            "last_error": node.last_error,
        }
