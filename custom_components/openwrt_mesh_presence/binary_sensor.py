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
        OpenWrtNodeStatusBinarySensor(coordinator, node_name)
        for node_name in coordinator.data.nodes
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
        self._attr_unique_id = f"openwrt_node_status_{clean_name}"
        self._attr_name = f"{self._node_name} Status"

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
            "last_error": node.last_error,
        }
