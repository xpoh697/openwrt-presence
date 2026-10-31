"""DataUpdateCoordinator for OpenWrt Mesh Presence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
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
    """Represents the current state of a wireless device or multi-MAC user in the mesh."""

    mac: str
    name: str
    is_home: bool
    connected_ap: str | None
    signal: int | None
    last_seen: datetime
    active_mac: str | None = None
    mac_addresses: list[str] = field(default_factory=list)
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
    users: dict[str, Any] = field(default_factory=dict)


class OpenWrtMeshCoordinator(DataUpdateCoordinator[MeshData]):
    """Aggregates wireless clients across multiple OpenWrt mesh nodes with auto-merge by name."""

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
    def secondary_macs(self) -> set[str]:
        """Return set of secondary MACs that are merged under a primary target name."""
        result: set[str] = set()
        name_groups: dict[str, list[str]] = {}
        for mac in self.tracked_macs:
            raw_name = self.device_names.get(mac) or self.get_device_hint(mac).get("name") or f"Device {mac[-8:]}"
            norm_key = raw_name.strip().lower()
            if norm_key not in name_groups:
                name_groups[norm_key] = []
            name_groups[norm_key].append(mac)

        for group in name_groups.values():
            if len(group) > 1:
                result.update(group[1:])
        return result

    @property
    def roaming_grace_period(self) -> int:
        """Return debounce grace period in seconds."""
        return self.entry.options.get(CONF_ROAMING_GRACE_PERIOD, DEFAULT_ROAMING_GRACE_PERIOD)

    def get_device_hint(self, mac: str) -> dict[str, Any]:
        """Look up device hostname and IP across all mesh nodes (Master router DHCP table)."""
        norm = normalize_mac(mac)
        if not norm:
            return {}
        # 1. Search host_hints across all nodes
        for client in self.clients:
            if norm in client.host_hints:
                hint = client.host_hints[norm]
                if hint.get("name") or hint.get("ip"):
                    return hint
        # 2. Check discovered cache
        if norm in self._discovered_info:
            info = self._discovered_info[norm]
            return {"name": info.get("hostname"), "ip": info.get("ip")}
        return {}

    def get_discovered_devices(self) -> dict[str, str]:
        """Return recently discovered MACs with rich labels for selection in Options Flow."""
        result: dict[str, str] = {}
        for mac in sorted(self._discovered_info.keys()):
            info = self._discovered_info[mac]
            hint = self.get_device_hint(mac)
            friendly = self.device_names.get(mac) or hint.get("name") or info.get("hostname")
            ip = info.get("ip") or hint.get("ip") or ""
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
        """Fetch clients from all mesh nodes concurrently, resolve roaming, and auto-merge MACs with identical names."""
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

                    # Update discovered cache for UI dropdown using network-wide hints
                    hint = self.get_device_hint(norm) or client.host_hints.get(norm, {})
                    self._discovered_info[norm] = {
                        "hostname": hint.get("name"),
                        "ip": hint.get("ip"),
                        "ap": client.node_name,
                        "signal": client_info.get("signal"),
                        "last_seen": now,
                    }

        # Step 3: Group tracked MACs by friendly name (case-insensitive auto-merge for 2.4 + 5 GHz)
        name_groups: dict[str, list[str]] = {}
        for mac in self.tracked_macs:
            hint = self.get_device_hint(mac)
            raw_name = self.device_names.get(mac) or hint.get("name") or f"Device {mac[-8:]}"
            norm_key = raw_name.strip().lower()
            if norm_key not in name_groups:
                name_groups[norm_key] = []
            name_groups[norm_key].append(mac)

        primary_macs: set[str] = set()
        grace_delta = timedelta(seconds=self.roaming_grace_period)
        newly_seen_macs: list[str] = []

        # Step 4: Process each target group
        for norm_name_key, group_macs in name_groups.items():
            primary_mac = group_macs[0]
            primary_macs.add(primary_mac)

            display_name = self.device_names.get(primary_mac) or self.get_device_hint(primary_mac).get("name") or f"Device {primary_mac[-8:]}"

            # Collect all active sightings across all MACs in this group
            active_group_sightings: list[dict[str, Any]] = []
            for m in group_macs:
                if m in current_active_clients:
                    for s in current_active_clients[m]:
                        entry_copy = dict(s)
                        entry_copy["mac"] = m
                        active_group_sightings.append(entry_copy)

            if active_group_sightings:
                # Target is connected via at least one band/MAC! Pick best signal
                best = max(active_group_sightings, key=lambda x: x.get("signal", -100))
                active_mac = best["mac"]
                ap_name = best.get("node_name")
                signal = best.get("signal")
                ssid = best.get("ssid")
                bssid = best.get("bssid")
                interface = best.get("interface")
                hint = self.get_device_hint(active_mac)
                ip = hint.get("ip") or self._discovered_info.get(active_mac, {}).get("ip")

                if primary_mac not in self._devices:
                    self._devices[primary_mac] = DeviceState(
                        mac=primary_mac,
                        name=display_name,
                        is_home=True,
                        connected_ap=ap_name,
                        signal=signal,
                        last_seen=now,
                        active_mac=active_mac,
                        mac_addresses=group_macs,
                        ip_address=ip,
                        ssid=ssid,
                        bssid=bssid,
                        interface=interface,
                    )
                    newly_seen_macs.append(primary_mac)
                else:
                    dev = self._devices[primary_mac]
                    if dev.connected_ap != ap_name and dev.is_home:
                        _LOGGER.info(
                            "Target '%s' roamed from %s to %s (active MAC: %s, RSSI: %s dBm)",
                            display_name,
                            dev.connected_ap,
                            ap_name,
                            active_mac,
                            signal,
                        )
                    dev.name = display_name
                    dev.is_home = True
                    dev.connected_ap = ap_name
                    dev.signal = signal
                    dev.last_seen = now
                    dev.active_mac = active_mac
                    dev.mac_addresses = group_macs
                    dev.ip_address = ip or dev.ip_address
                    dev.ssid = ssid
                    dev.bssid = bssid
                    dev.interface = interface
            else:
                # Target not active in this poll - apply grace period to group
                if primary_mac in self._devices:
                    dev = self._devices[primary_mac]
                    dev.name = display_name
                    dev.mac_addresses = group_macs
                    time_since_seen = now - dev.last_seen
                    if time_since_seen < grace_delta and dev.is_home:
                        _LOGGER.debug(
                            "Target '%s' not seen, in grace period (%ss / %ss)",
                            display_name,
                            int(time_since_seen.total_seconds()),
                            self.roaming_grace_period,
                        )
                    else:
                        if dev.is_home:
                            _LOGGER.info(
                                "Target '%s' offline after grace period (%ss)",
                                display_name,
                                self.roaming_grace_period,
                            )
                        dev.is_home = False
                        dev.connected_ap = None
                        dev.signal = None
                        dev.active_mac = None
                else:
                    self._devices[primary_mac] = DeviceState(
                        mac=primary_mac,
                        name=display_name,
                        is_home=False,
                        connected_ap=None,
                        signal=None,
                        last_seen=now,
                        active_mac=None,
                        mac_addresses=group_macs,
                    )
                    newly_seen_macs.append(primary_mac)

            # Ensure secondary MACs in this group are not duplicated as standalone devices
            for secondary_m in group_macs[1:]:
                self._devices.pop(secondary_m, None)

        # Step 5: Prune obsolete/untracked MACs from coordinator memory
        if self.tracking_mode == TRACK_MODE_SELECTED:
            untracked = [m for m in list(self._devices.keys()) if m not in primary_macs]
            for m in untracked:
                self._devices.pop(m, None)

        # Notify callbacks if new entities are needed
        for cb in self._new_device_callbacks:
            cb()

        return MeshData(
            devices=dict(self._devices),
            nodes=dict(self._nodes),
            total_clients=total_mesh_clients,
        )
