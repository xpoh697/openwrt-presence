<p align="center">
  <img src="images/icon.png" width="160" height="160" alt="OpenWrt Mesh Presence Logo">
</p>

# OpenWrt Mesh Presence Tracking для Home Assistant (HACS)

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/default)
[![OpenWrt](https://img.shields.io/badge/OpenWrt-21.x%20--%2025%2B-blue.svg)](https://openwrt.org)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue.svg)](https://www.home-assistant.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Интеграция для **Home Assistant**, предназначенная для высокоточного отслеживания присутствия устройств и мониторинга роуминга в Mesh-сетях из 2-х, 3-х и более точек доступа под управлением **OpenWrt (включая версию 25+)**.

---

## 🌟 Ключевые возможности

- **Zero-Touch на роутерах**: не требует компиляции или установки сторонних пакетов на OpenWrt. Работает «из коробки» со штатным веб-интерфейсом LuCI (`uhttpd` + `rpcd` / `ubus` JSON-RPC).
- **Отслеживание конкретной точки Mesh**: сенсор `sensor.<device>_connected_ap` отображает точное имя узла (например, «Зал», «Спальня», «Кухня»), к которому сейчас подключен клиент.
- **Сглаживание роуминга (Anti-Flapping Grace Period)**: устраняет ложные срабатывания `not_home` при быстром переходе смартфона между точками mesh (802.11k/v/r).
- **Мониторинг сигнала**: сенсор `sensor.<device>_signal` отслеживает реальный уровень RSSI в dBm с динамической иконкой качества связи.
- **Изоляция сбоев**: если один из роутеров выключен или перезагружается, опрос остальных точек сети продолжается без задержек.
- **Диагностика узлов**: сенсоры `binary_sensor.<ap>_status` (Online/Offline) и `sensor.<ap>_active_clients` (счетчик клиентов на каждой точке).
- **Гибкая фильтрация**:
  - Режим *«Отслеживать только выбранные устройства»* (защищает базу данных HA от мусорных рандомизированных MAC).
  - Режим *«Отслеживать все найденные»*.
  - Удобный селектор с показом найденных в эфире MAC-адресов.

---

## 📦 Установка

### Вариант 1: Через HACS (Рекомендуется)
1. Откройте **HACS** → **Интеграции** → меню в правом верхнем углу (три точки) → **Пользовательские репозитории**.
2. Добавьте URL вашего репозитория, категория: **Интеграция**.
3. Нажмите **Загрузить** и перезапустите Home Assistant.

### Вариант 2: Вручную
1. Скопируйте папку `custom_components/openwrt_mesh_presence` в каталог `config/custom_components/` вашего Home Assistant.
2. Перезапустите Home Assistant.

---

## ⚙️ Настройка в Home Assistant

1. В Home Assistant перейдите в **Настройки** → **Устройства и службы** → **Добавить интеграцию**.
2. Найдите **OpenWrt Mesh Presence**.
3. Введите данные для первой точки (Master AP):
   - **Имя**: например, `AP Зал`
   - **IP-адрес**: например, `192.168.1.1`
   - **Порт**: `80` (или `443` для SSL)
   - **Логин / Пароль**: учетные данные от LuCI (обычно `root`)
4. Мастер предложит добавить вторую и третью точки (например, `192.168.1.2`, `192.168.1.3`).
5. После завершения откройте **Параметры интеграции (Options Flow)** и отметьте галочками нужные устройства для трекинга.

---

## 🛠 Создаваемые сущности

| Платформа | Entity ID | Описание |
|---|---|---|
| `device_tracker` | `device_tracker.<mac>` | Статус присутствия (`home` / `not_home`) |
| `sensor` | `sensor.<device>_connected_ap` | Текущая подключенная точка доступа |
| `sensor` | `sensor.<device>_signal` | Уровень сигнала RSSI (dBm) |
| `sensor` | `sensor.<ap_name>_active_clients` | Количество клиентов на точке |
| `binary_sensor` | `binary_sensor.<ap_name>_status` | Доступность узла mesh (Online / Offline) |
