<div align="center">

<!-- LOGO PLACEHOLDER -->
<img style="margin-top: 15px; margin-bottom: -15px; margin-left: 25px" src="./.github/img/logo.svg" alt="BunnyACE" width="120" height="120" />
<h1 style="margin-top: 0">Bunny<span style="color:deepskyblue">ACE</span> </h1>

[![License](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE.md)
![Status](https://img.shields.io/badge/Status-WIP-orange)
![Klipper](https://img.shields.io/badge/Klipper-Module-blue)
![Anycubic ACE](https://img.shields.io/badge/Anycubic-ACE%20Pro-8A2BE2)

<p>Драйвер для Anycubic Color Engine Pro (ACE) под Klipper 🐰🎨</p>
<p>Управление подачей нити, сменой инструмента (до 4 каналов), сушилкой ACE и сценариями прямо из Klipper/G-code.</p>

[English version →](./README.md)

</div>

---

## 🧭 Оглавление
- [Возможности](#-возможности)
- [Требования](#-требования)
- [Установка](#-установка)
- [Обновление](#-обновление)
- [Удаление](#-удаление)
- [Быстрый старт](#-быстрый-старт)
- [Конфигурация (acecfg)](#-конфигурация-acecfg)
- [Команды G-code](#-команды-g-code)
- [Датчики и логика](#-датчики-и-логика)
- [Типичный workflow](#-типичный-workflow)
- [Пин-аут и подключение](#-пин-аут-и-подключение)
- [Отладка и логи](#-отладка-и-логи)
- [Планы развития](#-планы-развития)
- [Лицензия](#-лицензия)
- [Авторы и контрибьюторы](#-авторы-и-контрибьюторы)

## ✨ Возможности
- До 4 линий подачи (гейтов) и смена инструмента командой G-code 🔀
- Помощь подачи (Feed Assist) на стороне ACE 
- Управление сушилкой ACE Pro: старт по температуре/времени и остановка ♨️
- Настройка карты гейтов: цвет, материал, рекомендуемая температура 🎯
- Режим Endless Spool (автопереключение при окончании) ♾️
- Интеграция с датчиками филамента и макросами Klipper 🧩

## 📦 Требования
- Klipper + Moonraker
- Доступ к терминалу устройства с Klipper

## ⚙️ Установка
Скрипт автоматически установит последнюю версию драйвера.

Удалите/прокомментируйте все разделы о вашем текущем датчике филамента (filament runout sensor) в вашем printer.cfg, поскольку вы собираетесь использовать датчик в голове принтера (extruder_sensor) для обнаружения филамента.
```bash
cd ~
git clone https://github.com/BlackFrogKok/BunnyACE.git
cd BunnyACE
./install.sh
```

После установки:
- В конфиг printer.cf необходимо будет добавить [include ace.cfg].
- В Moonraker появится Update Manager "BunnyACE" для обновления из веб‑интерфейса.

Важно: если у вас уже есть свой [save_variables], перенесите переменные из ace_vars.cfg в ваш файл переменных и закомментируйте блок [save_variables] в ace.cfg.

## 🔄 Обновление
- Через Web UI: Moonraker Update Manager → BunnyACE

## 🗑️ Удаление
1) Уберите [include ace.cfg] из конфигурации Klipper и секцию обновления из moonraker.conf.
2) Выполните:
```bash
cd ~/BunnyACE
./install.sh -u
```

## 🚀 Быстрый старт
1) Подключите ACE по USB к хосту с Klipper.
2) Добавьте/проверьте конфиг: `ace.cfg`. Минимум:
   - serial: путь к ACE (например, `/dev/serial/by-id/usb-ANYCUBIC_ACE_1-if00`)
   - `extruder_sensor_pin:` пин датчика филамента у экструдера
   - `toolhead_sensor_pin:` пин датчика перед ножом (при наличии)
   - `toolchange_retract_length:` необходимо указать расстояние от сплитера до головы вашего принтера
   - `poop_macros:` необходимо прописать макрос прочистки сопла
   - `cut_macros:` необходимо прописать макрос обрезки кончика филамента
3) Перезапустите Klipper — в консоли появится сообщение об успешном подключении ACE (модель и прошивка).
4) Проверьте смену инструмента: `T0` / `T1` / `T2` / `T3` (или `ACE_CHANGE_TOOL TOOL=0..3`).

## 🛠️ Конфигурация (ace.cfg)
Основные параметры (см. `ace.cfg` полностью для макросов):
- serial: `/dev/serial/by-id/...` — идентификатор ACE
- baud: `115200` — скорость порта
- extruder_sensor_pin: пин датчика у экструдера (например, `!PA4`)
- toolhead_sensor_pin: пин датчика перед ножом (опционально)
- feed_speed: `10–80` — базовая скорость подачи (в этом профиле `80`; сток ACE `10–25`)
- retract_speed: `10–80` — базовая скорость ретракта (по умолчанию `80`)
- toolchange_retract_length: `650` мм — ретракт при смене инструмента
- toolhead_sensor_to_nozzle: `20` мм — от датчика головы до сопла
- poop_macros: макрос продувки после загрузки
- cut_macros: макрос обрезки при выгрузке
- max_dryer_temperature: предел температуры сушилки (по умолчанию `70°C`)

В конце `ace.cfg` есть заготовки макросов:
- `POOP` — продувка
- `CUT_TIP` — обрезка кончика
- `_ACE_PRE_TOOLCHANGE` / `_ACE_POST_TOOLCHANGE` — макросы перед/после смены
- `T0..T3` — шорткаты к `ACE_CHANGE_TOOL`

Переменные сохраняются в `ace_vars.cfg` через `[save_variables]`.

## ⌨️ Команды G-code
ACE добавляет команды, доступные из консоли/макросов Klipper.

- `ACE_CHANGE_TOOL TOOL=<-1..3>` — смена инструмента (TOOL=-1 выгрузить филамент из принтера)
- `ACE_START_DRYING TEMP=<°C> DURATION=<мин>` — старт сушилки (по умолчанию 240 мин; ограничено `max_dryer_temperature`)
- `ACE_STOP_DRYING` — стоп сушилки (выключается не сразу; требуется время, чтобы охладиться)
- `ACE_ENABLE_FEED_ASSIST INDEX=<0..3>` — включить помощь подачи для канала
- `ACE_DISABLE_FEED_ASSIST [INDEX=<0..3>]` — выключить помощь (если индекс не задан — берётся последний активный)
- `ACE_FEED INDEX=<0..3> LENGTH=<мм> [SPEED=<мм/с>]` — подать нить со стороны ACE
- `ACE_RETRACT INDEX=<0..3> LENGTH=<мм> [SPEED=<мм/с>]` — вернуть нить в ACE
- `ACE_GATE_MAP GATE=<0..3> [COLOR=<hexRGB>] [TYPE=<PLA/ABS/...>] [TEMP=<°C>]` — задать метаданные ячейки
- `ACE_ENDLESS_SPOOL ENABLE=<0|1>` — включить/выключить бесконечную катушку
- `ACE_DEBUG METHOD=<json_rpc_method> [PARAMS='{"k":"v"}']` — макрос для тестирования запросов к ACE

## 🧲 Датчики и логика
Используются два датчика наличия филамента:
- `extruder_sensor` — у экструдера (необходим для корректной работы)
- `toolhead_sensor` — у головы (опционально для точной доводки к соплу)

## 🧪 Типичный workflow
- Настройте макросы `POOP` и `CUT_TIP` под ваш принтер.
- В печати используйте `T0..T3` либо `ACE_CHANGE_TOOL TOOL=N`.
- Для сушки: `ACE_START_DRYING TEMP=55 DURATION=180`, остановка — `ACE_STOP_DRYING`.

## 🔌 Пин-аут и подключение
<img src="./.github/img/pinout.png" alt="drawing" width="500"/>

Важно: VCC (24 В) для логики не обязателен — ACE питает себя сам. Подключение по USB к обычному порту.

## 🐞 Отладка и логи
- В консоли Klipper ищите сообщения, начинающиеся с `ACE:` — статусы/ошибки.
- Если нет подключения — проверьте `serial` (/dev/serial/by-id/… или /dev/tty…) и права на устройство.
- Для низкоуровневой проверки связи используйте `ACE_DEBUG`.

## 🗺️ Планы развития
- [ ] UI-панель/карточка в Mainsail/Fluidd (управление сушилкой, маппинг гейтов)
- [ ] Автонастройка `serial` по VID/PID ACE
- [ ] Пресеты материалов для быстрого выбора (PLA/PETG/ABS и т. п.)
- [ ] Документация по интеграции с популярными профилями слайсеров
- [ ] Тесты и CI для стабильности

## 📜 Лицензия
См. [LICENSE.md](./LICENSE.md)

## 👥 Авторы и контрибьюторы
- Место для списка авторов и благодарностей 🙏
- PR приветствуются! Описывайте изменения и проверяйте стиль коммитов.