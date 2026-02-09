"""Application settings and configuration."""
from pathlib import Path
from typing import Optional

# Base directory for the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Путь к папке с данными (CSV файлы)
DATA_DIR = BASE_DIR / "ml_data"

# Путь к папке с моделями
MODELS_DIR = BASE_DIR / "ml_models"

# Путь к папке с логами
LOGS_DIR = BASE_DIR / "logs"
