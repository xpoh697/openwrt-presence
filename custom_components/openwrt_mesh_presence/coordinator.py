"""DataUpdateCoordinator for OpenWrt Mesh Presence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import OpenWrtUbusClient
from .const import (
    CONF_DEVICE_NAMES,
    CONF_POLL_INTERVAL,
    CONF_ROAMING_GRACE_PERIOD,
    CONF_TRACKED_MACS,
    CONF_TRACKING_MODE,
    DEFAULT_DEVICE_EXPIRY_HOURS,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_ROAMING_GRACE_PERIOD,
    DOMAIN,
    TRACK_MODE_ALL,
    TRACK_MODE_SELECTED,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class DeviceState:
    """Represents the current state of a wireless device in the mesh."""

    mac: str
    name: str
    is_home: bool
    connected_ap: str | None
    signal: int | None
    last_seen: datetime
    ssid: str | None = None
    bssid: str | None = None
    interface: str | None = None


@dataclass
class NodeState:
    """Represents the status of an individual OpenWrt mesh node."""

    node_name: str
    host: str
    is_online: bool
    clients_count: int
    last_error: str | None = None


@dataclass
class MeshData:
    """Coordinator payload containing all aggregated devices and nodes."""

    devices: dict[str, DeviceState]
    nodes: dict[str, NodeState]


class OpenWrtMeshCoordinator(DataUpdateCoordinator[MeshData]):
    """Aggregates wireless clients across multiple OpenWrt mesh nodes."""

    def __init__(
        self,
        hass: HomeAssistant,
        clients: list[OpenWrtUbusClient],
        options: dict[str, Any],
    ) -> None:
        """Initialize the mesh presence coordinator."""
        poll_interval = options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=poll_interval),
        )
        self.clients = clients
        self.options = options

        # Internal state
        self._devices: dict[str, DeviceState] = {}
        self._nodes: dict[str, NodeState] = {}
        self._discovered_macs: dict[str, datetime] = {}
        self._new_device_callbacks: list[Any] = []

    @property
    def tracking_mode(self) -> str:
        """Return configured tracking mode (selected vs all)."""
        return self.options.get(CONF_TRACKING_MODE, TRACK_MODE_SELECTED)

    @property
    def tracked_macs(self) -> set[str]:
        """Return set of explicitly tracked uppercase MACs."""
        macs = self.options.get(CONF_TRACKED_MACS, [])
        return {m.upper() for m in macs}

    @property
    def device_names(self) -> dict[str, str]:
        """Return mapping of MAC to friendly names."""
        names = self.options.get(CONF_DEVICE_NAMES, {})
        return {k.upper(): v for k, v in names.items()}

    @property
    def roaming_grace_period(self) -> int:
        """Return debounce grace period in seconds."""
        return self.options.get(CONF_ROAMING_GRACE_PERIOD, DEFAULT_ROAMING_GRACE_PERIOD)

    def get_discovered_devices(self) -> dict[str, str]:
        """Return recently discovered MACs for selection in Options Flow."""
        result: dict[str, str] = {}
        for mac in sorted(self._discovered_macs.keys()):
            friendly = self.device_names.get(mac, "")
            label = f"{mac} ({friendly})" if friendly else mac
            if mac in self._devices and self._devices[mac].connected_ap:
                label += f" — [{self._devices[mac].connected_ap}]"
            result[mac] = label
        return result

    def register_new_device_callback(self, callback: Any) -> None:
        """Register a callback when a new device entity needs to be added."""
        self._new_device_callbacks.append(callback)

    def is_device_tracked(self, mac: str) -> bool:
        """Check if a specific MAC should be tracked according to options."""
        if self.tracking_mode == TRACK_MODE_ALL:
            return True
        return mac.upper() in self.tracked_macs

    async def _async_update_data(self) -> MeshData:
        """Fetch clients from all mesh nodes concurrently and resolve roaming."""
        now = dt_util.now()

        # Step 1: Poll all mesh nodes in parallel with isolated error handling
        tasks = [client.get_clients() for client in self.clients]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        current_active_clients: dict[str, list[dict[str, Any]]] = {}

        # Step 2: Process node results
        for client, res in zip(self.clients, results):
            node_key = client.node_name
            if isinstance(res, Exception):
                _LOGGER.warning(
                    "Error querying OpenWrt node '%s' (%s): %s",
                    client.node_name,
                    client.host,
                    res,
                )
                self._nodes[node_key] = NodeState(
                    node_name=client.node_name,
                    host=client.host,
                    is_online=False,
                    clients_count=0,
                    last_error=str(res),
                )
            else:
                client_dict: dict[str, dict[str, Any]] = res
                self._nodes[node_key] = NodeState(
                    node_name=client.node_name,
                    host=client.host,
                    is_online=True,
                    clients_count=len(client_dict),
                    last_error=None,
                )
                for mac, client_info in client_dict.items():
                    clean_mac = mac.upper()
                    if clean_mac not in current_active_clients:
                        current_active_clients[clean_mac] = []
                    current_active_clients[clean_mac].append(client_info)
                    self._discovered_macs[clean_mac] = now

        # Step 3: Resolve active clients and detect roaming
        newly_seen_macs: list[str] = []

        for mac, sightings in current_active_clients.items():
            # If client is visible on multiple nodes during roaming, select node with highest signal
            best_sighting = max(sightings, key=lambda x: x.get("signal", -100))
            ap_name = best_sighting.get("node_name")
            signal = best_sighting.get("signal")
            ssid = best_sighting.get("ssid")
            bssid = best_sighting.get("bssid")
            interface = best_sighting.get("interface")

            friendly_name = self.device_names.get(mac) or f"OpenWrt Device {mac[-8:]}"

            if mac not in self._devices:
                self._devices[mac] = DeviceState(
                    mac=mac,
                    name=friendly_name,
                    is_home=True,
                    connected_ap=ap_name,
                    signal=signal,
                    last_seen=now,
                    ssid=ssid,
                    bssid=bssid,
                    interface=interface,
                )
                if self.is_device_tracked(mac):
                    newly_seen_macs.append(mac)
            else:
                dev = self._devices[mac]
                # If roamed to a different AP
                if dev.connected_ap != ap_name:
                    _LOGGER.info("Device %s roamed from %s to %s", mac, dev.connected_ap, ap_name)
                dev.is_home = True
                dev.connected_ap = ap_name
                dev.signal = signal
                dev.last_seen = now
                dev.ssid = ssid
                dev.bssid = bssid
                dev.interface = interface
                dev.name = friendly_name

        # Step 4: Handle devices not seen in this poll (Grace Period Anti-Flapping)
        grace_delta = timedelta(seconds=self.roaming_grace_period)

        for mac, dev in self._devices.items():
            if mac not in current_active_clients:
                time_since_seen = now - dev.last_seen
                if time_since_seen < grace_delta:
                    # Still in grace period: keep state as HOME to prevent false away triggers
                    _LOGGER.debug(
                        "Device %s not seen, in grace period (%s / %ss)",
                        mac,
                        int(time_since_seen.total_seconds()),
                        self.roaming_grace_period,
                    )
                    dev.is_home = True
                else:
                    if dev.is_home:
                        _LOGGER.info(
                            "Device %s expired grace period (%ss), marked NOT_HOME",
                            mac,
                            self.roaming_grace_period,
                        )
                    dev.is_home = False
                    dev.connected_ap = None
                    dev.signal = None

        # Step 5: Prune MACs inactive for > 24 hours (Memory Safety)
        expiry_limit = now - timedelta(hours=DEFAULT_DEVICE_EXPIRY_HOURS)
        expired_macs = [
            m
            for m, dev in self._devices.items()
            if not dev.is_home and dev.last_seen < expiry_limit and not self.is_device_tracked(m)
        ]
        for m in expired_macs:
            _LOGGER.debug("Pruning expired device %s from memory", m)
            self._devices.pop(m, None)
            self._discovered_macs.pop(m, None)

        # Notify callbacks if new entities are needed
        if newly_seen_macs:
            for cb in self._new_device_callbacks:
                cb(newly_seen_macs)

        return MeshData(devices=dict(self._devices), nodes=dict(self._nodes))
