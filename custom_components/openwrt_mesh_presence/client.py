"""Async ubus JSON-RPC client for OpenWrt LuCI."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import DEFAULT_REQUEST_TIMEOUT

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
        self._lock = asyncio.Lock()

    @property
    def node_name(self) -> str:
        """Return friendly name of the node."""
        return self._node_name

    @property
    def host(self) -> str:
        """Return router host."""
        return self._host

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
        try:
            status = await self.call("network.wireless", "status")
            if not status or not isinstance(status, dict):
                return

            interfaces: list[str] = []
            meta: dict[str, dict[str, Any]] = {}

            for radio_name, radio_info in status.items():
                if not isinstance(radio_info, dict):
                    continue
                vifs = radio_info.get("interfaces", [])
                for vif in vifs:
                    if not isinstance(vif, dict):
                        continue
                    ifname = vif.get("ifname")
                    config = vif.get("config", {})
                    data = vif.get("data", {})
                    ssid = config.get("ssid") or data.get("ssid") or "Unknown"
                    bssid = data.get("bssid") or config.get("bssid")

                    if ifname:
                        interfaces.append(ifname)
                        meta[ifname] = {
                            "radio": radio_name,
                            "ssid": ssid,
                            "bssid": bssid.upper() if bssid else None,
                        }

            if interfaces:
                self._known_interfaces = interfaces
                self._interface_meta = meta
                _LOGGER.debug("[%s] Discovered interfaces: %s", self._node_name, interfaces)
        except Exception as err:
            _LOGGER.debug("[%s] Error discovering wireless interfaces: %s", self._node_name, err)

    async def get_clients(self) -> dict[str, dict[str, Any]]:
        """Fetch all connected wireless clients from this node."""
        if not self._known_interfaces:
            await self.update_wireless_interfaces()

        clients: dict[str, dict[str, Any]] = {}

        if not self._known_interfaces:
            # Fallback if interface discovery is empty: try default names
            self._known_interfaces = ["wlan0", "wlan1"]

        # 1. First attempt: call hostapd.<ifname> get_clients (fastest, kernel-level)
        for ifname in self._known_interfaces:
            meta = self._interface_meta.get(ifname, {})
            try:
                res = await self.call(f"hostapd.{ifname}", "get_clients")
                if res and isinstance(res, dict) and "clients" in res:
                    for mac, data in res["clients"].items():
                        if not isinstance(data, dict):
                            continue
                        clean_mac = mac.upper()
                        # Verify station is actually authorized/associated
                        if data.get("authorized", True) and data.get("assoc", True):
                            signal = data.get("signal", 0)
                            clients[clean_mac] = {
                                "mac": clean_mac,
                                "signal": signal,
                                "interface": ifname,
                                "ssid": meta.get("ssid"),
                                "bssid": meta.get("bssid"),
                                "node_name": self._node_name,
                                "host": self._host,
                            }
                    continue
            except Exception as err:
                _LOGGER.debug("[%s] hostapd.%s get_clients failed: %s", self._node_name, ifname, err)

            # 2. Second attempt / Fallback: iwinfo assoclist
            try:
                iw_res = await self.call("iwinfo", "assoclist", {"device": ifname})
                if iw_res and isinstance(iw_res, dict) and "results" in iw_res:
                    for entry in iw_res["results"]:
                        if not isinstance(entry, dict):
                            continue
                        mac = entry.get("mac")
                        if mac:
                            clean_mac = mac.upper()
                            signal = entry.get("signal", 0)
                            clients[clean_mac] = {
                                "mac": clean_mac,
                                "signal": signal,
                                "interface": ifname,
                                "ssid": meta.get("ssid"),
                                "bssid": meta.get("bssid"),
                                "node_name": self._node_name,
                                "host": self._host,
                            }
            except Exception as err:
                _LOGGER.debug("[%s] iwinfo %s assoclist failed: %s", self._node_name, ifname, err)

        return clients
