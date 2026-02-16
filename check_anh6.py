#!/usr/bin/env python3
"""Простой скрипт для проверки ANH6"""
import subprocess
import sys
import os

# Устанавливаем кодировку
os.environ['PYTHONIOENCODING'] = 'utf-8'

# Запускаем скрипт для ANH6
result = subprocess.run(
    [sys.executable, "get_margin_ncm6.py", "ANH6"],
    encoding='utf-8',
    errors='replace'
)

sys.exit(result.returncode)
