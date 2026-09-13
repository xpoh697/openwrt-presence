"""Button platform for OpenWrt Mesh Presence."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import OpenWrtUbusClient
from .const import DOMAIN
from .coordinator import OpenWrtMeshCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OpenWrt reboot button entities based on config entry."""
    coordinator: OpenWrtMeshCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[ButtonEntity] = [
        OpenWrtNodeRebootButton(coordinator, client)
        for client in coordinator.clients
    ]
    async_add_entities(entities)


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


class OpenWrtNodeRebootButton(CoordinatorEntity[OpenWrtMeshCoordinator], ButtonEntity):
    """Button entity to trigger reboot of an individual OpenWrt mesh node."""

    _attr_has_entity_name = True
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_icon = "mdi:restart"

    def __init__(self, coordinator: OpenWrtMeshCoordinator, client: OpenWrtUbusClient) -> None:
        """Initialize reboot button."""
        super().__init__(coordinator)
        self._client = client
        self._node_name = client.node_name
        clean_name = self._node_name.replace(" ", "_").lower()
        self._attr_unique_id = f"openwrt_reboot_{clean_name}_{coordinator.entry.entry_id}"
        self._attr_name = f"{self._node_name} Reboot"

    @property
    def device_info(self) -> DeviceInfo:
        """Link to the single unified device."""
        return _get_shared_device_info(self.coordinator)

    @property
    def available(self) -> bool:
        """Button is clickable only when the node is reported online."""
        node = self.coordinator.data.nodes.get(self._node_name)
        return node.is_online if node else False

    async def async_press(self) -> None:
        """Handle button press to reboot the router."""
        _LOGGER.warning("User triggered reboot for OpenWrt node '%s' (%s)", self._node_name, self._client.host)
        await self._client.reboot()
