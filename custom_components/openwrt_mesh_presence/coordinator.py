"""DataUpdateCoordinator for OpenWrt Mesh Presence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .client import OpenWrtUbusClient
from .const import (
    CONF_DEVICE_NAMES,
    CONF_DEVICE_NAMES_TEXT,
    CONF_MANUAL_MACS,
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
    normalize_mac,
    parse_mac_list,
    parse_name_mapping,
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
    ip_address: str | None = None
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
    total_clients: int


class OpenWrtMeshCoordinator(DataUpdateCoordinator[MeshData]):
    """Aggregates wireless clients across multiple OpenWrt mesh nodes."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        clients: list[OpenWrtUbusClient],
    ) -> None:
        """Initialize the mesh presence coordinator."""
        self.entry = entry
        self.clients = clients

        poll_interval = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=poll_interval),
        )

        # Internal state
        self._devices: dict[str, DeviceState] = {}
        self._nodes: dict[str, NodeState] = {}
        self._discovered_info: dict[str, dict[str, Any]] = {}
        self._new_device_callbacks: list[Any] = []

    @property
    def tracking_mode(self) -> str:
        """Return configured tracking mode (selected vs all)."""
        return self.entry.options.get(CONF_TRACKING_MODE, TRACK_MODE_SELECTED)

    @property
    def tracked_macs(self) -> set[str]:
        """Return set of explicitly tracked uppercase MACs (from multi-select and manual input)."""
        # 1. From multi-select
        list_macs = self.entry.options.get(CONF_TRACKED_MACS, [])
        combined = parse_mac_list(list_macs)

        # 2. From manual text input
        manual_text = self.entry.options.get(CONF_MANUAL_MACS, "")
        combined.update(parse_mac_list(manual_text))

        return combined

    @property
    def device_names(self) -> dict[str, str]:
        """Return mapping of MAC to friendly names from options and host hints."""
        # 1. Host hints from routers (DHCP hostnames)
        names: dict[str, str] = {}
        for client in self.clients:
            for mac, hint in client.host_hints.items():
                hint_name = hint.get("name")
                if hint_name:
                    names[mac] = hint_name

        # 2. Stored options dict
        stored_dict = self.entry.options.get(CONF_DEVICE_NAMES, {})
        if isinstance(stored_dict, dict):
            for k, v in stored_dict.items():
                norm = normalize_mac(k)
                if norm and str(v).strip():
                    names[norm] = str(v).strip()

        # 3. Custom text mapping (MAC=Name)
        text_names = self.entry.options.get(CONF_DEVICE_NAMES_TEXT, "")
        parsed_text = parse_name_mapping(text_names)
        names.update(parsed_text)

        return names

    @property
    def roaming_grace_period(self) -> int:
        """Return debounce grace period in seconds."""
        return self.entry.options.get(CONF_ROAMING_GRACE_PERIOD, DEFAULT_ROAMING_GRACE_PERIOD)

    def get_discovered_devices(self) -> dict[str, str]:
        """Return recently discovered MACs with rich labels for selection in Options Flow."""
        result: dict[str, str] = {}
        for mac in sorted(self._discovered_info.keys()):
            info = self._discovered_info[mac]
            friendly = self.device_names.get(mac) or info.get("hostname")
            ip = info.get("ip") or ""
            ap = info.get("ap") or ""
            rssi = info.get("signal")

            parts = [mac]
            if friendly and friendly != mac:
                parts.append(f"({friendly})")
            if ip:
                parts.append(f"[{ip}]")
            if ap:
                rssi_str = f", {rssi} dBm" if rssi is not None else ""
                parts.append(f"— {ap}{rssi_str}")

            result[mac] = " ".join(parts)
        return result

    def register_new_device_callback(self, callback: Any) -> None:
        """Register a callback when a new device entity needs to be added."""
        self._new_device_callbacks.append(callback)

    def is_device_tracked(self, mac: str) -> bool:
        """Check if a specific MAC should be tracked according to options."""
        norm = normalize_mac(mac)
        if not norm:
            return False
        if self.tracking_mode == TRACK_MODE_ALL:
            return True
        # If tracked_macs is set, check membership
        return norm in self.tracked_macs

    async def _async_update_data(self) -> MeshData:
        """Fetch clients from all mesh nodes concurrently and resolve roaming."""
        now = dt_util.now()

        # Step 1: Poll all mesh nodes in parallel with isolated error handling
        tasks = [client.get_clients() for client in self.clients]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        current_active_clients: dict[str, list[dict[str, Any]]] = {}
        total_mesh_clients = 0

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
                count = len(client_dict)
                total_mesh_clients += count
                self._nodes[node_key] = NodeState(
                    node_name=client.node_name,
                    host=client.host,
                    is_online=True,
                    clients_count=count,
                    last_error=None,
                )
                for mac, client_info in client_dict.items():
                    norm = normalize_mac(mac)
                    if not norm:
                        continue
                    if norm not in current_active_clients:
                        current_active_clients[norm] = []
                    current_active_clients[norm].append(client_info)

                    # Update discovered cache for UI dropdown
                    hint = client.host_hints.get(norm, {})
                    self._discovered_info[norm] = {
                        "hostname": hint.get("name"),
                        "ip": hint.get("ip"),
                        "ap": client.node_name,
                        "signal": client_info.get("signal"),
                        "last_seen": now,
                    }

        # Step 3: Resolve active clients and detect roaming
        newly_seen_macs: list[str] = []

        # If in selected mode and tracked_macs specified, filter
        target_macs = set(current_active_clients.keys())
        if self.tracking_mode == TRACK_MODE_SELECTED:
            # Also ensure all tracked_macs exist in self._devices even if offline
            for tm in self.tracked_macs:
                if tm not in self._devices:
                    friendly_name = self.device_names.get(tm) or f"Device {tm[-8:]}"
                    self._devices[tm] = DeviceState(
                        mac=tm,
                        name=friendly_name,
                        is_home=False,
                        connected_ap=None,
                        signal=None,
                        last_seen=now,
                    )
                    newly_seen_macs.append(tm)

        for mac, sightings in current_active_clients.items():
            # If client is visible on multiple nodes during roaming, select node with highest signal
            best_sighting = max(sightings, key=lambda x: x.get("signal", -100))
            ap_name = best_sighting.get("node_name")
            signal = best_sighting.get("signal")
            ssid = best_sighting.get("ssid")
            bssid = best_sighting.get("bssid")
            interface = best_sighting.get("interface")

            # Check if this MAC should be tracked
            if not self.is_device_tracked(mac):
                continue

            friendly_name = self.device_names.get(mac) or self._discovered_info.get(mac, {}).get("hostname") or f"Device {mac[-8:]}"
            ip = self._discovered_info.get(mac, {}).get("ip")

            if mac not in self._devices:
                self._devices[mac] = DeviceState(
                    mac=mac,
                    name=friendly_name,
                    is_home=True,
                    connected_ap=ap_name,
                    signal=signal,
                    last_seen=now,
                    ip_address=ip,
                    ssid=ssid,
                    bssid=bssid,
                    interface=interface,
                )
                newly_seen_macs.append(mac)
            else:
                dev = self._devices[mac]
                # Check for roaming transition
                if dev.connected_ap != ap_name and dev.is_home:
                    _LOGGER.info("Device %s roamed from %s to %s (RSSI: %s dBm)", mac, dev.connected_ap, ap_name, signal)
                dev.is_home = True
                dev.connected_ap = ap_name
                dev.signal = signal
                dev.last_seen = now
                dev.ip_address = ip or dev.ip_address
                dev.ssid = ssid
                dev.bssid = bssid
                dev.interface = interface
                dev.name = friendly_name

        # Step 4: Handle tracked devices not seen in this poll (Grace Period Anti-Flapping)
        grace_delta = timedelta(seconds=self.roaming_grace_period)

        for mac, dev in self._devices.items():
            if mac not in current_active_clients:
                time_since_seen = now - dev.last_seen
                if time_since_seen < grace_delta and dev.is_home:
                    # Still in grace period: keep state as HOME to prevent false away triggers
                    _LOGGER.debug(
                        "Device %s not seen, in grace period (%ss / %ss)",
                        mac,
                        int(time_since_seen.total_seconds()),
                        self.roaming_grace_period,
                    )
                else:
                    if dev.is_home:
                        _LOGGER.info(
                            "Device %s offline after grace period (%ss)",
                            mac,
                            self.roaming_grace_period,
                        )
                    dev.is_home = False
                    dev.connected_ap = None
                    dev.signal = None

        # Step 5: Prune non-tracked MACs from memory
        if self.tracking_mode == TRACK_MODE_SELECTED:
            untracked = [m for m in self._devices if not self.is_device_tracked(m)]
            for m in untracked:
                self._devices.pop(m, None)

        # Notify callbacks if new entities are needed
        if newly_seen_macs:
            for cb in self._new_device_callbacks:
                cb(newly_seen_macs)

        return MeshData(
            devices=dict(self._devices),
            nodes=dict(self._nodes),
            total_clients=total_mesh_clients,
        )
