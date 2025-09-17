# MagicStore Automation

Автоматизация действий в экосистеме Magic Store и Zealy с помощью Chrome DevTools Protocol и Trio. Скрипт открывает профиль браузера (AdsPower), логинится, подтверждает email (Gmail), взаимодействует с MetaMask, выполняет задания/голосования и собирает метрики.

## Возможности
- Вход и навигация на `magic.store`, выполнение голосований и получение XP.
- Интеграция с Zealy (логйн/связка кошелька, выполнение квестов).
- Подписание запросов через MetaMask; извлечение кода подтверждения из Gmail.
- Проверка Gitcoin Passport и обновление состояния аккаунта в `alltheshit.json`.

## Требования
- Python 3.10+; установленный Chrome/Chromium профиль, управляемый AdsPower.
- Локальный API AdsPower: `http://local.adspower.net:50325` (по умолчанию в `utils.py`).
- В профиле должны быть установлены/сконфигурированы: MetaMask, доступ к Gmail для указанной почты.

## Установка
```bash
python -m venv venv
source venv/bin/activate
pip install trio trio-websocket trio-util trio-chrome-devtools-protocol portalocker requests
```

## Запуск
- Одноразовый запуск: `LOG_LEVEL=info python magicstore_automation.py <profile_id>`
- Через скрипт (случайная задержка и логирование): `bash run.sh <profile_id>` — логи сохраняются в `logs/<id>-<timestamp>.txt`.

`<profile_id>` — это ключ аккаунта в `alltheshit.json` (`account[<id>]`). Скрипт ожидает, что в этом файле есть почта/кошелёк/параметры AdsPower (`user_id`).

## Структура проекта
- Основные модули: `magicstore.py`, `magicstore_automation.py`, `metamask.py`, `gmail.py`, `cdp_utils.py`, `utils.py`.
- Данные/активы: `alltheshit.json` (состояние аккаунтов), `basic.json` (словарь), `email.csv`, `bplot.png`.
- Скрипты: `run.sh`; служебные: `plist` (опционально для LaunchAgents).
- Подмодули: `deps/` (клиенты CDP, при необходимости: `git submodule update --init --recursive`).

## Конфигурация и советы
- Измените `ADS_BASE_URI` в `utils.py`, если API AdsPower доступен по другому адресу.
- Настройте уровни логирования переменной окружения `LOG_LEVEL` (`debug|info|warning`).
- Старайтесь избегать жёстких `sleep`; используйте уже имеющиеся `try_hard`/`move_on_after` паттерны.
