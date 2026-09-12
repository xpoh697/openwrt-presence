<p align="center">
  <img src="https://raw.githubusercontent.com/xpoh697/openwrt-presence/main/images/icon.png" width="128" height="128" alt="OpenWrt Mesh Presence">
</p>

# OpenWrt Mesh Presence

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/default)
[![OpenWrt](https://img.shields.io/badge/OpenWrt-21.x%20--%2025%2B-blue.svg)](https://openwrt.org)

Интеграция для Home Assistant для высокоточного отслеживания присутствия устройств в Mesh-сетях из 2-х, 3-х и более точек доступа OpenWrt.

## Особенности
- **Zero-Touch на роутерах**: Работает напрямую со штатным LuCI (`uhttpd` + `rpcd` / `ubus` JSON-RPC). На роутеры ничего ставить не нужно.
- **Определение текущей точки Mesh**: Сенсор показывает, к какой именно точке (`Зал`, `Спальня`, `Кухня`) подключен клиент.
- **Сглаживание роуминга (Grace Period 15с)**: Предотвращает ложный статус `not_home` при быстром переходе между комнатами.
- **Уровень сигнала**: Мониторинг RSSI в dBm с динамической оценкой качества связи.
- **Изоляция сбоев**: Падение одного из узлов не блокирует опрос остальных.
