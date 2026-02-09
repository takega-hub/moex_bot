# Tinkoff Trading Bot

Торговый бот для биржи Тинькофф Инвестиции с использованием ML-моделей для генерации торговых сигналов.

## Структура проекта

```
moex_bot2/
├── bot/                    # Основные модули бота
│   ├── config.py          # Конфигурация
│   ├── state.py           # Управление состоянием
│   ├── trading_loop.py    # Торговый цикл
│   ├── strategy.py        # Базовые классы стратегий
│   ├── model_manager.py   # Менеджер ML моделей
│   ├── telegram_bot.py    # Telegram бот для управления
│   ├── ml/                # ML стратегии
│   │   ├── strategy_ml.py
│   │   └── feature_engineering.py
│   ├── exchange/          # Клиенты бирж
│   └── rl/                # Reinforcement Learning
├── data/                  # Работа с данными
│   ├── collector.py       # Сбор исторических данных (Tinkoff)
│   ├── storage.py         # Хранение данных (CSV файлы)
│   ├── preprocessor.py    # Предобработка данных
│   └── advanced_features.py  # Расширенные фичи
├── trading/               # Торговые модули
│   └── client.py          # Клиент Tinkoff Invest API
├── config/                # Конфигурация
│   └── settings.py
├── utils/                 # Утилиты
│   └── logger.py
├── run_bot.py             # Главный файл запуска
└── requirements.txt       # Зависимости
```

## Установка

1. Установите зависимости:
```bash
pip install -r requirements.txt
```

**Важно:** Библиотека `t-tech-investments` устанавливается из специального репозитория:
```bash
pip install t-tech-investments --index-url https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple
```

2. Создайте файл `.env` в корне проекта:
```env
# Tinkoff Invest API
TINKOFF_TOKEN=your_token_here
TINKOFF_SANDBOX=true  # true для песочницы, false для реального счета

# Telegram Bot
TELEGRAM_TOKEN=your_telegram_bot_token
ALLOWED_USER_ID=your_telegram_user_id

# Trading settings
TRADING_INSTRUMENTS=VBH6,SRH6,GLDRUBF  # Список инструментов через запятую
TIMEFRAME=15min  # Таймфрейм: 1min, 5min, 15min, 1hour, 4hour, day

# ML Strategy
ML_CONFIDENCE_THRESHOLD=0.35
ML_MIN_SIGNAL_STRENGTH=слабое
```

## Использование

### Получение исторических данных

Используйте существующую систему из `data/collector.py`:

```python
from data.collector import DataCollector
from trading.client import TinkoffClient
from datetime import datetime, timedelta

client = TinkoffClient()
collector = DataCollector(client=client)

# Найти инструмент
instrument = collector.collect_instrument_info("Si-3.25", instrument_type="futures")

# Собрать исторические данные
from_date = datetime.now() - timedelta(days=30)
to_date = datetime.now()
candles = collector.collect_candles(
    figi=instrument["figi"],
    from_date=from_date,
    to_date=to_date,
    interval="15min"
)
```

### Запуск бота

```bash
python run_bot.py
```

## Особенности

1. **Интеграция с существующей системой данных**: Использует `data/collector.py` и `data/storage.py` для работы с историческими данными Tinkoff
2. **ML стратегия**: Использует обученные ML модели для генерации сигналов
3. **Управление рисками**: Встроенные механизмы стоп-лоссов, тейк-профитов и управления позициями
4. **Telegram управление**: Управление ботом через Telegram
5. **Адаптация под Tinkoff**: Клиент адаптирован для работы с Tinkoff Invest API

## Основные отличия от крипто-бота

1. **Инструменты**: Работа с FIGI вместо символов криптовалют
2. **API**: Использование Tinkoff Invest API вместо Bybit
3. **Позиции**: Адаптация под особенности работы с фьючерсами на Tinkoff
4. **Данные**: Интеграция с существующей системой получения исторических данных

## Структура данных

Исторические данные хранятся в CSV файлах в папке `ml_data/` (аналогично криптоботу):

### Формат файлов:
- **Кэш-файлы**: `{TICKER}_{INTERVAL}_cache.csv` - актуальные данные (например, `VBH6_15_cache.csv`)
- **Исторические файлы**: `{TICKER}_{INTERVAL}_{START_DATE}_{END_DATE}.csv` - архивы по периодам
- **Инструменты**: `instruments.csv` - информация об инструментах (FIGI, ticker, name)
- **Сделки**: `trades.csv` - история сделок

### Формат CSV:
```csv
timestamp,open,high,low,close,volume
2026-02-07 11:45:00,8581.00,8595.00,8580.00,8589.00,1098
```

### Преимущества CSV хранения:
- ✅ Легко просматривать и анализировать данные
- ✅ Совместимость с криптоботом
- ✅ Простое резервное копирование
- ✅ Удобно для ML обучения

## Деплой на сервер

Проект настроен для автоматического деплоя через GitHub Actions.

### Быстрый старт

1. **Настройте сервер** (см. `deploy/README.md` для подробной инструкции)
2. **Настройте GitHub Secrets**:
   - `SSH_PRIVATE_KEY` - приватный SSH ключ для подключения к серверу
   - `SERVER_USER` - пользователь для SSH (например, `ubuntu`)
   - `SERVER_HOST` - IP адрес или домен сервера
   - `SERVER_PORT` - порт SSH (опционально, по умолчанию 22)
   - `DEPLOY_PATH` - путь к проекту на сервере (опционально, по умолчанию `/opt/moex_bot2`)

3. **Автоматический деплой**: При пуше в ветку `main` или `master` автоматически запустится деплой

4. **Ручной деплой**: Используйте скрипт `deploy.sh`:
   ```bash
   chmod +x deploy.sh
   ./deploy.sh user@example.com /opt/moex_bot2
   ```

Подробная инструкция по настройке и деплою находится в `deploy/README.md`.

## Разработка

Для добавления новых стратегий или улучшения существующих:
1. Создайте новую стратегию в `bot/ml/` или `bot/rl/`
2. Интегрируйте в `bot/trading_loop.py`
3. Добавьте настройки в `bot/config.py`

## Лицензия

MIT
