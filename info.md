<p align="center">
  <img src="https://raw.githubusercontent.com/xpoh697/openwrt-presence/main/custom_components/openwrt_mesh_presence/brand/icon.png" width="128" height="128" alt="OpenWrt Mesh Presence">
</p>

# OpenWrt Mesh Presence

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/default)
[![OpenWrt](https://img.shields.io/badge/OpenWrt-21.x%20--%2025%2B-blue.svg)](https://openwrt.org)

Интеграция Home Assistant для высокоточного отслеживания присутствия устройств и мониторинга Wi-Fi роуминга в Mesh-сетях под управлением **OpenWrt (включая версию 25+)**.

## ✨ Особенности
- **Единое устройство в HA**: Все датчики точек доступа и отслеживаемых клиентов сгруппированы на одной карточке устройства.
- **Удобное переименование**: Двухшаговый мастер настройки позволяет выбрать обнаруженные устройства и задать им понятные имена (например, «Телефон Виталия»).
- **Строгий трекинг**: Отслеживаются строго выбранные вами MAC-адреса, база Recorder не засоряется случайными адресами.
- **Zero-Touch на роутерах**: Работает напрямую со штатным LuCI ubus API (`luci-rpc` + `iwinfo`).
- **Сглаживание роуминга (Grace Period 15с)**: Предотвращает ложный статус `not_home` при быстром переходе смартфона между комнатами.
- **Полная диагностика**: Сенсоры подключенной AP, уровня сигнала в dBm, доступности точек и суммарного числа клиентов в сети.
