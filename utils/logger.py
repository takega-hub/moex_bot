"""Logging configuration for trading bot."""
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

# Создаем директорию для логов
logs_dir = Path("logs")
logs_dir.mkdir(exist_ok=True)

# Настройка основного логгера
logger = logging.getLogger("trading_bot")
logger.setLevel(logging.INFO)

# Очищаем существующие обработчики
logger.handlers.clear()

# Консольный обработчик
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

# Файловый обработчик с ротацией
file_handler = RotatingFileHandler(
    logs_dir / 'bot.log',
    maxBytes=10*1024*1024,  # 10 MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# Отключаем шумные логи библиотек
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
