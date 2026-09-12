"""Config flow for OpenWrt Mesh Presence integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .client import OpenWrtAuthError, OpenWrtConnectionError, OpenWrtUbusClient
from .const import (
    CONF_DEVICE_NAMES,
    CONF_DEVICE_NAMES_TEXT,
    CONF_HOST,
    CONF_MANUAL_MACS,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    CONF_ROAMING_GRACE_PERIOD,
    CONF_ROUTERS,
    CONF_SSL,
    CONF_TRACKED_MACS,
    CONF_TRACKING_MODE,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_ROAMING_GRACE_PERIOD,
    DEFAULT_SSL,
    DEFAULT_USERNAME,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    TRACK_MODE_ALL,
    TRACK_MODE_SELECTED,
    normalize_mac,
    parse_mac_list,
)

_LOGGER = logging.getLogger(__name__)


class OpenWrtMeshConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenWrt Mesh Presence."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow state."""
        self._routers: list[dict[str, Any]] = []

    async def _test_router_connection(self, data: dict[str, Any]) -> str | None:
        """Test router credentials and connection."""
        session = async_get_clientsession(self.hass, verify_ssl=data.get(CONF_VERIFY_SSL, False))
        client = OpenWrtUbusClient(
            session=session,
            host=data[CONF_HOST],
            port=data.get(CONF_PORT, DEFAULT_PORT),
            username=data.get(CONF_USERNAME, DEFAULT_USERNAME),
            password=data.get(CONF_PASSWORD, ""),
            ssl=data.get(CONF_SSL, DEFAULT_SSL),
            verify_ssl=data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
            node_name=data.get(CONF_NAME, data[CONF_HOST]),
        )
        try:
            await client.login()
            await client.update_wireless_interfaces()
            return None
        except OpenWrtAuthError:
            return "invalid_auth"
        except OpenWrtConnectionError:
            return "cannot_connect"
        except Exception as err:
            _LOGGER.exception("Unexpected error testing OpenWrt router: %s", err)
            return "unknown"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle adding the first mesh router node."""
        errors: dict[str, str] = {}

        if user_input is not None:
            err = await self._test_router_connection(user_input)
            if err:
                errors["base"] = err
            else:
                self._routers.append(user_input)
                return await self.async_step_add_more()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="AP 1 (Master)"): cv.string,
                vol.Required(CONF_HOST, default="192.168.1.1"): cv.string,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
                vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD, default=""): cv.string,
                vol.Optional(CONF_SSL, default=DEFAULT_SSL): cv.boolean,
                vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): cv.boolean,
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_add_router(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle adding an additional mesh router node."""
        errors: dict[str, str] = {}

        if user_input is not None:
            err = await self._test_router_connection(user_input)
            if err:
                errors["base"] = err
            else:
                self._routers.append(user_input)
                return await self.async_step_add_more()

        next_index = len(self._routers) + 1
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=f"AP {next_index}"): cv.string,
                vol.Required(CONF_HOST): cv.string,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
                vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD, default=""): cv.string,
                vol.Optional(CONF_SSL, default=DEFAULT_SSL): cv.boolean,
                vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): cv.boolean,
            }
        )

        return self.async_show_form(step_id="add_router", data_schema=schema, errors=errors)

    async def async_step_add_more(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Ask user whether to add another mesh router or finish."""
        if user_input is not None:
            if user_input.get("add_another"):
                return await self.async_step_add_router()
            return self.async_create_entry(
                title=f"OpenWrt Mesh ({len(self._routers)} AP)",
                data={CONF_ROUTERS: self._routers},
                options={
                    CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL,
                    CONF_ROAMING_GRACE_PERIOD: DEFAULT_ROAMING_GRACE_PERIOD,
                    CONF_TRACKING_MODE: TRACK_MODE_SELECTED,
                    CONF_TRACKED_MACS: [],
                    CONF_MANUAL_MACS: "",
                    CONF_DEVICE_NAMES: {},
                    CONF_DEVICE_NAMES_TEXT: "",
                },
            )

        schema = vol.Schema(
            {
                vol.Required("add_another", default=len(self._routers) < 3): cv.boolean,
            }
        )

        node_names = ", ".join(r[CONF_NAME] for r in self._routers)
        return self.async_show_form(
            step_id="add_more",
            data_schema=schema,
            description_placeholders={"added_nodes": node_names, "count": str(len(self._routers))},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Create options flow handler without passing config_entry to constructor."""
        return OpenWrtMeshOptionsFlowHandler()


class OpenWrtMeshOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for OpenWrt Mesh Presence."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage options: select tracked devices, enter manual MACs, set names."""
        coordinator = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)

        discovered_dict: dict[str, str] = {}
        if coordinator:
            discovered_dict = coordinator.get_discovered_devices()

        current_options = self.config_entry.options or {}

        if user_input is not None:
            selected_macs = [normalize_mac(m) for m in user_input.get(CONF_TRACKED_MACS, []) if normalize_mac(m)]
            user_input[CONF_TRACKED_MACS] = selected_macs
            return self.async_create_entry(title="", data=user_input)

        current_macs = current_options.get(CONF_TRACKED_MACS, []) or []
        current_manual = current_options.get(CONF_MANUAL_MACS, "") or ""
        current_names_text = current_options.get(CONF_DEVICE_NAMES_TEXT, "") or ""
        current_poll = current_options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        current_grace = current_options.get(CONF_ROAMING_GRACE_PERIOD, DEFAULT_ROAMING_GRACE_PERIOD)

        # Merge discovered devices and currently tracked MACs
        options_dict = dict(discovered_dict)
        for mac in current_macs:
            norm = normalize_mac(mac)
            if norm and norm not in options_dict:
                options_dict[norm] = norm

        select_options = [
            SelectOptionDict(value=val, label=lbl)
            for val, lbl in options_dict.items()
        ]

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TRACKED_MACS,
                    default=current_macs,
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=select_options,
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_MANUAL_MACS,
                    default=current_manual,
                ): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Optional(
                    CONF_DEVICE_NAMES_TEXT,
                    default=current_names_text,
                ): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Required(
                    CONF_POLL_INTERVAL,
                    default=current_poll,
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=2,
                        max=60,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_ROAMING_GRACE_PERIOD,
                    default=current_grace,
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=5,
                        max=120,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
