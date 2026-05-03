# QuantEX — Personal Crypto Assistant Bot

Особистий Telegram-бот для трекінга BTC-інвестицій, управління портфелем та сигналів за стратегією накопичення.

## Можливості

- Трекінг ціни BTCUSDT через Binance Public API
- Ведення портфеля (BTC + USDT резерв)
- Підрахунок середньої ціни входу та PnL
- Сигнали BUY/SELL за стратегією накопичення
- Ручне підтвердження кожної угоди
- Щомісячне та додаткове поповнення
- Дублювання даних у Google Sheets (опційно)
- Scheduler для автоматичних перевірок

---

## Встановлення

```bash
python3 -m venv venv
source venv/bin/activate      # Linux/Mac
# або: venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

---

## Налаштування .env

```bash
cp .env.example .env
nano .env   # або відкрий у редакторі
```

Заповни:

```env
BOT_TOKEN=<токен від @BotFather>
OWNER_TELEGRAM_ID=<свій Telegram ID>

CHECK_INTERVAL_MINUTES=5

GOOGLE_SHEETS_ENABLED=0
GOOGLE_SHEET_ID=
GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json
```

Отримати свій Telegram ID можна через бота [@userinfobot](https://t.me/userinfobot).

---

## Запуск

```bash
python main.py
```

Після запуску надішли боту `/start` — він ініціалізує базу і покаже головне меню.

---

## Ініціалізація портфеля

Надішли `/init` і введи стартовий капітал у USDT.

Бот розрахує:
- 70% → покупка BTC
- 30% → резерв

Підтвердь покупку за ринковою або власною ціною.

---

## Google Sheets (опційно)

### 1. Створи Service Account

1. Відкрий [Google Cloud Console](https://console.cloud.google.com/)
2. Створи проект або вибери існуючий
3. Перейди в **APIs & Services → Credentials**
4. Натисни **Create Credentials → Service Account**
5. Заповни назву, натисни **Create and Continue**
6. На кроці **Grant access** можна пропустити
7. Натисни **Done**

### 2. Завантаж service_account.json

1. У списку Service Accounts натисни на щойно створений акаунт
2. Перейди на вкладку **Keys**
3. Натисни **Add Key → Create new key → JSON**
4. Збережи файл як `service_account.json` у папці проекту

### 3. Увімкни Google Sheets API

У **APIs & Services → Library** знайди та увімкни:
- Google Sheets API
- Google Drive API

### 4. Розшар таблицю

1. Відкрий або створи Google Таблицю
2. Скопіюй її ID з URL (частина між `/d/` і `/edit`)
3. Натисни **Поділитись** і додай email service account (є у JSON файлі, поле `client_email`) з правами **Editor**

### 5. Налаштуй .env

```env
GOOGLE_SHEETS_ENABLED=1
GOOGLE_SHEET_ID=<ID твоєї таблиці>
GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json
```

---

## Команди

| Команда | Дія |
|---------|-----|
| `/start` | Запуск бота |
| `/init` | Ініціалізація портфеля |
| `/price` | Поточна ціна BTC |
| `/signal` | Перевірити сигнал |

---

## Структура проекту

```
quantex_bot/
├── main.py              — запуск бота
├── config.py            — конфігурація з .env
├── requirements.txt
├── .env.example
│
├── bot/
│   ├── handlers.py      — всі обробники команд та кнопок
│   ├── keyboards.py     — клавіатури
│   ├── messages.py      — форматування повідомлень
│   └── states.py        — FSM стани
│
├── database/
│   ├── db.py            — підключення та ініціалізація БД
│   └── schema.py        — SQL схема
│
├── services/
│   ├── binance_service.py   — ціна BTC з Binance
│   ├── owner_service.py     — авторизація власника
│   ├── portfolio_service.py — управління портфелем
│   ├── transaction_service.py
│   ├── signal_service.py
│   ├── settings_service.py
│   └── sheets_service.py    — Google Sheets
│
├── strategies/
│   ├── base.py          — базовий клас стратегії
│   ├── accumulation.py  — стратегія накопичення
│   └── registry.py      — реєстр стратегій
│
├── scheduler/
│   └── watcher.py       — фоновий моніторинг ціни
│
└── utils/
    ├── calculations.py  — математика
    └── formatters.py    — форматування чисел
```

---

## Додавання нової стратегії

1. Створи файл `strategies/my_strategy.py`
2. Успадкуй `BaseStrategy` з `strategies/base.py`
3. Реалізуй методи `check()`, `get_default_triggers()`, `get_parameters_text()`
4. Додай у `strategies/registry.py`:

```python
from strategies.my_strategy import MyStrategy

STRATEGIES = {
    "accumulation": AccumulationStrategy(),
    "my_strategy": MyStrategy(),
}
```

Жодних змін у handlers, scheduler або БД не потрібно.

---

## Деплой на VPS (systemd)

Створи файл `/etc/systemd/system/quantex.service`:

```ini
[Unit]
Description=QuantEX Telegram Bot
After=network.target

[Service]
WorkingDirectory=/var/www/quantex_bot
ExecStart=/var/www/quantex_bot/venv/bin/python main.py
Restart=always
RestartSec=5
EnvironmentFile=/var/www/quantex_bot/.env

[Install]
WantedBy=multi-user.target
```

Команди керування:

```bash
sudo systemctl daemon-reload
sudo systemctl enable quantex
sudo systemctl start quantex
sudo systemctl status quantex
sudo journalctl -u quantex -f   # логи в реальному часі
```
