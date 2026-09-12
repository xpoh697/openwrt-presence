"""Async ubus JSON-RPC client for OpenWrt LuCI."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import DEFAULT_REQUEST_TIMEOUT, normalize_mac

_LOGGER = logging.getLogger(__name__)

UBUS_STATUS_OK = 0
UBUS_STATUS_PERMISSION_DENIED = 6
UBUS_STATUS_NOT_FOUND = 4


class OpenWrtAuthError(Exception):
    """Exception raised for authentication errors."""


class OpenWrtConnectionError(Exception):
    """Exception raised for connection errors."""


class OpenWrtUbusClient:
    """Handles communication with OpenWrt via ubus JSON-RPC."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int = 80,
        username: str = "root",
        password: str = "",
        ssl: bool = False,
        verify_ssl: bool = False,
        node_name: str | None = None,
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        """Initialize the OpenWrt client."""
        self._session = session
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._ssl = ssl
        self._verify_ssl = verify_ssl
        self._node_name = node_name or host
        self._timeout = timeout

        proto = "https" if ssl else "http"
        self._url = f"{proto}://{host}:{port}/ubus"
        self._session_id: str = "00000000000000000000000000000000"
        self._logged_in: bool = False
        self._known_interfaces: list[str] = []
        self._interface_meta: dict[str, dict[str, Any]] = {}
        self._host_hints: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    @property
    def node_name(self) -> str:
        """Return friendly name of the node."""
        return self._node_name

    @property
    def host(self) -> str:
        """Return router host."""
        return self._host

    @property
    def host_hints(self) -> dict[str, dict[str, Any]]:
        """Return cached host hints (hostnames & IP)."""
        return self._host_hints

    async def _post_json(self, payload: dict[str, Any] | list[dict[str, Any]]) -> Any:
        """Send raw JSON-RPC POST request."""
        ssl_param = False if not self._verify_ssl else None
        try:
            async with asyncio.timeout(self._timeout):
                async with self._session.post(
                    self._url,
                    json=payload,
                    ssl=ssl_param,
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status == 403:
                        raise OpenWrtAuthError(f"HTTP 403 Forbidden from {self._host}")
                    if resp.status != 200:
                        raise OpenWrtConnectionError(
                            f"HTTP {resp.status} from {self._host}: {await resp.text()}"
                        )
                    return await resp.json()
        except asyncio.TimeoutError as err:
            raise OpenWrtConnectionError(f"Timeout connecting to {self._host}") from err
        except aiohttp.ClientError as err:
            raise OpenWrtConnectionError(f"Network error connecting to {self._host}: {err}") from err

    async def login(self) -> bool:
        """Authenticate with ubus rpcd and obtain session ID."""
        async with self._lock:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "call",
                "params": [
                    "00000000000000000000000000000000",
                    "session",
                    "login",
                    {"username": self._username, "password": self._password},
                ],
            }
            try:
                response = await self._post_json(payload)
            except Exception as err:
                _LOGGER.debug("[%s] Login request failed: %s", self._node_name, err)
                self._logged_in = False
                raise

            result = response.get("result")
            if not result or len(result) < 2:
                self._logged_in = False
                raise OpenWrtAuthError(f"[{self._node_name}] Invalid login response: {response}")

            code = result[0]
            data = result[1]
            if code != UBUS_STATUS_OK or not isinstance(data, dict):
                self._logged_in = False
                raise OpenWrtAuthError(f"[{self._node_name}] Authentication rejected (code {code})")

            self._session_id = data.get("ubus_rpc_session", "")
            if not self._session_id:
                self._logged_in = False
                raise OpenWrtAuthError(f"[{self._node_name}] No session ID received")

            self._logged_in = True
            _LOGGER.debug("[%s] Successfully authenticated to ubus", self._node_name)
            return True

    async def call(self, ubus_object: str, method: str, params: dict[str, Any] | None = None) -> Any:
        """Call a ubus method with auto-relogin on session expiration."""
        if not self._logged_in:
            await self.login()

        if params is None:
            params = {}

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "call",
            "params": [self._session_id, ubus_object, method, params],
        }

        try:
            response = await self._post_json(payload)
        except OpenWrtConnectionError:
            raise
        except Exception as err:
            _LOGGER.debug("[%s] Call error on %s.%s: %s", self._node_name, ubus_object, method, err)
            raise

        result = response.get("result")
        error = response.get("error")

        # Check if session expired or access denied
        if error or (result and len(result) > 0 and result[0] == UBUS_STATUS_PERMISSION_DENIED):
            _LOGGER.debug("[%s] Session expired or permission denied, re-authenticating...", self._node_name)
            await self.login()
            payload["params"][0] = self._session_id
            response = await self._post_json(payload)
            result = response.get("result")

        if result and len(result) >= 2 and result[0] == UBUS_STATUS_OK:
            return result[1]

        if result and len(result) >= 1 and result[0] != UBUS_STATUS_OK:
            _LOGGER.debug(
                "[%s] ubus %s.%s returned status %s",
                self._node_name,
                ubus_object,
                method,
                result[0],
            )
            return None

        return None

    async def update_wireless_interfaces(self) -> None:
        """Discover wireless interfaces and BSSIDs on this router."""
        interfaces: list[str] = []
        meta: dict[str, dict[str, Any]] = {}

        # 1. Primary discovery: luci-rpc getWirelessDevices (cleanest, reliable on OpenWrt 25+)
        try:
            wdevs = await self.call("luci-rpc", "getWirelessDevices")
            if wdevs and isinstance(wdevs, dict):
                for radio_name, rdata in wdevs.items():
                    if not isinstance(rdata, dict):
                        continue
                    for iface in rdata.get("interfaces", []):
                        if not isinstance(iface, dict):
                            continue
                        ifname = iface.get("ifname")
                        cfg = iface.get("config", {})
                        ssid = cfg.get("ssid") or iface.get("ssid") or "OpenWrt-WiFi"
                        bssid = cfg.get("bssid") or iface.get("bssid")
                        if ifname:
                            interfaces.append(ifname)
                            meta[ifname] = {
                                "radio": radio_name,
                                "ssid": ssid,
                                "bssid": bssid.upper() if bssid else None,
                            }
        except Exception as err:
            _LOGGER.debug("[%s] luci-rpc getWirelessDevices error: %s", self._node_name, err)

        # 2. Fallback: network.device status
        if not interfaces:
            try:
                devs = await self.call("network.device", "status")
                if devs and isinstance(devs, dict):
                    for dev_name, dev_info in devs.items():
                        if isinstance(dev_info, dict) and dev_info.get("type") == "Network device":
                            if "wlan" in dev_name or "phy" in dev_name or "ap" in dev_name:
                                interfaces.append(dev_name)
                                meta[dev_name] = {"radio": "unknown", "ssid": "WiFi", "bssid": None}
            except Exception as err:
                _LOGGER.debug("[%s] network.device status error: %s", self._node_name, err)

        # 3. Last resort fallback
        if not interfaces:
            interfaces = ["phy0-ap0", "phy1-ap0", "wlan0", "wlan1"]

        self._known_interfaces = interfaces
        self._interface_meta = meta
        _LOGGER.debug("[%s] Discovered wireless interfaces: %s", self._node_name, interfaces)

        # Also fetch host hints (DHCP / ARP cache)
        await self.update_host_hints()

    async def update_host_hints(self) -> None:
        """Fetch host hints to resolve friendly hostnames and IP addresses."""
        try:
            hints = await self.call("luci-rpc", "getHostHints")
            if hints and isinstance(hints, dict):
                normalized_hints: dict[str, dict[str, Any]] = {}
                for raw_mac, info in hints.items():
                    norm = normalize_mac(raw_mac)
                    if norm and isinstance(info, dict):
                        name = info.get("name")
                        # Strip .lan or .local suffix
                        if name:
                            name = name.removesuffix(".lan").removesuffix(".local")
                        ips = info.get("ipaddrs", [])
                        ip = ips[0] if ips else None
                        normalized_hints[norm] = {"name": name, "ip": ip}
                self._host_hints = normalized_hints
        except Exception as err:
            _LOGGER.debug("[%s] getHostHints error: %s", self._node_name, err)

    async def get_clients(self) -> dict[str, dict[str, Any]]:
        """Fetch all connected wireless clients from this node concurrently."""
        if not self._known_interfaces:
            await self.update_wireless_interfaces()

        clients: dict[str, dict[str, Any]] = {}

        # Fetch iwinfo assoclist for all interfaces concurrently
        async def _query_iface(ifname: str) -> list[dict[str, Any]]:
            meta = self._interface_meta.get(ifname, {})
            # Try iwinfo assoclist
            try:
                iw_res = await self.call("iwinfo", "assoclist", {"device": ifname})
                if iw_res and isinstance(iw_res, dict) and "results" in iw_res:
                    entries = iw_res["results"]
                    parsed = []
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        mac = entry.get("mac")
                        norm = normalize_mac(mac)
                        if norm:
                            parsed.append(
                                {
                                    "mac": norm,
                                    "signal": entry.get("signal", 0),
                                    "noise": entry.get("noise"),
                                    "connected_time": entry.get("connected_time", 0),
                                    "interface": ifname,
                                    "ssid": meta.get("ssid"),
                                    "bssid": meta.get("bssid"),
                                    "node_name": self._node_name,
                                    "host": self._host,
                                }
                            )
                    return parsed
            except Exception as err:
                _LOGGER.debug("[%s] iwinfo %s assoclist error: %s", self._node_name, ifname, err)

            # Fallback to hostapd get_clients
            try:
                res = await self.call(f"hostapd.{ifname}", "get_clients")
                if res and isinstance(res, dict) and "clients" in res:
                    parsed = []
                    for mac, data in res["clients"].items():
                        if isinstance(data, dict) and data.get("authorized", True):
                            norm = normalize_mac(mac)
                            if norm:
                                parsed.append(
                                    {
                                        "mac": norm,
                                        "signal": data.get("signal", 0),
                                        "noise": None,
                                        "connected_time": data.get("connected_time", 0),
                                        "interface": ifname,
                                        "ssid": meta.get("ssid"),
                                        "bssid": meta.get("bssid"),
                                        "node_name": self._node_name,
                                        "host": self._host,
                                    }
                                )
                    return parsed
            except Exception as err:
                _LOGGER.debug("[%s] hostapd.%s get_clients error: %s", self._node_name, ifname, err)

            return []

        tasks = [_query_iface(ifname) for ifname in self._known_interfaces]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, list):
                for client_info in res:
                    mac = client_info["mac"]
                    # If client appears on both 2.4 and 5GHz on the same router, keep higher signal
                    if mac not in clients or client_info.get("signal", -100) > clients[mac].get("signal", -100):
                        clients[mac] = client_info

        return clients
