<p align="center">
  <img src="https://raw.githubusercontent.com/xpoh697/openwrt-presence/main/custom_components/openwrt_mesh_presence/brand/icon.png" width="160" height="160" alt="OpenWrt Mesh Presence Logo">
</p>

# OpenWrt Mesh Presence Tracking для Home Assistant (HACS)

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/default)
[![OpenWrt](https://img.shields.io/badge/OpenWrt-21.x%20--%2025%2B-blue.svg)](https://openwrt.org)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue.svg)](https://www.home-assistant.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Интеграция для **Home Assistant**, предназначенная для высокоточного отслеживания присутствия устройств (Presence Detection) и мониторинга Wi-Fi роуминга в Mesh-сетях из 2-х, 3-х и более точек доступа под управлением **OpenWrt (включая версию 25+)**.

---

## 🌟 Ключевые возможности

- **Единое устройство (Single Unified Device)**: Все сенсоры точек доступа, диагностика сети и отслеживаемые мобильные устройства объединены в **одну аккуратную карточку устройства** в Home Assistant (никаких «несгруппированных» сущностей).
- **Удобный двухшаговый мастер настройки**:
  - **Шаг 1**: Интуитивный выбор устройств из списка реально обнаруженных в эфире клиентов (с показом моделей `Xiaomi`, `iPhone`, IP-адресов, текущей AP и уровня RSSI) + поле ручного ввода любых дополнительных MAC.
  - **Шаг 2**: Индивидуальные поля для удобного переименования каждого выбранного устройства (например, *«Телефон Виталия»*, *«Телефон Жены»*).
- **Строгий избирательный трекинг**: Интеграция создает сущности **строго и только для указанных вами устройств**, защищая базу данных Home Assistant от разрастания мусорными рандомизированными MAC-адресами.
- **Zero-Touch на роутерах**: Не требует компиляции или установки сторонних пакетов на OpenWrt. Работает напрямую со штатным LuCI API (`uhttpd` + `rpcd` / `ubus` JSON-RPC).
- **Отслеживание конкретной точки Mesh**: Сенсор `sensor.<device>_connected_ap` отображает точное имя узла (`AP_PARTER`, `AP_PIETRO`, `AP_PODDASZE` или `Не в сети`), к которому подключено устройство.
- **Сглаживание роуминга (Anti-Flapping Grace Period)**: Устраняет ложные срабатывания `not_home` при быстром переходе смартфона между точками mesh (802.11k/v/r).
- **Мониторинг сигнала**: Сенсор `sensor.<device>_signal` отслеживает реальный уровень RSSI в dBm с динамической иконкой качества связи.
- **Изоляция сбоев**: Если один из роутеров выключен или перезагружается, опрос остальных точек сети продолжается без задержек.
- **Диагностика сети**: 
  - `sensor.mesh_total_active_clients` — общее количество клиентов в mesh-сети.
  - `binary_sensor.<ap>_status` — онлайн/офлайн статус точек доступа.
  - `sensor.<ap>_active_clients` — счетчик клиентов на каждой точке.

---

## 📦 Установка

### Вариант 1: Через HACS (Рекомендуется)
1. Откройте **HACS** → **Интеграции** → меню в правом верхнем углу (**⋮**) → **Пользовательские репозитории**.
2. Добавьте URL репозитория: `https://github.com/xpoh697/openwrt-presence`, категория: **Интеграция**.
3. Нажмите **Загрузить** и перезагрузите Home Assistant.

### Вариант 2: Вручную
1. Скопируйте папку `custom_components/openwrt_mesh_presence` в каталог `config/custom_components/` вашего Home Assistant.
2. Перезагрузите Home Assistant.

---

## ⚙️ Настройка в Home Assistant

1. Перейдите в **Параметры** → **Устройства и службы** → **Добавить интеграцию**.
2. Найдите **OpenWrt Mesh Presence**.
3. Введите параметры для первой точки (Master AP):
   - **Имя**: например, `AP_PARTER`
   - **IP-адрес**: например, `192.168.100.2`
   - **Порт**: `80` (или `443` для SSL)
   - **Логин / Пароль**: учетные данные LuCI (обычно `root`)
4. Мастер предложит добавить остальные точки доступа (например, `AP_PIETRO`, `AP_PODDASZE`).
5. После добавления нажмите кнопку **«Настроить»** (Configure) на интеграции:
   - **Шаг 1**: Отметьте интересующие вас устройства галочками в списке.
   - **Шаг 2**: Задайте им понятные имена.

---

## 🛠 Создаваемые сущности

Все сущности сгруппированы внутри **единого устройства «OpenWrt Mesh Presence»**:

| Платформа | Entity ID | Описание |
|---|---|---|
| `sensor` | `sensor.mesh_total_active_clients` | Общее количество клиентов во всей mesh-сети |
| `sensor` | `sensor.<ap_name>_active_clients` | Количество активных клиентов на конкретной AP |
| `binary_sensor` | `binary_sensor.<ap_name>_status` | Доступность узла mesh (Online / Offline) |
| `sensor` | `sensor.<device>_connected_ap` | Имя точки доступа, к которой подключен девайс (`AP_PARTER`, `AP_PIETRO`, `AP_PODDASZE` или `Не в сети`) |
| `sensor` | `sensor.<device>_signal` | Уровень сигнала RSSI (в dBm) с динамической иконкой связи |
| `sensor` | `sensor.<device>_last_seen` | Временная метка последнего подтверждения присутствия |
| `device_tracker` | `device_tracker.<device>` | Статус присутствия (`home` / `not_home`) с дебаунсом роуминга |

---

## 📄 Лицензия

Проект распространяется под открытой лицензией MIT. Подробнее см. в файле [LICENSE](LICENSE).
