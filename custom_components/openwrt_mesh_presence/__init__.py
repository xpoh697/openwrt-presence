"""Initialization of OpenWrt Mesh Presence integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import OpenWrtUbusClient
from .const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_ROUTERS,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_PORT,
    DEFAULT_SSL,
    DEFAULT_USERNAME,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import OpenWrtMeshCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OpenWrt Mesh Presence from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    routers_config = entry.data.get(CONF_ROUTERS, [])
    clients: list[OpenWrtUbusClient] = []

    for router_data in routers_config:
        verify_ssl = router_data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
        session = async_get_clientsession(hass, verify_ssl=verify_ssl)
        client = OpenWrtUbusClient(
            session=session,
            host=router_data[CONF_HOST],
            port=router_data.get(CONF_PORT, DEFAULT_PORT),
            username=router_data.get(CONF_USERNAME, DEFAULT_USERNAME),
            password=router_data.get(CONF_PASSWORD, ""),
            ssl=router_data.get(CONF_SSL, DEFAULT_SSL),
            verify_ssl=verify_ssl,
            node_name=router_data.get(CONF_NAME, router_data[CONF_HOST]),
        )
        clients.append(client)

    coordinator = OpenWrtMeshCoordinator(
        hass=hass,
        clients=clients,
        options=entry.options,
    )

    # Perform first refresh
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setup to entity platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an OpenWrt Mesh Presence config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)
