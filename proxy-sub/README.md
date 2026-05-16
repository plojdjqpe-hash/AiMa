# Proxy Subscription Service

Автоматический сервис подписки для Hiddify: **API + Telegram Bot + WebApp**.

## Возможности

- Автосбор из 7+ источников (~1500 конфигов)
- Фильтрация по сети: LTE / 3G / Wi-Fi
- Приоритизация: REALITY > WS/TLS > gRPC
- **Telegram бот** — раздача подписок + управление
- **WebApp** — Telegram Mini App + веб-панель
- Формат совместим с Hiddify, v2rayNG, NekoBox, Streisand

## Быстрая установка (Linux VPS)

```bash
curl -sL https://raw.githubusercontent.com/plojdjqpe-hash/AiMa/devin/1777773350-add-claude-code-skill/proxy-sub/install.sh | sudo bash
```

Или вручную:

```bash
git clone https://github.com/plojdjqpe-hash/AiMa.git
cd AiMa/proxy-sub
sudo bash install.sh
```

Скрипт установит:
- Python 3 + venv + зависимости
- API сервис (FastAPI на порту 8000)
- Telegram бот (aiogram)
- WebApp (доступна по /app)
- systemd сервисы с автозапуском

## Эндпоинты

| URL | Описание |
|-----|----------|
| `/sub/lte` | Оптимизированные для LTE (REALITY) |
| `/sub/wifi` | Оптимизированные для Wi-Fi (WS/TLS) |
| `/sub/3g` | Оптимизированные для 3G (gRPC) |
| `/sub/best` | Топ-20 лучших |
| `/sub?ports=443,8443` | Фильтр по портам |
| `/sub?max=30` | Лимит количества |
| `/stats` | Статистика |
| `/app` | WebApp (графический интерфейс) |
| `/refresh` | Обновить кэш (POST) |

## Telegram бот

Команды:
- `/start` — главное меню с кнопками
- `/lte`, `/wifi`, `/3g` — получить подписку для сети
- `/best` — лучшие конфиги
- `/stats` — статистика
- `/admin` — управление (для админов)

## Переменные окружения

| Переменная | Описание |
|-----------|----------|
| `TELEGRAM_BOT_TOKEN` | Токен от @BotFather |
| `ADMIN_IDS` | Telegram ID админов (через запятую) |
| `PROXY_SUB_API` | URL API (default: http://127.0.0.1:8000) |
| `WEBAPP_URL` | URL WebApp для кнопки в боте |

## Управление

```bash
# Статус
systemctl status proxy-sub-api proxy-sub-bot

# Логи
journalctl -u proxy-sub-api -f
journalctl -u proxy-sub-bot -f

# Перезапуск
systemctl restart proxy-sub-api proxy-sub-bot

# Обновление
cd /opt/proxy-sub/repo && git pull
systemctl restart proxy-sub-api proxy-sub-bot
```
