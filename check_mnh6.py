#!/usr/bin/env python3
"""Проверка расчета ГО для MNH6 через find_margin_formula.py"""
import subprocess
import sys

print("=" * 80)
print("ПРОВЕРКА РАСЧЕТА ГО ДЛЯ MNH6")
print("=" * 80)
print()
print("Запускаем find_margin_formula.py для MNH6...")
print()

try:
    result = subprocess.run(
        [sys.executable, "find_margin_formula.py", "--ticker", "MNH6"],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace'
    )
    
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    
    if result.returncode != 0:
        print(f"Exit code: {result.returncode}")
        
except Exception as e:
    print(f"Ошибка при запуске: {e}")
